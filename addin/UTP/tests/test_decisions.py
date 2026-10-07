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
# Handler base classes, so events can be imported. They only have to be classes
# somebody can inherit from; nothing here calls notify.
for _base in ("CustomEventHandler", "DocumentEventHandler",
              "ApplicationCommandEventHandler", "WorkspaceEventHandler"):
    setattr(sys.modules["adsk.core"], _base, type(_base, (object,), {}))
sys.modules["adsk.cam"].OperationBaseEventHandler = type(
    "OperationBaseEventHandler", (object,), {})
sys.modules["adsk"].doEvents = lambda: None
sys.modules["adsk"].cam = sys.modules["adsk.cam"]
sys.modules["adsk"].core = sys.modules["adsk.core"]

from utp import compat, config, marks, presets, settings, state, values  # noqa: E402

_SCRATCH = tempfile.mkdtemp()
config.SETTINGS_FILE = os.path.join(_SCRATCH, "switches.json")
# Kept out of the real diagnostics folder: some of what is tested here logs.
config.REPORT_DIR = _SCRATCH
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

    operationId = "o1"

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

def test_an_untracked_operation_that_was_never_marked_is_left_alone():
    """Nothing to remove, so nothing is planned.

    This used to be the whole of the coverage here and it proved nothing: with
    record=None and no add-in line in the note there is nothing to take off, so
    plan() is empty for EVERY state, including states that should mark. The
    dangerous direction is the test below.
    """
    for kind in (state.NOT_ADOPTED, state.NOT_UTP, state.UNKNOWN, state.RETIRED):
        owner = Owner("my own words", None, "Blue")
        assert marks.plan(owner, verdict(kind)) == {}, kind


def test_what_a_marked_operation_loses_and_what_it_keeps():
    """Which verdicts take an existing note off, which is the dangerous half.

    No note is documented as "never put on a shop preset" -- also "nothing to
    do" -- so removing a yellow "v3 available" does not say "I am unsure", it
    says "there was never anything here". That must only happen when the
    add-in actually knows the operation is no longer tracked.

    UNKNOWN is the case that matters. values.scalars cannot tell "this preset
    holds nothing" from "this preset could not be read", so a transient read
    failure used to retire the task silently. All three ways reconcile reaches
    UNKNOWN now set "leave alone", which this pins.
    """
    def marked(kind):
        line = marks.ours("P Titanium v2 - v3 available")
        owner = Owner(line + "\nCHECK Z OFFSET", ADOPTED, "Yellow")
        return marks.plan(owner, verdict(kind, record="P Titanium"))

    # Unsure: the note and the colour stay exactly as they are.
    for kind in (state.UNKNOWN,):
        plan = marked(kind)
        assert plan == {}, (
            "%s took the mark off a tracked operation; unsure must not read as "
            "'never tracked'. Got %s" % (kind, plan))

    # Known to be out of the system: the add-in's line goes, their words stay.
    for kind in (state.NOT_ADOPTED, state.NOT_UTP):
        plan = marked(kind)
        assert plan.get("note"), "%s left the add-in's line on" % kind
        assert plan["note"]["to"] == "CHECK Z OFFSET", (
            "%s did not keep their own words: %r" % (kind, plan["note"]["to"]))


def test_a_verdict_that_cannot_compare_says_so_instead_of_matching():
    """Every comparison works on the names both sides share.

    So a side that is empty shares nothing, nothing differs, and the verdict
    fell through to "matches the library" -- green, which means do nothing.
    And a parameter present on only one side disagreed with nothing, so a shop
    preset that GAINED a depth of cut read as current and was labelled with the
    library's version number.

    versions.needed and library._describes both guard this. state.reconcile,
    the one that paints the dot, did not.
    """
    import inspect

    source = inspect.getsource(state.reconcile)
    assert "set(library_preset.values) - set(preset_values)" in source, (
        "reconcile no longer checks that the two sides hold the same "
        "parameter names, so a preset that gains one reads as current")
    assert "if not operation_values:" in source, (
        "reconcile no longer checks that the operation's own values could be "
        "read, so an unreadable operation reads as current")
    # and the state it lands in is one that marks, not one that goes quiet
    where = source.index("set(library_preset.values) - set(preset_values)")
    assert "BEHIND" in source[where:where + 1400], (
        "a name-set mismatch should read as behind, so there is something to "
        "pick; going quiet would hide it")


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
    # And without the flag too. This used to assert the opposite, on the
    # reasoning that it is "right when the add-in genuinely knows the preset
    # holds nothing" -- but values.scalars cannot tell a preset that holds
    # nothing from one that could not be read, and reconcile's own wording for
    # this case is "nothing could be READ from its preset". So the state alone
    # means do not touch, and the flag is belt and braces.
    assert marks.plan(owner, verdict(state.UNKNOWN, record=ADOPTED)) == {}


