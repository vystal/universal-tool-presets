"""What the add-in would put on an operation: a note, an icon colour, a record.

This module decides; it does not write. Nothing in it calls into Fusion except
to read what is there now, so what it would do can be reported and argued with
before anything is allowed to happen.

The add-in owns the first line of a note, which always starts with the prefix.
Everything else in a note is somebody's own text and is kept exactly, line
breaks and all.
"""

import json
import time

from . import config, settings, state


def _named(verdict, version):
    """The UTP's name, with a version when one is known."""
    name = verdict.get("preset") or "?"
    return config.VERSION_LABEL % (name, version) if version else name


def ours(words):
    """One line of the add-in's, encased so it can be told from anybody else's.

    Every line the add-in writes goes through here, so there is one place that
    decides what its own line looks like and one rule for recognising it.
    """
    return config.NOTE_PREFIX + words + config.NOTE_SUFFIX


def note_line(verdict):
    """The one line the add-in owns, or None if it should not be there.

    Version numbers are used when the library has them and left out when it
    does not, so a library nobody has stamped still gets useful notes.
    """
    kind = verdict["state"]
    if kind == state.CURRENT:
        return ours(_named(verdict, verdict.get("libraryVersion")))
    if kind == state.BEHIND:
        newer = verdict.get("libraryVersion")
        # "v2 - v3 available" when both are known. When the document's own
        # version is not, saying which version is newer is still worth more
        # than saying nothing, so only the second half is dropped.
        return ours("%s %s %s" % (
            _named(verdict, verdict.get("documentVersion")),
            config.NOTE_SEPARATOR,
            ("v%s available" % newer) if newer else config.NOTE_UPDATE))
    if kind == state.CUSTOM:
        return ours(config.NOTE_CUSTOM)
    # not adopted, not a UTP tool, retired: the add-in says nothing at all.
    return None


def setup_line(counts):
    """What a setup says about the operations inside it, or None.

    Colour answers "do I need to look in here", text says what is in it.
    Operations that were never on a UTP are counted out rather than counted
    against: a setup of twenty legacy operations has nothing to say, exactly
    as those operations have nothing to say themselves.
    """
    behind = counts.get(state.BEHIND, 0)
    custom = counts.get(state.CUSTOM, 0)
    tracked = behind + custom + counts.get(state.CURRENT, 0)
    if not tracked:
        return None, None
    if behind:
        return ours(config.SETUP_BEHIND % (behind, tracked)), "Yellow"
    if custom:
        # Green, because a deliberate override is not a task. The count is
        # still said, so green cannot be read as "everything here is on the
        # shop's presets".
        return ours(config.SETUP_CUSTOM % (tracked, custom)), "Green"
    return ours(config.SETUP_CLEAN % tracked), "Green"


def setup_plan(setup, counts):
    """What would change on a setup. Empty means nothing to do."""
    changes = {}
    if not settings.on("mark"):
        return changes
    line, colour = setup_line(counts)
    existing = _notes(setup)
    wanted = merge(existing, line)
    if wanted != (existing or ""):
        changes["note"] = {"from": existing or "", "to": wanted}
    if colour is None and _ours_in(existing):
        # Nothing tracked in here any more, usually because the last tracked
        # operation was deleted. Same as an operation: the colour comes off
        # with the line, or the setup keeps a yellow "look in here" over a
        # note that no longer exists.
        colour = _was_icon(setup) or config.ICON_DEFAULT
    if colour is not None and _icon(setup) != colour:
        changes["icon"] = {"from": _icon(setup), "to": colour}
    return changes


def merge(existing, line):
    """The note the add-in would leave behind, ours first and theirs below.

    Ours is a line that is encased, wherever in the note it sits. Everything
    else is somebody's own words and is kept exactly, in the order they put
    them.

    Two earlier rules got this wrong in the same direction. Owning every line
    that merely started with "[UTP] " deleted a note a person had typed in the
    same style, and "[UTP] check this one by hand before running" is exactly
    the sort of thing somebody who reads these notes would write. Owning only
    the first line narrowed that to one shape and still ate a line written
    above the add-in's own. Encasing the line settles it: there is a form only
    the add-in produces, so there is nothing left to guess about.
    """
    lines = (existing or "").splitlines()
    mine = _mine(lines)
    theirs = [l for index, l in enumerate(lines) if index not in mine]
    if line is None:
        return "\n".join(theirs).strip("\n")
    return "\n".join([line] + theirs).rstrip("\n")


