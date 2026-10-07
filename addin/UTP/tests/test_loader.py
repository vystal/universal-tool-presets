"""The loader, tested without Fusion.

    python -m pytest addin/UTP/tests -q

_sync does the whole of it -- probe, fetch, hash, unpack, shape check, swap --
and touches no Fusion API, so the entire update path can be driven here as many
times as it takes. That matters more than it sounds: the loader is the one piece
nobody can fix remotely. It is installed by hand, it never updates itself, and a
loader that stops updating leaves a machine running an old add-in indefinitely
with nothing on screen to say so.

A file:// base is what makes this possible, and it is the same code path a
release takes: only _url differs.
"""

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

for _name in ("adsk", "adsk.core"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["adsk"].core = sys.modules["adsk.core"]


def _loader(cache):
    """A fresh copy of the loader, pointed at a throwaway cache."""
    path = os.path.join(REPO, "addin", "loader", "UTP", "UTP.py")
    spec = importlib.util.spec_from_file_location("utploader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._CACHE = cache
    module._CODE = os.path.join(cache, "code")
    module._STAMP = os.path.join(cache, "version.txt")
    module._LOG = os.path.join(cache, "loader.log")
    return module


def _publish(folder, version):
    """A dist exactly as tools/package.py builds one: zip, then SHA256, then
    VERSION. The real package.py writes VERSION last on purpose, so a loader
    starting mid-build sees the old one and comes back rather than fetching a
    zip and a hash that do not match it."""
    os.makedirs(folder, exist_ok=True)
    package = os.path.join(REPO, "addin", "UTP", "utp")
    archive = os.path.join(folder, "utp.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for root, _dirs, files in os.walk(package):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(root, name)
                inside = "utp/" + os.path.relpath(
                    full, package).replace("\\", "/")
                if inside == "utp/version.py":
                    zipped.writestr(inside, 'VERSION = "%s"\n' % version)
                else:
                    zipped.write(full, inside)
    digest = hashlib.sha256(open(archive, "rb").read()).hexdigest()
    with open(os.path.join(folder, "SHA256"), "w", encoding="utf-8") as handle:
        handle.write("%s  utp.zip\n" % digest)
    with open(os.path.join(folder, "VERSION"), "w", encoding="utf-8") as handle:
        handle.write(version + "\n")


def _bench():
    scratch = tempfile.mkdtemp(prefix="utp-loader-test-")
    dist = os.path.join(scratch, "dist")
    loader = _loader(os.path.join(scratch, "cache"))
    source = {"base": "file:///" + dist.replace("\\", "/"),
              "asset": "utp.zip"}
    return scratch, dist, loader, source


def test_each_release_installs_and_is_recorded_as_what_it_is():
    scratch, dist, loader, source = _bench()
    try:
        for version in ("0.1.0", "0.2.0", "0.3.0"):
            _publish(dist, version)
            assert loader._sync(source) == version
            assert loader._version_in(loader._CODE) == version, (
                "installed code is not what was published")
            assert loader._installed() == version, (
                "the recorded version is not what was installed")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_a_leftover_that_will_not_delete_does_not_stop_a_machine_updating():
    """The way a machine could stop updating for ever.

    The old copy used to be renamed onto a fixed "code.old". The rmtree before
    that ignores errors, so a leftover nobody could delete simply stayed, and
    os.rename onto an existing folder fails on Windows -- FileExistsError 183 --
    which aborted that update and every later one. The add-in kept working, one
    version behind, with a traceback in a log nobody reads.

    Reproduced by holding a file open inside the leftovers, which is what a
    previous Fusion having the folder in use looks like.
    """
    scratch, dist, loader, source = _bench()
    held = []
    try:
        _publish(dist, "1.0.0")
        assert loader._sync(source) == "1.0.0"

        for name in ("code.old", "utp-old-stale"):
            folder = os.path.join(loader._CACHE, name)
            os.makedirs(folder, exist_ok=True)
            held.append(open(os.path.join(folder, "in-use.txt"), "w"))

        _publish(dist, "2.0.0")
        assert loader._sync(source) == "2.0.0", (
            "a leftover nobody can delete stopped the update")
        assert loader._version_in(loader._CODE) == "2.0.0"

        # And again, so one stuck leftover cannot wedge it permanently.
        _publish(dist, "3.0.0")
        assert loader._sync(source) == "3.0.0"
        assert loader._version_in(loader._CODE) == "3.0.0"
    finally:
        for handle in held:
            try:
                handle.close()
            except Exception:
                pass
        shutil.rmtree(scratch, ignore_errors=True)


def test_a_download_that_does_not_match_its_hash_is_refused():
    """The working copy has to survive a bad delivery."""
    scratch, dist, loader, source = _bench()
    try:
        _publish(dist, "1.0.0")
        assert loader._sync(source) == "1.0.0"

        _publish(dist, "2.0.0")
        with open(os.path.join(dist, "SHA256"), "w", encoding="utf-8") as handle:
            handle.write("%s  utp.zip\n" % ("0" * 64))
        assert loader._sync(source) is None, "installed a mismatched download"
        assert loader._version_in(loader._CODE) == "1.0.0", (
            "a mismatched download replaced the working copy")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_a_byte_order_mark_in_source_json_is_read_anyway():
    """Every ordinary way of editing that file on Windows leaves one, and
    json.load refuses it -- which left the machine running its cache for ever.
    """
    scratch = tempfile.mkdtemp(prefix="utp-loader-bom-")
    try:
        loader = _loader(os.path.join(scratch, "cache"))
        loader._HERE = scratch
        with open(os.path.join(scratch, "source.json"), "wb") as handle:
            handle.write(b'\xef\xbb\xbf{"repo": "owner/name"}')
        found = loader._source()
        assert found is not None, "a byte order mark still stops it reading"
        assert found["repo"] == "owner/name"
        assert found["asset"] == "utp.zip"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
