"""The half of this add-in that only Fusion can answer for.

    python tools/ask_fusion.py addin/UTP/tests/run_integration.py --writes

Run it against the bench document, which must be open and must have "UTP TEST"
in its name. It restores what it changes.

Why this exists. There are unit tests over every decision this add-in makes and
they run in a twentieth of a second without Fusion. Not one of the faults found
in the first two days of real use was a decision:

  a subscription collected by the garbage collector, so the edit listener went
  silent part-way through a session
  a report object missing two attributes the shared code counts with, so the
  save path's preset work raised and was swallowed
  a cold library cache deciding nothing and saying so only in a log file
  nothing selected when an operation dialog closes, so a first edit read the
  libraries and then marked nothing

Every one of those lives where this code meets Fusion: object lifetimes, which
events fire and when, what is still valid after an update, what a cache holds.
None of them are reachable by reasoning about dicts, and three code reviews read
past two of them. This is the suite that catches that class.

Each check says PASS, FAIL or SKIP. SKIP is used honestly: some things can only
be established by a person in front of Fusion, and a check that quietly tested
something easier instead would be worse than no check.
"""

import gc
import json
import os
import time

import adsk.cam
import adsk.core

from utp import (compat, config, diagnostics, events, library, marks, passes,
                 presets, settings, state, values)


class Quiet:
    """Enough of a Report for the shared pass functions."""

    def __init__(self):
        self.wrote = 0
        self.failures = 0

    def note(self, message, **detail):
        pass

    def failed(self, message):
        self.failures += 1


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------

