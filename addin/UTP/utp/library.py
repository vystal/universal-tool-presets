"""Reading the Hub libraries, once per pass.

Values are copied out at read time rather than holding on to Fusion's preset
objects, which go stale after the library is touched. Reading every machine
library takes a moment, so a pass does it once and hands the result around.
"""

import adsk.cam

from . import config, values, versions


class LibraryPreset:
    def __init__(self, preset, tool_id, library_path, library_url=None):
        self.id = preset.id
        self.name = preset.name
        self.tool_id = tool_id
        self.library = library_path
        # Kept so a version can be written back. The path is only a label.
        self.library_url = library_url
        self.values = values.scalars(preset)
        # Identity is the preset's own id, so nothing is stored for it. The
        # version is a label and may simply not be there.
        #
        # It is also only reported when it still describes what the preset
        # holds. A number goes stale whenever the values move and the bump
        # does not land, which happens if a library refuses the write, and a
        # stale number gets put on a copy of values it does not describe:
        # measured, two presets both labelled v1 holding different feeds.
        # Withheld, everything falls back to naming by date and saying
        # "update available", which is vaguer and never wrong.
        stated = _attribute(preset, config.KEY_VERSION)
        self.version = stated if self._describes(preset, stated,
                                                 self.values) else None

    @staticmethod
    def _describes(preset, stated, held):
        """Whether a stated version still describes the values held.

        Given the values rather than reading them again: every preset in
        every library was being read twice, once for `values` and once here,
        which was half the cost of reading the libraries at all.
        """
        if not stated:
            return False
        snapshot = versions.stored_snapshot(preset)
        if snapshot is None:
            return False
        return not (values.differences(held, snapshot)
                    or set(held) != set(snapshot))

    @property
    def label(self):
        """What a note would call this UTP: its version if it has one."""
        if self.version:
            return "%s v%s" % (self.name, self.version)
        return self.name


class LibraryTool:
    def __init__(self, tool, library_path, library_url=None):
        self.id = tool_id(tool)
        self.description = tool.description
        self.library = library_path
        self.library_url = library_url
        self.presets = {}
        # Counted rather than ignored. A bare "except: continue" here once hid
        # a dead config reference that emptied every tool's presets and made
        # the whole document look as though its presets had been retired.
        self.unreadable = 0
        for index in range(tool.presets.count):
            try:
                preset = LibraryPreset(tool.presets.item(index), self.id,
                                       library_path, library_url)
            except Exception:
                self.unreadable += 1
                continue
            self.presets[preset.id] = preset


def _attribute(owner, key):
    try:
        found = owner.attributes.itemByName(config.ATTRIBUTE_GROUP, key)
    except Exception:
        return None
    return found.value if found else None


def tool_id(tool):
    """A tool's own id.

    Storing a tool in a library gives it a fresh id, but a copy taken out of
    a library keeps the library's id exactly, so this is what ties a document
    tool back to the library tool it came from.
    """
    try:
        import json
        return json.loads(tool.toJson()).get("guid")
    except Exception:
        return None


def _walk(libraries, url, depth=0, path="", max_depth=6):
    """Every library under a location, as (path, url) pairs."""
    found = []
    if depth > max_depth:
        return found
    try:
        for child in libraries.childAssetURLs(url):
            found.append((path + "/" + (child.leafName or "?"), child))
    except Exception:
        pass
    try:
        for folder in libraries.childFolderURLs(url):
            name = path + "/" + (folder.leafName or "?")
            found.extend(_walk(libraries, folder, depth + 1, name, max_depth))
    except Exception:
        pass
    return found


_cache = {"tools": None, "ok": False}


def warm():
    """Whether the libraries have been read this session."""
    return _cache["tools"] is not None


def cached(report, do_events=None, force=False, wanted=None):
    """The libraries, read once per session.

    An operation edit must not pay for a Hub read: it took 6.7 seconds the
    first time and 4.0 the second, which inside somebody's command would look
    like Fusion hanging. So an edit uses this only when it is already warm,
    and says so when it is not.

    A reading that stopped as soon as one document's tools were found is
    handed back to the caller that asked for it and never kept, because a
    tool missing from it is indistinguishable from a tool that is not in the
    shop libraries at all. The second of those means "not a UTP tool", which
    takes the note off an operation: check one document, then save another
    whose tools live in a library the reading never reached, and every note
    in it would be deleted. The caller that named its tools is about to look
    for exactly those, so a short reading is no risk to it alone.

    Nothing is lost by not keeping it. The one caller that names tools asks
    with force anyway, so it re-reads whatever is held.
    """
    if force or _cache["tools"] is None:
        tools, ok, whole = read(report, do_events, wanted)
        if not whole:
            return tools, ok
        _cache["tools"], _cache["ok"] = tools, ok
    return _cache["tools"], _cache["ok"]


def forget():
    _cache["tools"], _cache["ok"] = None, False


def read(report, do_events=None, wanted=None):
    """Every tool in every Hub library, keyed by tool id.

    Returns (tools, ok, whole). ok is False when the library could not be
    reached, in which case nothing should be decided: a note that claims an
    operation is current would be a guess. whole is False when the reading
    stopped as soon as the named tools were found, so what is missing from it
    means nothing.
    """
    tools = {}
    try:
        libraries = adsk.cam.CAMManager.get().libraryManager.toolLibraries
        url = libraries.urlByLocation(adsk.cam.LibraryLocations.HubLibraryLocation)
    except Exception:
        report.failed("the Hub library could not be opened")
        return tools, False, False
    if url is None:
        report.note("no Hub library on this account; nothing to compare against")
        return tools, False, False

    assets = _walk(libraries, url)
    read_count = preset_count = unreadable = 0
    stopped_early = False
    # The tools this document actually uses, if the caller knows them. Each
    # library is a request over the network, measured between three and eight
    # seconds for all eight of them, and a document using two of them has no
    # reason to wait for the other six.
    looking_for = set(wanted) if wanted else None
    for path, asset_url in assets:
        try:
            library = libraries.toolLibraryAtURL(asset_url)
        except Exception:
            report.failed("could not read library %s" % path)
            continue
        if library is None:
            continue
        read_count += 1
        for index in range(library.count):
            try:
                tool = LibraryTool(library.item(index), path.lstrip("/"),
                                   asset_url)
            except Exception:
                continue
            if tool.id:
                tools[tool.id] = tool
                preset_count += len(tool.presets)
                unreadable += tool.unreadable
            if do_events is not None and index % config.OPERATIONS_PER_CHUNK == 0:
                do_events()

        if looking_for and looking_for.issubset(tools):
            report.note("stopped early: every tool this document uses was "
                        "found", libraries_read=read_count,
                        of=len(assets),
                        note="this reading describes this document only")
            stopped_early = True
            break

    report.note("read the Hub libraries",
                libraries=read_count, tools=len(tools), presets=preset_count)
    if unreadable:
        report.note("SOME PRESETS COULD NOT BE READ", count=unreadable,
                    consequence=("operations using them will look as though "
                                 "their preset was retired, which is wrong"))
    return tools, bool(tools), not stopped_early