def test_an_operation_on_a_preset_that_governs_the_cut_keeps_saying_so():
    """The warning used to vanish at the moment it mattered. "changes the cut"
    attaches to behind, so the instant somebody picked the newer preset the
    verdict became current and the note went plain green -- and the regeneration
    is needed after the pick, not before.

    Measured on 6 October: switching a preset moved an operation's feed and left
    isToolpathValid True, so Fusion does not treat the toolpath as stale and
    there is nothing for the add-in to read. So the note says it standing, while
    the operation is on a preset that decides the shape of the cut.
    """
    plain = marks.note_line(verdict(state.CURRENT))
    assert config.NOTE_SETS_THE_CUT not in plain

    governed = marks.note_line(verdict(state.CURRENT,
                                       carriesShape=["tool_stepdown"]))
    assert config.NOTE_SETS_THE_CUT in governed
    assert governed.endswith(config.NOTE_SUFFIX)
    assert all(ord(c) < 128 for c in governed)

    # and the two wordings are not the same sentence: one is about an update
    # that has not happened, the other about a toolpath that may be wrong now
    behind = marks.note_line(verdict(state.BEHIND,
                                     changesTheCut=["tool_stepdown"]))
    assert config.NOTE_CHANGES_THE_CUT in behind
    assert config.NOTE_SETS_THE_CUT not in behind


def test_nothing_promises_an_undo_that_does_not_happen():
    """Measured on 6 October: a check wrote four notes, four records and two
    setup notes; one undo was executed and the log confirms it ran; nothing
    reverted. What this add-in writes to notes, colours and attributes is not in
    Fusion's undo stack.

    Three screens had been telling people Ctrl+Z was the way back, which is the
    one thing they would reach for. This pins the wording so it cannot drift
    back in without somebody re-measuring.
    """
    for name in ("MARKED_TAIL", "UNMARKED", "UNMARK_CONFIRM", "COMMAND_TOOLTIP"):
        said = getattr(config, name)
        assert "ctrl+z" not in said.lower(), (
            "%s promises an undo that does not happen: %r" % (name, said))
    # the way back that does work is offered instead
    assert "Remove all notes" in config.MARKED_TAIL
    assert "Check this document" in config.UNMARKED


def test_nothing_reads_the_libraries_on_a_thread_of_its_own():
    """The libraries are read on Fusion's main thread, from an ordinary event.

    This was a worker thread firing a custom event a few seconds after load.
    It cost a session: the fire landed while Fusion was still starting, so the
    read never happened, and another worker thread calling into Fusion at the
    same moment died -- the test agent stopped taking jobs and stayed stopped.
    The API is main-thread only and nothing here is worth a thread.

    Pinned because the thread is the tempting fix every time this looks slow.
    """
    from utp import events

    source = open(os.path.join(HERE, "..", "utp", "events.py"),
                  encoding="utf-8").read()
    for banned in ("import threading", "threading.Thread",
                   "registerCustomEvent", "fireCustomEvent"):
        assert banned not in source, (
            "events.py is back to driving Fusion off its own thread (%r). "
            "The libraries are read from workspaceActivated, on the main "
            "thread." % banned)
    assert hasattr(events, "_WorkspaceActivated")
    assert config.CAM_WORKSPACES, "nothing names the workspace that reads them"


def test_switching_the_add_in_off_turns_the_early_read_off_too():
    """Nothing happens on its own when the master switch is off, and that has to
    include work the add-in schedules for itself rather than work somebody asked
    for.
    """
    from utp import events, library

    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
        json.dump({"on": False}, handle)
    settings.forget()
    try:
        assert not settings.on("on")
        reads = []
        was_cached, was_warm = library.cached, library.warm
        library.cached = lambda *a, **k: reads.append(1) or ({}, False)
        library.warm = lambda: False
        try:
            events._warm_now("test")
        finally:
            library.cached, library.warm = was_cached, was_warm
        assert reads == [], "read the libraries with the add-in switched off"
    finally:
        os.remove(config.SETTINGS_FILE)
        settings.forget()


