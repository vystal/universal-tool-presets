"""Build the two files a release needs: utp.zip and VERSION.

Run it from anywhere:  python tools/package.py

The version comes from utp/version.py and nowhere else, so the VERSION file
the loader compares against cannot drift from the code it describes.

Upload both as assets on a GitHub release. The loader fetches them from
releases/latest/download/, so publishing a release is what updates the shop.
"""

import os
import re
import shutil
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


def build():
    if not os.path.isdir(PACKAGE):
        raise SystemExit("no package at %s" % PACKAGE)
    number = version()
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)

    archive = os.path.join(OUT, "utp.zip")
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

    with open(os.path.join(OUT, "VERSION"), "w", encoding="utf-8") as handle:
        handle.write(number + "\n")

    # The same check the loader makes before it trusts a download, so a bad
    # release is caught here rather than on somebody's machine.
    needed = {"utp/__init__.py", "utp/addin.py"}
    missing = needed - set(included)
    if missing:
        raise SystemExit("the zip is missing %s" % ", ".join(sorted(missing)))

    print("version %s" % number)
    print("%s  (%d files, %d KB)"
          % (archive, len(included), os.path.getsize(archive) // 1024))
    print("%s" % os.path.join(OUT, "VERSION"))
    print()
    print("Upload both as assets on a GitHub release tagged v%s." % number)
    return 0


if __name__ == "__main__":
    sys.exit(build())
