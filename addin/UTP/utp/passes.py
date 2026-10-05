"""One pass over one document.

Phase 1 has exactly one trigger: somebody presses the button. There are no
automatic passes, because Fusion can be pushed into "not responding" by a
burst of API calls and a read-only phase has nothing urgent to say. The work
is chunked, with a breath between chunks, for the same reason.
"""

import time

import adsk.core
import adsk.cam

from . import (compat, config, diagnostics, library, marks, presets,
               settings, state, versions)


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


def _breathe(index, every=None):
    """Hand Fusion back the main thread for a moment.

    Everything here runs on that thread, because the Fusion API cannot be
    used off it, so a long uninterrupted loop is what makes Fusion go grey
    and say "not responding". Every loop that can run long gives it a breath.

    The cost of breathing is that somebody could change the document
    mid-pass. Nothing is held across a breath that would not be re-read
    anyway, and a verdict is worked out from the document as it stands.
    """
    if index and index % (every or config.OPERATIONS_PER_CHUNK) == 0:
        adsk.doEvents()


def _document_tools(cam):
    """Every tool in the document, by id. One pass over the shelf.

    Looking each one up on its own scanned the whole shelf and asked every
    tool on it for its id, and an id costs a toJson() of the entire tool. On
    a file with a hundred tools that is ten thousand tool serialisations for
    a hundred answers.
    """
    found = {}
    try:
        shelf = cam.documentToolLibrary
        for index in range(shelf.count):
            candidate = shelf.item(index)
            key = library.tool_id(candidate)
            if key:
                found[key] = candidate
            # An id costs a toJson() of the whole tool, so this is one of the
            # slowest loops in a pass.
            _breathe(index)
    except Exception:
        pass
    return found


def _id_by_description(shelf):
    """A cheap route to a tool's id, for the descriptions that allow one.

    The shelf map already knows every tool's id, and a description is free to
    read where an id costs a toJson() of the whole tool. Descriptions do
    collide, measured at four tools sharing one, so only descriptions held by
    exactly one tool are offered and everything else falls back to working
    the id out properly.
    """
    seen = {}
    for key, tool in shelf.items():
        try:
            name = (tool.description or "").strip()
        except Exception:
            continue
        seen.setdefault(name, []).append(key)
    unique = {name: ids[0] for name, ids in seen.items() if len(ids) == 1}

    def resolve(tool):
        try:
            return unique.get((tool.description or "").strip())
        except Exception:
            return None
    return resolve


def _document_tool(cam, tool_id, shelf=None):
    """A tool in the document by id, from a map built once if given one.

    update() leaves every tool reference taken before it invalid, so a map
    built before one has to be thrown away rather than reused.
    """
    if shelf is not None:
        return shelf.get(tool_id)
    return _document_tools(cam).get(tool_id)


class _Progress:
    """A progress bar, or nothing at all.

    Fusion's only on-screen progress is a dialog, and a dialog blocks working
    in Fusion while it is up, so this is off unless somebody asks for it. The
    session log gets a line every chunk either way, which is an indicator
    that gets in nobody's way but has to be looked at to be seen.

    Shown only for a document big enough to wait for: on a handful of
    operations a bar is a flicker.
    """

    def __init__(self, app, total, report):
        self.dialog = None
        self.cancelled = False
        self.report = report
        if not config.SHOW_PROGRESS or total < config.PROGRESS_FROM:
            return
        try:
            self.dialog = app.userInterface.createProgressDialog()
            self.dialog.isCancelButtonShown = True
            self.dialog.show(config.DIALOG_TITLE, config.PROGRESS_MESSAGE,
                             0, total)
        except Exception:
            self.dialog = None

    def saying(self, message):
        """Change what the bar says, for a later stage of the same pass."""
        if self.dialog is not None:
            try:
                self.dialog.message = message
            except Exception:
                pass

    def at(self, done):
        """Move it along. True means somebody pressed cancel."""
        if self.dialog is None:
            return False
        try:
            if self.dialog.wasCancelled:
                self.cancelled = True
                return True
            self.dialog.progressValue = done
        except Exception:
            self.dialog = None
        return False

    def done(self):
        if self.dialog is not None:
            try:
                self.dialog.hideDialog()
            except Exception:
                pass
            self.dialog = None
        if self.cancelled:
            self.report.note("STOPPED: somebody pressed cancel",
                             note="whatever was written stays, and one undo "
                                  "takes it back")


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
    return found


