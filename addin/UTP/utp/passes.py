"""One pass over one document.

Phase 1 has exactly one trigger: somebody presses the button. There are no
automatic passes, because Fusion can be pushed into "not responding" by a
burst of API calls and a read-only phase has nothing urgent to say. The work
is chunked, with a breath between chunks, for the same reason.
"""

import time

import adsk.core
import adsk.cam

from . import (compat, config, diagnostics, dropdown, identity, library,
               marks, presets, settings, state, survey)


def _users(vector):
    """inUseBy hands back a collection of User objects, not names."""
    def name_of(user):
        return (getattr(user, "displayName", None)
                or getattr(user, "userName", None)
                or getattr(user, "email", None) or "?")

    for get in (lambda v: list(v),
                lambda v: [v.item(i) for i in range(v.count)],
                lambda v: [v[i] for i in range(len(v))]):
        try:
            return ", ".join(name_of(u) for u in get(vector)) or "nobody named"
        except Exception:
            continue
    return "could not be read"


class _Clock:
    """How long each stage of a pass took.

    Added because the first run on a four hundred operation file took
    twenty-seven seconds and nobody could say which part of it did, which
    made the next change a guess.
    """

    def __init__(self, report):
        self.report = report
        self.last = time.time()
        self.stages = {}

    def at(self, stage):
        now = time.time()
        self.stages[stage] = round(now - self.last, 2)
        self.last = now

    def say(self):
        if self.stages:
            self.report.note("seconds spent", **self.stages)










class _Progress:
    """Fusion's busy bar in the corner, for a button press. Never a dialog.

    ui.progressBar.showBusy is the moving bar in the lower-right of the Fusion
    window -- the one Fusion puts up itself while a document opens. It is not
    modal, so somebody can carry on working while a pass runs, and it carries
    no percentage: it says something is happening, which is all there is to
    say when the slow part is a library read of unknown length.

    A createProgressDialog was tried first and was wrong on both counts: a
    dialog in the middle of the screen, in the way, for a job nobody asked to
    be interrupted by. It also brought a cancel button, which this has no
    equivalent of -- the busy bar has no buttons at all. No loss worth the
    dialog: a button press runs to the end in a couple of seconds, and the
    automatic passes are capped and never show a bar at all.
    """

    def __init__(self, app, report):
        self.bar = None
        self.report = report
        if not config.SHOW_PROGRESS:
            return
        try:
            self.bar = app.userInterface.progressBar
            # isModal False, explicitly: modal here would take the whole UI
            # away, and a modal bar left showing by a raise on the way out is
            # a Fusion somebody has to kill.
            self.bar.showBusy(config.PROGRESS_READING, False)
        except Exception:
            self.bar = None

    def saying(self, message):
        """Change what the bar says, for a later stage of the same pass."""
        if self.bar is None:
            return
        try:
            self.bar.message = message
        except Exception:
            self.bar = None

    def at(self, done):
        """Kept for the callers that count. A busy bar has nothing to move."""
        return False

    def done(self):
        # Called twice: where the pass finishes, and from the finally that
        # guarantees it comes down whichever way the pass leaves.
        if self.bar is not None:
            try:
                self.bar.hide()
            except Exception:
                pass
            self.bar = None


