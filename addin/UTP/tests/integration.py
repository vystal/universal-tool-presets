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

    def operations(self):
        return passes._walk(self.cam)[0]

    def tools(self):
        quiet = Quiet()
        tools, ok = library.cached(quiet)
        return tools if ok else {}

    def restore(self):
        """Put the notes and colours back, so the suite can run again."""
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

@check("a save marks the document and then settles")
def _save_settles(bench):
    library.forget()
    first = events.mark_document(bench.document, "integration: first save")
    second = events.mark_document(bench.document, "integration: second save")
    if second:
        return "FAIL", ("the second save wrote %d more marks, so the document "
                        "never settles and dirties on every save" % second)
    return "PASS", "first save wrote %d, second wrote nothing" % first


@check("a save keeps to its budget and carries on next time")
def _save_budget(bench):
    total = len(bench.operations())
    if total < 2:
        return "SKIP", "needs more than one operation"
    was = config.SAVE_SECONDS
    # Small enough that one save cannot finish the document, not so small that
    # it cannot start it. Zero progress at all is a separate thing and the
    # add-in now guarantees one operation a save whatever the budget says.
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
        return "FAIL", ("the cursor did not move across saves (%s), so a "
                        "document too big for one save would never finish" % flat)
    return "PASS", "cursor advanced across saves: %s" % flat


@check("setups are marked by a save, but only a complete one")
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


@check("a part-read of the libraries is never kept")
def _partial_not_cached(bench):
    library.forget()
    shelf = passes._document_tools(bench.cam)
    quiet = Quiet()
    tools, ok = library.cached(quiet, None, force=True, wanted=set(shelf))
    if not ok:
        return "SKIP", "the libraries could not be read"
    kept = library.warm()
    if kept and len(tools) and not library.incomplete():
        # A read that happened to go all the way through is fine to keep.
        return "SKIP", ("this document's tools were only found by reading every "
                        "library, so nothing was cut short to test")
    if kept:
        return "FAIL", ("a reading that stopped early was kept; another "
                        "document would read as untracked and lose its notes")
    return "PASS", "the short reading was handed back and not cached"


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
