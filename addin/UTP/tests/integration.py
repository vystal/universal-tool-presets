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
        # Whether this machine had ever had switches chosen on it. save() leaves
        # a mark saying so, kept where nothing syncs, and restoring the file
        # without restoring the mark left the machine looking like one whose
        # switches had been taken away -- which stands the irreversible ones
        # down. Measured: after a suite run the shop machine read every switch
        # off, which is a test making the thing it tests worse.
        self.chosen = os.path.exists(config.SETTINGS_CHOSEN)
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
            if not self.chosen and os.path.exists(config.SETTINGS_CHOSEN):
                os.remove(config.SETTINGS_CHOSEN)
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


def readable():
    """Whether the shop libraries can be read at all, right now.

    Checks that depend on a reading must skip rather than fail when there is
    none to be had. Measured 8 October: the suite ran 83 seconds after a cold
    Fusion start, before the Hub was ready, and reported five failures including
    "entering CAMEnvironment did not read the libraries" -- which reads as a
    regression and is not one. A minute later the same read took 3.67 seconds
    and found eight libraries. A suite that cannot tell a broken add-in from a
    machine that has not finished starting is a suite that gets ignored.
    """
    library.forget()
    _tools, ok = library.cached(Quiet(), None)
    return bool(ok) and not library.incomplete()


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

@check("the add-in running in Fusion is the one in this repository")
def _right_build(bench):
    """First of all, because everything after it is about the running add-in.

    The suite imports its own code from the repository but exercises the modules
    Fusion already has loaded, which come from the installed cache. If those are
    a release behind, every verdict below describes code nobody is changing.

    Measured 7 October: a full suite ran green against 0.23.1 while the fixes
    being tested were in 0.24.0, because the loader had installed the older
    build and nothing in the run said so. The version was only noticed by hand.
    """
    import os
    import re

    from utp import version

    running = version.VERSION
    # This file lives in the repository, beside the package it tests, so the
    # repository's version is readable from here without being told where it is.
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "utp", "version.py")
    try:
        text = open(here, encoding="utf-8").read()
        wanted = re.search(r'VERSION\s*=\s*"([^"]+)"', text).group(1)
    except Exception as exc:
        return "SKIP", "could not read the repository's version: %s" % exc
    if running != wanted:
        return "FAIL", ("Fusion is running %s and this repository is %s. "
                        "Restart Fusion so the loader installs %s, then run "
                        "this again -- these results describe %s."
                        % (running, wanted, wanted, running))
    return "PASS", "both are %s" % running


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
    if not readable():
        return "SKIP", ("the shop libraries cannot be read on this machine "
                        "right now, so nothing could warm them")

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