def test_every_switch_the_code_asks_about_is_a_switch_that_exists():
    """settings.on answers True for a name it does not know.

    That is the right default for a file written by an older version, and a trap
    for a typo or a rename: a switch that does not exist reads as switched on, so
    the thing it was meant to govern happens anyway, silently. It happened --
    _may_write kept a default of trigger="save" after the save switch was renamed
    to "open", which would have ignored that switch entirely.

    So every literal the package passes to settings.on has to be a real control.
    """
    import glob
    import re

    known = {key for key, _l, _g, _s in settings.CONTROLS}
    package = os.path.join(HERE, "..", "utp")
    asked = {}
    for path in glob.glob(os.path.join(package, "*.py")):
        text = open(path, encoding="utf-8").read()
        for found in re.finditer(r"""(?:settings\.)?on\(["'](\w+)["']\)""", text):
            asked.setdefault(found.group(1), []).append(os.path.basename(path))
        # Defaults that name a switch, like trigger="open" on _may_write.
        for found in re.finditer(r"""trigger\s*=\s*["'](\w+)["']""", text):
            asked.setdefault(found.group(1), []).append(os.path.basename(path))
    assert asked, "found nothing asking about switches; the pattern is wrong"
    unknown = {name: where for name, where in asked.items() if name not in known}
    assert not unknown, (
        "these are asked about but are not switches, so they read as on: %s. "
        "Known switches: %s" % (unknown, sorted(known)))


def test_the_tidy_never_offers_a_preset_an_operation_is_running():
    """The first of removable's three rules, and the only one that destroys work.

    Deleting a copy an operation points at re-points that operation at whatever
    is left, silently, with its values unchanged -- so it ends up named after a
    preset whose feeds it does not hold. There is no undo after a save.

    Worth a test of its own because the set that protects them was, until now,
    built from the verdicts, and a verdict is allowed not to look: state reads
    an operation's preset through a getattr that answers None on an exception,
    so "could not read its preset" and "on no preset" produced the same verdict
    with no failure recorded. The copy in use looked spare. The set is walked
    from the operations now, and this pins what it is for.
    """
    library_tool = type("T", (), {"presets": {"lib-P Titanium": None}})()

    def copy(name, version):
        return FakePreset(name, held={config.KEY_SOURCE_PRESET: "lib-P Titanium",
                                      config.KEY_VERSION: version})

    one, two, three = copy("P Titanium v1", "1"), copy("P Titanium v2", "2"), \
        copy("P Titanium v3", "3")
    tool = FakeTool([one, two, three])

    # Nothing in use: the two older copies go, the newest is kept.
    spare = presets.removable(tool, library_tool, set())
    assert len(spare) == 2, spare
    assert [row[1] for row in spare] == ["P Titanium v2", "P Titanium v1"], spare

    # The oldest is in use: it must not be offered, whatever else is.
    spare = presets.removable(tool, library_tool, {one.id})
    offered = [row[1] for row in spare]
    assert "P Titanium v1" not in offered, (
        "offered a copy an operation is running: %s" % offered)

    # Every copy in use: nothing at all is offered.
    assert presets.removable(
        tool, library_tool, {one.id, two.id, three.id}) == []

    # And one in use with only one other present leaves nothing to take, since
    # the most recently retired copy is kept as the record of what it ran.
    assert presets.removable(FakeTool([one, two]), library_tool, {two.id}) == []


def test_numbering_the_shop_library_is_on_by_default():
    """Decided on 7 October: the shop wants version numbers on.

    It is the only thing the add-in writes outside somebody's own document, and
    the only write with no undo, so it is worth being deliberate about. The
    two-writer race it carries is narrowed and detected rather than closed --
    see versions.review -- and the alternative is notes that can only say
    "something newer" instead of "v3 available".

    Pinned because this default is the sort of thing that gets flipped while
    investigating something else. The test agent sets it False for the duration
    of a job, on purpose, to keep tests off the real libraries; that is a
    runtime guard and must not become the shipped default.
    """
    import os
    import tempfile

    scratch = tempfile.mkdtemp()
    was, was_mark = config.SETTINGS_FILE, config.SETTINGS_CHOSEN
    config.SETTINGS_FILE = os.path.join(scratch, "none.json")
    # The mark too. Without this the test read the real machine's mark, so a
    # machine that had ever saved switches made it fail -- it was asserting
    # something about this computer rather than about a fresh install.
    config.SETTINGS_CHOSEN = os.path.join(scratch, "mark", "none")
    settings.forget()
    try:
        assert config.MAY_BUMP_LIBRARY_VERSIONS is True
        assert settings.default("stamp") is True
        assert settings.on("stamp") is True, "a fresh install would not number"
    finally:
        config.SETTINGS_FILE, config.SETTINGS_CHOSEN = was, was_mark
        settings.forget()


