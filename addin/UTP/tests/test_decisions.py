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
