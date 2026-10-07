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
import json

from . import compat, config, values


def latest_name(name, version=None):
    """What the newest copy is called in the dropdown."""
    base = without_suffix(name)
    if version:
        base = config.VERSION_LABEL % (base, version)
    return "%s %s" % (base, config.LATEST_SUFFIX)


def retired_name(name, taken=(), when=None, version=None):
    """What a copy is called once something newer exists.

    Its version if it has one, because "P Titanium v2" beside
    "P Titanium v3 (latest)" says at a glance how far behind an operation is.
    The date form below is the fallback for libraries with no version numbers
    yet, and reads far worse for exactly that reason.
    """
    if version:
        numbered = config.VERSION_LABEL % (without_suffix(name), version)
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


def stood_for(preset):
    """The library values this copy was made to hold, if it recorded them.

    The question plan() needs answered is "has the library moved on since this
    copy was made", and the only honest way to ask it is to compare the library
    against what the library held at the time. Comparing against the copy's own
    values asks something subtly different -- "does the copy match the library"
    -- and gets a permanent yes-it-differs for any value that would not go in.
    That turned into a new "(latest)" preset on every pass, for ever.
    """
    try:
        found = preset.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_VALUES)
    except Exception:
        return None
    if found is None:
        return None
    try:
        held = json.loads(found.value)
        return held if isinstance(held, dict) else None
    except Exception:
        return None


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


def represented(tool, library_preset_id):
    """Whether this document knows about a library preset at all.

    Either as the copy that arrived with the tool, which keeps the library
    preset's own id, or as a copy the add-in made, which carries that id as
    an attribute because presets.add() gave it one of its own.
    """
    try:
        for index in range(tool.presets.count):
            preset = tool.presets.item(index)
            if preset.id == library_preset_id:
                return True
            if source_of(preset) == library_preset_id:
                return True
    except Exception:
        pass
    return False


def missing(tool, library_tool):
    """Library presets this document has never seen.

    A UTP added at the shop after a job was made is otherwise invisible in
    that job: nothing is behind, because no operation is on it, so nothing
    brings it in and somebody would have to re-select the tool to reach it.
    """
    return [preset for preset in library_tool.presets.values()
            if not represented(tool, preset.id)]


def oddly_named(tool):
    """Copies the add-in made that carry neither suffix. Names only.

    Every copy it makes is called "<name> v<N> (latest)" and every one it
    retires becomes "<name> (until <date>)", so a copy of its own with neither
    is a name that no path here produces -- a rename that stopped half way, or
    something outside renaming it.

    Worth saying rather than fixing, for two reasons. It sits in the dropdown
    looking like a preset somebody made by hand, so nobody can tell it is the
    add-in's. And removable sorts candidates by the version in their name, so a
    suffixless copy carrying v23 outranks a properly retired one carrying none
    -- the tidy would keep the anomaly and delete the copy whose date says what
    an operation used to run. Found on the bench 8 October: "P Copper v23",
    made by the add-in, no suffix, beside "P Copper (until 07 Oct 2026 12:55)".
    """
    odd = []
    try:
        for index in range(tool.presets.count):
            preset = tool.presets.item(index)
            if source_of(preset) is None:
                continue
            name = preset.name or ""
            if name.endswith(config.LATEST_SUFFIX):
                continue
            if config.RETIRED_SUFFIX % "" in name or "(until " in name:
                continue
            odd.append(name)
    except Exception:
        return odd
    return odd


def removable(tool, library_tool, used_ids):
    """Copies the add-in made that nothing needs any more, oldest first.

    Three rules, and the first is the one that matters. A preset an operation
    points at is never touched: removing one re-points those operations at
    whatever is left, silently, without changing their values, so they end up
    naming a preset whose feeds they do not hold.

    The second is that only copies the add-in made are candidates. A preset
    somebody created by hand, or one that arrived with the tool, is theirs.

    The third is that the most recently retired copy stays even when unused.
    The library keeps one preset per UTP with today's values, so a document's
    retired copy is the only surviving record of what an operation used to
    run, and after a save there is no undo to go back with.
    """
    ours = []
    try:
        for index in range(tool.presets.count):
            preset = tool.presets.item(index)
            source = source_of(preset)
            if source is None or source not in library_tool.presets:
                continue
            if preset.id in used_ids:
                continue
            if (preset.name or "").endswith(config.LATEST_SUFFIX):
                continue
            ours.append((index, preset.name, _version_number(preset)))
    except Exception:
        return []
    if len(ours) <= 1:
        return []
    # Newest kept, whichever that is; the rest go. Highest index first, so
    # removing one does not shift the next.
    ours.sort(key=lambda row: (row[2], row[0]))
    return sorted(ours[:-1], key=lambda row: -row[0])


def _version_number(preset):
    """The version a copy holds, as a number for sorting. 0 if unknown."""
    try:
        return int(version_of(preset) or 0)
    except Exception:
        return 0


def plan(tool, library_preset):
    """What this tool needs so the newer values are pickable. Empty if none."""
    copy = claiming_latest(tool, library_preset.id)
    if copy is None:
        return {"add": library_preset.name}
    snapshot = stood_for(copy)
    if snapshot is not None:
        # The library then against the library now. A value that never made it
        # into the copy is on neither side of this, so it cannot make the copy
        # look stale on every pass.
        stale = values.differences(library_preset.values, snapshot)
    else:
        # A copy made before copies recorded what they stood for. Falling back
        # to its own values is what the churn came from, so it is worth saying
        # which comparison was used when this happens.
        stale = values.differences(values.scalars(copy), library_preset.values)
    if stale:
        # The library has moved on again since this copy was made. The copy
        # keeps its values, because operations may be using it; it just stops
        # claiming to be the newest.
        return {"retire": copy.name, "add": library_preset.name,
                "because": stale[:4],
                "compared": "the library against what the copy stood for"
                            if snapshot is not None
                            else "the copy's own values, which it did not record"}
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
            # What the library held when this copy was made, so the next pass
            # can ask whether the library has moved rather than whether every
            # value went in. Written even when some did not: that is the point.
            fresh.attributes.add(config.ATTRIBUTE_GROUP, config.KEY_VALUES,
                                 json.dumps(library_preset.values))
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


def remove(cam, tool, rows):
    """Remove copies nothing needs. rows come from removable(), highest first.

    ToolPresets.remove takes an index rather than a preset, which is exactly
    the kind of call that deletes the wrong thing if the list shifts under
    it, so the rows are applied from the end and the name is checked before
    each one goes.
    """
    done = []
    for index, name, _version in rows:
        try:
            if tool.presets.item(index).name != name:
                done.append("SKIPPED %s: the list moved under us" % name)
                continue
            tool.presets.remove(index)
            done.append("removed %s" % name)
        except Exception as exc:
            done.append("could not remove %s: %s" % (name, exc))
    if done:
        cam.documentToolLibrary.update(tool, False)
    return done
