"""The triggers. Phase 2a listens and records; it still writes nothing.

Two events matter, and they are deliberately different sizes:

  * operationBaseChanged fires while the person's own command is still
    running. Writing from there is what makes the note part of their edit
    rather than a step on top of it: measured on 24 September, one Ctrl+Z took
    the preset and the note back together, and this event does not fire during
    an undo, so there is nothing that can loop. It handles one operation.
  * documentSaving handles the backlog. Save is not undoable, so a pass of any
    size is safe there, and it is the only place a whole document is walked.

An edit must never trigger a full pass. Forty notes written inside somebody's
edit would all land in their undo step, so one Ctrl+Z would revert their
change along with dozens of notes they never touched. That is the same rule
speed asks for, arrived at from a different direction.
"""

import threading
import time

import adsk.core
import adsk.cam

from . import compat, config, diagnostics, library, marks, settings, state

_handlers = []
_running = {"undo": False}
_state = {}

# Operations the edit handler saw before the libraries had been read. Emptied
# when the dialog closes, which is where the reading happens.
_waiting = []

# The last few command ids with a time against each, so a save that nothing
# marked can say what was happening just before it.
_recent = []

# Every command id this session has raised. Only for the debug report: the
# save command is matched on a substring because its exact id differs
# between builds, and this is how the real one gets found rather than
# guessed at.
_commands = set()


def seen_commands():
    return _commands

# Documents the button has been pressed in, by name. The rollout guard uses
# this so an edit or a save cannot start marking a document nobody asked it
# to. Held in memory only: a restart means pressing the button again, which is
# the safe direction to fail in.
_in_the_system = set()


def identify(document):
    """A document's id, or None if it cannot be told apart from another.

    Not the name. Two jobs called "OP2" are not the same document, and a
    document that gets renamed is still the same one, so keying the rollout
    guard on names would both confuse files and lose track of them. The
    dataFile id is stable; an unsaved document has none, so it falls back to
    the name, which is safe because an unsaved document cannot be confused
    with a saved one.
    """
    try:
        data = document.dataFile
        if data is not None and data.id:
            return data.id
    except Exception:
        pass
    try:
        return "unsaved:" + document.name
    except Exception:
        return None


def joined(document):
    """Remember that this document has been marked deliberately."""
    found = identify(document)
    if found:
        _in_the_system.add(found)


def _may_write(document, operations=(), trigger="save"):
    """Whether an event is allowed to write to this document.

    The trigger says which switch to look at: somebody may want their saves
    checked but not want notes moving under them as they edit, or the other
    way about.
    """
    if not settings.on("on"):
        return False, "the add-in is switched off"
    if not settings.on(trigger):
        return False, "checking when I %s is switched off" % trigger
    if not config.MAY_WRITE_ON_EVENTS:
        return False, "writing on events is switched off"
    understood, refusal = compat.may_write(compat.survey(operations))
    if not understood:
        return False, refusal
    if not config.ONLY_DOCUMENTS_ALREADY_MARKED:
        return True, None
    found = identify(document)
    if found is None:
        return False, "the document could not be identified"
    if found in _in_the_system:
        return True, None
    return False, ("the check button has not been pressed in this document, "
                   "so the rollout guard is holding writes back")


def _document_of(operation, app):
    """The document an operation belongs to.

    The active document is usually right but not necessarily: an event can
    arrive for a document that is not the one in front of somebody. The
    operation's own chain is tried first and the active document is the
    fallback, which is reported so a wrong guess is visible rather than
    silent.
    """
    for get in (lambda o: o.parentSetup.parentCAM.parentDocument,
                lambda o: o.parentCAM.parentDocument,
                lambda o: o.parentSetup.parentDocument):
        try:
            found = get(operation)
            if found is not None:
                return found, None
        except Exception:
            continue
    return app.activeDocument, "fell back to the active document"