def _review_versions(cam, decided, tools, report, writing):
    """Bring version numbers up to date, for the UTPs this document uses.

    Returns the libraries to carry on with: after a bump they have to be read
    again, or the pass that moved a number writes notes that do not carry it.

    Only the presets in hand, never all of them: this runs on a button press
    and every library write is risk for no gain. A library nobody has stamped
    still works; its notes just carry no numbers.
    """
    wanted = {}
    for operation, verdict in decided:
        found = verdict.get("libraryPresetId")
        if not found:
            continue
        library_tool = tools.get(verdict.get("toolId"))
        if library_tool is None:
            continue
        preset = library_tool.presets.get(found)
        if preset is not None:
            wanted[preset.id] = preset
    if not wanted:
        return tools
    libraries = adsk.cam.CAMManager.get().libraryManager.toolLibraries
    allowed = writing and settings.on("stamp")
    if versions.review(libraries, wanted.values(), report, allowed) and allowed:
        library.forget()          # the numbers just moved; read them again
        fresh, ok = library.cached(report, adsk.doEvents, force=True)
        if ok:
            return fresh
    return tools


def _sync_and_tidy(cam, in_use, used_ids, report, writing):
    """Bring in UTPs the document has never seen, and drop copies nothing needs.

    Returns True if anything was written, since update() leaves every tool
    reference taken before it stale.
    """
    wrote = False
    shelf = _document_tools(cam)
    for seen, (tool_id, library_tool) in enumerate(in_use.items()):
        _breathe(seen, 5)
        tool = shelf.get(tool_id)
        if tool is None:
            continue

        absent = presets.missing(tool, library_tool)
        if absent:
            allowed = writing and settings.on("presets")
            names = [presets.latest_name(p.name, p.version) for p in absent]
            if not allowed:
                report.note("would bring in presets this document has not seen",
                            tool=library_tool.description, presets=names)
            else:
                for library_preset in absent:
                    try:
                        done = presets.apply(cam, tool, library_preset,
                                             {"add": library_preset.name})
                        report.note("brought in a preset from the library",
                                    did=done)
                        report.wrote += len(done)
                        wrote = True
                    except Exception:
                        report.failed("could not bring in %s"
                                      % library_preset.name)
                shelf = _document_tools(cam)   # update() invalidated them
                tool = shelf.get(tool_id)
                if tool is None:
                    continue

        spare = presets.removable(tool, library_tool, used_ids)
        if not spare:
            continue
        if report.failures:
            # Nothing is deleted after a pass that went wrong. The operation
            # walk is defensive, so a collection that threw leaves an
            # operation invisible rather than raising, and an invisible
            # operation's preset is one nothing is protecting.
            report.note("not tidying: something went wrong in this pass",
                        failures=report.failures,
                        would_have_removed=[n for _i, n, _v in spare])
            continue
        allowed = writing and settings.on("tidy")
        if not allowed:
            report.note("would remove copies nothing uses any more",
                        tool=library_tool.description,
                        presets=[name for _i, name, _v in spare],
                        held_back=("tidying is switched off" if writing
                                   else "writing is switched off"),
                        kept=("whatever operations point at, and the most "
                              "recently retired copy"))
            continue
        try:
            report.note("tidied the document tool library",
                        did=presets.remove(cam, tool, spare))
            report.wrote += len(spare)
            wrote = True
            shelf = _document_tools(cam)   # update() invalidated them
        except Exception:
            report.failed("could not tidy %s" % library_tool.description)
    return wrote


def _ensure_presets(cam, decided, tools, report, writing):
    """Make the newer values pickable for every behind operation.

    Returns True if anything was written, since the caller must then re-read
    the operations: update() leaves the references it was given stale.

    One preset per library preset, not per operation. Six operations sharing a
    tool need one new entry in the dropdown between them, not six.
    """
    wanted = {}
    # Which presets operations actually sit on, and which tools this document
    # uses. Both are needed before anything can be removed: a preset an
    # operation points at must never go.
    used_ids = set()
    in_use = {}
    for operation, verdict in decided:
        if verdict.get("presetId"):
            used_ids.add(verdict["presetId"])
        found = verdict.get("toolId")
        library_tool = tools.get(found) if found else None
        if library_tool is not None:
            in_use[found] = library_tool
        if verdict["state"] != state.BEHIND:
            continue
        if library_tool is None:
            continue
        # By the library preset the verdict resolved, not by the id of the
        # preset the operation sits on. Once an operation is on a copy the
        # add-in made, that id is the copy's own and the library has never
        # heard of it, so newer versions would silently stop being offered.
        library_preset = library_tool.presets.get(verdict["libraryPresetId"])
        if library_preset is None:
            continue
        # Tools are remembered by id, not by reference: the first update()
        # below invalidates every tool object gathered here.
        wanted.setdefault(library_preset.id, (found, library_preset))

    wrote = _sync_and_tidy(cam, in_use, used_ids, report, writing)

    if not wanted:
        return wrote

    allowed = writing and settings.on("presets")
    shelf = _document_tools(cam)
    for tool_id, library_preset in wanted.values():
        tool = shelf.get(tool_id)
        if tool is None:
            report.failed("the tool for %s is no longer in the document"
                          % library_preset.name)
            continue
        intended = presets.plan(tool, library_preset)
        if not intended:
            report.note("the newer values are already pickable",
                        preset=presets.latest_name(library_preset.name))
            continue
        if not allowed:
            report.note("would add a preset to the document", plan=intended,
                        preset=presets.latest_name(library_preset.name),
                        held_back=("adding presets is switched off"
                                   if writing else "writing is switched off"))
            continue
        try:
            done = presets.apply(cam, tool, library_preset, intended)
            # The plan as well as what was done. plan() says which values made
            # the existing copy stale, and that was reported on the dry run
            # and thrown away here — which is the one path where it matters,
            # because a copy that is stale again on the next pass means a new
            # one is added every time and only this field says why.
            report.note("added to the document tool library", did=done,
                        plan=intended)
            report.wrote += len(done)
            shelf = _document_tools(cam)   # update() invalidated them
            wrote = True
        except Exception:
            report.failed("could not add a preset for %s" % library_preset.name)
    return wrote


