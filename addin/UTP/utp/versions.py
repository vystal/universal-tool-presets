"""Version numbers on library presets. The only thing written outside a document.

A version number decides nothing. Whether an operation is behind is settled by
comparing values, and that works with no numbers at all. The number is what
somebody reads in a dropdown and in a note, and dates turned out to be a poor
substitute for it: "until 30 Sep 2026" makes you do arithmetic where "v2"
tells you at a glance how far behind you are.

So it is a label, kept honest by a snapshot of the values it describes. When a
preset's values no longer match its snapshot, somebody has changed the UTP and
the number moves on. The first add-in to notice does it; two noticing at once
write the same number and the same values, so the race is harmless, and a
refused write breaks nothing because nothing depended on it.
"""

import json

from . import config, values


def stored_snapshot(preset):
    """The values this preset had when its version was last set."""
    try:
        found = preset.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_VALUES)
    except Exception:
        return None
    if found is None:
        return None
    try:
        return json.loads(found.value)
    except Exception:
        return None


def stored_version(preset):
    try:
        found = preset.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_VERSION)
    except Exception:
        return None
    if found is None:
        return None
    try:
        return int(found.value)
    except Exception:
        return None


def needed(preset):
    """What this preset's version should become, or None if it is right.

    Three cases. It has never been stamped, so it becomes version 1 and its
    current values are what version 1 means. Its values have moved since the
    snapshot, so the version goes up. Or nothing has changed and nothing is
    written, which is the usual answer and must stay cheap.
    """
    current = values.scalars(preset)
    version = stored_version(preset)
    snapshot = stored_snapshot(preset)

    if version is None or snapshot is None:
        # Adopted, not rewritten: whatever it holds today is version 1, so
        # nobody has to rename or rebuild anything to join the system.
        return 1, current, "adopted as version 1"

    if values.differences(current, snapshot) or set(current) != set(snapshot):
        return version + 1, current, "its values have changed since version %d" % version

    return None


def review(libraries, library_presets, report, allowed):
    """Bring the version numbers up to date on the presets that matter.

    Only the presets used by the document in hand, not all 427 of them: this
    runs on a button press and every extra library write is risk for no gain.
    """
    # Grouped by the url's text, because adsk.core.URL cannot be a dict key:
    # it is unhashable, and using one is a TypeError rather than a wrong
    # answer. The object itself is carried alongside, since that is what
    # opening and updating a library actually needs.
    by_library = {}
    for preset in library_presets:
        if preset.library_url is None:
            continue
        try:
            key = preset.library_url.toString()
        except Exception:
            continue
        url, preset_ids = by_library.setdefault(
            key, (preset.library_url, set()))
        preset_ids.add(preset.id)

    changed = []
    for url, preset_ids in by_library.values():
        try:
            shelf = libraries.toolLibraryAtURL(url)
        except Exception:
            report.failed("could not open a library to check its versions")
            continue
        if shelf is None:
            continue
        wrote_here = False
        for index in range(shelf.count):
            tool = shelf.item(index)
            try:
                count = tool.presets.count
            except Exception:
                continue
            for position in range(count):
                preset = tool.presets.item(position)
                if preset.id not in preset_ids:
                    continue
                wanted = needed(preset)
                if wanted is None:
                    continue
                version, snapshot, why = wanted
                changed.append({"preset": preset.name, "version": version,
                                "why": why})
                if not allowed:
                    continue
                try:
                    group = config.ATTRIBUTE_GROUP
                    preset.attributes.add(group, config.KEY_VERSION,
                                          str(version))
                    preset.attributes.add(group, config.KEY_VALUES,
                                          json.dumps(snapshot))
                    wrote_here = True
                except Exception:
                    report.failed("could not stamp %s" % preset.name)
        if wrote_here:
            try:
                libraries.updateToolLibrary(url, shelf)
            except Exception:
                report.failed("the library refused the version write")

    if changed:
        # Summarised, not listed. A document using 25 tools produces 25
        # identical-looking entries, which buries anything worth noticing.
        reasons = {}
        for entry in changed:
            reasons[entry["why"]] = reasons.get(entry["why"], 0) + 1
        moved = [e for e in changed if e["version"] > 1]
        report.note("version numbers" if allowed else "version numbers would move",
                    presets=len(changed),
                    why="; ".join("%d %s" % (n, w) for w, n in sorted(reasons.items())),
                    moved_on=[("%s to v%d" % (e["preset"], e["version"]))
                              for e in moved[:10]] or "none",
                    written="yes" if allowed else "no")
    return changed