class Bench:
    """The document under test, and how to put it back."""

    def __init__(self, app):
        self.app = app
        self.document = app.activeDocument
        self.cam = self.document.products.itemByProductType("CAMProductType")
        self.before = {}
        for operation in self.operations():
            self.before[operation.operationId] = {
                "notes": operation.notes or "",
                "icon": marks._icon(operation),
            }
        self.setup_notes = [self.cam.setups.item(i).notes or ""
                            for i in range(self.cam.setups.count)]
        # Every switch on for the duration, and put back afterwards.
        #
        # Without this the suite reads whatever the machine happens to be set
        # to, and a switch that blocks writing turns most of these checks into
        # vacuous passes rather than failures: "a pass marks the document and
        # then settles" asks whether the second pass wrote more than the first,
        # and 0 then 0 satisfies it perfectly. Measured 6 October, with the
        # open switch off: one check failed honestly and three passed for no
        # reason at all. A suite that goes quiet when it is disabled is worse
        # than no suite.
        self.switches = None
        if os.path.exists(config.SETTINGS_FILE):
            with open(config.SETTINGS_FILE, encoding="utf-8") as handle:
                self.switches = handle.read()
        settings.save({key: True for key, _l, _g, _s in settings.CONTROLS})

    def operations(self):
        return passes._walk(self.cam)[0]

    def tools(self):
        quiet = Quiet()
        tools, ok = library.cached(quiet)
        return tools if ok else {}

    def restore(self):
        """Put the notes, colours and switches back, so the suite can run again."""
        try:
            if self.switches is None:
                if os.path.exists(config.SETTINGS_FILE):
                    os.remove(config.SETTINGS_FILE)
            else:
                with open(config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
                    handle.write(self.switches)
            settings.forget()
        except Exception:
            pass
        with marks.holding():
            for operation in self.operations():
                was = self.before.get(operation.operationId)
                if not was:
                    continue
                if (operation.notes or "") != was["notes"]:
                    operation.notes = was["notes"]
                if was["icon"] and marks._icon(operation) != was["icon"]:
                    value = getattr(adsk.cam.NoteIconColors, was["icon"], None)
                    if value is not None:
                        operation.noteIconColor = value
            for index, notes in enumerate(self.setup_notes):
                if index < self.cam.setups.count:
                    if (self.cam.setups.item(index).notes or "") != notes:
                        self.cam.setups.item(index).notes = notes

    def a_tracked_operation(self):
        """One the add-in has something to say about, or None."""
        tools = self.tools()
        seen = {}
        for operation in self.operations():
            verdict = state.reconcile(operation, tools, seen)
            if verdict["state"] in (state.CURRENT, state.BEHIND, state.CUSTOM):
                return operation, verdict
        return None, None


def pump(times=40):
    for _ in range(times):
        adsk.doEvents()


CHECKS = []


def check(name):
    def keep(function):
        CHECKS.append((name, function))
        return function
    return keep


# ---------------------------------------------------------------------------
# The listeners: do they exist, fire, and survive?
# ---------------------------------------------------------------------------

@check("writing is permitted, so the rest of this suite means something")
def _may_write_at_all(bench):
    """Put first on purpose.

    Most of what follows asks "did the add-in write the right thing". With
    writing switched off they ask "did it write nothing", which almost all of
    them accept. Bench forces every switch on, so this failing means something
    other than the switches is refusing -- a read-only file, a document the
    add-in will not claim, a newer schema -- and every later verdict should be
    read as suspect.
    """
    allowed, held_back = events._may_write(bench.document, bench.operations(),
                                           "open")
    if not allowed:
        return "FAIL", ("writing is refused: %s. Every check after this that "
                        "expects a write will fail, and several that expect "
                        "nothing will pass for the wrong reason." % held_back)
    return "PASS", "the add-in may write to the bench"


@check("the listeners are attached")
def _attached(bench):
    held = sorted(events._held.keys())
    if len(events._handlers) < 5:
        return "FAIL", "only %d handlers attached" % len(events._handlers)
    if "cam events" not in held or "operation event" not in held:
        return "FAIL", ("the CAM event manager is not being kept alive: %s. "
                        "This is the shape of the fault where the subscription "
                        "was collected and the edit listener went silent." % held)
    return "PASS", "%d handlers, keeping %s" % (len(events._handlers), held)


@check("entering Manufacture reads the libraries")
def _warmed(bench):
    """What stops an edit or an open paying for the Hub read.

    The handler is called here the same way Fusion calls it, with the workspace
    id it actually raises, so a wrong id shows up as a failure rather than as an
    add-in that quietly never warms. That is not hypothetical: the save command
    id was wrong for eight releases for exactly this reason.
    """
    attached = [h for _e, h in events._handlers
                if isinstance(h, events._WorkspaceActivated)]
    if not attached:
        return "FAIL", "nothing is listening for the workspace to change"

    class Args:
        class workspace:
            id = config.CAM_WORKSPACES[0]

    library.forget()
    started = time.time()
    attached[0].notify(Args())
    if not library.warm():
        return "FAIL", ("entering %s did not read the libraries"
                        % config.CAM_WORKSPACES[0])
    if library.incomplete():
        return "FAIL", "a library would not open, so nothing can be decided"

    # A workspace that is not Manufacture must not pay for it.
    library.forget()

    class Other:
        class workspace:
            id = "FusionSolidEnvironment"

    attached[0].notify(Other())
    if library.warm():
        return "FAIL", "entering the Design workspace read the shop libraries"

    attached[0].notify(Args())
    tools, _ok = library.cached(Quiet(), None)
    return "PASS", ("read %d tools in %.1fs on entering %s, and nothing on "
                    "entering Design"
                    % (len(tools), time.time() - started,
                       config.CAM_WORKSPACES[0]))


@check("the edit listener fires")
def _fires(bench):
    operation = bench.operations()[0]
    held = operation.notes or ""
    before = events.calls()["edits"]
    operation.notes = "integration probe"
    pump()
    after = events.calls()["edits"]
    with marks.holding():
        operation.notes = held
    pump(10)
    if after <= before:
        return "FAIL", "operationBaseChanged did not fire for a note write"
    return "PASS", "edits %d -> %d" % (before, after)


@check("the edit listener survives collection")
def _survives(bench):
    operation = bench.operations()[0]
    held = operation.notes or ""
    for _ in range(3):
        gc.collect()
    before = events.calls()["edits"]
    operation.notes = "integration probe after gc"
    pump()
    after = events.calls()["edits"]
    with marks.holding():
        operation.notes = held
    pump(10)
    if after <= before:
        return "FAIL", ("the listener stopped firing after a garbage "
                        "collection, which is exactly how it failed before")
    return "PASS", "still firing after three collections"


@check("a cold library cache puts the edit by instead of dropping it")
def _cold_edit(bench):
    operation, verdict = bench.a_tracked_operation()
    if operation is None:
        return "SKIP", "no tracked operation on the bench"
    library.forget()
    del events._waiting[:]
    held = operation.notes or ""
    # A line of ours that is wrong, not a cleared note. Clearing one is a
    # deliberate feature -- a note somebody deletes while editing stays deleted
    # until a save -- so using that as the nudge tested the wrong thing and
    # failed for the right reason the first time this suite ran.
    operation.notes = marks.ours("deliberately wrong")
    pump()
    waiting = len(events._waiting)
    if not waiting:
        with marks.holding():
            operation.notes = held
        return "FAIL", ("the edit was seen with a cold cache and not put by, "
                        "so nothing would ever come back to it")
    # and the command-end hook reads the libraries and marks what was waiting
    events._mark_what_they_just_edited("IronEditOperation")
    pump()
    now = operation.notes or ""
    with marks.holding():
        operation.notes = held
    pump(10)
    if "deliberately wrong" in now:
        return "FAIL", ("the hook read the libraries and left the wrong line "
                        "in place: %r" % now)
    if not now.startswith(config.NOTE_PREFIX):
        return "FAIL", "nothing was written when the dialog closed: %r" % now
    return "PASS", "put by, then corrected when the dialog closed: %r" % now


@check("a warm cache marks the edit at once")
def _warm_edit(bench):
    operation, verdict = bench.a_tracked_operation()
    if operation is None:
        return "SKIP", "no tracked operation on the bench"
    bench.tools()                   # warm
    if not library.warm():
        return "SKIP", "the libraries could not be read"
    held = operation.notes or ""
    del events._waiting[:]
    operation.notes = marks.ours("deliberately wrong")
    pump()
    now = operation.notes or ""
    put_by = len(events._waiting)
    with marks.holding():
        operation.notes = held
    pump(10)
    if put_by:
        return "FAIL", "it was put by although the cache was warm"
    if "deliberately wrong" in now:
        return "FAIL", "a warm edit left the wrong line in place: %r" % now
    if not now.startswith(config.NOTE_PREFIX):
        return "FAIL", "a warm edit wrote nothing: %r" % now
    return "PASS", "corrected inside the edit: %r" % now


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

@check("an opening pass marks the document and then settles")
def _open_settles(bench):
    """A document is marked once and then left alone.

    Something is deliberately broken first. Two passes that both write nothing
    satisfy "it settles" without testing anything, and that is what this check
    did until 6 October, when it passed with writing switched off.
    """
    operation, _verdict = bench.a_tracked_operation()
    if operation is None:
        return "SKIP", "no tracked operation on the bench"
    held = operation.notes or ""
    try:
        with marks.holding():
            operation.notes = marks.ours("deliberately wrong")
        library.forget()
        first = events.mark_document(bench.document, "integration: first pass")
        second = events.mark_document(bench.document, "integration: second pass")
    finally:
        if (operation.notes or "") == marks.ours("deliberately wrong"):
            with marks.holding():
                operation.notes = held
    if not first:
        return "FAIL", ("a wrong note was waiting and the pass wrote nothing, "
                        "so either it cannot write or it cannot see the fault")
    if second:
        return "FAIL", ("the second pass wrote %d more marks, so the document "
                        "never settles and dirties every time" % second)
    return "PASS", "first pass wrote %d, second wrote nothing" % first


@check("a pass keeps to its budget and carries on next time")
def _pass_budget(bench):
    total = len(bench.operations())
    if total < 2:
        return "SKIP", "needs more than one operation"
    was = config.SAVE_SECONDS
    # Small enough that one pass cannot finish the document, not so small that
    # it cannot start it. Zero progress at all is a separate thing and the
    # add-in now guarantees one operation a pass whatever the budget says.
    config.SAVE_SECONDS = 0.001
    _state = events._state
    _state.pop("save cursor", None)
    try:
        seen = []
        for _ in range(4):
            events.mark_document(bench.document, "integration: budget")
            seen.append(list(_state.get("save cursor", {}).values()))
        flat = [v[0] for v in seen if v]
    finally:
        config.SAVE_SECONDS = was
        _state.pop("save cursor", None)
    if len(set(flat)) < 2:
        return "FAIL", ("the cursor did not move across passes (%s), so a "
                        "document too big for one pass would never finish" % flat)
    return "PASS", "cursor advanced across passes: %s" % flat


@check("a save writes nothing, so the document does not dirty")
def _save_writes_nothing(bench):
    """The regression guard for the double-save.

    Marking during a save landed after Fusion's snapshot on a cloud document and
    left the file modified the instant the save finished. Measured 6 October: a
    save that wrote four notes left an asterisk in the title bar and needed a
    second save to settle; a save with nothing to write did not. So a save writes
    nothing at all now, and this holds that.

    Deliberately done with a backlog waiting, because a save that writes nothing
    when there was nothing to write proves nothing. One note is made wrong first,
    and it has to still be wrong afterwards.

    The handler is called with the id Fusion actually raises rather than a real
    save being executed: a real save would persist whatever state the bench is
    part-way through restoring.
    """
    operations = bench.operations()
    if not operations:
        return "SKIP", "no operations on the bench"
    target = operations[0]
    held = target.notes or ""
    wrong = marks.ours("deliberately wrong, a save must not fix this")
    try:
        with marks.holding():
            target.notes = wrong
        before = [(o.name, o.notes or "") for o in bench.operations()]

        class Args:
            commandId = "PLM360SaveCommand"

        events._CommandStarting().notify(Args())

        after = [(o.name, o.notes or "") for o in bench.operations()]
    finally:
        with marks.holding():
            target.notes = held
    changed = [a[0] for a, b in zip(after, before) if a[1] != b[1]]
    if changed:
        return "FAIL", ("a save wrote to %d operation(s) (%s); on a cloud "
                        "document those writes land after the snapshot and the "
                        "file needs saving twice" % (len(changed), changed[:4]))
    if not any(text == wrong for _name, text in after):
        return "FAIL", "the wrong note vanished, so something else wrote instead"
    return "PASS", ("%d operations, one with a wrong note waiting, and the save "
                    "wrote nothing" % len(after))


@check("setups are marked by a pass, but only a complete one")
def _setups(bench):
    with marks.holding():
        for i in range(bench.cam.setups.count):
            bench.cam.setups.item(i).notes = ""
    library.forget()
    events.mark_document(bench.document, "integration: setups")
    said = [bench.cam.setups.item(i).notes or ""
            for i in range(bench.cam.setups.count)]
    ours = [n for n in said if n.startswith(config.NOTE_PREFIX)]
    tracked = 0
    tools = bench.tools()
    seen = {}
    for operation in bench.operations():
        if state.reconcile(operation, tools, seen)["state"] in (
                state.CURRENT, state.BEHIND, state.CUSTOM):
            tracked += 1
    if tracked and not ours:
        return "FAIL", ("%d tracked operations and no setup note; only the "
                        "button used to write these" % tracked)
    if not tracked:
        return "SKIP", "nothing tracked on the bench, so no setup has anything to say"
    return "PASS", "%d of %d setups marked" % (len(ours), len(said))


# ---------------------------------------------------------------------------
# The button's pass
# ---------------------------------------------------------------------------

@check("a check settles, so a second one writes nothing")
def _check_settles(bench):
    library.forget()
    passes.run(bench.app)
    _path, _counts, message = passes.run(bench.app)
    headline = message.splitlines()[0]
    if " 0 of " not in headline:
        return "FAIL", ("a second check still had work to do: %r. The document "
                        "never settles." % headline)
    return "PASS", headline


@check("a check adds one preset when the library moves, and never a second")
def _no_churn(bench):
    tools = bench.tools()
    target = None
    seen = {}
    for operation in bench.operations():
        verdict = state.reconcile(operation, tools, seen)
        if verdict.get("libraryPresetId") and verdict["state"] == state.CURRENT:
            target = verdict
            break
    if target is None:
        return "SKIP", "no operation sits on a readable library preset"

    libraries = adsk.cam.CAMManager.get().libraryManager.toolLibraries
    url = None
    for path, asset in library._walk(
            libraries,
            libraries.urlByLocation(adsk.cam.LibraryLocations.HubLibraryLocation)):
        if "TEST" in asset.leafName:
            url = asset
            break
    if url is None:
        return "SKIP", "no TEST library to move"

    def nudge(by):
        shelf = libraries.toolLibraryAtURL(url)
        for i in range(shelf.count):
            tool = shelf.item(i)
            for j in range(tool.presets.count):
                preset = tool.presets.item(j)
                if preset.id == target["libraryPresetId"]:
                    found = preset.parameters.itemByName("tool_feedCutting")
                    if found is None:
                        return None
                    was = found.value.value
                    found.value.value = was + by
                    libraries.updateToolLibrary(url, shelf)
                    return was
        return None

    def dropdown():
        counted = 0
        for _key, tool in passes._document_tools(bench.cam).items():
            for i in range(tool.presets.count):
                if tool.presets.item(i).name.endswith(config.LATEST_SUFFIX):
                    counted += 1
        return counted

    was = nudge(77.0)
    if was is None:
        return "SKIP", "that preset has no feed to move"
    try:
        library.forget()
        passes.run(bench.app)
        after_one = dropdown()
        for _ in range(2):
            library.forget()
            passes.run(bench.app)
        after_three = dropdown()
    finally:
        shelf = libraries.toolLibraryAtURL(url)
        for i in range(shelf.count):
            tool = shelf.item(i)
            for j in range(tool.presets.count):
                if tool.presets.item(j).id == target["libraryPresetId"]:
                    tool.presets.item(j).parameters.itemByName(
                        "tool_feedCutting").value.value = was
                    libraries.updateToolLibrary(url, shelf)
        library.forget()
    if after_three > after_one:
        return "FAIL", ("(latest) copies grew from %d to %d across three "
                        "checks, so every check adds another for ever"
                        % (after_one, after_three))
    return "PASS", "%d (latest) copies after one check and after three" % after_one


@check("removing the notes removes everything, and a check puts it back")
def _remove_and_restore(bench):
    library.forget()
    passes.run(bench.app)
    before = [o for o in bench.operations()
              if (o.notes or "").startswith(config.NOTE_PREFIX)]
    if not before:
        return "SKIP", "nothing marked to remove"
    passes.remove_marks(bench.app)
    left = [o for o in bench.operations()
            if (o.notes or "").startswith(config.NOTE_PREFIX)]
    records = [o for o in bench.operations()
               if o.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                          config.KEY_RECORD) is not None]
    library.forget()
    passes.run(bench.app)
    back = [o for o in bench.operations()
            if (o.notes or "").startswith(config.NOTE_PREFIX)]
    if left:
        return "FAIL", "%d notes survived Remove all notes" % len(left)
    if records:
        return "FAIL", "%d records survived Remove all notes" % len(records)
    if len(back) != len(before):
        return "FAIL", ("%d notes before, %d after putting them back"
                        % (len(before), len(back)))
    return "PASS", "removed %d and a check restored all of them" % len(before)


