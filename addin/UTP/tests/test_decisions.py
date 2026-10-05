"""The decisions, tested without Fusion.

    python -m pytest addin/UTP/tests -q

Most of what this add-in decides is pure functions over plain dicts: what a
note says, which line of a note is its own, what a version should become,
which presets are spare, what a damaged switches file means. None of that
needs Fusion, and until now none of it was tested at all -- the suite in
tests/utp_test_lib asks Fusion how it behaves, which was the right instrument
for the questions it answers and the wrong one for these.

It lives beside the package rather than in tests/, because tests/ is a
repository of its own and git will not track a path inside it. A change to a
decision and the test that pins it should land in one commit, which is the
whole point.

Two of the cases here are bugs a reviewer found by reading, which is the
argument for the file: they would have been caught by a dozen assertions.

adsk is stubbed rather than imported. Nothing here touches it, but the modules
import it at the top, and a test that cannot run outside Fusion is a test
nobody runs.
"""

import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

for _name in ("adsk", "adsk.core", "adsk.cam", "adsk.fusion"):
    sys.modules.setdefault(_name, types.ModuleType(_name))


class _Colours:
    Gray, Red, Blue, Green, Yellow = 0, 1, 2, 3, 4


sys.modules["adsk.cam"].NoteIconColors = _Colours
sys.modules["adsk"].cam = sys.modules["adsk.cam"]
sys.modules["adsk"].core = sys.modules["adsk.core"]

from utp import compat, config, marks, presets, settings, state, values  # noqa: E402

config.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "switches.json")
settings.forget()


# ---------------------------------------------------------------------------
# Fakes. Small on purpose: a fake that grows features grows bugs of its own.
# ---------------------------------------------------------------------------

class Attr:
    def __init__(self, name, value):
        self.name, self.value = name, value

    def deleteMe(self):
        return True


class Attrs:
    def __init__(self, held):
        self.held = dict(held)

    def itemByName(self, group, key):
        value = self.held.get(key)
        return Attr(key, value) if value is not None else None

    def itemsByGroup(self, group):
        raise RuntimeError("not enumerable in the fake")

    def add(self, group, key, value):
        self.held[key] = value


class Owner:
    """An operation or a setup, as far as the decisions are concerned."""

    def __init__(self, notes="", record=None, icon="Gray"):
        self.notes = notes
        self.noteIconColor = getattr(_Colours, icon)
        self.attributes = Attrs(
            {config.KEY_RECORD: json.dumps(record)} if record else {})


ADOPTED = {"s": config.SCHEMA, config.KEY_ADOPTED_PRESET: "p1",
           config.KEY_OPERATION_ID: "o1", "i": "Gray"}


def verdict(kind, **extra):
    base = {"state": kind, "preset": "Titanium", "presetId": "p1",
            "operationId": "o1", "documentVersion": 2, "libraryVersion": 3,
            "record": None}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# The line the add-in owns
# ---------------------------------------------------------------------------

def test_its_own_line_is_encased_and_plain_ascii():
    line = marks.note_line(verdict(state.BEHIND))
    assert line.startswith(config.NOTE_PREFIX)
    assert line.endswith(config.NOTE_SUFFIX)
    assert all(ord(c) < 128 for c in line), "this text is posted into the NC"


def test_somebody_elses_text_survives_wherever_they_put_it():
    ours = marks.note_line(verdict(state.BEHIND))
    # Deliberately not "[UTP] something": a bare old-style line in a note this
    # version has never marked cannot be told apart from a mark an older
    # version left behind, and migrating those was chosen over protecting an
    # imitation of a format that is no longer written.
    for theirs in ("CHECK Z OFFSET", "first\n\nsecond", "   indented",
                   "my own words", "`UTP looks like ours but is not"):
        kept = marks.merge(marks.merge(theirs, ours), None)
        assert theirs in kept, theirs


def test_a_second_pass_changes_nothing():
    ours = marks.note_line(verdict(state.BEHIND))
    for before in ("", "CHECK Z", ours, ours + "\nCHECK Z", "top\n" + ours):
        once = marks.merge(before, ours)
        assert marks.merge(once, ours) == once, before


def test_their_line_in_our_style_below_ours_is_not_ours():
    ours = marks.note_line(verdict(state.BEHIND))
    note = ours + "\n" + config.NOTE_PREFIX + "check by hand"
    assert config.NOTE_PREFIX + "check by hand" in marks.merge(note, None)


def test_a_prefixed_line_without_a_closing_mark_is_not_ours():
    """Found by review: _mine checked the opening mark only.

    merge()'s docstring argues that encasing the line is what makes it
    recognisable. If only the opening mark is checked then that is not what is
    happening, and a sentence somebody typed starting with the prefix is
    deleted on the strength of a promise the code does not keep.
    """
    theirs = config.NOTE_PREFIX + "check this by hand before running"
    assert not theirs.endswith(config.NOTE_SUFFIX)
    assert theirs in marks.merge(theirs, marks.note_line(verdict(state.BEHIND)))


# ---------------------------------------------------------------------------
# What a verdict leads to
# ---------------------------------------------------------------------------