class _OperationChanged(adsk.cam.OperationBaseEventHandler):
    """One operation, while the person's command is still open."""

    def notify(self, args):
        try:
            _calls["edits"] += 1
            operation = getattr(args, "operationbase", None)
            if operation is None:
                return
            if not (settings.on("on") and settings.on("edit")):
                # Out before reading anything. _may_write would refuse this
                # too, but only after reconciling the operation, and an edit
                # somebody has switched off should cost nothing.
                return
            name = getattr(operation, "name", "?")
            if marks.busy():
                # Our own write set this off. Reacting to it would half-repeat
                # work already in hand, and relies on plan() being idempotent
                # to ever stop.
                return
            if _running["undo"]:
                _running["during"] = _running.get("during", 0) + 1
                diagnostics.session_log(
                    "edit ignored", operation=name,
                    reason="an undo or redo is running; writing here would "
                           "fight the undo stack")
                return
            if not library.warm():
                # Never read the Hub from inside somebody's command: it takes
                # between three and eight seconds and would look like Fusion
                # hanging, in the middle of their own edit.
                #
                # So the first edit of a session decides nothing. Saving
                # reads the libraries and catches the whole document up, and
                # so does the check button, and after either of those every
                # edit is decided as it happens.
                # Put by for the moment the dialog closes, which is where the
                # libraries get read. The handler knows exactly which operation
                # this is; nothing else afterwards does, because Fusion leaves
                # nothing selected once the dialog has gone.
                _waiting.append(operation)
                diagnostics.session_log(
                    "edit seen, nothing decided yet", operation=name,
                    reason="the libraries have not been read yet this "
                           "session, and reading them inside an edit would "
                           "stall Fusion for seconds",
                    caught_up_by="the moment this dialog closes")
                return
            tools, ok = library.cached(_Quiet())
            if not ok:
                return
            verdict = state.reconcile(operation, tools)
            # The only place a cleared note is left cleared: this runs inside
            # the person's own edit, so a line of ours that has gone was
            # taken out by them, a moment ago.
            would = marks.plan(operation, verdict, during_their_edit=True)
            owner, guessed = _document_of(
                operation, adsk.core.Application.get())
            allowed, held_back = _may_write(owner, [operation], "edit")
            written = None
            if would and allowed:
                # Written here, inside the person's own command, which is what
                # makes the note part of their edit rather than a step on top
                # of it. One Ctrl+Z then takes both back.
                try:
                    written = marks.apply(operation, would)
                except Exception as exc:
                    written = "failed: %s" % exc
            diagnostics.session_log(
                "edit seen", operation=name, verdict=verdict["state"],
                preset=verdict.get("preset"),
                record=verdict.get("record") or "none",
                why=verdict.get("why"),
                would=marks.describe(would) if would else "nothing",
                written=written or "nothing", held_back=held_back,
                document_guess=guessed)
        except Exception as exc:
            diagnostics.session_log("edit handler failed", error=str(exc))


def _key(document):
    """Something to remember a per-document position against."""
    return identify(document) or getattr(document, "name", "?")


def _cam_of(document):
    try:
        return document.products.itemByProductType("CAMProductType")
    except Exception:
        return None


