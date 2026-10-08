"""Reading the Hub libraries, once per pass.

Values are copied out at read time rather than holding on to Fusion's preset
objects, which go stale after the library is touched. Reading every machine
library takes a moment, so a pass does it once and hands the result around.

A whole read of eight libraries, 390 tools and 441 presets takes about 3.3
seconds, measured 6 October. Older notes in this repo say three to eleven; the
eleven came from reports written before every preset stopped being read twice.

Fusion keeps its own copy of these libraries in a file, and it is not usable
here. It is tempting -- 2.5 MB of JSON under NsHubLibrariesCache that parses in
23 milliseconds, with every tool, every preset, and this add-in's own stamps in
it. Three measurements on 6 October say no:

  * Its numbers are not the API's numbers. Of 930 values compared against the
    snapshot UTP itself had written into the same preset, 192 -- one in five --
    differed, in units and in significant digits: v_c 47.1238898038469 against
    tool_surfaceSpeed 47123.8898038469, v_f_plunge 1317.80292880089 against
    1317.8029288008897. Deciding "has this preset changed" from those would
    leave every tool permanently behind, and a tolerance in that one comparison
    is the last thing a shop tool should have.
  * Fusion rewrites it in place, non-atomically. A read parsed 441 presets and
    then measured the file at 0 bytes.
  * Its mtime moves for reasons unrelated to any library change, so it is not a
    change detector either.

The one field worth anything is sync.lastSyncTime, which says when Fusion last
asked the cloud. An API read does not move it, so an API read does not consult
the cloud; what that means for a change made on another machine is still open,
and needs a second machine to settle.
"""

import time

import adsk.cam

from . import config, values


class LibraryPreset:
    def __init__(self, preset, tool_id, library_path, library_url=None):
        self.id = preset.id
        self.name = preset.name
        self.tool_id = tool_id
        self.library = library_path
        # The path is only a label; the url is what a library is opened by.
        self.library_url = library_url
        self.values = values.scalars(preset)
        # Identity is the preset's own id, so nothing is stored for it.
        #
        # There used to be a version here, read from a stamp this add-in wrote
        # into the shop library. The whole of it is gone: whether an operation
        # is behind has always been decided by comparing values, never by a
        # number, and the numbers themselves produced one wrong name after
        # another -- "v1 - v1 available", a copy stamped v3 beside a library
        # at v1, and finally two names for one preset that told nobody which
        # was newer. A preset is now either what the library holds or it is
        # not, which is the only question anybody asked.

    @property
    def label(self):
        """What a note calls this UTP."""
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
        # Separately counted: a preset that builds fine and yields no values is
        # not a preset that failed to build, and it is the more dangerous of
        # the two. Every comparison works on the names both sides share, so an
        # empty one shares nothing and nothing ever differs. That used to read
        # as "matches the library".
        self.valueless = 0
        # Presets Fusion made rather than somebody in the shop. See
        # config.NOT_A_UTP_NAMES.
        self.ignored = 0
        for index in range(tool.presets.count):
            try:
                preset = LibraryPreset(tool.presets.item(index), self.id,
                                       library_path, library_url)
            except Exception:
                self.unreadable += 1
                continue
            if not config.is_a_utp(preset.name):
                # Not offered as a UTP at all, which is what stops it being
                # synced into documents, stamped with a version, or copied as
                # "(latest)". Counted so the report can say how many were
                # passed over rather than leaving a tool looking presetless.
                self.ignored += 1
                continue
            if not preset.values:
                self.valueless += 1
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


_cache = {"tools": None, "ok": False, "read at": 0.0, "missed": False}


def warm():
    """Whether the libraries have been read this session."""
    return _cache["tools"] is not None


def read_at():
    """When the reading in hand was taken. 0.0 if there is none.

    Used to tell whether a document that was swept was swept against the
    reading that is current now, or against an older one.
    """
    return _cache["read at"]


def incomplete():
    """Whether the last reading had a library it could not open.

    Asked by the verdict, so an unmatched tool is left alone instead of being
    called untracked on the strength of a reading that was missing a library.
    """
    return bool(_cache.get("missed"))