def _mark_setups(cam, tools, report, writing, decided=None):
    """A signpost on each setup, because a collapsed one hides everything.

    Done after the operations, so it describes what they have just become
    rather than what they were.
    """
    known = {}
    for operation, verdict in (decided or []):
        if verdict.get("operationId"):
            known[verdict["operationId"]] = verdict
    for setup, operations in by_setup(cam):
        counts = {}
        for index, operation in enumerate(operations):
            _breathe(index)
            try:
                verdict = known.get(str(operation.operationId))
                if verdict is None:
                    verdict = state.reconcile(operation, tools)
            except Exception:
                continue
            counts[verdict["state"]] = counts.get(verdict["state"], 0) + 1
        try:
            changes = marks.setup_plan(setup, counts)
        except Exception:
            report.failed("could not work out a note for a setup")
            continue
        if not changes:
            continue
        name = getattr(setup, "name", "?")
        if not writing:
            report.note("would mark the setup %s" % name,
                        would=marks.describe(changes))
            continue
        try:
            marks.apply(setup, changes)
            adsk.doEvents()
            report.wrote += len(changes)
            report.note("marked the setup %s" % name,
                        did=marks.describe(changes))
        except Exception:
            report.failed("could not mark the setup %s" % name)


def remove_marks(app):
    """Take every trace of the add-in back out of the active document.

    The way back out, so installing this is not a one-way door. It lands as
    one undo step like any other pass, and it leaves presets alone: an
    operation may be on one the add-in added, and removing that would
    re-point it without changing its values.
    """
    with marks.holding():
        document = app.activeDocument
        report = diagnostics.Report((document.name if document else "?") + " - unmark")
        try:
            products = document.products if document else None
            cam = products.itemByProductType("CAMProductType") if products else None
            if cam is None:
                report.note("this document has no manufacturing data")
                return report.close(), {}, config.NOTHING_TO_CHECK
            if not _writable(document, report):
                return report.close(), {}, config.READ_ONLY

            cleared = 0
            looked = 0
            for setup, operations in by_setup(cam):
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


def by_setup(cam):
    """[(setup, [operations])], so a setup can be told what is inside it."""
    found = []
    try:
        for index in range(cam.setups.count):
            setup = cam.setups.item(index)
            found.append((setup, _within(setup)))
    except Exception:
        pass
    return found


def operations_of(document):
    """Every operation in a document, or none if it has no Manufacture data."""
    try:
        products = document.products if document else None
        cam = products.itemByProductType("CAMProductType") if products else None
    except Exception:
        return []
    return _operations(cam) if cam is not None else []


def _operations(cam):
    """Every operation in the document, setups and folders alike.

    Operations inside folders and patterns do not appear in a setup's own
    operations collection on every build, so the tree is walked rather than
    assumed to be flat.
    """
    found = []
    for index in range(cam.setups.count):
        setup = cam.setups.item(index)
        found.extend(_within(setup))
    return found