def mark_document(document, why):
    """Bring a whole document up to date. Used before a save, and by it.

    Shared so that marking can happen before Fusion starts saving, where
    what it writes becomes part of that save, rather than during, where it
    lands after the snapshot and leaves the file dirty again.
    """
    with marks.holding():
        from . import passes
        report = _Quiet()
        # Timed separately and reported, because it is the one part of a save
        # the budget below cannot cap: deciding anything at all needs the
        # libraries, and reading them is all or nothing. It happens once per
        # Fusion session, so the first save of the day is seconds and every
        # save after it is milliseconds. Without this in the log, that first
        # one looks like the add-in being slow rather than the network being
        # read once.
        reading = time.time()
        tools, ok = library.cached(report,
                                   stale_after=config.LIBRARY_STALE_AFTER)
        reading = round(time.time() - reading, 2)
        if not ok:
            diagnostics.session_log("%s: nothing decided" % why,
                                    reason="the Hub libraries could not be read")
            return 0
        all_operations = list(passes.operations_of(document))
        allowed, held_back = _may_write(document, all_operations)
        counts = {}
        planned = wrote = failed = 0
        seen = {}
        # What it did, named. A count said "wrote: 1" whether that was a note
        # somebody would see or a record nobody would, which made working
        # behaviour and broken behaviour look identical.
        did = []

        # Where the last save got to in this document, so a job too big for one
        # save is finished by the next few rather than freezing every one of
        # them. Judging is most of the cost, so the budget has to cover judging
        # and not only writing.
        started = time.time()
        budget = config.SAVE_SECONDS
        cursor = _state.get("save cursor", {}).get(_key(document), 0)
        if cursor >= len(all_operations):
            cursor = 0
        order = all_operations[cursor:] + all_operations[:cursor]

        behind = []
        looked = 0
        for operation in order:
            # The budget is consulted only once something has been done. A
            # budget already spent before the loop starts -- because the
            # libraries had to be read, or because it is set very low -- would
            # otherwise look at nothing, advance the cursor by nothing, and do
            # the same on every save for ever. A document that never progresses
            # is worse than a save that takes a moment longer, so at least one
            # operation is always looked at. Found by the integration suite on
            # its first run.
            if budget and looked and time.time() - started > budget:
                break
            verdict = state.reconcile(operation, tools, seen)
            looked += 1
            counts[verdict["state"]] = counts.get(verdict["state"], 0) + 1
            if verdict["state"] == state.BEHIND:
                behind.append((operation, verdict))
            would = marks.plan(operation, verdict)
            if not would:
                continue
            planned += 1
            if not allowed:
                continue
            try:
                marks.apply(operation, would)
                wrote += 1
                did.append("%s: %s" % (getattr(operation, "name", "?"),
                                       marks.describe(would)))
                adsk.doEvents()
            except Exception:
                failed += 1

        # A behind operation needs the newer values pickable in its dropdown
        # before its note is worth anything: the note says "pick the one ending
        # (latest)", and that entry used to be created only by the button, so on
        # a machine where nobody pressed it a save put "v3 available" on
        # operations with no v3 to pick. Only for the ones this save actually
        # looked at, and only if there is time left, because bringing a preset
        # in is a bigger write than a note.
        if behind and allowed and (not budget or time.time() - started < budget):
            cam = _cam_of(document)
            if cam is not None:
                try:
                    changed = passes._ensure_presets(cam, behind, tools,
                                                     _Quiet(), True,
                                                     tidying=False)
                    if changed:
                        did.append("brought %d preset(s) into the document"
                                   % len(changed))
                        # update() leaves tool and preset references stale, so
                        # the ones that changed are read and judged again rather
                        # than reused, as the button's pass does.
                        seen = {}
                        for operation in passes.operations_of(document):
                            verdict = state.reconcile(operation, tools, seen)
                            if verdict["state"] != state.BEHIND:
                                continue
                            would = marks.plan(operation, verdict)
                            if would:
                                try:
                                    marks.apply(operation, would)
                                    wrote += 1
                                except Exception:
                                    failed += 1
                except Exception as exc:
                    diagnostics.session_log(
                        "%s: could not bring presets in" % why, error=str(exc))

        # The setups, but only when this save got all the way round. A setup
        # note counts what is inside it, and a count taken from part of a
        # document is a wrong number rather than an old one. Until now nothing
        # but the button ever updated them, so somebody working with setups
        # collapsed -- the person the setup note exists for -- was reading
        # whatever was true when the button was last pressed, possibly never.
        if looked >= len(all_operations) and allowed:
            cam = _cam_of(document)
            if cam is not None:
                try:
                    passes._mark_setups(cam, tools, _Quiet(), True)
                except Exception as exc:
                    diagnostics.session_log("%s: setups not marked" % why,
                                            error=str(exc))

        left = len(all_operations) - looked
        _state.setdefault("save cursor", {})[_key(document)] = (
            (cursor + looked) % len(all_operations) if all_operations else 0)
        diagnostics.session_log(
            why, document=getattr(document, "name", "?"), verdicts=counts,
            looked_at=looked, of=len(all_operations),
            seconds_reading_the_libraries=reading or None,
            left_for_the_next_save=left or None,
            seconds=round(time.time() - started, 2),
            would_mark=planned, wrote=wrote, did=did[:20] or "nothing",
            failed=failed or None, held_back=held_back)
        return wrote


class _DocumentSaving(adsk.core.DocumentEventHandler):
    """Watches for a save that nothing marked first.

    This used to carry a second copy of the whole marking pass, for when
    marking happened during a save rather than before it. Marking before the
    save won that argument months ago, so the copy was unreachable, and it had
    already drifted from the live one it was copied from.

    What it does now is the job that copy could not: it fires for every save,
    whatever Fusion called the command, so it can say when a save happened that
    the command hook did not recognise. That matters because the hook matches
    command ids exactly, and exact matching fails quietly -- a build that names
    its save something else would simply stop being marked, with nothing
    anywhere saying so. Now there is a line in the log.
    """

    def notify(self, args):
        try:
            _calls["saves"] += 1
            document = getattr(args, "document", None)
            name = getattr(document, "name", "?")
            marked = _state.pop("marked before save", None)
            if marked is None:
                diagnostics.session_log(
                    "A SAVE THAT NOTHING MARKED FIRST", document=name,
                    reason=("no command this build raised matched "
                            "config.SAVE_COMMANDS, so the document was saved "
                            "without being brought up to date"),
                    in_the_three_seconds_before_it=[
                        i for at, i in _recent if time.time() - at < 3.0],
                    fix="add the id Fusion actually raised to SAVE_COMMANDS")
                return
            diagnostics.session_log("saved", document=name,
                                    marked_before_it=marked)
        except Exception as exc:
            diagnostics.session_log("save handler failed", error=str(exc))