# ---------------------------------------------------------------------------
# Things the add-in must refuse, and things it must not lose
# ---------------------------------------------------------------------------

@check("it stands down on data from a newer add-in")
def _stand_down(bench):
    operation = bench.operations()[0]
    key = config.KEY_RECORD
    held = operation.attributes.itemByName(config.ATTRIBUTE_GROUP, key)
    held = held.value if held else None
    try:
        with marks.holding():
            operation.attributes.add(
                config.ATTRIBUTE_GROUP, key,
                json.dumps({"s": config.SCHEMA + 2,
                            config.KEY_ADOPTED_PRESET: "whatever",
                            config.KEY_OPERATION_ID: operation.operationId}))
        newest = compat.survey(bench.operations())
        understood, refusal = compat.may_write(newest)
        library.forget()
        _path, _counts, message = passes.run(bench.app)
    finally:
        with marks.holding():
            if held is None:
                found = operation.attributes.itemByName(
                    config.ATTRIBUTE_GROUP, key)
                if found:
                    found.deleteMe()
            else:
                operation.attributes.add(config.ATTRIBUTE_GROUP, key, held)
        library.forget()
    if newest <= config.SCHEMA:
        return "FAIL", "a schema %d record was not noticed" % (config.SCHEMA + 2)
    if understood:
        return "FAIL", "it would have written over a newer version's data"
    if "stopped early" in message.lower():
        return "FAIL", "standing down reported as a crash: %r" % message.splitlines()[0]
    return "PASS", "saw schema %d, refused to write, reported properly" % newest


