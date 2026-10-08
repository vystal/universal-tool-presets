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


def _our_markers():
    """Every suffix this add-in puts on a name, longest first.

    Longest first so "(previous 2)" is matched before "(previous)" would be.
    """
    marks = [config.LATEST_SUFFIX, config.PREVIOUS_SUFFIX]
    marks.extend(config.PREVIOUS_NUMBERED % n for n in range(2, 30))
    return sorted(set(marks), key=len, reverse=True)


_OURS = _our_markers()


def latest_name(name):
    """What the newest copy is called while an older one is still here.

    The suffix means exactly that and nothing more: there is something older
    in this dropdown. Once the older copy goes, plain_name puts it back to the
    bare name, so a tool nobody has touched looks the way it always did.
    """
    return "%s %s" % (without_suffix(name), config.LATEST_SUFFIX)


def plain_name(name):
    """The bare name, for the copy that is the only one of its preset."""
    return without_suffix(name)


def spare_name(name, taken=()):
    """A name for an old copy that cannot keep the bare one.

    Only reached when two operations sit on two different generations of one
    preset, so the newest cannot be the only plain-named entry. Everything
    else is named by plain_name or latest_name.
    """
    base = without_suffix(name)
    plain = "%s %s" % (base, config.PREVIOUS_SUFFIX)
    if plain not in set(taken):
        return plain
    count = 2
    while "%s %s" % (base, config.PREVIOUS_NUMBERED % count) in set(taken):
        count += 1
    return "%s %s" % (base, config.PREVIOUS_NUMBERED % count)


def without_suffix(name):
    """The name with this add-in's own suffixes taken off.

    Only its own. It used to strip a trailing " v12" as well, from when copies
    were numbered, and that was always a hazard: a shop preset genuinely called
    "P Copper v23" -- and they are named like that -- came back as "P Copper".
    Nothing is numbered now, and every name is derived from the library
    preset's own name rather than from another copy's, so there is no longer
    anything to strip but the three markers this add-in adds.
    """
    for marker in _OURS:
        if name.endswith(" " + marker):
            return name[:-len(marker) - 1]
    return name


def _names(tool):
    """Every preset name on this tool, so a new one cannot collide."""
    try:
        return [tool.presets.item(i).name for i in range(tool.presets.count)]
    except Exception:
        return []


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


def _ours_by_source(tool, library_tool):
    """This tool's copies, grouped by the library preset each belongs to.

    {source id: [(index, preset)]}. A copy the add-in made carries the source
    as an attribute; the preset the tool arrived with carries the library
    preset's own id, which is the same thing said a different way.
    """
    found = {}
    try:
        for index in range(tool.presets.count):
            preset = tool.presets.item(index)
            source = source_of(preset)
            if source is None and preset.id in library_tool.presets:
                source = preset.id
            if source is None or source not in library_tool.presets:
                continue
            found.setdefault(source, []).append((index, preset))
    except Exception:
        return {}
    return found


def _is_newest(preset, library_preset):
    """Whether this copy holds what the library holds now."""
    snapshot = stood_for(preset)
    if snapshot is None:
        # The preset the tool arrived with, or a copy from before copies
        # recorded what they stood for. Its own values are all there is.
        snapshot = values.scalars(preset)
    return not (values.differences(library_preset.values, snapshot)
                or set(library_preset.values) - set(snapshot))


def _split(copies, library_preset):
    """(the newest copy, everything else). Exactly one copy is ever newest.

    Two copies can hold the library's values at once -- it happened on the
    bench, from a pass that added one while an identical one was already
    there -- and if both are called "the newest" then both keep the bare name
    and the dropdown shows the same word twice. The first is the newest; any
    other match is just another old copy, and the tidy will offer it once
    nothing is using it.
    """
    newest = None
    others = []
    for index, copy in copies:
        if newest is None and _is_newest(copy, library_preset):
            newest = (index, copy)
            continue
        others.append((index, copy))
    return newest, others