class _DocumentSaved(adsk.core.DocumentEventHandler):
    """Did writing during the save leave the file dirty again?

    The marking runs on documentSaving, before the save, so that what it
    writes is part of that save. If Fusion has already taken its snapshot by
    then, the writes land after it and the document is modified the instant
    it finishes, which would mean never being able to close one cleanly.
    Asked rather than assumed.
    """

    def notify(self, args):
        try:
            document = getattr(args, "document", None)
            diagnostics.session_log(
                "saved", document=getattr(document, "name", "?"),
                modified_again=getattr(document, "isModified", "unknown"),
                wrote_before_the_save=_state.pop("wrote_before_save", 0),
                note="modified_again here can read false before Fusion has "
                     "settled the flag; what the title bar says is the truth")
        except Exception:
            pass


class _CommandStarting(adsk.core.ApplicationCommandEventHandler):
    def notify(self, args):
        try:
            _calls["commands"] += 1
            _commands.add(str(args.commandId))
            # With a time against it, so a save nothing marked can name what
            # was happening in the seconds before it. The set on its own could
            # not: it holds every id of the whole session, so when a Ctrl+S went
            # unmarked it listed twelve commands and the one that mattered was
            # indistinguishable from eleven that did not.
            _recent.append((time.time(), str(args.commandId)))
            del _recent[:-40]
            if str(args.commandId) in config.SAVE_COMMANDS:
                # Recorded whatever happens next, so documentSaving can tell a
                # save nothing recognised from one that was deliberately left
                # alone. Without that, a build naming its save something else
                # would stop being marked in silence.
                _state["marked before save"] = "held back"
                if (not marks.busy() and not _running["undo"]
                        and settings.on("on") and settings.on("save")):
                    app = adsk.core.Application.get()
                    wrote = mark_document(
                        app.activeDocument,
                        "marking before the save (%s)" % args.commandId)
                    _state["wrote_before_save"] = wrote
                    _state["marked before save"] = "%d written" % wrote
            if args.commandId in ("UndoCommand", "RedoCommand"):
                _running["undo"] = True
                # Logged so the guard is visible. Without this an undo that
                # raised no operation event looks exactly like a handler that
                # never ran, and the one piece of safety machinery here cannot
                # be told apart from nothing happening at all.
                diagnostics.session_log("undo or redo started",
                                        command=args.commandId)
        except Exception:
            pass


class _CommandTerminated(adsk.core.ApplicationCommandEventHandler):
    def notify(self, args):
        try:
            if args.commandId in ("UndoCommand", "RedoCommand"):
                _running["undo"] = False
                diagnostics.session_log(
                    "undo or redo ended", command=args.commandId,
                    operation_events_during_it=_running.pop("during", 0))
                return
            if str(args.commandId) in config.EDIT_COMMANDS:
                _mark_what_they_just_edited(args.commandId)
        except Exception as exc:
            diagnostics.session_log("command end handler failed", error=str(exc))