def age():
    """How long ago the libraries were read, in seconds, or None."""
    if _cache["tools"] is None:
        return None
    return time.time() - _cache["read at"]


def cached(report, do_events=None, force=False, stale_after=None):
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
    old = (stale_after and _cache["tools"] is not None
           and time.time() - _cache["read at"] > stale_after)
    if force or _cache["tools"] is None or old:
        if old:
            report.note("the reading of the shop libraries was old, so it was "
                        "taken again",
                        seconds_old=round(time.time() - _cache["read at"]))
        tools, ok, whole = read(report, do_events)
        if not whole:
            return tools, ok
        _cache["tools"], _cache["ok"] = tools, ok
        _cache["read at"] = time.time()
    return _cache["tools"], _cache["ok"]


def forget():
    _cache["tools"], _cache["ok"], _cache["read at"] = None, False, 0.0


def read(report, do_events=None):
    """Every tool in every Hub library, keyed by tool id.

    Returns (tools, ok, whole). ok is False when the library could not be
    reached, in which case nothing should be decided: a note that claims an
    operation is current would be a guess.

    Every library is always opened, so the set of tool ids is always complete
    and `whole` is True unless a library refused. This used to stop as soon as
    the tools one document used had been found, which made a reading in which a
    tool was simply absent -- and an absent tool reads as "not a shop tool",
    which removes a note. That reading could never be kept, so the button paid
    for a read and cached nothing, and the first edit of every session paid for
    another. Both are gone.

    Reading the preset values is not the expensive part, whatever it looks like.
    Measured 6 October, for 8 libraries, 470 tools and 441 presets: opening the
    libraries 1.82s, reading every tool's id 0.07s, enumerating the presets for
    their ids and names 1.11s, and reading every value in all of them 0.35s.
    Identity is the cost and identity cannot be deferred, so an attempt to read
    values lazily and top them up per document was both slower (3.03s plus
    0.85s a document, against 3.39s once) and more code. Do not try it again.
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
    read_count = preset_count = unreadable = valueless = ignored = 0
    # Libraries that would not open. One of eight failing used to be a note in
    # a log and nothing else: the tools in it were simply absent, so every
    # operation using one read as "not a UTP tool", and that takes the note and
    # the colour off. A yellow "v3 available" became no note at all, which both
    # documentation pages define as "never put on a shop preset". The person
    # sees nothing flagged and ships the old feeds.
    missed = []
    for path, asset_url in assets:
        try:
            library = libraries.toolLibraryAtURL(asset_url)
        except Exception:
            report.failed("could not read library %s" % path)
            missed.append(path)
            continue
        if library is None:
            missed.append(path)
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
                valueless += tool.valueless
                ignored += tool.ignored
            if do_events is not None and index % config.OPERATIONS_PER_CHUNK == 0:
                do_events()

    report.note("read the Hub libraries",
                libraries=read_count, tools=len(tools), presets=preset_count)
    if ignored:
        report.note("presets Fusion created rather than somebody in the shop",
                    count=ignored, names=list(config.NOT_A_UTP_NAMES),
                    consequence=("not treated as UTPs, so operations on them "
                                 "are left alone"))
    if valueless:
        report.note("SOME PRESETS HELD NO VALUES AT ALL", count=valueless,
                    consequence=("operations using them cannot be judged, so "
                                 "they are reported as unknown rather than "
                                 "current; a green note here would have meant "
                                 "nothing to do"))
    if unreadable:
        report.note("SOME PRESETS COULD NOT BE READ", count=unreadable,
                    consequence=("operations using them will look as though "
                                 "their preset was retired, which is wrong"))
    if missed:
        report.failed("SOME LIBRARIES WOULD NOT OPEN: %s" % ", ".join(missed))
        report.note("what that means for this pass",
                    consequence=("a tool from one of those cannot be found, so "
                                 "operations using it are left exactly as they "
                                 "are rather than being read as untracked"))
    _cache["missed"] = bool(missed)
    return tools, bool(tools), True