def record(verdict):
    """What the add-in would store on the operation, or None.

    Only operations that are in the system get a record. An operation whose
    values already match its preset is in the system whether or not anything
    said so, which is how the first one ever gets adopted.
    """
    if verdict["state"] not in (state.CURRENT, state.BEHIND, state.CUSTOM):
        return None
    if not verdict.get("presetId"):
        return None
    # The schema rides inside the record, so one write says both what the
    # operation was set from and which rules wrote it.
    return {"s": config.SCHEMA,
            config.KEY_ADOPTED_PRESET: verdict["presetId"],
            config.KEY_OPERATION_ID: verdict["operationId"]}


def _was_icon(owner):
    """The colour an operation had before the add-in first touched it."""
    try:
        record = owner.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_RECORD)
        if record is not None:
            return json.loads(record.value).get("i")
    except Exception:
        pass
    return None


def _marked_before(owner):
    """Whether the add-in has written a record on this one.

    Asked rather than inferred from the verdict, because the verdict's record
    is a checked one: state._record withholds it the moment the operation
    moves to a different preset. The attribute is still sitting there, and
    for "has this ever been marked" that is the honest question.
    """
    try:
        return owner.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                           config.KEY_RECORD) is not None
    except Exception:
        return False


def _mine(lines):
    """Which lines of a note the add-in wrote, by position.

    An encased line is the add-in's wherever it sits, which is the whole point
    of encasing it.

    A bare "[UTP] " line is only considered when there is no encased one in
    the note at all. Then it was written by a version that had not started
    encasing yet, and rewriting it is how a document stops carrying the old
    form. But if the note already holds a line in the current form, the add-in
    has already said its piece here, so a bare one is somebody's own words and
    is left alone.

    What cannot be told apart either way is a bare line somebody typed in a
    note the add-in has never marked. That ambiguity is the whole reason the
    form changed, and it narrows to nothing as documents are re-marked.
    """
    mine = {index for index, line in enumerate(lines)
            if line.startswith(config.NOTE_PREFIX)}
    if mine:
        return mine
    if lines and lines[0].startswith(config.NOTE_PREFIX_WAS):
        return {0}
    return set()


def _ours_in(existing):
    """Whether a line of ours is in a note at all."""
    return bool(_mine((existing or "").splitlines()))


def plan(operation, verdict, during_their_edit=False):
    """What would change on this operation. Empty means nothing to do.

    Idempotent by construction: it compares against what is there now, so a
    second pass over an unchanged document plans nothing. That is what makes
    re-running after a crash harmless.
    """
    changes = {}
    if not settings.on("mark"):
        # Switched off: it still reads and reports, and writes nothing to an
        # operation at all. Records included, because an invisible attribute
        # is still a write to somebody who asked for none.
        return changes
    existing = _notes(operation)
    line = note_line(verdict)

    if (during_their_edit and line and _marked_before(operation)
            and not _ours_in(existing)):
        # They have just cleared our line, and clearing a note raises the
        # same event as any other edit, so putting it straight back meant it
        # could not be deleted at all. Left alone for now.
        #
        # Asked of the record attribute rather than of the verdict, which
        # withholds its record whenever the operation has moved to a
        # different preset. Clearing the note in the same visit to the dialog
        # as picking the new preset is the likeliest moment of all for this to
        # happen, and that was the one case where the line came straight back.
        #
        # Not for ever: the note says where the operation stands, so the next
        # save works it out and writes it again. Only the fight in the moment
        # was the problem.
        return changes

    wanted = merge(existing, line)
    if wanted != (existing or ""):
        changes["note"] = {"from": existing or "", "to": wanted}

    colour = config.ICON_FOR_STATE.get(verdict["state"])
    if colour is None and _marked_before(operation):
        # An operation that has left the tracked states: its preset was
        # retired, or somebody moved it off a UTP. The line comes off, and
        # the colour has to come off with it. Leaving it was worse than
        # saying nothing: a green dot means "on the current feeds, nothing to
        # do" and no note means "never on a shop preset", so the operation
        # showed both at once and the green was a lie.
        colour = _was_icon(operation) or config.ICON_DEFAULT
    if colour is not None:
        now = _icon(operation)
        if now != colour:
            changes["icon"] = {"from": now, "to": colour}

    wanted_record = record(verdict)
    if wanted_record and not verdict.get("record"):
        # What the icon was before any of this, so unmarking can put it
        # back. A note's own text is kept carefully and a colour somebody
        # chose deliberately was simply overwritten, which is inconsistent.
        #
        # Whatever a previous record says comes first. A record is rewritten
        # whenever the operation moves to a different preset, which is the
        # one action this add-in exists to encourage, and reading the live
        # icon at that moment captured the add-in's own green as "the colour
        # it had before the add-in touched it". Remove all notes then painted
        # an up-to-date operation yellow, and a red one somebody had marked
        # by hand stayed lost.
        was = _was_icon(operation) or _icon(operation)
        if was is not None:
            wanted_record["i"] = was
        changes["record"] = wanted_record

    return changes