def _mark_what_they_just_edited(command):
    """Bring the operation somebody has just finished editing up to date.

    The operation is taken from the selection, because Fusion leaves it selected
    when the dialog closes, and because the alternative is a pass over the whole
    document for one operation's sake.

    This is also where the libraries get read for the first time in a session.
    operationBaseChanged fires during the dialog and cannot pay for a Hub read
    there -- three to eight seconds inside somebody's own command looks like
    Fusion hanging, which is why that handler stands down when the cache is cold
    and says so in the log. Nobody reads the log. What they see is an add-in that
    does nothing when they change a feed, and until a save happened that was
    every edit of the session.

    Here the dialog has closed, so a pause is a pause rather than a freeze, and
    it happens once. Breathing while it reads, so Fusion does not grey out.
    """
    if not (settings.on("on") and settings.on("edit")):
        return
    if marks.busy() or _running["undo"]:
        return
    app = adsk.core.Application.get()
    if not _waiting:
        # Nothing was put by, so either the edit handler decided it already or
        # there was no edit to decide. Checked before the libraries are read,
        # because pressing Cancel on an operation dialog reaches here too and
        # was paying three and a half seconds for a reading nobody needed.
        return
    cold = not library.warm()
    if cold:
        diagnostics.session_log(
            "reading the libraries after an edit", command=command,
            reason=("first edit of the session; the dialog has closed so this "
                    "is the moment to pay for it"))
    tools, ok = library.cached(_Quiet(), adsk.doEvents if cold else None,
                               stale_after=config.LIBRARY_STALE_AFTER)
    if not ok:
        return
    # The operations the edit handler saw and could not decide on. Taken from
    # what it put by, not from the selection: measured on 6 October, Fusion
    # leaves nothing selected when an operation dialog closes, so a first edit
    # read the libraries and then marked nothing at all.
    picked, _waiting[:] = list(_waiting), []
    done = []
    for entity in picked:
        owner, _guessed = _document_of(entity, app)
        allowed, held_back = _may_write(owner, [entity], "edit")
        verdict = state.reconcile(entity, tools)
        would = marks.plan(entity, verdict, during_their_edit=True)
        written = None
        if would and allowed:
            try:
                with marks.holding():
                    written = marks.apply(entity, would)
            except Exception as exc:
                written = "failed: %s" % exc
        done.append({"operation": verdict["operation"],
                     "verdict": verdict["state"],
                     "would": marks.describe(would) if would else "nothing",
                     "written": written or "nothing",
                     "held back": held_back})
    if not picked:
        # Nothing was waiting, so the edit handler decided it already. Said at
        # all only because silence here was what hid the last fault.
        return
    diagnostics.session_log("edit finished", command=command,
                            waiting=len(picked), did=done)


class _Quiet:
    """A report that goes to the session log instead of a file of its own.

    It has to answer everything diagnostics.Report answers, because the pass
    functions are shared and they count what they wrote and consult whether
    anything failed. It did not, so the moment the save path started using
    _ensure_presets, report.wrote raised AttributeError inside a try and was
    logged as "could not bring in that preset" -- the opposite of what had
    happened -- and report.failures raised outside one and took the whole
    preset step down, swallowed. The save path silently brought in no presets
    at all, which is exactly the fault it had been changed to fix.
    """

    def __init__(self):
        self.wrote = 0
        self.failures = 0

    def note(self, message, **detail):
        diagnostics.session_log("note", message=message, **detail)

    def failed(self, message):
        self.failures += 1
        diagnostics.session_log("failed", message=message)


# Fusion objects a subscription depends on. Nothing reads these; they exist so
# the garbage collector cannot take a listener away from under the add-in.
_held = {}

# How many times each listener has actually been called. Counted because the
# listener died once and nothing could tell: "listening" was in the log, five
# handlers were attached, and the subscription had been collected. A count of
# zero against a session somebody has been working in is the symptom, and
# until now there was nothing that showed it.
_calls = {"edits": 0, "saves": 0, "commands": 0}


def calls():
    """How many times each listener has fired this session."""
    return dict(_calls)


# ---------------------------------------------------------------------------
# Reading the libraries before anybody needs them
# ---------------------------------------------------------------------------

_WARM_EVENT_ID = "UTPWarmLibraries"
_warming = {}


class _WarmLibraries(adsk.core.CustomEventHandler):
    """Reads the shop libraries, on the main thread, when Fusion is idle."""

    def notify(self, args):
        try:
            _warm_now()
        except Exception as exc:
            diagnostics.session_log("reading the libraries early failed",
                                    error=str(exc))


def _warm_now():
    if library.warm():
        return
    if not settings.on("on"):
        diagnostics.session_log("not reading the libraries early",
                                reason="the add-in is switched off")
        return
    started = time.time()
    tools, ok = library.cached(_Quiet(), adsk.doEvents)
    diagnostics.session_log(
        "read the shop libraries before anybody needed them",
        ok=ok, tools=len(tools), seconds=round(time.time() - started, 2),
        why="so the first edit of the session does not pay for it")


