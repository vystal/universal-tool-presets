"""Build the two files a release needs: utp.zip and VERSION.

Run it from anywhere:  python tools/package.py

The version comes from utp/version.py and nowhere else, so the VERSION file
the loader compares against cannot drift from the code it describes.

Upload both as assets on a GitHub release. The loader fetches them from
releases/latest/download/, so publishing a release is what updates the shop.
"""

import hashlib
import os
import re
import shutil
import tempfile
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "addin", "UTP", "utp")
OUT = os.path.join(ROOT, "dist")

# Files the add-in does not need and a release should not carry.
SKIP_DIRS = {"__pycache__"}
SKIP_NAMES = {".DS_Store"}


def version():
    text = open(os.path.join(PACKAGE, "version.py"), encoding="utf-8").read()
    found = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
    if not found:
        raise SystemExit("no VERSION in utp/version.py")
    return found.group(1)


def _published():
    """The version and hash dist currently holds, if any."""
    try:
        version = open(os.path.join(OUT, "VERSION"), encoding="utf-8").read().strip()
        digest = open(os.path.join(OUT, "SHA256"), encoding="utf-8").read().split()[0]
        return version, digest
    except Exception:
        return None, None


def build():
    if not os.path.isdir(PACKAGE):
        raise SystemExit("no package at %s" % PACKAGE)
    number = version()
    # Read before the folder is cleared, which is where the first attempt at
    # this check went wrong: it looked afterwards and there was nothing left
    # to compare against.
    was_version, was_digest = _published()

    # Built somewhere else and moved in at the end, so a refusal below -- or a
    # failure anywhere in here -- leaves the release that is already published
    # exactly as it was. Clearing the folder first meant the check that exists
    # to protect a release destroyed it on the way to saying no.
    staging = tempfile.mkdtemp(prefix="utp-package-")
    archive = os.path.join(staging, "utp.zip")
    included = []
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for folder, folders, names in os.walk(PACKAGE):
            folders[:] = [f for f in folders if f not in SKIP_DIRS]
            for name in sorted(names):
                if name in SKIP_NAMES or name.endswith(".pyc"):
                    continue
                full = os.path.join(folder, name)
                # Stored as utp/..., which is what the loader unpacks and
                # what _usable() checks for.
                inside = os.path.join(
                    "utp", os.path.relpath(full, PACKAGE)).replace("\\", "/")
                zipped.write(full, inside)
                included.append(inside)

    # What the loader checks a download against before it unpacks anything.
    #
    # Be clear what this is and is not. It catches a download that arrived
    # wrong: truncated, a proxy's error page saved as a zip, the wrong asset, a
    # CDN serving half a file. It is not a signature. Anyone who could replace
    # utp.zip on a release could replace this file in the same breath, so it
    # adds nothing against the release itself being tampered with. That needs a
    # key the loader trusts, with the private half kept off these machines, and
    # is a different piece of work.
    digest = hashlib.sha256(open(archive, "rb").read()).hexdigest()

    # Refuse to publish different content under a version already published.
    #
    # The loader decides whether to fetch by comparing version numbers, which
    # is right: a release is a fixed thing. So repackaging without bumping
    # leaves every machine on the old content and nothing says so. Done it
    # repeatedly this week -- most visibly on 8 October, when redrawn icons
    # never reached Fusion and the add-in looked unchanged, and it is very
    # likely the whole of the "installs one version behind" mystery that cost
    # an afternoon chasing the loader, which turned out to be correct.
    if was_version == number and was_digest and was_digest != digest:
        raise SystemExit(
            "dist already held a different %s.\n"
            "Bump the version in addin/UTP/utp/version.py first: the loader "
            "fetches by version, so machines would keep the old one and "
            "nothing would say so." % number)
    with open(os.path.join(staging, "SHA256"), "w", encoding="utf-8") as handle:
        handle.write("%s  utp.zip\n" % digest)

    # VERSION last, because it is the only one of the three the loader reads to
    # decide whether to fetch anything at all. Written first -- which it was --
    # it advertises a release the other two files do not back yet, and a loader
    # starting in that window fetches a zip and a hash that are still the
    # previous pair. Measured 7 October: the loader installed 0.23.1 from a dist
    # whose VERSION said 0.24.0, with the SHA256 checking out, and said so in
    # its log. Its own check caught that; this removes the window rather than
    # relying on it. Written last, the worst case is a loader that sees the old
    # version, fetches the matching old pair, and comes back next start.
    with open(os.path.join(staging, "VERSION"), "w", encoding="utf-8") as handle:
        handle.write(number + "\n")

    # The same check the loader makes before it trusts a download, so a bad
    # release is caught here rather than on somebody's machine.
    needed = {"utp/__init__.py", "utp/addin.py"}
    missing = needed - set(included)
    if missing:
        raise SystemExit("the zip is missing %s" % ", ".join(sorted(missing)))

    # Everything checked out, so the release is replaced now and not before.
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.move(staging, OUT)
    archive = os.path.join(OUT, "utp.zip")

    print("version %s" % number)
    print("%s  (%d files, %d KB)"
          % (archive, len(included), os.path.getsize(archive) // 1024))
    print("%s" % os.path.join(OUT, "VERSION"))
    print()
    print("%s" % os.path.join(OUT, "SHA256"))
    print()
    print("Upload all three as assets on a GitHub release tagged v%s." % number)
    return 0


if __name__ == "__main__":
    sys.exit(build())
