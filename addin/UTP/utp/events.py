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

import time

import adsk.core
import adsk.cam

from . import compat, config, diagnostics, library, marks, settings, state

_handlers = []
_running = {"undo": False}
_state = {}

# What the last complete pass over each document found, keyed as _key() keys it.
# Only so a save can say whether the job it is saving was ever swept: a save
# writes nothing now, and this is the one cheap signal that would show the
# marking had stopped happening at all.
_swept = {}

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


def _may_write(document, operations=(), trigger="open"):
    """Whether this is allowed to write to this document.

    The trigger names the switch to look at, and must be one of settings.CONTROLS
    -- settings.on answers True for a name it does not know, so a trigger that
    does not exist reads as switched on. This defaulted to "save" for one commit
    after the save switch became "open", which is exactly that.

    trigger=None is for a button. The switches under "When it checks on its own"
    govern what the add-in does unasked; they have no business refusing somebody
    who has just pressed something. Pick up library changes went through here
    with the default trigger and did nothing at all with "when I open a job"
    switched off, then reported how many changes it had made.
    """
    if not settings.on("on"):
        return False, "the add-in is switched off"
    if trigger is not None and not settings.on(trigger):
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
            if not settings.on("on"):
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
            # Somebody has changed something in this document, so whatever a
            # sweep concluded about it no longer describes it. Said here, above
            # the edit switch, because the sweep is not the edit switch's
            # business: with "when I edit" off, a hand-changed feed used to keep
            # its green note until the reading went stale AND somebody happened
            # to enter Manufacture, because catch_up skips a document it has
            # been all the way through. Costs a dict delete, and it is only
            # reached for a change that is not one of ours -- marks.busy above
            # is what makes that true.
            _forget_sweep_of(operation)
            if not settings.on("edit"):
                # Out before reading anything: an edit somebody has switched
                # off should cost nothing.
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


