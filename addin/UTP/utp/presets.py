"""Presets inside a document. Adds, never replaces.

A behind operation needs somewhere to go: the newer values have to exist as a
preset in this document before anybody can pick them in the dropdown. The
preset it is using keeps its values untouched, so nothing changes underneath
anyone who is not asking for it.

A preset created here cannot be found in the library by its id, because
presets.add() gives it a fresh one. So it carries the library preset's id as
an attribute. Phase 1 showed that attribute was unnecessary when nothing
created presets; creating them makes it necessary again, for these presets
only.
"""

import datetime

from . import compat, config, values


def latest_name(name, version=None):
    """What the newest copy is called in the dropdown."""
    base = without_suffix(name)
    if version:
        base = "%s v%s" % (base, version)
    return "%s %s" % (base, config.LATEST_SUFFIX)


def retired_name(name, taken=(), when=None, version=None):
    """What a copy is called once something newer exists.

    Its version if it has one, because "P Titanium v2" beside
    "P Titanium v3 (latest)" says at a glance how far behind an operation is.
    The date form below is the fallback for libraries with no version numbers
    yet, and reads far worse for exactly that reason.
    """
    if version:
        numbered = "%s v%s" % (without_suffix(name), version)
        if numbered not in set(taken):
            return numbered
    return _dated_name(name, taken, when)


def _dated_name(name, taken=(), when=None):
    """What a copy is called once something newer exists.

    Not the bare name: the preset the tool arrived with is already called
    that, so simply dropping the suffix leaves two identical entries in the
    dropdown and nobody can tell which is which. The date it stopped being
    current is both a distinguisher and something worth knowing, since it
    says how old the feeds an operation is running actually are.

    A UTP changed twice in one day gives two copies the same date, so the
    time is added when, and only when, the date alone is already taken. That
    keeps the ordinary case readable and the awkward one unambiguous.
    """
    when = when or datetime.datetime.now()
    base = without_suffix(name)
    dated = "%s %s" % (base, config.RETIRED_SUFFIX
                       % when.strftime(config.RETIRED_FORMAT))
    if dated not in set(taken):
        return dated
    return "%s %s" % (base, config.RETIRED_SUFFIX
                      % when.strftime(config.RETIRED_FORMAT_EXACT))


def without_suffix(name):
    """The name with the (latest) marker and any version stripped off.

    Both go, because a retired copy keeps its own version in its name and a
    fresh one gets the library's; leaving the old number on would produce
    "P Titanium v2 v3 (latest)".
    """
    suffix = " " + config.LATEST_SUFFIX
    if name.endswith(suffix):
        name = name[:-len(suffix)]
    parts = name.rsplit(" v", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return name


def _names(tool):
    """Every preset name on this tool, so a new one cannot collide."""
    try:
        return [tool.presets.item(i).name for i in range(tool.presets.count)]
    except Exception:
        return []


def version_of(preset):
    """The version a copy was made from, if the add-in made it and knew one."""
    try:
        found = preset.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_VERSION)
    except Exception:
        return None
    return found.value if found else None


def source_of(preset):
    """The library preset this one was copied from, if it was."""
    try:
        found = preset.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_SOURCE_PRESET)
    except Exception:
        return None
    return found.value if found else None


def claiming_latest(tool, library_preset_id):
    """The copy that currently claims to be the newest, if there is one.

    Only a copy still carrying the suffix counts. Matching on the attribute
    alone finds retired copies too, and since their values are stale by
    definition the plan would retire them again and add another copy on every
    single pass, growing the dropdown without end.
    """
    try:
        for index in range(tool.presets.count):
            preset = tool.presets.item(index)
            if (source_of(preset) == library_preset_id
                    and (preset.name or "").endswith(config.LATEST_SUFFIX)):
                return preset
    except Exception:
        pass
    return None


def plan(tool, library_preset):
    """What this tool needs so the newer values are pickable. Empty if none."""
    copy = claiming_latest(tool, library_preset.id)
    if copy is None:
        return {"add": library_preset.name}
    stale = values.differences(values.scalars(copy), library_preset.values)
    if stale:
        # The library has moved on again since this copy was made. The copy
        # keeps its values, because operations may be using it; it just stops
        # claiming to be the newest.
        return {"retire": copy.name, "add": library_preset.name,
                "because": stale[:4]}
    return {}


def apply(cam, tool, library_preset, intended):
    """Carry out a plan. Returns what was done, and the tool goes stale after.

    update() is what makes a preset change visible at all, and the False
    matters: it means no operation's values are touched.
    """
    done = []
    if "retire" in intended:
        copy = claiming_latest(tool, library_preset.id)
        if copy is not None:
            copy.name = retired_name(copy.name, _names(tool),
                                     version=version_of(copy))
            done.append("retired as %s" % copy.name)
    if "add" in intended:
        fresh = tool.presets.add()
        fresh.name = latest_name(library_preset.name, library_preset.version)
        missing = []
        for name in sorted(library_preset.values):
            parameter = fresh.parameters.itemByName(name)
            if parameter is None:
                missing.append(name)
                continue
            try:
                parameter.value.value = library_preset.values[name]
            except Exception:
                missing.append(name)
        try:
            fresh.attributes.add(config.ATTRIBUTE_GROUP,
                                 config.KEY_SOURCE_PRESET, library_preset.id)
            compat.stamp(fresh)
            if library_preset.version:
                # Recorded now, because later the library will have moved on
                # and there would be no way to tell which version this copy
                # actually holds.
                fresh.attributes.add(config.ATTRIBUTE_GROUP,
                                     config.KEY_VERSION,
                                     str(library_preset.version))
        except Exception:
            # Without this the copy cannot be tied back to the library, so an
            # operation moved onto it would look as though its preset had been
            # retired. Better to say so than to leave a preset that lies.
            done.append("COULD NOT STAMP the new preset")
        done.append("added %s" % fresh.name)
        if missing:
            done.append("could not set %d values: %s"
                        % (len(missing), ", ".join(missing[:4])))
    if done:
        cam.documentToolLibrary.update(tool, False)
    return done
