"""UTP loader. Installed once per machine; this file never changes.

The real code lives in a GitHub release and is cached on each machine. This
file fetches it, keeps it up to date and hands over to it, so updating the
shop means publishing a release rather than visiting every computer.

How it behaves, and why:

  * It always imports from the local cache, never straight from the network.
    A machine with no connection, or a laptop away from the shop, runs the
    last copy it got. A network problem means "slightly out of date", not
    "the add-in is gone".
  * It checks for a newer release before handing over, not in the background.
    This paragraph used to claim a background thread. There is not one: the
    check moved in front of the handover on purpose, so a machine that has
    just been updated runs the new code this session rather than the next, and
    the cost is a probe of about three seconds at startup, or about twenty on
    the one start that finds a release to download. Updates still land on a
    restart either way, because Fusion holds imported modules for a whole
    session and swapping code under running event handlers is how an add-in
    crashes it.
  * With no cache it has to fetch before it can do anything, so the first run
    after installation is the only one that can block, and it gives up after
    a while rather than hanging.
  * A download is checked against a SHA256 published beside it, then unpacked
    to a temporary folder and checked for shape, before it replaces anything.
    Anything that arrived wrong leaves the working copy alone.

    That is integrity, not authenticity. It catches a truncated download, a
    proxy's error page saved as a zip, the wrong asset, a CDN serving half a
    file. It does not protect against the release itself being tampered with,
    because anyone who could replace the zip could replace the hash beside it.
    The trust anchor for that is still HTTPS and the GitHub account, and the
    only thing that would change it is a signature checked against a key
    pinned in this file, with the private half kept off these machines.
  * It is pinned to released assets, never to a branch, so an unfinished
    commit cannot ship itself to every machine the moment it is pushed.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
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

# The check for something newer is a one-line file, so it can be waited for
# at startup: measured at about a third of a second. Only when it says there
# is an update does anything larger get fetched. A machine with no connection
# pays this once per Fusion start and carries on with its cache.
_PROBE_TIMEOUT = 3


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


def _version_in(folder):
    """The version the downloaded code says it is.

    Read from the package rather than believed from the VERSION file. GitHub
    serves release assets through a cache: measured, a VERSION 85 seconds
    stale while the zip beside it was current. Trusting the probe would let a
    machine run one version while recording another, and a report claiming a
    version it is not running is worse than no version at all.
    """
    path = os.path.join(folder, "utp", "version.py")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VERSION"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return None


def _usable(folder):
    """Whether an unpacked download has the shape of the add-in.

    A shape check and nothing more: two filenames. It is the last of three
    gates, after the hash and after the zip opening at all, and on its own it
    would pass anything containing those two names. Worth keeping as the one
    that survives a release built wrongly rather than delivered wrongly.
    """
    return (os.path.isfile(os.path.join(folder, "utp", "__init__.py"))
            and os.path.isfile(os.path.join(folder, "utp", "addin.py")))


def _expected_digest(source):
    """The SHA256 published beside the asset, or None if there is not one.

    Releases up to 0.17.0 have no such file. Those are allowed through with a
    line saying so rather than refused, because refusing would mean a loader
    that cannot install any release made before the check existed, including
    the one a machine might need to go back to.
    """
    try:
        published = _fetch(_url(source, "SHA256"), _TIMEOUT).decode()
    except Exception:
        return None
    for word in published.split():
        if len(word) == 64 and all(c in "0123456789abcdef" for c in word.lower()):
            return word.lower()
    return None


def _sync(source, probe_timeout=_TIMEOUT):
    """Fetch and install if there is something newer. Returns the version."""
    try:
        available = _fetch(_url(source, "VERSION"),
                           probe_timeout).decode().strip()
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

    expected = _expected_digest(source)
    got = hashlib.sha256(payload).hexdigest()
    if expected is None:
        _note("no SHA256 published for %s; installing %s unverified"
              % (source["asset"], available))
    elif got != expected:
        # Nothing is unpacked and nothing is replaced. The working copy stands.
        _note("the download of %s does not match the SHA256 published beside "
              "it, so it was discarded and %s is still in use. Expected %s, "
              "got %s (%d bytes)."
              % (source["asset"], _installed() or "nothing",
                 expected[:16], got[:16], len(payload)))
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
        # What the code says it is, not what the probe said. They differ
        # while the cache is catching up with a release.
        installed = _version_in(_CODE) or available
        with open(_STAMP, "w", encoding="utf-8") as handle:
            handle.write(installed)
        if installed != available:
            _note("the version file said %s but the code is %s; recorded the "
                  "code" % (available, installed))
        _note("installed %s" % installed)
        return installed
    except Exception:
        _note("installing failed:\n%s" % traceback.format_exc())
        return None
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# Fusion's entry points
# ---------------------------------------------------------------------------

def run(context):
    app = adsk.core.Application.get()
    try:
        source = _source()
        have = _usable(_CODE)

        if have and source is not None:
            # Before anything is imported, so a release published today is
            # running after one restart rather than two. Fetching afterwards
            # instead cost nothing at startup, but the copy it collected then
            # sat unused until the restart after that.
            _sync(source, probe_timeout=_PROBE_TIMEOUT)

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
        from utp import addin
        addin.shutdown(app)
    except Exception:
        _note("stopping failed:\n%s" % traceback.format_exc())