def mark_document(document, why, budget=-1, trigger="open"):
    """Bring a whole document up to date, as far as the budget allows.

    Judges from whatever reading is in hand and never reads the libraries
    itself; catch_up does that first, where the staleness rule lives. This used
    to take may_read_libraries, whose only caller always passed False, so the
    staleness branch it guarded could never run and the one automatic write
    path in the add-in judged against a reading of any age.
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
        tools, ok = library.cached(report)
        reading = round(time.time() - reading, 2)
        if not ok:
            diagnostics.session_log("%s: nothing decided" % why,
                                    reason="the Hub libraries could not be read")
            return 0
        all_operations = list(passes.operations_of(document))
        allowed, held_back = _may_write(document, all_operations, trigger)
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
        # -1 means "the usual cap". None means no cap, for a button press:
        # somebody is waiting and expects the job finished, not advanced.
        if budget == -1:
            budget = config.PASS_SECONDS
        cursor = _state.get("save cursor", {}).get(_key(document), 0)
        if cursor >= len(all_operations):
            cursor = 0
        order = all_operations[cursor:] + all_operations[:cursor]

        behind = []
        looked_at = []
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
            try:
                verdict = state.reconcile(operation, tools, seen)
            except Exception as exc:
                # Per operation, as the button's pass has always done. Without
                # this, one operation that throws on a property read took down
                # the sweep for every operation after it in the walk, the
                # cursor was not advanced, and the enclosing handler logged
                # "open handler failed" -- so the user saw a job that was
                # half marked and nothing saying why.
                failed += 1
                report.failed("could not read an operation: %s" % exc)
                looked += 1
                continue
            looked += 1
            counts[verdict["state"]] = counts.get(verdict["state"], 0) + 1
            looked_at.append((operation, verdict))
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
        # Not gated on budget left over, which it used to be. That gate was
        # false by construction in exactly the case it mattered: a sweep that
        # ran out of budget is a sweep that marked operations "v3 available",
        # and this is the step that brings the v3 in for them to pick. So a
        # part-swept document got the notes and not the presets -- the precise
        # failure the step was written to prevent. It only ever runs for what
        # this pass marked behind, which the budget already bounds.
        # Every operation looked at, not just the behind ones, and the tidy
        # runs too. Both were wrong for the same case: somebody picks the
        # (latest) entry in the dropdown and presses OK, which leaves nothing
        # behind at all -- so this block was skipped entirely and the copy
        # they had just moved off stayed in the dropdown until somebody
        # pressed the button. Reported 8 October, and it is the ordinary way
        # the thing is used.
        if allowed:
            cam = _cam_of(document)
            if cam is not None:
                try:
                    changed = passes._ensure_presets(cam, looked_at, tools,
                                                     _Quiet(), True)
                    if changed:
                        # _ensure_presets returns True or False, not a list.
                        # len() on it raised TypeError, the enclosing except
                        # caught it, and every open that actually brought a
                        # preset in was logged as "could not bring presets in"
                        # -- the opposite of what happened -- while the
                        # re-judge below, the entire reason for this block,
                        # never ran. Same fault the _Quiet docstring was
                        # written about; that fix mended the fake report object
                        # and left this call site.
                        did.append("brought newer preset(s) into the document")
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
                    passes._clear_setup_marks(cam, _Quiet(), True)
                except Exception as exc:
                    diagnostics.session_log("%s: setups not marked" % why,
                                            error=str(exc))

        left = len(all_operations) - looked
        _state.setdefault("save cursor", {})[_key(document)] = (
            (cursor + looked) % len(all_operations) if all_operations else 0)
        whole = looked >= len(all_operations)
        _swept[_key(document)] = {
            "complete": whole,
            # Which reading of the shop libraries this was judged against. A
            # complete sweep is only worth skipping while that reading is still
            # the one in hand.
            "reading": library.read_at(),
            "said": ("swept at %s, %d operations, %d written"
                     % (time.strftime("%H:%M:%S"), looked, wrote)) if whole else
                    ("partly swept at %s, %d of %d, %d left for next time"
                     % (time.strftime("%H:%M:%S"), looked,
                        len(all_operations), left)),
        }
        diagnostics.session_log(
            why, document=getattr(document, "name", "?"), verdicts=counts,
            looked_at=looked, of=len(all_operations),
            seconds_reading_the_libraries=reading or None,
            left_for_the_next_save=left or None,
            seconds=round(time.time() - started, 2),
            would_mark=planned, wrote=wrote, did=did[:20] or "nothing",
            failed=failed or None, held_back=held_back)
        return wrote


def _forget_sweep_of(operation):
    """Forget that the document holding this operation was swept through."""
    try:
        owner, _guessed = _document_of(operation,
                                       adsk.core.Application.get())
    except Exception:
        owner = None
    if owner is None:
        # Which document it belongs to could not be told, so every sweep is
        # suspect rather than one of them. Cheaper to be wrong this way: the
        # cost is a pass that was not needed, against a note that stays green
        # over a feed somebody just changed.
        _swept.clear()
        return
    _swept.pop(_key(owner), None)


def forget_sweeps():
    """Forget which documents have been swept.

    For the two buttons: somebody pressing one is asking for the work to be
    done now, not told that it was done earlier against a reading that has
    since been thrown away.
    """
    _swept.clear()


def catch_up(document, why):
    """Bring one document up to date, reading the libraries first if need be.

    The single path behind all three automatic triggers: a job opening, the
    Manufacture workspace being entered, and an edit finishing. They were three
    different things doing three different amounts of work, and between them
    they left two holes.

    Entering Manufacture read the libraries and marked nothing, while the
    instructions told people it marked. And opening a job marked but never read,
    so it was the one write path with no bound on how old its reading was: enter
    Manufacture at eight, open a job at four, and every note in it was written
    against the morning's libraries. config.LIBRARY_STALE_AFTER exists to stop
    exactly that.

    They also each did one budgeted pass and stopped. A pass is capped so no
    trigger can stall Fusion, and a document bigger than one pass carries on at
    the next one -- which only works if there IS a next one. When the only
    trigger was a job opening, there was not: it fires once per document per
    session, so the cursor was written and never read again and a job past about
    six marks stayed half marked all day. Three recurring triggers is what makes
    the cursor mean something.

    A document that has been swept all the way through against the reading in
    hand is left alone, so switching workspaces in a settled job costs nothing.
    """
    if not (settings.on("on") and settings.on("open")):
        return 0
    if marks.busy() or _running["undo"]:
        return 0
    if document is None:
        return 0
    # Read first, so the pass below judges against something current. Bounded
    # by the staleness window, so this is at most one read per fifteen minutes
    # across all three triggers.
    _warm_now(why)
    if not library.warm():
        diagnostics.session_log(
            "nothing decided", why=why,
            document=getattr(document, "name", "?"),
            reason="the shop libraries could not be read")
        return 0
    done = _swept.get(_key(document)) or {}
    if done.get("complete") and done.get("reading") == library.read_at():
        return 0
    return mark_document(document, why)


class _DocumentOpened(adsk.core.DocumentEventHandler):
    """Bring a job up to date as it opens.

    This is where the backlog is cleared, and it is here rather than on a save
    because a save cannot do it. Marking during a save left the document dirty
    the instant the save finished -- measured 6 October: a save that wrote four
    notes left the title bar reading "UTP TEST bench*" and a second save was
    needed to clear it, while a save with nothing to mark left it clean. For a
    cloud document the writes land after Fusion has taken its snapshot. Opening
    has no snapshot to miss, and it is a moment somebody already expects to wait.

    Measured the same day, across four documents: documentOpened fires with the
    CAM product present and every operation readable, whatever workspace the
    document opens into -- a job saved in Design reported all thirteen of its
    operations here. A document with no manufacturing data raises from
    itemByProductType rather than returning None, which _cam_of allows for.

    Done now rather than deferred to an idle moment on purpose. By the time an
    idle handler runs, the active document can be a different one: measured three
    times in one session, where a workspace change on one document was followed a
    second later by activeDocument being another. A deferred pass would have to
    carry its document with it, and getting that wrong marks the wrong job in
    silence. The budget inside mark_document bounds what this costs.

    It never reads the libraries. If they have not been read yet this session it
    does nothing, because a Hub read inside an open would stall the open; by then
    entering the Manufacture workspace has almost always done it first.
    """

    def notify(self, args):
        try:
            if not (settings.on("on") and settings.on("open")):
                return
            if marks.busy() or _running["undo"]:
                return
            document = getattr(args, "document", None)
            if document is None:
                return
            catch_up(document, "marking the job that was opened")
        except Exception as exc:
            diagnostics.session_log("open handler failed", error=str(exc))


class _DocumentSaving(adsk.core.DocumentEventHandler):
    """Watches saves. Writes nothing, and that is the point.

    A save used to mark the whole document first. It no longer does: for a cloud
    document the writes land after Fusion's snapshot and leave the file dirty the
    moment it finishes, which is the "I have to save twice" this add-in was
    reported for. The backlog is cleared as a job opens instead.

    What is left here is worth keeping. It fires for every save, whatever Fusion
    called the command, so it can say when a save happened that the command hook
    did not recognise -- the hook matches command ids exactly, and exact matching
    fails quietly. A real Ctrl+S on a cloud document raises PLM360SaveCommand,
    not SaveDocumentCommand, and because that id was chosen by reading names
    rather than measuring, saving did nothing at all for eight releases with
    nothing anywhere saying so. Now there is a line in the log.

    It also says whether the job being saved was ever swept, which is the cheap
    signal that marking has stopped happening.
    """

    def notify(self, args):
        try:
            _calls["saves"] += 1
            document = getattr(args, "document", None)
            name = getattr(document, "name", "?")
            state_of_it = _state.pop("marked before save", None)
            if state_of_it is None:
                diagnostics.session_log(
                    "A SAVE THIS BUILD DOES NOT RECOGNISE", document=name,
                    reason=("no command this build raised matched "
                            "config.SAVE_COMMANDS. Nothing is written on a save "
                            "any more, so this costs nothing today, but it means "
                            "the id list is wrong and whatever next depends on "
                            "knowing a save happened will not work"),
                    in_the_three_seconds_before_it=[
                        i for at, i in _recent if time.time() - at < 3.0],
                    fix="add the id Fusion actually raised to SAVE_COMMANDS")
                return
            diagnostics.session_log("saved", document=name,
                                    wrote="nothing; a save does not write",
                                    this_job=state_of_it)
        except Exception as exc:
            diagnostics.session_log("save handler failed", error=str(exc))


class _DocumentSaved(adsk.core.DocumentEventHandler):
    """Is the document clean after a save?

    It has to be. Nothing is written during a save any more, so anything that
    leaves the file modified here is the add-in writing when it believes it is
    not, and that is the fault worth catching: it is how the double-save came
    back the first time, and it is invisible unless somebody is watching the
    title bar.
    """

    def notify(self, args):
        try:
            document = getattr(args, "document", None)
            modified = getattr(document, "isModified", "unknown")
            diagnostics.session_log(
                "settled after the save",
                document=getattr(document, "name", "?"),
                modified_again=modified,
                should_be=False,
                note="modified_again can read true here before Fusion has "
                     "settled the flag; what the title bar says a moment later "
                     "is the truth")
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
                # A save writes nothing. It used to mark the whole document
                # first, on the understanding that commandStarting runs before
                # Fusion takes its snapshot. For a cloud document it does not:
                # measured 6 October, a save that wrote four notes left the
                # document modified the moment it finished and needed a second
                # save to settle, while a save with nothing to write left it
                # clean. That is the "I have to save twice" this add-in was
                # reported for in its first week.
                #
                # So the backlog is cleared as a job opens instead, where there
                # is no snapshot to land after. All that happens here is the
                # record of whether that worked, which costs a dict lookup and
                # is the only thing that would show it had stopped working.
                app = adsk.core.Application.get()
                try:
                    where = _key(app.activeDocument)
                except Exception:
                    where = None
                _state["marked before save"] = (
                    _swept.get(where) or {}).get(
                        "said", "this job has not been swept this session")
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
    # Before the early return below, and only when there is already a reading
    # to be stale.
    #
    # Entering the Manufacture workspace was the only thing that refreshed, and
    # somebody working all day in one document never enters it again -- they are
    # already there. So the reading they were judged against was from whenever
    # they arrived, however many hours ago, and the green notes said the shop's
    # feeds had not moved because nobody had looked.
    #
    # An edit finishing is the right heartbeat: working on a job means editing
    # operations, the dialog has closed so a pause is a pause, and the fifteen
    # minute window means one read however many operations get edited. Only when
    # already warm, because a cold read here is what the _waiting check below
    # exists to avoid -- pressing Cancel reaches this line too.
    if library.warm():
        _warm_now("an edit finished (%s)" % command)
        # And carry the sweep on, which is the third of the three recurring
        # triggers that let a document bigger than one pass ever finish. Free
        # on a document already swept through against this reading, so editing
        # in a settled job costs nothing; bounded by the budget otherwise, and
        # it stops costing anything once the job converges.
        catch_up(app.activeDocument, "an edit finished (%s)" % command)
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

def _warm_now(why):
    """Read the shop libraries: the first time, and again once it goes stale.

    About 3.4 seconds for eight libraries. Nearly all of it is opening them and
    enumerating their presets; the values are 0.35s of it, so there is nothing
    here worth deferring -- see library.read.

    Called from somewhere a pause is survivable, never from inside an operation
    edit, which is what the cache exists to protect.
    """
    if not settings.on("on"):
        return False
    was = library.warm()
    started = time.time()
    tools, ok = library.cached(_Quiet(), adsk.doEvents,
                               stale_after=config.LIBRARY_STALE_AFTER)
    if was and time.time() - started < 0.1:
        return ok               # nothing was read; it was already in hand
    diagnostics.session_log(
        "read the shop libraries before anybody needed them", why=why,
        ok=ok, tools=len(tools), again=was or None,
        seconds=round(time.time() - started, 2))
    return ok


class _WorkspaceActivated(adsk.core.WorkspaceEventHandler):
    """Entering the Manufacture workspace is where the libraries get read.

    This was a worker thread firing a custom event a few seconds after the
    add-in loaded. That was wrong twice over. It fired while Fusion was still
    showing "Preparing your experience", so the event went nowhere and the
    libraries were never read; and the add-in's thread firing into Fusion at the
    same moment as another worker thread doing the same left that other thread
    dead -- measured 6 October, the test agent stopped six seconds after the
    first fire and never took another job.

    Entering Manufacture needs none of it. It is an ordinary event on the main
    thread, it happens before anybody can touch an operation, it is exactly the
    moment the libraries become relevant, and a pause here reads as a workspace
    loading rather than as Fusion hanging. Measured the same day: it fires on
    every switch in, and on opening a document that goes straight to CAM.
    """

    def notify(self, args):
        try:
            which = ""
            try:
                which = args.workspace.id
            except Exception:
                return
            if which not in config.CAM_WORKSPACES:
                return
            if marks.busy() or _running["undo"]:
                return
            app = adsk.core.Application.get()
            catch_up(app.activeDocument, "entering %s" % which)
        except Exception as exc:
            diagnostics.session_log("workspace handler failed", error=str(exc))


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
            ("documents opening", app.documentOpened, _DocumentOpened()),
            ("workspaces opening", app.userInterface.workspaceActivated,
             _WorkspaceActivated()),
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
    # Released only now, after the handlers have been taken off them.
    _held.clear()
    diagnostics.session_log("stopped listening")
    diagnostics.close_session()