@check("somebody's own note text survives a pass")
def _their_text(bench):
    operation, _verdict = bench.a_tracked_operation()
    if operation is None:
        return "SKIP", "no tracked operation on the bench"
    theirs = "CHECK Z OFFSET BEFORE RUNNING"
    with marks.holding():
        operation.notes = theirs
    library.forget()
    passes.run(bench.app)
    after = operation.notes or ""
    if theirs not in after:
        return "FAIL", "their line was lost: %r" % after
    if not after.startswith(config.NOTE_PREFIX):
        return "FAIL", "the add-in did not mark it: %r" % after
    return "PASS", "kept below ours: %r" % after


@check("an icon colour can be written and read back")
def _icons(bench):
    operation = bench.operations()[0]
    was = marks._icon(operation)
    try:
        with marks.holding():
            for name in ("Yellow", "Red", "Blue"):
                operation.noteIconColor = getattr(adsk.cam.NoteIconColors, name)
                if marks._icon(operation) != name:
                    return "FAIL", ("setting %s read back %s; the colour side "
                                    "of this add-in does nothing"
                                    % (name, marks._icon(operation)))
    finally:
        with marks.holding():
            if was:
                value = getattr(adsk.cam.NoteIconColors, was, None)
                if value is not None:
                    operation.noteIconColor = value
    return "PASS", "Yellow, Red and Blue all written and read back"