def warm_later(app):
    """Arrange for the libraries to be read once, soon, while Fusion is idle.

    A worker thread sleeps and then fires a custom event. The thread touches
    nothing of Fusion's -- it sleeps and it fires, and that is the whole of it,
    because the API is main-thread only and a worker that called it would take
    Fusion down with it. What the custom event buys is not another thread to
    work on but the timing: Fusion runs the handler on the main thread at a
    moment it is idle, so the pause lands where nobody is waiting on it.

    One attempt. If the Hub is not reachable yet this early, nothing is kept and
    every path that needs the libraries reads them on demand exactly as it did
    before, so the worst case is the behaviour this replaces.
    """
    if not config.WARM_LIBRARIES_AFTER:
        return False
    try:
        # A stale registration from a previous load of the add-in would send
        # this to a handler that no longer exists.
        app.unregisterCustomEvent(_WARM_EVENT_ID)
    except Exception:
        pass
    try:
        event = app.registerCustomEvent(_WARM_EVENT_ID)
        handler = _WarmLibraries()
        event.add(handler)
    except Exception as exc:
        diagnostics.session_log("could not arrange to read the libraries early",
                                error=str(exc))
        return False
    # Held for the same reason the CAM subscription is: the event wrapper going
    # out of scope takes the subscription with it.
    _held["warm event"] = event
    _handlers.append((event, handler))
    _warming["off"] = False

    def sleep_then_fire():
        time.sleep(config.WARM_LIBRARIES_AFTER)
        if _warming.get("off"):
            return
        try:
            app.fireCustomEvent(_WARM_EVENT_ID, "")
        except Exception:
            pass

    thread = threading.Thread(target=sleep_then_fire, daemon=True)
    _warming["thread"] = thread
    thread.start()
    return True


def arm(app):
    """Start listening. Returns a list of what was armed, for the report."""
    armed = []
    try:
        # Both the manager and the event are kept, not just the handler.
        #
        # They used to be locals. The handler survived, because it went into
        # _handlers, but the CAMEventManager and the event wrapper went out of
        # scope the moment arm() returned, and once Python collected them the
        # subscription went with them. The symptom was an edit handler that
        # worked for the first minutes of a session and then went silent, which
        # is exactly what it looks like from the outside: change a feed, and the
        # note does not move. Measured today -- two parameter changes and a note
        # write produced no handler call at all, in a session where "listening"
        # had been logged perfectly happily.
        #
        # Also why operationBaseChanged is read once into a variable rather than
        # twice: the property hands back a new wrapper each time it is read, so
        # subscribing to one and remembering another meant disarm() was removing
        # the handler from an object that was not the one holding it.
        manager = adsk.cam.CAMManager.get().camEventManager
        event = manager.operationBaseChanged
        handler = _OperationChanged()
        event.add(handler)
        _held["cam events"] = manager
        _held["operation event"] = event
        _handlers.append((event, handler))
        armed.append("operation edits")
        # operationBaseCommandButtonPressed is not listened to. It sounded like
        # the hook this add-in wanted -- on OK, inside the person's own command,
        # so the note would be part of their edit and one Ctrl+Z would take both.
        # It was attached as a watcher for one release and recorded nothing
        # across two real edits in the dialog, so it does not fire on OK. The
        # watcher came out rather than being left in on the chance it meant
        # something.
    except Exception as exc:
        diagnostics.session_log("operationBaseChanged unavailable", error=str(exc))

    for label, event, handler in (
            ("document saving", app.documentSaving, _DocumentSaving()),
            ("document saved", app.documentSaved, _DocumentSaved()),
            ("commands starting", app.userInterface.commandStarting,
             _CommandStarting()),
            ("commands ending", app.userInterface.commandTerminated,
             _CommandTerminated())):
        try:
            event.add(handler)
            _handlers.append((event, handler))
            armed.append(label)
        except Exception as exc:
            diagnostics.session_log("could not listen to %s" % label,
                                    error=str(exc))
    diagnostics.session_log("listening", to=armed,
                            writing=config.MAY_WRITE_ON_EVENTS)
    if warm_later(app):
        diagnostics.session_log("will read the shop libraries shortly",
                                in_seconds=config.WARM_LIBRARIES_AFTER,
                                on="the main thread, once Fusion is idle")
    return armed


def disarm(app):
    """Detach every handler from the event it was actually attached to.

    Each is remembered with its own event rather than every handler being
    offered to every event, which was both wasteful and capable of removing
    the wrong thing.
    """
    # Told first, so a thread still sleeping does not fire into a handler that
    # is about to be taken off its event.
    _warming["off"] = True
    for event, handler in _handlers:
        try:
            event.remove(handler)
        except Exception:
            continue
    del _handlers[:]
    try:
        app.unregisterCustomEvent(_WARM_EVENT_ID)
    except Exception:
        pass
    # Released only now, after the handlers have been taken off them.
    _held.clear()
    diagnostics.session_log("stopped listening")
    diagnostics.close_session()