def test_an_untracked_operation_is_left_entirely_alone():
    for kind in (state.NOT_ADOPTED, state.NOT_UTP, state.UNKNOWN):
        owner = Owner("my own words", None, "Blue")
        assert marks.plan(owner, verdict(kind)) == {}, kind


def test_the_colour_they_chose_survives_being_adopted_and_updated():
    first = marks.plan(Owner("", None, "Red"), verdict(state.BEHIND))
    assert first["record"]["i"] == "Red"
    # Picking the newer preset makes state._record withhold the record, so a
    # fresh one is written. It must not capture the add-in's own colour.
    second = marks.plan(Owner(marks.note_line(verdict(state.BEHIND)),
                              first["record"], "Yellow"),
                        verdict(state.CURRENT, presetId="p2"))
    assert second["record"]["i"] == "Red"


def test_our_colour_comes_off_when_our_note_does():
    owner = Owner(marks.note_line(verdict(state.CURRENT)) + "\nmine",
                  ADOPTED, "Green")
    planned = marks.plan(owner, verdict(state.RETIRED, record=ADOPTED))
    assert planned["icon"]["to"] == "Gray"
    assert planned["note"]["to"] == "mine"


def test_a_setup_remembers_the_colour_it_had():
    """Found by review: setup_plan never writes a record, so strip() cannot
    put a setup's colour back and always paints it grey."""
    setup = Owner("", None, "Blue")
    planned = marks.setup_plan(setup, {state.BEHIND: 2, state.CURRENT: 5})
    assert "record" in planned, "nothing remembers the setup was Blue"
    assert planned["record"].get("i") == "Blue"


def test_clearing_a_note_during_their_own_edit_leaves_it_cleared():
    owner = Owner("", ADOPTED)
    assert marks.plan(owner, verdict(state.BEHIND, record=ADOPTED),
                      during_their_edit=True) == {}
    # and a save works it out again
    assert "note" in marks.plan(Owner("", ADOPTED),
                                verdict(state.BEHIND, record=ADOPTED))


def test_a_preset_change_that_moves_the_cut_says_so():
    """Measured: 3 of 441 presets in this shop carry tool_stepdown and
    tool_stepover, so picking the newer one can change the depth of cut, not
    only the feed. A toolpath left ungenerated then posts the old shape at the
    new numbers, which is the one failure here that reaches the machine."""
    plain = marks.note_line(verdict(state.BEHIND))
    assert config.NOTE_CHANGES_THE_CUT not in plain

    deeper = marks.note_line(verdict(state.BEHIND,
                                     changesTheCut=["tool_stepdown"]))
    assert config.NOTE_CHANGES_THE_CUT in deeper
    assert deeper.endswith(config.NOTE_SUFFIX)
    assert all(ord(c) < 128 for c in deeper)


def test_fusions_own_preset_is_not_a_shop_preset():
    """Nearly every preset in this shop's libraries is the one Fusion creates
    by itself, which is a tool's baseline and not somebody's decision. Treating
    it as a UTP gave notes reading "Default preset v1", version numbers stamped
    onto defaults in the shared library, and copies of them accumulating in
    dropdowns."""
    assert config.is_a_utp("P Titanium")
    assert config.is_a_utp("FAST")
    assert not config.is_a_utp("Default preset")
    assert not config.is_a_utp("  default PRESET ")
    # and a copy the add-in made of one before this rule existed, which is
    # what state.reconcile strips before asking
    for made in ("Default preset v1 (latest)", "Default preset v12", 
                 "Default preset (latest)"):
        assert not config.is_a_utp(presets.without_suffix(made)), made
    # a real one keeps its identity through the same stripping
    assert config.is_a_utp(presets.without_suffix("P Titanium v3 (latest)"))


# ---------------------------------------------------------------------------
# Comparing values
# ---------------------------------------------------------------------------

def test_nothing_in_common_is_not_the_same_as_agreeing():
    """An empty side shares no names with anything, so no value differs."""
    assert values.differences({}, {"tool_feedCutting": 1200.0}) == []
    assert values.differences({"a": 1.0}, {"b": 1.0}) == []


def test_floats_get_room_but_not_too_much():
    assert values.differences({"f": 1000.0}, {"f": 1000.0 + 1e-9}) == []
    assert values.differences({"f": 1000.0}, {"f": 1001.0}) == ["f"]


# ---------------------------------------------------------------------------
# Version numbers
# ---------------------------------------------------------------------------