def _verdicts(operations, tools, report, progress=None, resolve=None):
    """Every operation's verdict, worked out once.

    It used to be worked out four times a pass, by the version review, the
    preset step, the marking loop and the setup rollup. At about ten
    milliseconds each that is forty per operation, so a two hundred
    operation job spent eight seconds doing the same arithmetic four times.
    """
    found = []
    seen = {}
    for index, operation in enumerate(operations):
        try:
            known = None
            if resolve is not None:
                try:
                    known = resolve(operation.tool)
                except Exception:
                    known = None
            found.append((operation,
                          state.reconcile(operation, tools, seen, known)))
        except Exception:
            report.failed("could not work out %s"
                          % getattr(operation, "name", "an operation"))
        # A breath, and a line in the session log, so a long pass can be
        # watched rather than guessed at.
        if index and index % config.OPERATIONS_PER_CHUNK == 0:
            diagnostics.session_log("working", done=index,
                                    of=len(operations))
            adsk.doEvents()
            # Moved here rather than on every operation: setting the value
            # repaints the dialog, and doing that four hundred times cost
            # more than the work it was reporting on.
            if progress is not None and progress.at(index + 1):
                break
        elif progress is not None and progress.at(index + 1):
            break

    # Said out loud, because the thing it describes is an administrative
    # action somewhere else that quietly changes what this add-in can tell.
    # C44: duplicating or re-importing a Hub library gives every tool in it a
    # fresh guid, so each description ends up held twice and no operation can
    # be tied to one of them. Nothing is un-marked over it any more, but
    # nothing newer is offered either, and without this line the only sign is
    # a count of operations that read as neither current nor behind.
    confused = sorted({v.get("tool") for _op, v in found
                       if str(v.get("matched by") or "").startswith(
                           identity.AMBIGUOUS)})
    if confused:
        report.note("TWO SHOP TOOLS SHARE ONE DESCRIPTION",
                    tools=confused[:10],
                    consequence=("operations on them are left exactly as they "
                                 "are: their notes stay, and nothing newer is "
                                 "offered until it can be told which tool "
                                 "they are on"),
                    likely_cause=("a Hub library duplicated, re-imported or "
                                  "rebuilt: storing a tool in a library gives "
                                  "it a new id, so the same tool in two "
                                  "libraries is two tools"))
    return found












def _setups_of(cam, report):
    """Every setup, without walking what is inside them."""
    found = []
    try:
        for index in range(cam.setups.count):
            found.append(cam.setups.item(index))
    except Exception:
        report.failed("could not read the setups")
    return found


def _clear_setup_marks(cam, report, writing):
    """Take the add-in's line and colour off every setup.

    Setups are not marked any more, and this is what sees the ones already out
    there off. A note nothing maintains is worse than no note: a collapsed setup
    reading "2 of 7 need updating" when it is one, for ever, is the exact thing
    the note was there to prevent.

    Dropped on 8 October, decided in the shop. Two reasons, and the second is
    the one that settles it.

    Fusion will not allow it where it would have to happen. A setup's note is a
    count of what is inside it, so it is wrong the instant one of those
    operations changes -- and writing it from inside the person's edit, where it
    would have been part of their own undo step, is refused outright: "the given
    operation cannot be edited while another one is edited", measured. So it
    could only ever be written after their dialog closed, as a separate step
    they had to undo separately.

    And it was never the protection it looked like. A collapsed setup hides its
    operations, which is why the note existed -- but patterns and folders hide
    them exactly the same way and never carried one. Partial cover nobody can
    rely on is worse than none, because it reads as cover.

    Nothing replaces it. The operations carry their own notes and colours, which
    is where the information belongs.
    """
    # cam.setups directly. This asked survey.by_setup for every setup and every
    # operation beneath it and then used only the setups -- a whole extra
    # traversal of the document, on every pass, thrown away.
    clean = 0
    for setup in _setups_of(cam, report):
        # Nothing of ours on it, so there is nothing to take off. This runs on
        # every pass, for ever, over documents that were never marked by a
        # build that marked setups -- which before long is all of them. Asked
        # per setup rather than remembered on the document, so a setup that
        # somehow gains a mark again is still seen.
        if not marks.touched(setup):
            clean += 1
            continue
        try:
            changes = marks.strip(setup)
        except Exception:
            report.failed("could not work out what to take off a setup")
            continue
        if not changes:
            continue
        name = getattr(setup, "name", "?")
        if not writing:
            report.note("would take the old note off the setup %s" % name,
                        would=marks.describe(changes))
            continue
        try:
            marks.apply(setup, changes)
            adsk.doEvents()
            report.wrote += len(changes)
            report.note("took the old note off the setup %s" % name,
                        did=marks.describe(changes),
                        why="setups are not marked any more")
        except Exception:
            report.failed("could not clear the setup %s" % name)
    if clean:
        report.note("setups with nothing of ours on them", count=clean,
                    note="not looked at any further")


