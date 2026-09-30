"""One pass over one document.

Phase 1 has exactly one trigger: somebody presses the button. There are no
automatic passes, because Fusion can be pushed into "not responding" by a
burst of API calls and a read-only phase has nothing urgent to say. The work
is chunked, with a breath between chunks, for the same reason.
"""

import adsk.core
import adsk.cam

from . import (compat, config, diagnostics, library, marks, presets,
               state, versions)


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


def _document_tool(cam, tool_id):
    """A tool in the document, looked up fresh by id.

    update() leaves every tool reference taken before it invalid, so a pass
    that touches more than one tool has to re-find each one rather than hold
    on to it.
    """
    try:
        shelf = cam.documentToolLibrary
        for index in range(shelf.count):
            candidate = shelf.item(index)
            if library.tool_id(candidate) == tool_id:
                return candidate
    except Exception:
        pass
    return None


def _review_versions(cam, operations, tools, report, writing):
    """Bring version numbers up to date, for the UTPs this document uses.

    Returns the libraries to carry on with: after a bump they have to be read
    again, or the pass that moved a number writes notes that do not carry it.

    Only the presets in hand, never all of them: this runs on a button press
    and every library write is risk for no gain. A library nobody has stamped
    still works; its notes just carry no numbers.
    """
    wanted = {}
    for operation in operations:
        verdict = state.reconcile(operation, tools)
        found = verdict.get("libraryPresetId")
        if not found:
            continue
        tool = getattr(operation, "tool", None)
        library_tool = tools.get(library.tool_id(tool)) if tool else None
        if library_tool is None:
            continue
        preset = library_tool.presets.get(found)
        if preset is not None:
            wanted[preset.id] = preset
    if not wanted:
        return tools
    libraries = adsk.cam.CAMManager.get().libraryManager.toolLibraries
    allowed = writing and config.MAY_BUMP_LIBRARY_VERSIONS
    if versions.review(libraries, wanted.values(), report, allowed) and allowed:
        library.forget()          # the numbers just moved; read them again
        fresh, ok = library.cached(report, adsk.doEvents, force=True)
        if ok:
            return fresh
    return tools


def _ensure_presets(cam, operations, tools, report, writing):
    """Make the newer values pickable for every behind operation.

    Returns True if anything was written, since the caller must then re-read
    the operations: update() leaves the references it was given stale.

    One preset per library preset, not per operation. Six operations sharing a
    tool need one new entry in the dropdown between them, not six.
    """
    wanted = {}
    for operation in operations:
        verdict = state.reconcile(operation, tools)
        if verdict["state"] != state.BEHIND:
            continue
        tool = getattr(operation, "tool", None)
        library_tool = tools.get(library.tool_id(tool)) if tool else None
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
        wanted.setdefault(library_preset.id,
                          (library.tool_id(tool), library_preset))

    if not wanted:
        return False

    allowed = writing and config.MAY_ADD_PRESETS
    wrote = False
    for tool_id, library_preset in wanted.values():
        tool = _document_tool(cam, tool_id)
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
            report.note("added to the document tool library", did=done)
            report.wrote += len(done)
            wrote = True
        except Exception:
            report.failed("could not add a preset for %s" % library_preset.name)
    return wrote


def _mark_setups(cam, tools, report, writing):
    """A signpost on each setup, because a collapsed one hides everything.

    Done after the operations, so it describes what they have just become
    rather than what they were.
    """
    for setup, operations in by_setup(cam):
        counts = {}
        for operation in operations:
            try:
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
            report.wrote += len(changes)
            report.note("marked the setup %s" % name,
                        did=marks.describe(changes))
        except Exception:
            report.failed("could not mark the setup %s" % name)


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


def _within(owner):
    found = []
    for attribute in ("operations", "folders", "patterns"):
        try:
            collection = getattr(owner, attribute)
        except Exception:
            continue
        for index in range(collection.count):
            try:
                item = collection.item(index)
            except Exception:
                continue
            if attribute == "operations":
                found.append(item)
            else:
                found.extend(_within(item))
    return found