def _within(owner, seen=None):
    """Every operation under a setup, folder or pattern.

    Counted as it goes, because this walk has never met a folder: a real job
    organises its operations into them, and a walk that quietly failed to
    descend would leave whole sections of a file with no notes and nothing
    anywhere saying they had been missed.
    """
    if seen is None:
        seen = _nothing_seen()
    found = []
    for attribute in ("operations", "folders", "patterns"):
        try:
            collection = getattr(owner, attribute)
        except Exception:
            # A setup that has no patterns at all is not a failure, it is a
            # setup with no patterns. Only an item that will not come out of
            # a collection it is listed in counts below.
            continue
        for index in range(collection.count):
            _breathe(index)
            try:
                item = collection.item(index)
            except Exception:
                # Counted, because an operation that cannot be read is an
                # operation nothing is protecting: it is absent from the
                # verdicts, so the preset it sits on is absent from the set
                # of presets in use, and the tidy would be free to delete
                # the preset it is running. Swallowing this silently is what
                # made the guard against exactly that case unreachable.
                seen["unreadable"] += 1
                continue
            if attribute == "operations":
                found.append(item)
            else:
                seen[attribute] += 1
                inside = _within(item, seen)
                seen["deepest"] = max(seen["deepest"], 1)
                found.extend(inside)
    return found


def _walk(cam):
    """Every operation, and what the tree it came from looks like.

    One traversal. Counting the shape used to be a second walk of the whole
    document for no reason but to describe it.
    """
    seen = _nothing_seen()
    found = []
    try:
        for index in range(cam.setups.count):
            setup = cam.setups.item(index)
            try:
                seen["loose"] += setup.operations.count
            except Exception:
                pass
            found.extend(_within(setup, seen))
    except Exception:
        # Half the setups may have been walked. Same reasoning as above: an
        # incomplete walk must not be mistaken for a complete one.
        seen["unreadable"] += 1
    shape = {"operations found": len(found),
             "folders": seen["folders"],
             "patterns": seen["patterns"],
             "directly under a setup": seen["loose"],
             "inside a folder or pattern": len(found) - seen["loose"],
             "could not be read": seen["unreadable"]}
    return found, shape


def _nothing_seen():
    return {"folders": 0, "patterns": 0, "deepest": 0, "loose": 0,
            "unreadable": 0}


def run(app, allow_writing=True):
    """Check the active document. Returns (report path, counts, message)."""
    with marks.holding():
        document = app.activeDocument
        report = diagnostics.Report(document.name if document else "no document")
        try:
            products = document.products if document else None
            cam = products.itemByProductType("CAMProductType") if products else None
            if cam is None:
                report.note("this document has no manufacturing data")
                return report.close(), {}, config.NOTHING_TO_CHECK

            # Pressing the button is also what warms the cache the edit handler
            # needs, so it always re-reads rather than trusting an old read.
            clock = _Clock(report)
            marks.forget_cost()
            shelf = _document_tools(cam)
            resolve = _id_by_description(shelf)
            clock.at("read the document's tools")

            tools, ok = library.cached(report, adsk.doEvents, force=True,
                                       wanted=set(shelf))
            clock.at("read the Hub libraries")
            if not ok:
                report.note("stopping: without the library nothing can be decided")
                return (report.close(), {},
                        config.NO_LIBRARY)

            # Walked once. The schema survey and the shape of the tree used to
            # traverse the whole document again each, for nothing but to read it.
            operations, shape = _walk(cam)
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
            newest = compat.survey(operations, _breathe)
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

            progress = _Progress(app, len(operations), report)
            decided = _verdicts(operations, tools, report, progress, resolve)
            clock.at("worked out every verdict")

            # Versions before anything reads them, so a note can name one. The
            # refreshed libraries are taken back, because a bump changes what
            # every later step should be reading.
            tools = _review_versions(cam, decided, tools, report, writing)
            clock.at("reviewed version numbers")

            # Presets first, notes second. A behind operation's note is worth
            # little until the newer values are pickable in its dropdown, and
            # update() leaves the tool and preset references stale, so the
            # operations are re-read and judged again afterwards rather than
            # reused.
            changed_presets = _ensure_presets(cam, decided, tools, report, writing)
            clock.at("presets in the document")
            if changed_presets:
                operations = _operations(cam)
                decided = _verdicts(operations, tools, report, progress,
                                    _id_by_description(_document_tools(cam)))
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
                        _breathe(1, config.WRITES_PER_CHUNK)
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
            _mark_setups(cam, tools, report, writing, decided)
            clock.at("setup notes")
            clock.say()

            counts = dict(report.counts)
            path = report.close()
            summary = "\n".join("%s: %d" % (k, counts[k]) for k in sorted(counts))
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
                headline = config.MARKED % (wrote, len(operations))
                tail = config.MARKED_TAIL
            else:
                headline = config.CHECKED % len(operations)
                tail = config.CHECKED_TAIL % planned
            events_seen = diagnostics.session_count()
            if events_seen:
                tail += "\n\n" + config.EVENTS_SEEN % (events_seen,
                                                       diagnostics.session_path())
            return path, counts, ("%s\n\n%s\n\n%s"
                                  % (headline, summary or "nothing found", tail))
        except Exception:
            report.failed("the pass stopped early")
            return report.close(), {}, config.STOPPED_EARLY
