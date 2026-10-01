"""What the add-in would put on an operation: a note, an icon colour, a record.

This module decides; it does not write. Nothing in it calls into Fusion except
to read what is there now, so what it would do can be reported and argued with
before anything is allowed to happen.

The add-in owns the first line of a note, which always starts with the prefix.
Everything else in a note is somebody's own text and is kept exactly, line
breaks and all.
"""

from . import compat, config, state


def _named(verdict, version):
    """The UTP's name, with a version when one is known."""
    name = verdict.get("preset") or "?"
    return config.VERSION_LABEL % (name, version) if version else name


def note_line(verdict):
    """The one line the add-in owns, or None if it should not be there.

    Version numbers are used when the library has them and left out when it
    does not, so a library nobody has stamped still gets useful notes.
    """
    kind = verdict["state"]
    if kind == state.CURRENT:
        return config.NOTE_PREFIX + _named(verdict, verdict.get("libraryVersion"))
    if kind == state.BEHIND:
        newer = verdict.get("libraryVersion")
        # "v2 - v3 available" when both are known. When the document's own
        # version is not, saying which version is newer is still worth more
        # than saying nothing, so only the second half is dropped.
        return "%s%s %s %s" % (
            config.NOTE_PREFIX,
            _named(verdict, verdict.get("documentVersion")),
            config.NOTE_SEPARATOR,
            ("v%s available" % newer) if newer else config.NOTE_UPDATE)
    if kind == state.CUSTOM:
        return config.NOTE_PREFIX + config.NOTE_CUSTOM
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
        return (config.NOTE_PREFIX + config.SETUP_BEHIND % (behind, tracked),
                "Yellow")
    if custom:
        # Green, because a deliberate override is not a task. The count is
        # still said, so green cannot be read as "everything here is on the
        # shop's presets".
        return (config.NOTE_PREFIX + config.SETUP_CUSTOM % (tracked, custom),
                "Green")
    return config.NOTE_PREFIX + config.SETUP_CLEAN % tracked, "Green"


def setup_plan(setup, counts):
    """What would change on a setup. Empty means nothing to do."""
    line, colour = setup_line(counts)
    changes = {}
    existing = _notes(setup)
    wanted = merge(existing, line)
    if wanted != (existing or ""):
        changes["note"] = {"from": existing or "", "to": wanted}
    if colour is not None and _icon(setup) != colour:
        changes["icon"] = {"from": _icon(setup), "to": colour}
    return changes


def merge(existing, line):
    """The note the add-in would leave behind, ours first and theirs below.

    Every line starting with the prefix is treated as ours, not just the
    first. A second one can only have got there from a run that was
    interrupted, so it is cleaned up rather than preserved.
    """
    theirs = [l for l in (existing or "").splitlines()
              if not l.startswith(config.NOTE_PREFIX)]
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
    return {config.KEY_ADOPTED_PRESET: verdict["presetId"],
            config.KEY_OPERATION_ID: verdict["operationId"]}


def plan(operation, verdict):
    """What would change on this operation. Empty means nothing to do.

    Idempotent by construction: it compares against what is there now, so a
    second pass over an unchanged document plans nothing. That is what makes
    re-running after a crash harmless.
    """
    changes = {}

    existing = _notes(operation)
    wanted = merge(existing, note_line(verdict))
    if wanted != (existing or ""):
        changes["note"] = {"from": existing or "", "to": wanted}

    colour = config.ICON_FOR_STATE.get(verdict["state"])
    if colour is not None:
        now = _icon(operation)
        if now != colour:
            changes["icon"] = {"from": now, "to": colour}

    wanted_record = record(verdict)
    if wanted_record and not verdict.get("record"):
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
    if now is not None and now != config.ICON_DEFAULT:
        changes["icon"] = {"from": now, "to": config.ICON_DEFAULT}
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
    for key in (config.KEY_ADOPTED_PRESET, config.KEY_OPERATION_ID,
                config.KEY_SCHEMA, config.KEY_SOURCE_PRESET,
                config.KEY_VERSION, config.KEY_VALUES):
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


def _apply(operation, changes):
    done = []
    if "note" in changes:
        operation.notes = changes["note"]["to"]
        done.append("note")
    if "icon" in changes:
        import adsk.cam
        value = getattr(adsk.cam.NoteIconColors, changes["icon"]["to"], None)
        if value is not None:
            operation.noteIconColor = value
            done.append("icon")
    if "record" in changes:
        for key in sorted(changes["record"]):
            operation.attributes.add(config.ATTRIBUTE_GROUP, key,
                                     str(changes["record"][key]))
        compat.stamp(operation)
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
        parts.append("adopt")
    return ", ".join(parts)


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