@check("a tool whose values were not read is unknown, never current")
def _values_not_read(bench):
    """The property the cheap read rests on.

    The warm reading holds every tool's name and id and no values at all, so the
    whole shop is known but nothing is judged from it until the values for a
    document's own tools are topped up. If a tool without values ever compared
    as matching, every operation in the shop would go green on a reading that
    had looked at nothing. state.reconcile has to answer unknown.

    This replaces a check on the old partial read, where a library was skipped
    entirely and tools were simply absent -- and an absent tool reads as "not a
    shop tool", which removes the note and the colour.
    """
    library.forget()
    quiet = Quiet()
    tools, ok = library.cached(quiet, None, wanted=set())
    if not ok:
        return "SKIP", "the libraries could not be read"
    if library.detailed():
        return "FAIL", ("asked for no values and got them for %d tools"
                        % len(library.detailed()))
    if not tools:
        return "FAIL", "no tools at all, so nothing was read"

    verdicts = set()
    seen = {}
    for operation in bench.operations():
        verdicts.add(state.reconcile(operation, tools, seen)["state"])
    wrong = verdicts & {state.CURRENT, state.BEHIND, state.CUSTOM}
    if wrong:
        return "FAIL", ("judged operations from a reading with no values in it: "
                        "%s. A green note here means nothing was compared."
                        % sorted(wrong))

    # And the top-up fills them in, from the libraries holding them only.
    shelf = set(passes._document_tools(bench.cam))
    tools, ok = library.cached(quiet, None, wanted=shelf)
    got = library.detailed()
    if not shelf & got:
        return "FAIL", ("topping up read values for none of this document's %d "
                        "tools" % len(shelf))
    after = set()
    seen = {}
    for operation in bench.operations():
        after.add(state.reconcile(operation, tools, seen)["state"])
    if not after & {state.CURRENT, state.BEHIND, state.CUSTOM}:
        return "FAIL", ("after the top-up nothing could still be judged: %s"
                        % sorted(after))
    return "PASS", ("no values read: everything unknown; topped up %d of this "
                    "document's %d tools: %s"
                    % (len(shelf & got), len(shelf), sorted(after)))