def test_the_add_in_taking_its_own_note_off_is_not_somebody_clearing_it():
    """Reported from real use on 7 October, and the cause of the flakiness.

    Create an operation; pick a tool whose preset the add-in tracks and a note
    appears; then, without leaving the dialog, pick a tool whose only preset is
    the one Fusion makes by itself. The add-in correctly takes its line off,
    because that is not a shop preset. Pick the first tool again and the note
    never comes back -- not even on OK.

    Because "this was marked before, and there is no line of ours there now" is
    exactly what a person deleting the note looks like, and the add-in stands
    down for that on purpose so a note can be deleted at all. Its own removal
    was indistinguishable, and the record survives a "not a UTP tool" verdict,
    so the guard latched for the rest of the visit.

    Both halves are pinned here: the sequence must end with the note back, and
    a person clearing it must still be left alone.
    """
    marks._last_cleared["id"] = None

    owner = Owner("", None, "Gray")
    steps = []
    for kind in (state.CURRENT, state.NOT_UTP, state.CURRENT):
        change = marks.plan(owner, verdict(kind), during_their_edit=True)
        marks.apply(owner, change)
        steps.append(sorted(change))

    assert "note" in steps[0], "picking a tracked tool wrote no note: %s" % steps
    assert "note" in steps[1], "picking an untracked tool left the note on"
    assert owner.notes, (
        "the note did not come back after picking the tracked tool again; "
        "the add-in mistook its own removal for somebody deleting it")
    assert "note" in steps[2]

    # The feature that guard exists for still has to work: a person clearing
    # the note is left alone while they are still editing.
    owner.notes = ""
    during = marks.plan(owner, verdict(state.CURRENT, record="P Titanium"),
                        during_their_edit=True)
    assert during == {}, (
        "a note the person cleared was put straight back, so it cannot be "
        "deleted at all: %s" % during)
    # and a check or an open works it out again
    after = marks.plan(owner, verdict(state.CURRENT, record="P Titanium"))
    assert "note" in after, "a check no longer restores a cleared note"