def remove_marks(app):
    """Take every trace of the add-in back out of the active document.

    The way back out, so installing this is not a one-way door. It lands as
    one undo step like any other pass, and it leaves presets alone: an
    operation may be on one the add-in added, and removing that would
    re-point it without changing its values.
    """
    with marks.holding():
        document = app.activeDocument
        report = diagnostics.Report((document.name if document else "?") + " - unmark",
                                    keeping=settings.on("report"))
        try:
            products = document.products if document else None
            cam = products.itemByProductType("CAMProductType") if products else None
            if cam is None:
                report.note("this document has no manufacturing data")
                return report.close(), {}, config.NOTHING_TO_CHECK
            if not _writable(document, report):
                return report.close(), {}, config.READ_ONLY

            # The same stand-down the marking pass makes, which this did not.
            # A build that refuses to WRITE to a document carrying data from a
            # newer version of the add-in would still cheerfully DELETE all of
            # it, which is the worse of the two by a distance: an old build
            # cannot know what the newer one was recording, and there is no undo
            # once the document is saved.
            operations_here = survey.operations(cam)
            understood, refusal = compat.may_write(compat.survey(operations_here))
            if not understood:
                report.failed("not removing anything: %s" % refusal)
                return report.close(), {}, refusal

            cleared = 0
            looked = 0
            for setup, operations in survey.by_setup(cam, report):
                for owner in [setup] + list(operations):
                    looked += 1
                    try:
                        changes = marks.strip(owner)
                    except Exception:
                        report.failed("could not look at %s"
                                      % getattr(owner, "name", "?"))
                        continue
                    if not changes:
                        continue
                    try:
                        done = marks.unapply(owner, changes)
                        adsk.doEvents()
                        report.wrote += len(changes)
                        cleared += 1
                        # Named, not just counted. A command whose job is removal
                        # should say what it removed.
                        report.note("unmarked %s" % getattr(owner, "name", "?"),
                                    did=", ".join(done))
                    except Exception:
                        report.failed("could not unmark %s"
                                      % getattr(owner, "name", "?"))
                    if looked % config.OPERATIONS_PER_CHUNK == 0:
                        adsk.doEvents()
            _forget_leave_alone(document, report)
            report.note("unmarked", looked_at=looked, cleared=cleared,
                        presets="left alone; an operation may be using one")
            return (report.close(), {"cleared": cleared},
                    config.UNMARKED % (cleared, looked))
        except Exception:
            report.failed("unmarking stopped early")
            return report.close(), {}, config.STOPPED_EARLY


def _flag_store(document):
    """Somewhere on the document to keep a flag that travels with the file.

    Tried in order rather than assumed: a Document has no attributes of its
    own, and which of these a build offers has not been worth guessing at
    after the week this has had. Whichever answers first is used, and all of
    them are read, so a flag written by one build is found by another.
    """
    stores = []
    try:
        design = document.products.itemByProductType("DesignProductType")
        if design is not None:
            stores.append(design.rootComponent.attributes)
    except Exception:
        pass
    try:
        cam = document.products.itemByProductType("CAMProductType")
        if cam is not None:
            if getattr(cam, "attributes", None) is not None:
                stores.append(cam.attributes)
            if cam.setups.count:
                stores.append(cam.setups.item(0).attributes)
    except Exception:
        pass
    return stores


def _forget_leave_alone(document, report=None):
    """Take out the flag that removing the marks used to write.

    Only ever deletes now. Documents marked by 0.8.0 to 0.8.5 may be carrying
    one, and an attribute nothing reads is exactly the sort of thing an add-in
    should not leave behind in somebody's job.
    """
    done = False
    for store in _flag_store(document):
        try:
            found = store.itemByName(config.ATTRIBUTE_GROUP,
                                     config.KEY_LEAVE_ALONE)
            if found is not None:
                found.deleteMe()
                done = True
        except Exception:
            continue
    if report is not None and done:
        report.note("took out an old leave-alone flag")
    return done


def _writable(document, report):
    """Whether it is safe to write to this document.

    Only a read-only file stops it. isInUse and inUseBy are reported rather
    than obeyed: the person running this usually has the file open themselves,
    so treating that flag as a refusal would quietly disable everything.
    """
    try:
        data = document.dataFile
    except Exception:
        data = None
    if data is None:
        return True          # never saved, so nothing to conflict with
    try:
        if data.isReadOnly:
            report.note("not writing: the file is read-only")
            return False
    except Exception:
        pass
    try:
        if data.isInUse:
            report.note("the file is marked in use", by=_users(data.inUseBy),
                        note="writing anyway; this is normally just you")
    except Exception:
        pass
    return True