_writing = {"depth": 0}


def busy():
    """True while the add-in is part-way through writing something.

    Writing a note fires operationBaseChanged, so without this the add-in
    reacts to itself: measured on the first run with events writing, one
    button press produced 21 handler calls, each half-finishing work the
    press was already doing. It converged only because plan() happens to be
    idempotent, which is far too thin a margin for a loop inside Fusion's
    event handling.
    """
    return _writing["depth"] > 0


class holding:
    """Keep the add-in's own writes from waking its own listeners.

    busy() covers one apply(). It is not enough. The pass hands Fusion the
    thread back between writes, which is what keeps Fusion responsive, and
    doing that dispatches the operationBaseChanged that each write queued. By
    then apply() had let go, so the edit handler treated the pass's own write
    as somebody's edit, reconciled the operation against the session's library
    cache, and wrote its own note over the one the pass had just written.

    Measured on a bench document: every check reported marking all eight
    operations, for ever, because the notes it wrote were overwritten before
    the pass had finished. A whole document could never settle, which is also
    why checking one job twice kept finding the same work to do.

    So a pass holds this for its whole length, not one write at a time.
    """

    def __enter__(self):
        _writing["depth"] += 1
        return self

    def __exit__(self, *failure):
        _writing["depth"] -= 1
        return False


def strip(owner):
    """What removing every trace from one operation or setup would change.

    The way back out. An add-in that marks a hundred files and cannot unmark
    them is one nobody should install, so this undoes everything it writes:
    its line out of the note, the icon back to the default, the record gone.

    It does not touch presets. An operation may be sitting on one the add-in
    added, and removing that would re-point it at another preset without
    changing its values, which is the one genuinely dangerous thing here.
    """
    changes = {}
    existing = _notes(owner)
    wanted = merge(existing, None)
    if wanted != (existing or ""):
        changes["note"] = {"from": existing or "", "to": wanted}
    now = _icon(owner)
    # Back to whatever it was before the add-in touched it, not to the
    # default: somebody may have coloured it themselves.
    before = _was_icon(owner) or config.ICON_DEFAULT
    if now is not None and now != before:
        changes["icon"] = {"from": now, "to": before}
    held = _group_keys(owner)
    if held:
        changes["record"] = {"remove": held}
    return changes


def _group_keys(owner):
    """Every attribute this add-in has in its group, whatever it is called.

    Asked of the document rather than assumed from a list of keys: a file
    written by a newer version may carry attributes this one has never heard
    of, and a removal that left those behind while reporting success would be
    worse than refusing. Falls back to the keys this version knows if the
    group cannot be enumerated.
    """
    try:
        found = owner.attributes.itemsByGroup(config.ATTRIBUTE_GROUP)
        names = [found.item(i).name for i in range(found.count)]
        if names:
            return names
    except Exception:
        pass
    known = []
    for key in (config.KEY_RECORD, config.KEY_ADOPTED_PRESET,
                config.KEY_OPERATION_ID, config.KEY_SCHEMA,
                config.KEY_SOURCE_PRESET, config.KEY_VERSION,
                config.KEY_VALUES):
        try:
            if owner.attributes.itemByName(config.ATTRIBUTE_GROUP, key):
                known.append(key)
        except Exception:
            continue
    return known