@check("a stale reading is refreshed without changing workspace")
def _stale_refreshed(bench):
    """Somebody working all day in one document never enters Manufacture again.

    Entering it was the only thing that refreshed, so the reading they were
    judged against was from whenever they arrived. An edit finishing is the
    heartbeat now. Checked here with the clock wound back rather than by
    waiting fifteen minutes.
    """
    if not readable():
        return "SKIP", "the shop libraries cannot be read right now"
    library.forget()
    events._warm_now("integration: cold")
    if not library.warm():
        return "SKIP", "the libraries could not be read"
    first = library._cache["read at"]

    # An edit finishing with a fresh reading must not re-read.
    del events._waiting[:]
    started = time.time()
    events._mark_what_they_just_edited(config.EDIT_COMMANDS[0])
    if library._cache["read at"] != first:
        return "FAIL", ("an edit re-read the libraries when the reading was "
                        "%.0fs old" % (time.time() - first))
    quick = time.time() - started

    # Wound back past the window, the same edit must re-read.
    library._cache["read at"] = time.time() - (config.LIBRARY_STALE_AFTER + 60)
    events._mark_what_they_just_edited(config.EDIT_COMMANDS[0])
    if library._cache["read at"] <= time.time() - config.LIBRARY_STALE_AFTER:
        return "FAIL", ("a reading %d minutes old was not refreshed when an "
                        "edit finished, so a day in one document is judged "
                        "against whatever was true that morning"
                        % (config.LIBRARY_STALE_AFTER // 60))
    return "PASS", ("fresh reading left alone (%.2fs), one %d minutes old "
                    "refreshed" % (quick, config.LIBRARY_STALE_AFTER // 60))


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
    if not readable():
        return "SKIP", "the shop libraries cannot be read right now"
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
    if not readable():
        return "SKIP", "the shop libraries cannot be read right now"
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
    was = config.PASS_SECONDS
    # Small enough that one pass cannot finish the document, not so small that
    # it cannot start it. Zero progress at all is a separate thing and the
    # add-in now guarantees one operation a pass whatever the budget says.
    config.PASS_SECONDS = 0.001
    _state = events._state
    _state.pop("save cursor", None)
    try:
        seen = []
        for _ in range(4):
            events.mark_document(bench.document, "integration: budget")
            seen.append(list(_state.get("save cursor", {}).values()))
        flat = [v[0] for v in seen if v]
    finally:
        config.PASS_SECONDS = was
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


@check("setups are not marked, and old setup notes are taken off")
def _setups(bench):
    """Dropped on 8 October, decided in the shop.

    Fusion will not allow it where it would have to happen: writing a setup's
    note from inside the person's edit, where it would have joined their own
    undo step, is refused outright -- "the given operation cannot be edited
    while another one is edited", straight out of the log. So it could only ever
    be a separate step they had to undo separately, and one Ctrl+Z after an edit
    reverted the setup's icon and nothing else.

    And it was never the cover it looked like: folders and patterns hide their
    operations exactly the same way and never carried one.

    So a pass takes the old ones off instead, and writes none.
    """
    with marks.holding():
        for i in range(bench.cam.setups.count):
            bench.cam.setups.item(i).notes = marks.ours("2 of 7 need updating")
    library.forget()
    passes.run(bench.app)

    left = []
    for i in range(bench.cam.setups.count):
        said = bench.cam.setups.item(i).notes or ""
        if said.startswith(config.NOTE_PREFIX) or config.NOTE_PREFIX in said:
            left.append(bench.cam.setups.item(i).name)
    if left:
        return "FAIL", ("a pass left its own note on %d setup(s): %s. Nothing "
                        "maintains them now, so one that stays is wrong for "
                        "ever." % (len(left), left[:3]))

    # And a second pass must not put any back.
    library.forget()
    passes.run(bench.app)
    again = [bench.cam.setups.item(i).name
             for i in range(bench.cam.setups.count)
             if config.NOTE_PREFIX in (bench.cam.setups.item(i).notes or "")]
    if again:
        return "FAIL", "a pass wrote a setup note: %s" % again[:3]
    return "PASS", ("%d setups, none marked, old notes taken off"
                    % bench.cam.setups.count)


@check("a part-swept document carries on at the next trigger")
def _resumes(bench):
    """The cursor has to mean something.

    A pass is capped so nothing hangs, and a document bigger than one pass
    carries on at the next one. While a job opening was the only trigger that
    was a fiction: documentOpened fires once per document per session, so the
    cursor was written and never read again and anything past about six marks
    stayed half marked all day. Entering Manufacture and finishing an edit are
    passes too now, which is what makes resuming real.

    Driven here through catch_up, the path all three triggers share, with the
    budget squeezed so one pass cannot finish the bench.
    """
    total = len(bench.operations())
    if total < 2:
        return "SKIP", "needs more than one operation"
    if not readable():
        return "SKIP", "the shop libraries cannot be read right now"
    was = config.PASS_SECONDS
    config.PASS_SECONDS = 0.001
    events.forget_sweeps()
    events._state.pop("save cursor", None)
    try:
        seen = []
        for _ in range(4):
            events.catch_up(bench.document, "integration: resuming")
            seen.append(list(events._state.get("save cursor", {}).values()))
    finally:
        config.PASS_SECONDS = was
        events._state.pop("save cursor", None)
        events.forget_sweeps()
    flat = [v[0] for v in seen if v]
    if len(set(flat)) < 2:
        return "FAIL", ("the cursor did not move across triggers (%s), so a "
                        "document too big for one pass never finishes" % flat)
    return "PASS", "cursor advanced across repeated triggers: %s" % flat


@check("a settled document is skipped, so switching workspace costs nothing")
def _skips_settled(bench):
    """Otherwise every workspace switch re-judges the whole job.

    Measured 7 October: three milliseconds an operation, so a four hundred
    operation job is over a second every time somebody enters Manufacture, for
    no change. A document swept all the way through against the reading in hand
    is left alone until that reading is replaced.
    """
    events.forget_sweeps()
    events.catch_up(bench.document, "integration: first sweep")
    first = (events._swept.get(events._key(bench.document)) or {})
    if not first.get("complete"):
        return "SKIP", ("the bench did not finish in one pass, so there is no "
                        "settled state to test")
    started = time.time()
    wrote = events.catch_up(bench.document, "integration: should be skipped")
    took = time.time() - started
    if wrote:
        return "FAIL", "the second pass wrote %d more; it should be skipped" % wrote
    if took > 0.05:
        return "FAIL", ("the second pass took %.2fs, so it re-judged the "
                        "document instead of being skipped" % took)

    # And a new reading of the libraries must make it sweep again.
    library.forget()
    events.catch_up(bench.document, "integration: after a new reading")
    again = (events._swept.get(events._key(bench.document)) or {})
    if again.get("reading") == first.get("reading"):
        return "FAIL", ("a fresh reading of the libraries did not make the "
                        "document be swept again, so a shop change would never "
                        "reach a settled job")
    return "PASS", ("skipped in %.3fs while settled, and swept again after a "
                    "new reading" % took)


@check("changing an operation un-settles the document")
def _change_unsettles(bench):
    """Otherwise a settled document stays settled over somebody's change.

    catch_up skips a document it has swept all the way through against the
    reading in hand, which is what makes switching workspace free. The skip has
    to end when somebody changes something, and the edit listener is where that
    is known -- above the "when I edit" switch, because with that switch off a
    hand-changed feed otherwise kept its green note until the reading went
    stale and somebody happened to enter Manufacture.
    """
    operation, _verdict = bench.a_tracked_operation()
    if operation is None:
        return "SKIP", "no tracked operation on the bench"

    events.forget_sweeps()
    events.catch_up(bench.document, "integration: settle it")
    key = events._key(bench.document)
    if not (events._swept.get(key) or {}).get("complete"):
        return "SKIP", "the bench did not settle in one pass"
    if events.catch_up(bench.document, "integration: should skip") != 0:
        return "FAIL", "a settled document was not skipped"

    # The listener's own path, with the operation it would be handed.
    handler = [h for _e, h in events._handlers
               if isinstance(h, events._OperationChanged)][0]

    class Args:
        operationbase = operation

    handler.notify(Args())
    if (events._swept.get(key) or {}).get("complete"):
        return "FAIL", ("a change left the document marked as swept through, so "
                        "the next trigger would skip it and the note would stay "
                        "as it was")
    return "PASS", "a change on an operation un-settles its document"


@check("a check settles, so a second one writes nothing")
def _check_settles(bench):
    library.forget()
    passes.run(bench.app)
    _path, _counts, message = passes.run(bench.app)
    headline = message.splitlines()[0]
    # Taken from config rather than matched on " 0 of ", which is what this
    # looked for until the headline was reworded on 8 October: a pass that
    # wrote nothing started saying so in words and this read it as a failure.
    # A real regression still fails it, because writing anything puts the
    # count back in the headline.
    settled = config.MARKED_NOTHING % len(bench.operations())
    if headline != settled and " 0 of " not in headline:
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
        if verdict.get("libraryPresetId") and verdict["state"] in (
                state.CURRENT, state.BEHIND):
            target = verdict
            break
    if target is None:
        return "SKIP", ("no operation resolves to a library preset, so there "
                        "is nothing whose values can be moved")

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
                    # Every value, not just this one. Fusion recomputes the
                    # linked feeds from whichever one is set, so moving
                    # tool_feedCutting moves five -- feedEntry, feedExit,
                    # feedPerTooth and feedTransition came with it, measured.
                    # Putting one back left four moved, which left the bench
                    # permanently behind and made the NEXT run of this check
                    # skip itself: a test degrading its own precondition.
                    held = values.scalars(preset)
                    found.value.value = found.value.value + by
                    libraries.updateToolLibrary(url, shelf)
                    return held
        return None

    def dropdown():
        counted = 0
        for _key, tool in passes._document_tools(bench.cam).items():
            for i in range(tool.presets.count):
                if tool.presets.item(i).name.endswith(config.LATEST_SUFFIX):
                    counted += 1
        return counted

    held = nudge(77.0)
    if held is None:
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
                preset = tool.presets.item(j)
                if preset.id != target["libraryPresetId"]:
                    continue
                for name, value in held.items():
                    try:
                        param = preset.parameters.itemByName(name)
                        if param is not None:
                            param.value.value = value
                    except Exception:
                        continue
                libraries.updateToolLibrary(url, shelf)
        library.forget()
    if after_three > after_one:
        return "FAIL", ("(latest) copies grew from %d to %d across three "
                        "checks, so every check adds another for ever"
                        % (after_one, after_three))
    return "PASS", "%d (latest) copies after one check and after three" % after_one


@check("removing the notes removes everything, and a check puts back what it can")
def _remove_and_restore(bench):
    """And is honest about what it cannot.

    Everything the add-in wrote comes off, records included -- that is what
    "remove every trace" has to mean. But a grey Custom verdict exists ONLY
    because of that record: it is what says this operation was deliberately put
    on a shop preset and has since been changed. Remove the record and a later
    check cannot tell a hand-tuned operation from one that was never tracked, so
    it reads "not adopted" and writes no note.

    So those do not come back, and the only way back is to pick the preset
    again. The confirmation dialog says so now; it used to promise that a check
    "works them all out again", which is true for every verdict except the one
    somebody is most likely to have.
    """
    library.forget()
    passes.run(bench.app)
    tools = bench.tools()
    seen = {}
    custom = set()
    marked = set()
    for operation in bench.operations():
        if (operation.notes or "").startswith(config.NOTE_PREFIX):
            marked.add(operation.operationId)
        if state.reconcile(operation, tools, seen)["state"] == state.CUSTOM:
            custom.add(operation.operationId)
    if not marked:
        return "SKIP", "nothing marked to remove"

    passes.remove_marks(bench.app)
    left = [o for o in bench.operations()
            if (o.notes or "").startswith(config.NOTE_PREFIX)]
    records = [o for o in bench.operations()
               if o.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                          config.KEY_RECORD) is not None]
    if left:
        return "FAIL", "%d notes survived Remove all notes" % len(left)
    if records:
        return "FAIL", "%d records survived Remove all notes" % len(records)

    library.forget()
    passes.run(bench.app)
    back = {o.operationId for o in bench.operations()
            if (o.notes or "").startswith(config.NOTE_PREFIX)}
    should = marked - custom
    missing = should - back
    if missing:
        return "FAIL", ("%d note(s) that should have come back did not"
                        % len(missing))
    came_back_anyway = (custom & back)
    if came_back_anyway:
        return "FAIL", ("%d Custom note(s) came back, which means a record "
                        "survived Remove all notes" % len(came_back_anyway))
    # And the wording has to admit it.
    said = config.UNMARK_CONFIRM.lower()
    if "custom" not in said:
        return "FAIL", ("the confirmation does not mention that Custom "
                        "operations do not come back")
    return "PASS", ("removed %d, %d came back, %d Custom did not and the "
                    "dialog says so" % (len(marked), len(back), len(custom)))


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


@check("a reading covers every library, and is kept")
def _whole_and_kept(bench):
    """Both halves of the fault that cost four releases.

    The read used to stop as soon as one document's tools were found. A tool
    missing from a reading is indistinguishable from a tool that is not in the
    shop libraries at all, and that verdict -- "not a shop tool" -- takes the
    note and the colour off. So such a reading could never be cached, which
    meant the check button paid for a read and kept nothing: measured 5 October,
    a check read 2 libraries of 8 in 3.3s and two seconds later the log still
    said the libraries had not been read this session. The first edit of every
    session then paid for another read.

    Both are gone, and this is what holds them gone.
    """
    library.forget()
    quiet = Quiet()
    tools, ok = library.cached(quiet, None)
    if not ok:
        return "SKIP", "the libraries could not be read"
    if not library.warm():
        return "FAIL", ("the reading was not kept, so the next edit or open "
                        "pays for another one")
    first = set(tools)
    if not first:
        return "FAIL", "no tools at all"

    # Reading again must describe the same shop, not a subset of it.
    library.forget()
    again, ok = library.cached(quiet, None)
    if ok and set(again) != first:
        missing = len(first - set(again))
        return "FAIL", ("two readings of the same libraries disagree by %d "
                        "tools; a tool missing from one reads as 'not a shop "
                        "tool' and loses its note" % missing)

    # And a second call does not re-read.
    started = time.time()
    library.cached(quiet, None)
    if time.time() - started > 0.5:
        return "FAIL", "a second call re-read the libraries instead of using "                       "the one it had"
    return "PASS", ("%d tools over every library, kept, and not read twice"
                    % len(first))


# The two-writer race check lived here. It covered versions.review, which
# snapshotted a whole library, decided, re-opened it and refused the write if
# anything had moved -- because updateToolLibrary puts back the WHOLE library
# from the shelf it is given, so a stamp written from a stale shelf reverted a
# feed change somebody else had just made. Measured 7 October, and real.
#
# The check goes with the thing it guarded. Version stamping was removed on
# 8 October and with it the only write this add-in ever made outside the
# person's own document, so there is no longer a library write to race on.

@check("a pass leaves nothing it would have tidied or renamed")
def _pass_finishes_its_own_work(bench):
    """After a pass, asking the deciding functions again must find nothing.

    An invariant rather than a scenario, and it is the check this suite was
    missing. Twice on 8 October the decisions were right and nothing carried
    them out: a "continue" skipped the renaming whenever there was nothing to
    tidy, and a "return" skipped both whenever no operation was behind -- which
    is exactly the state somebody is in the moment they move onto the newer
    preset. Both left removable() naming a spare copy on every pass with
    nothing asking it.

    So this does not describe what should happen. It presses the button and
    then asks whether the add-in still has work it says it wants to do.
    """
    library.forget()
    passes.run(bench.app)

    report = diagnostics.Report("settled", keeping=False)
    tools, ok = library.cached(report, adsk.doEvents)
    if not ok:
        return "SKIP", "the libraries could not be read"
    used = passes._presets_in_use(bench.cam, report)
    left = []
    for key, tool in passes._document_tools(bench.cam).items():
        library_tool = tools.get(key)
        if library_tool is None:
            continue
        for row in presets.removable(tool, library_tool, used):
            left.append("would still remove %s" % row[1])
        for preset, wanted in presets.wanted_names(tool, library_tool, used):
            left.append("would still rename %s to %s" % (preset.name, wanted))
    if left:
        return "FAIL", ("the pass finished with work it still says it wants "
                        "to do: %s" % "; ".join(left[:6]))
    return "PASS", "nothing left to remove or rename after a pass"


@check("what the tidy may not delete is read from the operations, not the verdicts")
def _in_use_from_operations(bench):
    """Where the tidy's protection comes from.

    The rule itself -- never offer a preset an operation is on -- is pure logic
    and is pinned by the unit tests. What only Fusion can answer is whether the
    set handed to that rule is complete.

    It used to be read off the verdicts, and a verdict is allowed not to look:
    state reads an operation's preset through a getattr that answers None on an
    exception, so "could not read its preset" and "on no preset" produced the
    same verdict -- presetId None, and no failure recorded, because reconcile
    returned rather than raised. The copy that operation was running looked
    spare. Walking the operations cannot decline in that way: a read that fails
    reports a failure, and a failure is what stands the tidy down.
    """
    quiet = Quiet()
    walked = passes._presets_in_use(bench.cam, quiet)
    if quiet.failures:
        return "FAIL", ("reading what the operations are on reported %d "
                        "failure(s). The tidy would stand down, which is "
                        "correct, but something on the bench cannot be read"
                        % quiet.failures)
    if not walked:
        return "SKIP", "no operation on the bench is on a preset"

    # What the verdicts would have said, for comparison. The walked set must
    # cover it: it may hold more, never less.
    tools = bench.tools()
    seen = {}
    from_verdicts = set()
    for operation in bench.operations():
        found = state.reconcile(operation, tools, seen).get("presetId")
        if found:
            from_verdicts.add(found)
    missing = from_verdicts - walked
    if missing:
        return "FAIL", ("the walk missed %d preset(s) the verdicts found, so "
                        "it is the weaker of the two" % len(missing))
    extra = walked - from_verdicts
    return "PASS", ("%d preset(s) in use, read from the operations; covers all "
                    "%d the verdicts found%s"
                    % (len(walked), len(from_verdicts),
                       ", plus %d the verdicts did not report" % len(extra)
                       if extra else ""))


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