def test_a_whole_document_pass_does_not_stand_the_cleared_note_guard_down():
    """The memory of "we took this line off" is one slot, and must stay one.

    operationId is a small per-document integer, so two open documents share
    ids. And a pass removes many lines at once: held as a set, every operation
    in the job would be remembered as "we cleared it", and a person could then
    not delete any of those notes because the guard would never fire again.

    So a pass over several operations must leave at most the last one
    remembered, and clearing a note the add-in did NOT just remove must still be
    respected.
    """
    marks._last_cleared["id"] = None

    class Numbered(Owner):
        def __init__(self, number, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.operationId = number

    # Three operations lose their line in one pass, as Remove all notes does.
    for number in (1, 2, 3):
        owner = Numbered(number, marks.ours("P Titanium v6"), ADOPTED, "Green")
        marks.apply(owner, {"note": {"from": owner.notes, "to": ""}})
    assert marks._last_cleared["id"] == 3, (
        "the memory is not one slot any more: %r" % (marks._last_cleared,))

    # Operation 1 was cleared by the pass, not by a person -- but that was two
    # operations ago, so a person clearing ITS note now must be respected.
    first = Numbered(1, "", ADOPTED, "Gray")
    plan = marks.plan(first, verdict(state.CURRENT, record="P Titanium"),
                      during_their_edit=True)
    assert plan == {}, (
        "a pass's own removals are suppressing the guard for operations it is "
        "no longer about, so those notes cannot be deleted: %s" % plan)


def test_moving_to_another_shop_preset_and_tuning_it_stays_grey():
    """The commonest thing to do in one visit to the dialog.

    Pick the newer preset AND adjust a feed before pressing OK. The record names
    the preset the operation used to be on, so state._record withholds itself --
    correctly, it no longer describes where these values came from. But the FACT
    that somebody put this operation on a shop preset is still true, and losing
    it with the name dropped the verdict to "never set from a UTP", which writes
    no note. The operation left the system silently, and only an exact match
    would ever have brought it back.
    """
    # A record naming a DIFFERENT preset from the one the operation is on now.
    moved = dict(ADOPTED)
    moved[config.KEY_ADOPTED_PRESET] = "some-older-preset"
    owner = Owner(marks.ours("P Copper v2"), moved, "Green")

    assert state._record(owner, "p1") is None, (
        "a record naming another preset should not be trusted to describe this "
        "one")
    assert state._was_adopted(owner) is True, (
        "the fact that it was put on a shop preset is still true")

    # And the verdict that follows must be Custom, which marks, not
    # "not adopted", which does not.
    said = marks.note_line(verdict(state.CUSTOM, record=None))
    assert said and config.NOTE_CUSTOM in said
    nothing = marks.note_line(verdict(state.NOT_ADOPTED))
    assert nothing is None, "not adopted should still say nothing"


def test_a_value_the_document_copy_cannot_hold_does_not_say_pick_the_latest():
    """Yellow has to be actionable or it stops being read.

    Two situations look identical to the name-set check: the library gained a
    value since this copy was made, where picking the newer preset brings it in;
    and the value was always there and never went into the copy, where picking
    makes another copy that lacks it too and presets.plan rightly refuses. The
    first is "update available". The second has to say something else.
    """
    gained = verdict(state.BEHIND, libraryVersion=3, documentVersion=2)
    assert "available" in marks.note_line(gained), (
        "a preset that gained a value should still send somebody to the dropdown")

    cannot = verdict(state.BEHIND, libraryVersion=3, documentVersion=2,
                     copyCannotHold=["tool_stepdown"])
    said = marks.note_line(cannot)
    assert config.NOTE_COPY_CANNOT_HOLD in said, said
    assert "available" not in said, (
        "still telling somebody to pick a preset that cannot help: %s" % said)
    assert config.NOTE_UPDATE not in said


def test_switches_that_vanish_after_being_chosen_do_not_come_back_on():
    """OneDrive resolves a conflict by renaming, not by corrupting.

    settings._read already refuses to guess when the file is there and cannot be
    read, for the right reason: the person who switched something off is the
    person it must stay off for. An absent file read as a fresh install, and a
    fresh install has everything on -- including the two switches that write
    outside somebody's own document, one of which deletes presets and one of
    which writes to the shared shop library.

    Documents is redirected into OneDrive on a lot of machines, and save()'s own
    comment has said so all along. So a mark is kept where nothing syncs, and an
    absent file means defaults only if nothing was ever chosen here.
    """
    scratch = tempfile.mkdtemp()
    was_file, was_mark = config.SETTINGS_FILE, config.SETTINGS_CHOSEN
    config.SETTINGS_FILE = os.path.join(scratch, "UTP switches.json")
    config.SETTINGS_CHOSEN = os.path.join(scratch, "mark", "switches-chosen")
    try:
        # A fresh machine: no file, no mark. Defaults, which are everything on.
        settings.forget()
        assert settings.on("on") is True
        assert settings.damaged["gone"] is False

        # Somebody turns the two outward-facing ones off.
        settings.save({"on": True, "open": True, "edit": True, "mark": True,
                       "presets": True, "tidy": False, "stamp": False})
        settings.forget()
        assert settings.on("tidy") is False and settings.on("stamp") is False
        assert os.path.exists(config.SETTINGS_CHOSEN), "no mark was left"

        # A sync renames the file out from under it.
        os.replace(config.SETTINGS_FILE,
                   config.SETTINGS_FILE.replace(".json", "-DESKTOP-AB1.json"))
        settings.forget()
        settings.values()          # damaged is only set once the read happens
        assert settings.damaged["gone"] is True, (
            "a chosen file going missing was read as a fresh install")
        # Only the two that cannot be taken back. Standing everything down was
        # the first attempt and it stopped the add-in doing anything at all,
        # which is its own silent failure and not what a missing file is
        # evidence of.
        for key in settings.CANNOT_BE_TAKEN_BACK:
            assert settings.on(key) is False, (
                "%s came back on by itself; stamp writes to the shared library "
                "and tidy deletes presets, and neither can be undone" % key)
        for key in ("on", "open", "edit", "mark"):
            assert settings.on(key) is True, (
                "%s was stood down, so the add-in does nothing and says nothing "
                "-- notes come back off with Remove all notes, so there is no "
                "reason to refuse them" % key)

        # And saving from the Switches dialog is the cure.
        settings.save({key: True for key, _l, _g, _s in settings.CONTROLS})
        settings.forget()
        settings.values()
        assert settings.damaged["gone"] is False
        assert settings.on("on") is True
    finally:
        config.SETTINGS_FILE, config.SETTINGS_CHOSEN = was_file, was_mark
        settings.forget()