@check("default presets are left alone")
def _defaults(bench):
    tools = bench.tools()
    seen = {}
    offered = 0
    for tool in tools.values():
        for preset in tool.presets.values():
            if not config.is_a_utp(preset.name):
                offered += 1
    on_one = []
    for operation in bench.operations():
        verdict = state.reconcile(operation, tools, seen)
        preset = operation.toolPreset
        if preset is not None and not config.is_a_utp(
                presets.without_suffix(preset.name)):
            on_one.append((operation, verdict))
    if offered:
        return "FAIL", ("%d presets Fusion made are still offered as UTPs"
                        % offered)
    if not on_one:
        return "SKIP", "nothing on the bench is on a default preset"
    wrong = [o.name for o, v in on_one if v["state"] != state.NOT_UTP]
    noted = [o.name for o, _v in on_one
             if (o.notes or "").startswith(config.NOTE_PREFIX)]
    if wrong:
        return "FAIL", "treated as tracked: %s" % wrong
    if noted:
        return "FAIL", "still carrying a note: %s" % noted
    return "PASS", "%d operations on a default preset, all left alone" % len(on_one)


@check("an operation whose preset sets the depth of cut says so")
def _cut_warning(bench):
    tools = bench.tools()
    carrying = []
    for tool in tools.values():
        for preset in tool.presets.values():
            if any(n in config.CUT_DEPTH_PARAMETERS for n in preset.values):
                carrying.append(preset.name)
    if not carrying:
        return "SKIP", ("no preset in these libraries carries a stepdown or "
                        "stepover, so there is nothing to warn about. The "
                        "wording itself is covered by the unit tests.")
    seen = {}
    missing = []
    for operation in bench.operations():
        verdict = state.reconcile(operation, tools, seen)
        if verdict.get("carriesShape") and verdict["state"] == state.CURRENT:
            if config.NOTE_SETS_THE_CUT not in (operation.notes or ""):
                missing.append(operation.name)
    if missing:
        return "FAIL", "green with no warning: %s" % missing
    return "PASS", "%d presets carry one and every operation on them says so" % len(carrying)