def unapply(owner, changes):
    """Carry out a strip(). Returns what actually went."""
    done = []
    if "note" in changes:
        owner.notes = changes["note"]["to"]
        done.append("note")
    if "icon" in changes:
        import adsk.cam
        value = getattr(adsk.cam.NoteIconColors, changes["icon"]["to"], None)
        if value is not None:
            owner.noteIconColor = value
            done.append("icon")
    if "record" in changes:
        for key in changes["record"]["remove"]:
            try:
                found = owner.attributes.itemByName(config.ATTRIBUTE_GROUP, key)
                if found:
                    found.deleteMe()
            except Exception:
                continue
        done.append("record")
    return done


def apply(operation, changes):
    """Write the planned changes. Returns what actually went in.

    The order matters a little: the record goes last, so a run interrupted
    half way leaves an operation that looks unadopted and gets its note
    re-derived next time, rather than one that claims to be adopted with no
    note to show for it.
    """
    _writing["depth"] += 1
    try:
        return _apply(operation, changes)
    finally:
        _writing["depth"] -= 1


# What each kind of write costs, summed over a pass. Writing marks turned out
# to be 6 seconds for eleven operations where reading them was free, and that
# is the cost that grows with how much there is to do: a file needing two
# hundred marks would spend minutes here.
cost = {"note": 0.0, "icon": 0.0, "record": 0.0}


def forget_cost():
    for key in cost:
        cost[key] = 0.0


def _apply(operation, changes):
    done = []
    if "note" in changes:
        mark = time.time()
        operation.notes = changes["note"]["to"]
        cost["note"] += time.time() - mark
        done.append("note")
    if "icon" in changes:
        import adsk.cam
        value = getattr(adsk.cam.NoteIconColors, changes["icon"]["to"], None)
        if value is not None:
            mark = time.time()
            operation.noteIconColor = value
            cost["icon"] += time.time() - mark
            done.append("icon")
    if "record" in changes:
        mark = time.time()
        operation.attributes.add(config.ATTRIBUTE_GROUP, config.KEY_RECORD,
                                 json.dumps(changes["record"]))
        cost["record"] += time.time() - mark
        done.append("record")
    return done


def describe(changes):
    """One short line for a report."""
    if not changes:
        return "nothing"
    parts = []
    if "note" in changes:
        was = changes["note"]["from"]
        lines = changes["note"]["to"].splitlines()
        first = lines[0] if lines else ""
        if not first:
            parts.append("note cleared")
        else:
            parts.append("%s %s" % ("note ->" if was else "note +", first))
    if "icon" in changes:
        parts.append("icon %s -> %s" % (changes["icon"]["from"] or "none",
                                        changes["icon"]["to"]))
    if "record" in changes:
        # strip() puts a removal in the same slot, and calling that "adopt"
        # made the report of taking the marks out read as putting them in.
        parts.append("forget which preset it came from"
                     if "remove" in changes["record"] else "adopt")
    return ", ".join(parts) or "nothing"


# ---------------------------------------------------------------------------

def _notes(operation):
    try:
        return operation.notes or ""
    except Exception:
        return ""


def _icon(operation):
    """The current icon colour as a name, or None.

    noteIconColor hands back an enum value, not a name, so it is turned back
    into one. Without that the plan would see "3" where it wanted "Green" and
    claim a change on every pass. noteIconColor is a preview API and may
    simply not be there, which is why this can return None.
    """
    try:
        import adsk.cam
        value = operation.noteIconColor
        for name in config.ICON_NAMES:
            if getattr(adsk.cam.NoteIconColors, name, None) == value:
                return name
        return str(value)
    except Exception:
        return None
