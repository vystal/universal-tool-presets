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

import adsk.core
import adsk.cam

from . import compat, config, diagnostics, library, marks, state

_handlers = []
_running = {"undo": False}
_state = {}

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


def _may_write(document, operations=()):
    """Whether an event is allowed to write to this document."""
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
            operation = getattr(args, "operationbase", None)
            if operation is None:
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
                # seconds and would look like Fusion hanging.
                diagnostics.session_log(
                    "edit seen, nothing decided", operation=name,
                    reason="the libraries have not been read yet this session; "
                           "press the check button once to warm them")
                return
            tools, ok = library.cached(_Quiet())
            if not ok:
                return
            verdict = state.reconcile(operation, tools)
            would = marks.plan(operation, verdict)
            owner, guessed = _document_of(
                operation, adsk.core.Application.get())
            allowed, held_back = _may_write(owner, [operation])
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


class _DocumentSaving(adsk.core.DocumentEventHandler):
    """The backlog, at the one moment a pass of any size is safe."""

    def notify(self, args):
        try:
            document = getattr(args, "document", None)
            from . import passes
            report = _Quiet()
            tools, ok = library.cached(report)
            if not ok:
                diagnostics.session_log(
                    "save seen, nothing decided",
                    reason="the Hub libraries could not be read")
                return
            all_operations = list(passes.operations_of(document))
            allowed, held_back = _may_write(document, all_operations)
            counts = {}
            planned = wrote = failed = 0
            # Shared across the pass, as the button's does: six operations on
            # one preset read its values six times otherwise.
            seen = {}
            for index, operation in enumerate(all_operations):
                verdict = state.reconcile(operation, tools, seen)
                counts[verdict["state"]] = counts.get(verdict["state"], 0) + 1
                would = marks.plan(operation, verdict)
                if not would:
                    continue
                planned += 1
                if not allowed:
                    continue
                try:
                    marks.apply(operation, would)
                    wrote += 1
                    # After each write, not every twentieth operation: a
                    # marked operation costs two writes at about 150
                    # milliseconds and twenty of those is six seconds with
                    # Fusion frozen mid-save.
                    adsk.doEvents()
                except Exception:
                    failed += 1
                if index % config.OPERATIONS_PER_CHUNK == 0:
                    adsk.doEvents()
            _state["wrote_during_save"] = wrote
            diagnostics.session_log(
                "save seen", document=getattr(document, "name", "?"),
                verdicts=counts, would_mark=planned, wrote=wrote,
                failed=failed or None, held_back=held_back)
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
                wrote_during_the_save=_state.pop("wrote_during_save", 0))
        except Exception:
            pass


class _CommandStarting(adsk.core.ApplicationCommandEventHandler):
    def notify(self, args):
        try:
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
        except Exception:
            pass


class _Quiet:
    """A report that goes to the session log instead of a file of its own."""

    def note(self, message, **detail):
        diagnostics.session_log("note", message=message, **detail)

    def failed(self, message):
        diagnostics.session_log("failed", message=message)


def arm(app):
    """Start listening. Returns a list of what was armed, for the report."""
    armed = []
    try:
        cam_events = adsk.cam.CAMManager.get().camEventManager
        handler = _OperationChanged()
        cam_events.operationBaseChanged.add(handler)
        _handlers.append((cam_events.operationBaseChanged, handler))
        armed.append("operation edits")
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
    return armed


def disarm(app):
    """Detach every handler from the event it was actually attached to.

    Each is remembered with its own event rather than every handler being
    offered to every event, which was both wasteful and capable of removing
    the wrong thing.
    """
    for event, handler in _handlers:
        try:
            event.remove(handler)
        except Exception:
            continue
    del _handlers[:]
    diagnostics.session_log("stopped listening")
    diagnostics.close_session()