@check("a check's writes are not undoable, which is what the wording says")
def _not_undoable(bench):
    """Measures the fact the wording now rests on.

    A check writes outside any command of the person's, so Fusion has nothing to
    roll back. Three screens used to say "One Ctrl+Z undoes the lot". This is
    here so that if Fusion ever changes, or somebody finds a way to group these
    writes into an undo step, we find out and can make the better promise
    instead of the safe one.
    """
    library.forget()
    passes.remove_marks(bench.app)
    passes.run(bench.app)
    before = len([o for o in bench.operations()
                  if (o.notes or "").startswith(config.NOTE_PREFIX)])
    if not before:
        return "SKIP", "the check wrote nothing, so there is nothing to undo"
    found = bench.app.userInterface.commandDefinitions.itemById("UndoCommand")
    if found is None:
        return "SKIP", "no UndoCommand on this build"
    found.execute()
    pump(60)
    after = len([o for o in bench.operations()
                 if (o.notes or "").startswith(config.NOTE_PREFIX)])
    if after < before:
        return "FAIL", ("one undo took %d of %d notes back, so the writes ARE "
                        "undoable and the wording should say so again"
                        % (before - after, before))
    return "PASS", ("%d notes before and after one undo, as the wording assumes"
                    % before)


# ---------------------------------------------------------------------------

def run(app, say):
    """Run every check. Returns a summary dict."""
    bench = Bench(app)
    say("bench: %r, %d operations, %d setups"
        % (bench.document.name, len(bench.operations()), bench.cam.setups.count))
    from utp import version
    say("live: UTP %s, schema %d" % (version.VERSION, config.SCHEMA))
    say("")

    results = []
    started = time.time()
    for name, function in CHECKS:
        at = time.time()
        try:
            verdict, detail = function(bench)
        except Exception as exc:
            import traceback
            verdict = "FAIL"
            detail = "raised: %s" % traceback.format_exc().strip().splitlines()[-1]
        results.append((name, verdict, detail))
        say("%-4s %-54s %5.1fs  %s"
            % (verdict, name[:54], time.time() - at, detail[:110]))
        pump(5)

    try:
        bench.restore()
        library.forget()
        passes.run(app)
    except Exception as exc:
        say("")
        say("the bench could not be put back: %s" % exc)

    counts = {}
    for _name, verdict, _detail in results:
        counts[verdict] = counts.get(verdict, 0) + 1
    say("")
    say("%d checks in %.1fs: %s"
        % (len(results), time.time() - started,
           ", ".join("%d %s" % (n, v) for v, n in sorted(counts.items()))))
    failed = [n for n, v, _d in results if v == "FAIL"]
    if failed:
        say("")
        say("FAILED: %s" % ", ".join(failed))
    return {"counts": counts, "failed": failed,
            "results": [{"check": n, "verdict": v, "detail": d}
                        for n, v, d in results]}
