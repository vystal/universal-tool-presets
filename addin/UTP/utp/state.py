"""The verdict for one operation. Reads only; writes nothing, ever.

This is the part worth being sure about, so it is kept free of side effects:
it can be run at any time, twice, or after a crash, without consequence.

Every verdict comes from the document and the library as they stand. Nothing
is carried between sessions, so a crash cannot leave the add-in believing
something the file does not say.
"""

import json

from . import config, identity, presets, values

NOT_UTP = "not a UTP tool"
NOT_ADOPTED = "not adopted"
CUSTOM = "custom"
BEHIND = "behind"
CURRENT = "current"
RETIRED = "preset not in the library"
UNKNOWN = "unknown"


def reconcile(operation, library_tools, seen=None, tool_id=None):
    """What the add-in would say about one operation.

    `seen` is an optional dict for one pass to share preset readings in.
    Six operations on the same preset read its values six times otherwise.
    """
    verdict = {
        "operation": _name(operation),
        "operationId": _id(operation),
        "state": UNKNOWN,
        "tool": None,
        "preset": None,
        "presetId": None,
        "matched by": None,
        "toolId": None,
        "matched preset by": None,
        "libraryPresetId": None,
        "libraryVersion": None,
        "documentVersion": None,
        "record": None,
        "preset found in library": None,
        "why": "",
        "differences": [],
        "changed": {},
    }

    tool = _attribute(operation, "tool")
    if tool is None:
        verdict["state"] = NOT_UTP
        verdict["why"] = "the operation has no tool"
        return verdict
    verdict["tool"] = getattr(tool, "description", "?")

    library_tool, how, found = identity.match(tool, library_tools, tool_id)
    verdict["matched by"] = how
    # Kept so nothing has to serialise the tool again to learn its id.
    verdict["toolId"] = found
    if library_tool is None:
        verdict["state"] = NOT_UTP
        verdict["why"] = "its tool is not in any Hub library: %s" % how
        return verdict

    preset = _attribute(operation, "toolPreset")
    if preset is None:
        verdict["state"] = NOT_UTP
        verdict["why"] = "the operation is on no preset"
        return verdict
    verdict["preset"] = preset.name
    verdict["presetId"] = preset.id
    verdict["record"] = _record(operation, preset.id)

    # Looked up here rather than further down, so it is known for every
    # operation and not only the ones that reach the comparison. Whether a
    # preset id survives from library into document decides whether identity
    # needs anything written to the library at all.
    library_preset = library_tool.presets.get(preset.id)
    if library_preset is None:
        # A preset the add-in created carries the library preset's id as an
        # attribute, because presets.add() gave it an id of its own.
        source = presets.source_of(preset)
        if source:
            library_preset = library_tool.presets.get(source)
            verdict["matched preset by"] = "sourcePreset attribute"
    else:
        verdict["matched preset by"] = "id"
    verdict["preset found in library"] = library_preset is not None
    # Handed back, because a preset the add-in created has an id of its own:
    # a caller that looked the library preset up by the operation's preset id
    # would find nothing, and quietly stop offering newer versions.
    if library_preset is not None:
        verdict["libraryPresetId"] = library_preset.id
        verdict["libraryVersion"] = library_preset.version
        # Which version the document holds. A copy the add-in made recorded it
        # at the time. The preset the tool arrived with never did, so it is
        # only known when its values still match the library.
        verdict["documentVersion"] = presets.version_of(preset)

    # Custom beats behind: somebody who changed values on purpose is not
    # told to update. Compared against the preset inside this document,
    # because that is what the operation's values were set from.
    # The preset first, then the operation asked only for what the preset
    # has. Reading all of an operation's parameters and intersecting
    # afterwards did the same work ten times over.
    if seen is not None and preset.id in seen:
        preset_values = seen[preset.id]
    else:
        preset_values = values.scalars(preset)
        if seen is not None:
            seen[preset.id] = preset_values
    operation_values = values.named(operation, preset_values)
    edited = values.differences(operation_values, preset_values)
    if edited:
        verdict["differences"] = edited
        verdict["changed"] = values.detail(operation_values, preset_values, edited)
        if verdict["record"]:
            verdict["state"] = CUSTOM
            verdict["why"] = "was set from %s; %d values now differ, e.g. %s" % (
                verdict["record"], len(edited), _sample(verdict["changed"]))
        else:
            # Never put on a UTP at all. Nearly every operation in a file that
            # predates the system lands here: measured on a real document, 20
            # of 27. A grey note on every one of them would be noise rather
            # than information, so this state says nothing and marks nothing.
            # An operation joins the system when somebody picks a UTP preset
            # for it, and only then can it be behind or custom.
            verdict["state"] = NOT_ADOPTED
            verdict["why"] = ("never set from a UTP; %d values differ from its "
                              "preset, e.g. %s"
                              % (len(edited), _sample(verdict["changed"])))
        return verdict

    if library_preset is None:
        verdict["state"] = RETIRED
        verdict["why"] = ("its preset is not in the library tool any more, so "
                          "there is nothing to compare it against")
        return verdict
    verdict["preset"] = library_preset.name

    moved = values.differences(preset_values, library_preset.values)
    if moved:
        verdict["state"] = BEHIND
        verdict["differences"] = moved
        verdict["changed"] = values.detail(preset_values, library_preset.values, moved)
        verdict["why"] = "the library has moved on: %s" % _sample(verdict["changed"])
        return verdict

    verdict["state"] = CURRENT
    verdict["why"] = "matches the library"
    return verdict


# ---------------------------------------------------------------------------

def _record(operation, preset_id):
    """Which preset this operation was deliberately put on, if anything says so.

    Checked, never believed, on two counts. A record whose operationId does
    not match the operation holding it was copied there by duplicating an
    operation. And a record naming a different preset from the one the
    operation is on now means somebody moved it since, so it no longer
    describes this operation either. Both are ignored rather than trusted,
    which is what makes an interrupted or crashed run harmless.
    """
    held = _held(operation)
    if not held:
        return None
    adopted = held.get(config.KEY_ADOPTED_PRESET)
    if not adopted:
        return None
    owner = held.get(config.KEY_OPERATION_ID)
    if owner is not None and str(owner) != _id(operation):
        return None
    if preset_id and adopted != preset_id:
        return None
    return adopted


def _held(operation):
    """The record, from whichever shape wrote it.

    Schema 2 keeps the whole thing in one attribute, because every write to
    a CAM operation costs about 120 milliseconds and three attributes were
    three of them. Schema 1 wrote them separately and those files are still
    read; an operation is rewritten to the new shape the next time it is
    marked.
    """
    group = config.ATTRIBUTE_GROUP
    try:
        record = operation.attributes.itemByName(group, config.KEY_RECORD)
        if record is not None:
            return json.loads(record.value)
    except Exception:
        return {}
    held = {}
    for key in (config.KEY_ADOPTED_PRESET, config.KEY_OPERATION_ID):
        try:
            found = operation.attributes.itemByName(group, key)
        except Exception:
            continue
        if found is not None:
            held[key] = found.value
    return held


def _sample(changed, count=3):
    return "; ".join("%s %s" % (k, changed[k]) for k in sorted(changed)[:count])


def _attribute(owner, name):
    try:
        return getattr(owner, name)
    except Exception:
        return None


def _name(operation):
    try:
        return operation.name
    except Exception:
        return "?"


def _id(operation):
    try:
        return str(operation.operationId)
    except Exception:
        return None
