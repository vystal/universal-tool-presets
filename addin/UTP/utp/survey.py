"""Reading what is in a document: the operation tree, and the tool shelf.

Lifted out of passes.py, where it sat between the two passes and the preset
machinery with nothing to say to either. Both of those import this; it imports
neither, which is what keeps the three apart.

Nothing here writes. Every function is defensive about a collection that
throws, because an operation that cannot be read must come back as a counted
failure rather than take a whole pass down -- what is counted here is what the
tidy's protection is built from.
"""

import adsk.cam

from . import config, library


def breathe(index, every=None):
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


def document_tools(cam):
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
            breathe(index)
    except Exception:
        pass
    return found


def id_by_description(shelf):
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


def by_setup(cam, report=None):
    """[(setup, [operations])], so a setup can be told what is inside it.

    Per setup, and counted. One try around the whole loop meant a setup that
    threw truncated the list at that point and said nothing: Remove all notes
    walks this, so it could clear half a document, report "removed the notes
    from 6 of 6" from the half it could see, and leave the rest marked. The
    count it reports is of what it found, which is the number that looked
    right.
    """
    found = []
    try:
        count = cam.setups.count
    except Exception as exc:
        if report is not None:
            report.failed("could not read the setups: %s" % exc)
        return found
    for index in range(count):
        try:
            setup = cam.setups.item(index)
            found.append((setup, _within(setup)))
        except Exception as exc:
            if report is not None:
                report.failed("could not read setup %d of %d (%s), so what it "
                              "holds was not reached" % (index + 1, count, exc))
            continue
    return found


def operations_of(document):
    """Every operation in a document, or none if it has no Manufacture data."""
    try:
        products = document.products if document else None
        cam = products.itemByProductType("CAMProductType") if products else None
    except Exception:
        return []
    return operations(cam) if cam is not None else []


def operations(cam):
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
            breathe(index)
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


def walk(cam):
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