def run(app, allow_writing=True):
    """Check the active document. Returns (report path, counts, message)."""
    with marks.holding():
        document = app.activeDocument
        report = diagnostics.Report(document.name if document else "no document",
                                    keeping=settings.on("report"))
        # Named before the try, so the finally can always take the bar down.
        # It goes up before the library read now, and there are three returns
        # between there and the end: a progress dialog left showing is a
        # Fusion somebody has to kill.
        progress = None
        try:
            products = document.products if document else None
            cam = products.itemByProductType("CAMProductType") if products else None
            if cam is None:
                report.note("this document has no manufacturing data")
                return report.close(), {}, config.NOTHING_TO_CHECK

            # Always re-read: the button means "tell me what is in the library
            # now", and an old reading could call a feed current that somebody
            # changed a minute ago.
            #
            # This also warms the cache, now that it does. It used to ask with
            # wanted=, which stopped as soon as this document's tools were
            # found, and a reading with tools missing from it can never be kept
            # -- an absent tool reads as "not a shop tool" and that removes a
            # note. So the button paid for a read and cached nothing: measured
            # 5 October, a check on Atom A49 OP2 read 2 libraries of 8 in 3.3s
            # and two seconds later the log still said the libraries had not
            # been read this session. Every library is read now.
            clock = _Clock(report)
            marks.forget_cost()
            # Up before the library read rather than after it. The read is the
            # slow part -- about three and a half seconds -- and a bar that
            # only appears once that is over shows nothing worth seeing.
            # Started at an unknown total, because the operations have not been
            # walked yet; _Progress.total() sets it once they have.
            progress = _Progress(app, report)
            shelf = survey.document_tools(cam)
            resolve = survey.id_by_description(shelf)
            clock.at("read the document's tools")

            tools, ok = library.cached(report, adsk.doEvents, force=True)
            clock.at("read the Hub libraries")
            if not ok:
                report.note("stopping: without the library nothing can be decided")
                return (report.close(), {},
                        config.NO_LIBRARY)

            # Walked once. The schema survey and the shape of the tree used to
            # traverse the whole document again each, for nothing but to read it.
            operations, shape = survey.walk(cam)
            if shape["could not be read"]:
                # Said as a failure, not a note, because that is what the tidy
                # consults before it deletes anything. An operation missing from
                # this walk is missing from the set of presets in use, and a
                # preset wrongly thought spare is one an operation is running.
                report.failed("could not read %d thing(s) in the operation tree, "
                              "so nothing will be removed in this pass"
                              % shape["could not be read"])

            # allow_writing is how "check without changing anything" works: the
            # same pass, deciding everything and writing none of it.
            writing = (allow_writing and settings.on("on")
                       and config.MAY_WRITE_ON_DEMAND
                       and _writable(document, report))
            # A file written by a newer add-in is read and reported on, never
            # changed: its rules are not this version's to second-guess.
            newest = compat.survey(operations, survey.breathe)
            understood, refusal = compat.may_write(newest)
            if not understood:
                report.note("NOT WRITING", reason=refusal)
                writing = False
            report.writing = writing
            if writing:
                # Pressing the button is how a document joins the system, which is
                # what lets later edits and saves write to it.
                from . import events
                events.joined(document)
            report.note("found operations", count=len(operations),
                        writing="yes" if writing else "no", **shape)

            clock.at("walked the document")

            progress.saying(config.PROGRESS_MESSAGE)
            decided = _verdicts(operations, tools, report, progress, resolve)
            clock.at("worked out every verdict")

            # Presets first, notes second. A behind operation's note is worth
            # little until the newer values are pickable in its dropdown, and
            # update() leaves the tool and preset references stale, so the
            # operations are re-read and judged again afterwards rather than
            # reused.
            progress.saying(config.PROGRESS_PRESETS)
            changed_presets = dropdown.ensure_presets(cam, decided, tools, report, writing)
            clock.at("presets in the document")
            if changed_presets:
                operations = survey.operations(cam)
                decided = _verdicts(operations, tools, report, progress,
                                    survey.id_by_description(survey.document_tools(cam)))
                clock.at("judged them all again, after the presets moved")

            progress.saying(config.PROGRESS_MARKING)
            # Timed from the inside. Seventeen milliseconds an operation for what
            # should be two property reads does not add up, and guessing which
            # part of it is wrong has been wrong three times.
            spent = {"deciding what to mark": 0.0, "writing marks": 0.0,
                     "recording the verdict": 0.0}
            for index, (operation, verdict) in enumerate(decided):
                try:
                    # Worked out whether or not it is allowed to happen, so the
                    # decisions can be read and argued with either way.
                    mark = time.time()
                    verdict["would"] = marks.plan(operation, verdict)
                    spent["deciding what to mark"] += time.time() - mark
                    if writing and verdict["would"]:
                        mark = time.time()
                        try:
                            verdict["written"] = marks.apply(operation,
                                                             verdict["would"])
                            report.wrote += len(verdict["written"])
                        except Exception:
                            verdict["written"] = "failed"
                            report.failed("could not write to %s"
                                          % verdict["operation"])
                        spent["writing marks"] += time.time() - mark
                        # After writing, not every twentieth operation: two
                        # writes at 150ms each means twenty of them is six
                        # seconds with Fusion frozen.
                        survey.breathe(1, config.WRITES_PER_CHUNK)
                    mark = time.time()
                    report.operation(verdict)
                    spent["recording the verdict"] += time.time() - mark
                except Exception:
                    report.failed("could not work out %s" % getattr(
                        operation, "name", "an operation"))
                if index and index % config.OPERATIONS_PER_CHUNK == 0:
                    adsk.doEvents()
                    if progress.at(index + 1):
                        break

            clock.at("notes and icons")
            report.note("of which, seconds",
                        **{k: round(v, 2) for k, v in spent.items()})
            report.note("and of the writing, seconds",
                        **{k: round(v, 2) for k, v in marks.cost.items()})
            progress.done()
            _clear_setup_marks(cam, report, writing)
            clock.at("setup notes")
            clock.say()

            counts = dict(report.counts)
            path = report.close()
            # One line rather than one per kind. This dialog is read standing
            # at a machine; four stacked lines and two file paths was more
            # screen than the answer was worth.
            summary = ", ".join("%d %s" % (counts[k], k)
                                for k in sorted(counts))
            planned = sum(1 for e in report.operations if e.get("would"))
            wrote = sum(1 for e in report.operations
                        if e.get("written") and e["written"] != "failed")
            if not understood:
                headline = refusal
                # Assigned here too, or standing down raises on the way out and
                # the person is told the check crashed when in fact it did
                # exactly what it should: worked everything out and wrote none
                # of it.
                tail = config.STOOD_DOWN_TAIL % len(operations)
            elif writing:
                headline = (config.MARKED % (wrote, len(operations)) if wrote
                            else config.MARKED_NOTHING % len(operations))
                tail = config.MARKED_TAIL
            else:
                headline = config.CHECKED % len(operations)
                tail = config.CHECKED_TAIL % planned
            # Said once, after a check, rather than trusting somebody to read
            # every note. Picking a preset does not rebuild a toolpath and
            # Fusion does not mark one as needing it, so this is the only place
            # the add-in can reliably put the instruction in front of the person
            # who just acted on its advice.
            governs = [v for _op, v in decided if v.get("carriesShape")]
            if governs:
                tail += config.REGENERATE_TAIL % len(governs)
                report.note("OPERATIONS ON PRESETS THAT SET THE CUT",
                            count=len(governs),
                            operations=[v["operation"] for v in governs][:10],
                            consequence=("their toolpaths hold whatever shape "
                                         "they were last generated with; "
                                         "regenerate before posting"))

            # The session's event log used to be named here as well. It is a
            # developer's file, the path is long, and Write a debug report
            # gathers it along with everything else -- so two paths in a
            # dialog bought nothing that one did not.
            return path, counts, ("%s\n%s\n\n%s"
                                  % (headline, summary or "nothing found", tail))
        except Exception:
            report.failed("the pass stopped early")
            return report.close(), {}, config.STOPPED_EARLY
        finally:
            if progress is not None:
                progress.done()