def run(app):
    """Check the active document. Returns (report path, counts, message)."""
    document = app.activeDocument
    report = diagnostics.Report(document.name if document else "no document")
    try:
        products = document.products if document else None
        cam = products.itemByProductType("CAMProductType") if products else None
        if cam is None:
            report.note("this document has no manufacturing data")
            return report.close(), {}, "Nothing to check: no Manufacture data here."

        # Pressing the button is also what warms the cache the edit handler
        # needs, so it always re-reads rather than trusting an old read.
        tools, ok = library.cached(report, adsk.doEvents, force=True)
        if not ok:
            report.note("stopping: without the library nothing can be decided")
            return (report.close(), {},
                    "The Hub library could not be read, so nothing was decided.")

        writing = config.MAY_WRITE_ON_DEMAND and _writable(document, report)
        # A file written by a newer add-in is read and reported on, never
        # changed: its rules are not this version's to second-guess.
        newest = compat.survey(_operations(cam))
        understood, refusal = compat.may_write(newest)
        if not understood:
            report.note("NOT WRITING", reason=refusal)
            writing = False
        if writing:
            # Pressing the button is how a document joins the system, which is
            # what lets later edits and saves write to it.
            from . import events
            events.joined(document)
        operations = _operations(cam)
        report.note("found operations", count=len(operations),
                    writing="yes" if writing else "no")

        # Versions before anything reads them, so a note can name one. The
        # refreshed libraries are taken back, because a bump changes what
        # every later step should be reading.
        tools = _review_versions(cam, operations, tools, report, writing)

        # Presets first, notes second. A behind operation's note is worth
        # little until the newer values are pickable in its dropdown, and
        # update() leaves the tool and preset references stale, so the
        # operations are re-read afterwards rather than reused.
        if _ensure_presets(cam, operations, tools, report, writing):
            operations = _operations(cam)

        for index, operation in enumerate(operations):
            try:
                verdict = state.reconcile(operation, tools)
                # Worked out whether or not it is allowed to happen, so the
                # decisions can be read and argued with either way.
                verdict["would"] = marks.plan(operation, verdict)
                if writing and verdict["would"]:
                    try:
                        verdict["written"] = marks.apply(operation,
                                                         verdict["would"])
                        report.wrote += len(verdict["written"])
                    except Exception:
                        verdict["written"] = "failed"
                        report.failed("could not write to %s"
                                      % verdict["operation"])
                report.operation(verdict)
            except Exception:
                report.failed("could not work out %s" % getattr(
                    operation, "name", "an operation"))
            if index % config.OPERATIONS_PER_CHUNK == 0:
                adsk.doEvents()

        _mark_setups(cam, tools, report, writing)

        counts = dict(report.counts)
        path = report.close()
        summary = "\n".join("%s: %d" % (k, counts[k]) for k in sorted(counts))
        planned = sum(1 for e in report.operations if e.get("would"))
        wrote = sum(1 for e in report.operations
                    if e.get("written") and e["written"] != "failed")
        if not understood:
            headline = refusal
        elif writing:
            headline = "Marked %d of %d operations." % (wrote, len(operations))
            tail = "One Ctrl+Z undoes the lot; the document is not saved."
        else:
            headline = "Checked %d operations. Nothing was changed." % len(operations)
            tail = ("Writing is off. %d operations would have been marked; "
                    "the report says exactly how." % planned)
        events_seen = diagnostics.session_count()
        if events_seen:
            tail += ("\n\n%d events recorded this session:\n%s"
                     % (events_seen, diagnostics.session_path()))
        return path, counts, ("%s\n\n%s\n\n%s"
                              % (headline, summary or "nothing found", tail))
    except Exception:
        report.failed("the pass stopped early")
        return report.close(), {}, "The check stopped early; see the report."