def wanted_names(tool, library_tool, used_ids=()):
    """What every copy should be called. [(preset, wanted)], renames only.

    One place decides naming, which is the whole point of it. Three rules:

      the copy holding the library's current values is the newest
      if it is the only copy of its preset, it takes the bare name
      otherwise it takes (latest) and the older ones keep the bare name

    A copy is only renamed when its name is actually wrong. That matters more
    than it sounds: an operation points at a preset by id and keeps running
    whatever it was running, but the entry shown in its dropdown is the
    preset's NAME, so renaming a copy somebody is sitting on changes what they
    see they are on. Reported on 8 October -- an operation on "FAST" found
    itself on "FAST (previous)" without anybody touching it -- and the answer
    is that nothing is renamed to make room for something newer. The newer one
    takes the suffix instead.
    """
    renames = []
    try:
        taken = set(_names(tool))
        for source, copies in _ours_by_source(tool, library_tool).items():
            library_preset = library_tool.presets.get(source)
            if library_preset is None:
                continue
            bare = plain_name(library_preset.name)
            newest, older = _split(copies, library_preset)

            def rename(preset, wanted):
                if (preset.name or "") == wanted or wanted in taken:
                    return
                taken.discard(preset.name or "")
                taken.add(wanted)
                renames.append((preset, wanted))

            # The older ones first, so a name the newest wants is free by
            # the time it asks for it. Done the other way round, a stale copy
            # still holding "(latest)" blocked the new one from taking it and
            # the new one stayed bare beside its predecessor.
            for position, (_index, copy) in enumerate(older):
                if (copy.name or "") == bare:
                    continue
                rename(copy, bare if position == 0 and bare not in taken
                       else spare_name(bare, taken))
            if newest is not None:
                rename(newest[1], bare if not older else latest_name(bare))
    except Exception:
        return renames
    return renames


def rename(cam, tool, renames):
    """Carry out the renames. Returns what was done."""
    done = []
    for preset, wanted in renames:
        was = preset.name
        try:
            preset.name = wanted
            done.append("%s renamed to %s" % (was, wanted))
        except Exception:
            continue
    if done:
        # The same call every other write here makes. This was
        # cam.manufacturingModel.designModel.allToolLibrary -- an attribute
        # chain that does not exist -- inside a bare except, so every rename
        # was set on the object, never committed, and swallowed without a
        # word. Two passes on the bench showed two presets both called
        # "P Titanium" while the rename was being asked for each time.
        # Not caught here any more: a rename that cannot be committed is the
        # caller's to report.
        cam.documentToolLibrary.update(tool, False)
    return done


def removable(tool, library_tool, used_ids):
    """Copies nothing is using that are not the newest. [(index, name, id)].

    The one rule that is never bent: a preset an operation points at is never
    offered here. Removing it would re-point that operation at another preset
    with different values, which is wrong feeds at the machine.

    Everything else goes. There used to be a rule keeping the most recently
    retired copy as a record of what an operation used to run; it is gone
    because it was asked for on 8 October and because it was the thing filling
    these dropdowns. Once somebody has moved to the newer preset there is one
    entry again, exactly as there was before anybody changed anything.
    """
    going = []
    try:
        for source, copies in _ours_by_source(tool, library_tool).items():
            library_preset = library_tool.presets.get(source)
            if library_preset is None:
                continue
            newest, others = _split(copies, library_preset)
            if newest is None:
                # Nothing here holds the library's values yet, so every copy
                # is somebody's current one until the newer copy arrives.
                continue
            for index, preset in others:
                if preset.id in used_ids:
                    continue
                going.append((index, preset.name or "", preset.id))
    except Exception:
        return []
    # Highest index first, so removing one cannot shift the next.
    return sorted(going, key=lambda row: -row[0])


def plan(tool, library_preset):
    """What this tool needs so the newer values are pickable. Empty if none.

    Only ever "add" now. Retiring -- renaming the copy already there so the
    new one could take its name -- is gone: the copy somebody is sitting on
    keeps the name they chose it by, and the newer one carries the (latest)
    marker instead. wanted_names settles every name afterwards.
    """
    try:
        for index in range(tool.presets.count):
            preset = tool.presets.item(index)
            if source_of(preset) != library_preset.id                     and preset.id != library_preset.id:
                continue
            if _is_newest(preset, library_preset):
                return {}
    except Exception:
        return {}
    return {"add": library_preset.name}


def apply(cam, tool, library_preset, intended):
    """Carry out a plan. Returns what was done, and the tool goes stale after.

    update() is what makes a preset change visible at all, and the False
    matters: it means no operation's values are touched.
    """
    done = []
    if "add" in intended:
        fresh = tool.presets.add()
        # Named bare here and settled by wanted_names in the same pass, which
        # is the one place that knows whether an older copy survives beside it.
        fresh.name = plain_name(library_preset.name)
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
    for row in rows:
        index, name = row[0], row[1]
        held = row[3] if len(row) > 3 else None
        try:
            if tool.presets.item(index).name != name:
                done.append("SKIPPED %s: the list moved under us" % name)
                continue
            if held is not None and tool.presets.item(index).id != held:
                # Belt and braces beside the name: two presets on one tool can
                # share a name, and the id is what an operation points at.
                done.append("SKIPPED %s: not the preset that was chosen" % name)
                continue
            tool.presets.remove(index)
            done.append("removed %s" % name)
        except Exception as exc:
            done.append("could not remove %s: %s" % (name, exc))
    if done:
        cam.documentToolLibrary.update(tool, False)
    return done