def test_a_switches_file_that_cannot_be_read_turns_everything_off():
    for text in ("{ truncated", "", "[]", '{"on": 0}', '{"on": "false"}'):
        with open(config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            handle.write(text)
        settings.forget()
        assert settings.on("on") is False, text
        assert settings.damaged["file"] is True, text


def test_no_switches_file_at_all_is_a_fresh_install():
    os.remove(config.SETTINGS_FILE)
    settings.forget()
    assert settings.on("on") is True
    assert settings.damaged["file"] is False


def test_a_file_from_an_older_version_keeps_this_versions_defaults():
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
        json.dump({"on": False}, handle)
    settings.forget()
    assert settings.on("on") is False
    assert settings.on("mark") is True
    assert settings.damaged["file"] is False
    os.remove(config.SETTINGS_FILE)
    settings.forget()


# ---------------------------------------------------------------------------
# Naming presets in the dropdown
# ---------------------------------------------------------------------------

def test_the_newest_copy_says_so_and_the_retired_one_does_not():
    latest = presets.latest_name("P Titanium", 3)
    assert latest.endswith(config.LATEST_SUFFIX)
    assert "v3" in latest
    assert config.LATEST_SUFFIX not in presets.retired_name(latest, version=2)


def test_a_retired_name_does_not_collide_with_one_already_there():
    taken = ["P Titanium v2"]
    assert presets.retired_name("P Titanium v2 (latest)", taken=taken,
                                version=2) not in taken


# ---------------------------------------------------------------------------
# Meeting a newer version of the add-in
# ---------------------------------------------------------------------------

def test_a_higher_schema_stops_it_writing_and_an_unreadable_one_counts_as_higher():
    assert compat.may_write(config.SCHEMA)[0] is True
    assert compat.may_write(config.SCHEMA + 1)[0] is False
    # survey() answers 0 when nothing carries a schema, not None.
    assert compat.may_write(0)[0] is True, "no data is not newer data"


# ---------------------------------------------------------------------------
# The copy in a document's own tool library
# ---------------------------------------------------------------------------

class FakePreset:
    def __init__(self, name, held=None, params=None):
        self.name = name
        self.id = "copy-" + name
        self.attributes = Attrs(held or {})
        self._params = dict(params or {})

    class _Value:
        def __init__(self, value):
            self.value = value

    class _Param:
        def __init__(self, name, value):
            self.name = name
            self.value = FakePreset._Value(value)

    @property
    def parameters(self):
        items = [FakePreset._Param(n, v) for n, v in self._params.items()]

        class Coll:
            count = len(items)

            def item(self, i):
                return items[i]

        return Coll()


class FakeTool:
    def __init__(self, items):
        self._items = list(items)

    @property
    def presets(self):
        items = self._items

        class Coll:
            count = len(items)

            def item(self, i):
                return items[i]

        return Coll()


class FakeLibraryPreset:
    def __init__(self, name, values_now):
        self.name = name
        self.id = "lib-" + name
        self.values = dict(values_now)
        self.version = 2


def test_a_value_that_will_not_go_in_does_not_cause_a_new_copy_every_pass():
    """The churn. presets.apply copies the library's values into a fresh
    preset; any that will not take leave the copy differing from the library
    for ever, so plan() retired and re-added on every single pass and the
    dropdown grew without end. A copy records what the library held when it was
    made, and plan asks whether the library has moved since.
    """
    library_preset = FakeLibraryPreset("P Titanium",
                                       {"tool_feedCutting": 1200.0,
                                        "tool_coolant": "flood"})
    # The copy holds the feed but not the coolant: the write was accepted and
    # discarded, which is what was measured in a real document.
    copy = FakePreset(
        "P Titanium v2 " + config.LATEST_SUFFIX,
        held={config.KEY_SOURCE_PRESET: library_preset.id,
              config.KEY_VALUES: json.dumps(library_preset.values)},
        params={"tool_feedCutting": 1200.0, "tool_coolant": "mist"})
    tool = FakeTool([copy])

    assert presets.plan(tool, library_preset) == {}, "nothing has moved"

    # Now the shop really does change a feed.
    library_preset.values["tool_feedCutting"] = 1500.0
    moved = presets.plan(tool, library_preset)
    assert moved.get("add") == "P Titanium"
    assert "tool_feedCutting" in moved.get("because", [])


def test_a_copy_that_recorded_nothing_still_gets_compared():
    """Copies made before this existed have no snapshot. They fall back to the
    old comparison, and the plan says which comparison it used."""
    library_preset = FakeLibraryPreset("P Copper", {"tool_feedCutting": 900.0})
    copy = FakePreset("P Copper v1 " + config.LATEST_SUFFIX,
                      held={config.KEY_SOURCE_PRESET: library_preset.id},
                      params={"tool_feedCutting": 900.0})
    assert presets.plan(FakeTool([copy]), library_preset) == {}
    assert presets.stood_for(copy) is None


def test_an_operation_is_left_alone_when_something_could_not_be_established():
    """A library that would not open used to make every tool in it look absent,
    so operations using one read as untracked and had their notes and colours
    removed. The person then sees nothing flagged and ships the old feeds. A
    verdict that cannot be reached must leave what is there alone."""
    owner = Owner(marks.note_line(verdict(state.BEHIND)) + "\nCHECK Z",
                  ADOPTED, "Yellow")
    unsure = verdict(state.UNKNOWN, record=ADOPTED)
    unsure["leave alone"] = True
    assert marks.plan(owner, unsure) == {}
    # without the flag, an unknown verdict does take the note off, which is
    # right when the add-in genuinely knows the preset holds nothing
    assert "note" in marks.plan(owner, verdict(state.UNKNOWN, record=ADOPTED))
