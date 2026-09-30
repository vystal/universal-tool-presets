"""UTP loader. Installed once per machine; this file never changes.

The real code lives in a GitHub release and is cached on each machine. This
file fetches it, keeps it up to date and hands over to it, so updating the
shop means publishing a release rather than visiting every computer.

How it behaves, and why:

  * It always imports from the local cache, never straight from the network.
    A machine with no connection, or a laptop away from the shop, runs the
    last copy it got. A network problem means "slightly out of date", not
    "the add-in is gone".
  * With a cache in hand it hands over immediately and fetches in the
    background for next time. Fusion never waits on a slow network. Updates
    land on the next restart, which is true regardless: Fusion holds imported
    modules for a whole session, and swapping code under running event
    handlers is how an add-in crashes it.
  * With no cache it has to fetch before it can do anything, so the first run
    after installation is the only one that can block, and it gives up after
    a while rather than hanging.
  * A download is unpacked to a temporary folder and checked before it
    replaces anything. A truncated or wrong-looking download leaves the
    working copy alone.
  * It is pinned to released assets, never to a branch, so an unfinished
    commit cannot ship itself to every machine the moment it is pushed.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
import zipfile

import adsk.core

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
                      "UTP", "cache")
_CODE = os.path.join(_CACHE, "code")
_STAMP = os.path.join(_CACHE, "version.txt")
_LOG = os.path.join(_CACHE, "loader.log")

# Long enough for a slow link, short enough that a first run does not look
# like Fusion has hung.
_TIMEOUT = 20

_worker = [None]


# ---------------------------------------------------------------------------
# Saying what happened
# ---------------------------------------------------------------------------

def _note(message):
    """Appended as it happens, because this runs before anything else can."""
    try:
        os.makedirs(_CACHE, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write("%s\n" % message)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Where to fetch from
# ---------------------------------------------------------------------------

def _source():
    """Where to fetch from, read from source.json beside this file.

    Either {"repo": "owner/name"} for the published releases, or {"base":
    "..."} pointing anywhere else, which is how this gets exercised while the
    add-in is being written: a file:// base makes the loader fetch, unpack,
    check and swap exactly as it would from GitHub, so the whole path is used
    every day rather than only on the day it ships.
    """
    path = os.path.join(_HERE, "source.json")
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
    except Exception:
        _note("source.json could not be read at %s" % path)
        return None
    if not found.get("repo") and not found.get("base"):
        _note("source.json names neither a repo nor a base")
        return None
    found.setdefault("asset", "utp.zip")
    return found


def _url(source, name):
    base = source.get("base")
    if base:
        return base.rstrip("/") + "/" + name
    # Released assets only. A branch url would ship whatever was last pushed.
    return "https://github.com/%s/releases/latest/download/%s" % (
        source["repo"], name)


def _fetch(url, timeout=_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": "UTP-loader"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.read()


# ---------------------------------------------------------------------------
# Keeping the cache current
# ---------------------------------------------------------------------------

def _installed():
    try:
        with open(_STAMP, encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return None


def _usable(folder):
    """Whether an unpacked download looks like the add-in.

    Checked before it is allowed to replace a working copy: a truncated
    download, a wrong asset or an error page saved as a zip all get this far.
    """
    return (os.path.isfile(os.path.join(folder, "utp", "__init__.py"))
            and os.path.isfile(os.path.join(folder, "utp", "addin.py")))


def _sync(source):
    """Fetch and install if there is something newer. Returns the version."""
    try:
        available = _fetch(_url(source, "VERSION"), _TIMEOUT).decode().strip()
    except urllib.error.URLError as exc:
        _note("could not check for updates: %s" % exc.reason)
        return None
    except Exception as exc:
        _note("could not check for updates: %s" % exc)
        return None

    if available == _installed() and _usable(_CODE):
        return available

    try:
        payload = _fetch(_url(source, source["asset"]), _TIMEOUT)
    except Exception as exc:
        _note("could not download %s: %s" % (source["asset"], exc))
        return None

    staging = tempfile.mkdtemp(prefix="utp-update-")
    try:
        archive = os.path.join(staging, "download.zip")
        with open(archive, "wb") as handle:
            handle.write(payload)
        unpacked = os.path.join(staging, "unpacked")
        try:
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(unpacked)
        except zipfile.BadZipFile:
            # An expected way for this to fail, not a fault: a truncated
            # download, or a proxy returning an error page with a 200. Said
            # in one line rather than as a traceback.
            _note("the download was not a zip (%d bytes); keeping %s"
                  % (len(payload), _installed() or "nothing"))
            return None
        if not _usable(unpacked):
            _note("the download did not look like the add-in; keeping %s"
                  % (_installed() or "nothing"))
            return None
        # Swapped, never edited in place, so a failure here cannot leave a
        # half-written copy behind.
        os.makedirs(_CACHE, exist_ok=True)
        replaced = _CODE + ".old"
        shutil.rmtree(replaced, ignore_errors=True)
        if os.path.isdir(_CODE):
            os.rename(_CODE, replaced)
        shutil.move(unpacked, _CODE)
        shutil.rmtree(replaced, ignore_errors=True)
        with open(_STAMP, "w", encoding="utf-8") as handle:
            handle.write(available)
        _note("installed %s" % available)
        return available
    except Exception:
        _note("installing failed:\n%s" % traceback.format_exc())
        return None
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _sync_later(source):
    """Fetch for next time, off the main thread.

    Touches no Fusion API: the Fusion API is not safe off the main thread,
    and this only moves files about.
    """
    def work():
        try:
            _sync(source)
        except Exception:
            _note("background update failed:\n%s" % traceback.format_exc())

    _worker[0] = threading.Thread(target=work, daemon=True)
    _worker[0].start()


# ---------------------------------------------------------------------------
# Fusion's entry points
# ---------------------------------------------------------------------------

def run(context):
    app = adsk.core.Application.get()
    try:
        source = _source()
        have = _usable(_CODE)

        if not have:
            if source is None:
                app.userInterface.messageBox(
                    "UTP has no code to run and no source.json telling it "
                    "where to get some.\n\nExpected at:\n%s" % _HERE, "UTP")
                return
            _note("no cached copy; fetching before starting")
            if _sync(source) is None:
                app.userInterface.messageBox(
                    "UTP could not download the add-in and has no cached "
                    "copy to fall back on.\n\nCheck the network, then start "
                    "the add-in again.\n\nDetails:\n%s" % _LOG, "UTP")
                return

        if _CODE not in sys.path:
            sys.path.insert(0, _CODE)
        for name in [n for n in sys.modules if n == "utp" or n.startswith("utp.")]:
            del sys.modules[name]

        from utp import addin
        addin.start(app, loaded_from_path="%s (%s)" % (_CODE, _installed()))

        # Only once there is something running: an update fetched now takes
        # effect at the next restart, so it must never delay this one.
        if have and source is not None:
            _sync_later(source)
    except Exception:
        _note("starting failed:\n%s" % traceback.format_exc())
        try:
            app.userInterface.messageBox(
                "UTP could not start.\n\n%s" % traceback.format_exc(), "UTP")
        except Exception:
            pass


def stop(context):
    app = adsk.core.Application.get()
    try:
        worker = _worker[0]
        if worker is not None and worker.is_alive():
            # Briefly: it only moves files, and a half-finished download is
            # discarded rather than installed.
            worker.join(timeout=2)
        from utp import addin
        addin.shutdown(app)
    except Exception:
        _note("stopping failed:\n%s" % traceback.format_exc())
