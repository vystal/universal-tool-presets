"""What to send when something has gone wrong.

One command that writes down everything worth knowing about this machine and
this document, in one file, so a problem can be looked into from a report
rather than from a description of a report.

It also lists Fusion's own workspaces, tabs and panels, because where a
button can be put has been guessed at twice and guessing is slower than
asking.
"""

import datetime
import os
import platform
import sys

import adsk.core
import adsk.cam

from . import config, diagnostics, library, version


def _switches():
    return {name: getattr(config, name) for name in sorted(dir(config))
            if name.startswith("MAY_") or name in
            ("LISTEN_TO_EVENTS", "ONLY_DOCUMENTS_ALREADY_MARKED",
             "SHOW_PROGRESS", "SCHEMA", "ATTRIBUTE_GROUP")}


def _panels(ui):
    """Every workspace, tab and panel this build of Fusion has.

    The reason a button ends up somewhere unintended, and the only reliable
    way to find out where it should go instead.
    """
    found = {}
    try:
        for index in range(ui.workspaces.count):
            workspace = ui.workspaces.item(index)
            if not workspace.id.startswith("CAM"):
                continue
            panels = []
            try:
                for position in range(workspace.toolbarPanels.count):
                    panel = workspace.toolbarPanels.item(position)
                    panels.append("%s  (%s)" % (panel.id, panel.name))
            except Exception as exc:
                panels.append("could not be listed: %s" % exc)
            found[workspace.id] = panels
    except Exception as exc:
        found["failed"] = str(exc)
    return found


def _libraries():
    try:
        libraries = adsk.cam.CAMManager.get().libraryManager.toolLibraries
        url = libraries.urlByLocation(
            adsk.cam.LibraryLocations.HubLibraryLocation)
    except Exception as exc:
        return {"failed": str(exc)}
    if url is None:
        return {"hub": "no Hub library on this account"}
    try:
        from .library import _walk
        assets = _walk(libraries, url)
        return {"hub libraries": [path.lstrip("/") for path, _u in assets]}
    except Exception as exc:
        return {"failed": str(exc)}


def _document(app):
    try:
        document = app.activeDocument
    except Exception:
        return {"open": "none"}
    found = {"name": getattr(document, "name", "?")}
    try:
        data = document.dataFile
        found["saved"] = data is not None
        if data is not None:
            found["read only"] = data.isReadOnly
            found["in use"] = data.isInUse
    except Exception as exc:
        found["file"] = "could not be read: %s" % exc
    try:
        products = document.products
        cam = products.itemByProductType("CAMProductType")
        found["has manufacturing data"] = cam is not None
        if cam is not None:
            found["setups"] = cam.setups.count
            found["tools in the document"] = cam.documentToolLibrary.count
    except Exception as exc:
        found["manufacture"] = "could not be read: %s" % exc
    return found


def _loader():
    base = os.environ.get("LOCALAPPDATA") or ""
    cache = os.path.join(base, "UTP", "cache")
    found = {"cache": cache, "present": os.path.isdir(cache)}
    for name, path in (("version", os.path.join(cache, "version.txt")),
                       ("log", os.path.join(cache, "loader.log"))):
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read().strip()
            found[name] = text.splitlines()[-8:] if name == "log" else text
        except Exception:
            found[name] = "not present"
    return found


def _recent_commands():
    """The command ids this session has seen, so a save can be recognised."""
    try:
        from . import events
        seen = sorted(events.seen_commands())
        return seen[-40:] or ["none yet"]
    except Exception as exc:
        return ["could not be read: %s" % exc]


def collect(app):
    """Everything worth knowing, written to one file. Returns its path."""
    from . import addin
    lines = ["# UTP debug", "",
             datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""]

    def section(title, rows):
        lines.append("## %s" % title)
        lines.append("")
        if isinstance(rows, dict):
            for key in sorted(rows):
                value = rows[key]
                if isinstance(value, list):
                    lines.append("- **%s:**" % key)
                    lines.extend("    - `%s`" % item for item in value)
                else:
                    lines.append("- **%s:** `%s`" % (key, value))
        else:
            lines.extend("- `%s`" % row for row in rows)
        lines.append("")

    section("This add-in", {
        "version": version.VERSION,
        "schema": config.SCHEMA,
        "loaded from": addin.loaded_from() or "in place",
        "reports go to": config.REPORT_DIR,
        "session log": diagnostics.session_path() or "none yet",
        "events recorded this session": diagnostics.session_count(),
    })
    section("Switches", _switches())
    section("This machine", {
        "Fusion": getattr(app, "version", "?"),
        "Python": sys.version.split()[0],
        "operating system": platform.platform(),
        "user": getattr(app, "userName", "?"),
    })
    section("The loader", _loader())
    section("The open document", _document(app))
    section("Hub libraries", _libraries())
    section("Where a button can go", _panels(app.userInterface))
    section("Commands seen this session", _recent_commands())

    try:
        os.makedirs(config.REPORT_DIR, exist_ok=True)
        path = os.path.join(
            config.REPORT_DIR,
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S debug.md"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        return path
    except Exception:
        return None
