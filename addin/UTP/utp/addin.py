"""Wiring: one dropdown of commands, the listeners, and taking them down.

Inside the package rather than in the entry point, so the copy a machine
downloads runs exactly the same code as the copy sitting in the repo. The
entry points are two thin files that do nothing but call start() and
shutdown().

Every command goes through one handler that takes a function, rather than a
pair of classes each. Eight commands as sixteen near-identical classes is
how a file stops being readable.
"""

import os
import subprocess
import sys
import traceback

import adsk.core

from . import config, diagnostics, version

_handlers = []
_state = {"panel": None, "loaded_from": None, "where": None}


def loaded_from():
    """Where this copy of the code came from, for the report to say."""
    return _state.get("loaded_from")


# ---------------------------------------------------------------------------
# One handler for every command
# ---------------------------------------------------------------------------

class _Created(adsk.core.CommandCreatedEventHandler):
    def __init__(self, work, confirm=None):
        super().__init__()
        self.work, self.confirm = work, confirm

    def notify(self, args):
        try:
            run = _Execute(self.work, self.confirm)
            args.command.execute.add(run)
            _handlers.append(run)
            # Nothing to configure, so skip the OK/Cancel dialog and just do
            # it. Anything that needs asking asks for itself.
            args.command.isAutoExecute = True
        except Exception:
            _report_failure("preparing a command")


class _Execute(adsk.core.CommandEventHandler):
    def __init__(self, work, confirm=None):
        super().__init__()
        self.work, self.confirm = work, confirm

    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            if self.confirm:
                answer = app.userInterface.messageBox(
                    self.confirm, config.DIALOG_TITLE,
                    adsk.core.MessageBoxButtonTypes.YesNoButtonType)
                if answer != adsk.core.DialogResults.DialogYes:
                    return
            message, path = self.work(app)
            if message:
                _say(app, message, path)
        except Exception:
            _report_failure("doing that")


def _say(app, message, path=None):
    app.userInterface.messageBox(message + ("\n\n%s" % path if path else ""),
                                 config.DIALOG_TITLE)


def _report_failure(what):
    app = adsk.core.Application.get()
    try:
        app.userInterface.messageBox(
            config.FAILED % (what, traceback.format_exc()),
            config.DIALOG_TITLE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# What each command does
# ---------------------------------------------------------------------------

def _check(app):
    from . import passes
    path, _counts, message = passes.run(app)
    return message, path and ("Report:\n%s" % path)


def _check_only(app):
    from . import passes
    path, _counts, message = passes.run(app, allow_writing=False)
    return message, path and ("Report:\n%s" % path)


def _unmark(app):
    from . import passes
    path, _counts, message = passes.remove_marks(app)
    return message, path and ("Report:\n%s" % path)


def _refresh(app):
    """Read the Hub libraries again, for when somebody has changed one."""
    from . import library
    report = diagnostics.Report("library refresh")
    library.forget()
    tools, ok = library.cached(report, adsk.doEvents, force=True)
    presets = sum(len(tool.presets) for tool in tools.values())
    shelves = len({tool.library for tool in tools.values()})
    path = report.close()
    if not ok:
        return config.NO_LIBRARY, None
    return (config.REFRESHED % (len(tools), presets, shelves),
            "Report:\n%s" % path if path else None)


def _folder(app):
    try:
        os.makedirs(config.REPORT_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(config.REPORT_DIR)
        else:
            subprocess.Popen(["open", config.REPORT_DIR])
        return None, None          # the folder opening is the whole answer
    except Exception:
        return "The reports folder could not be opened.", config.REPORT_DIR


def _switches(app):
    names = [n for n in sorted(dir(config))
             if n.startswith("MAY_") or n in ("LISTEN_TO_EVENTS",
                                              "ONLY_DOCUMENTS_ALREADY_MARKED",
                                              "SHOW_PROGRESS")]
    lines = ["%s   %s" % ("yes" if getattr(config, name) else " no", name)
             for name in names]
    lines += ["", "version %s, schema %d" % (version.VERSION, config.SCHEMA),
              "running from %s" % (loaded_from() or "in place")]
    return "What this add-in is allowed to do:\n\n" + "\n".join(lines), None


def _help(app):
    """Opened as a page, not shown in a dialog.

    A Fusion message box renders in a proportional font and swallows blank
    lines, so an aligned plain-text sheet came out as a wall of words.
    """
    from . import instructions
    path = instructions.show(version.VERSION)
    if path is None:
        return config.INSTRUCTIONS, None
    return None, None


def _debug(app):
    from . import debug
    path = debug.collect(app)
    return (config.DEBUG_WRITTEN if path else config.DEBUG_FAILED,
            path and ("Report:\n%s" % path))


# The order they are read in, not the order they were built: the two used
# most first, instructions last.
COMMANDS = [
    (config.COMMAND_ID, config.COMMAND_NAME, config.COMMAND_TOOLTIP,
     _check, None),
    (config.DRY_COMMAND_ID, config.DRY_COMMAND_NAME,
     config.DRY_COMMAND_TOOLTIP, _check_only, None),
    (config.REFRESH_COMMAND_ID, config.REFRESH_COMMAND_NAME,
     config.REFRESH_COMMAND_TOOLTIP, _refresh, None),
    (config.UNMARK_COMMAND_ID, config.UNMARK_COMMAND_NAME,
     config.UNMARK_COMMAND_TOOLTIP, _unmark, config.UNMARK_CONFIRM),
    (config.FOLDER_COMMAND_ID, config.FOLDER_COMMAND_NAME,
     config.FOLDER_COMMAND_TOOLTIP, _folder, None),
    (config.SWITCHES_COMMAND_ID, config.SWITCHES_COMMAND_NAME,
     config.SWITCHES_COMMAND_TOOLTIP, _switches, None),
    (config.DEBUG_COMMAND_ID, config.DEBUG_COMMAND_NAME,
     config.DEBUG_COMMAND_TOOLTIP, _debug, None),
    (config.HELP_COMMAND_ID, config.HELP_COMMAND_NAME,
     config.HELP_COMMAND_TOOLTIP, _help, None),
]


# ---------------------------------------------------------------------------
# Where it lives
# ---------------------------------------------------------------------------

def _own_panel(ui):
    """A panel of this add-in's own, on the Utilities tab if there is one.

    Putting a dropdown into one of Fusion's panels nested it inside that
    panel's own menu. Giving our panel a dropdown of its own then meant two
    things both called UTP, one inside the other. The commands sit in the
    panel directly.

    The tab is matched rather than named, because tab and panel ids differ
    between builds and naming them has been wrong twice. The debug report
    lists every tab and panel this Fusion has, which is how this gets
    corrected rather than guessed at again.
    """
    try:
        workspace = ui.workspaces.itemById("CAMEnvironment")
        if workspace is None:
            return None, None
        tabs = workspace.toolbarTabs
        wanted = None
        for index in range(tabs.count):
            tab = tabs.item(index)
            if config.PREFERRED_TAB in ("%s %s" % (tab.id, tab.name)).lower():
                wanted = tab
                break
        if wanted is None and tabs.count:
            wanted = tabs.item(tabs.count - 1)
        if wanted is None:
            return None, None
        existing = wanted.toolbarPanels.itemById(config.PANEL_ID)
        if existing:
            existing.deleteMe()
        panel = wanted.toolbarPanels.add(config.PANEL_ID, config.PANEL_NAME)
        return panel, "%s / %s" % (wanted.id, config.PANEL_ID)
    except Exception:
        return None, None


def _fallback_panel(ui):
    """One of Fusion's panels, if a panel of our own cannot be made."""
    for workspace_id, panel_id in config.CANDIDATE_PANELS:
        try:
            workspace = ui.workspaces.itemById(workspace_id)
            if workspace is None:
                continue
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is not None:
                return panel, "%s / %s (not our own)" % (workspace_id, panel_id)
        except Exception:
            continue
    return None, None


# ---------------------------------------------------------------------------

def start(app, loaded_from_path=None):
    ui = app.userInterface
    _state["loaded_from"] = loaded_from_path
    try:
        definitions = ui.commandDefinitions
        built = []
        for command_id, name, tooltip, work, confirm in COMMANDS:
            existing = definitions.itemById(command_id)
            if existing:
                existing.deleteMe()
            definition = definitions.addButtonDefinition(
                command_id, name, tooltip)
            created = _Created(work, confirm)
            definition.commandCreated.add(created)
            _handlers.append(created)
            built.append(definition)

        if config.LISTEN_TO_EVENTS:
            from . import events
            events.arm(app)

        panel, where = _own_panel(ui)
        _state["panel"] = panel
        if panel is None:
            panel, where = _fallback_panel(ui)
        _state["where"] = where
        if panel is not None:
            # Straight into our own panel. A dropdown inside it meant two
            # things both called UTP, one nested in the other.
            for definition in built:
                existing = panel.controls.itemById(definition.id)
                if existing:
                    existing.deleteMe()
                panel.controls.addCommand(definition)

        diagnostics.session_log("started", version=version.VERSION,
                                loaded_from=loaded_from_path or "in place",
                                schema=config.SCHEMA, commands=len(built),
                                panel=where or "nowhere")
        if panel is None:
            ui.messageBox(config.NO_PANEL, config.DIALOG_TITLE)
    except Exception:
        _report_failure("starting")


def shutdown(app):
    ui = app.userInterface
    try:
        try:
            from . import events
            events.disarm(app)
        except Exception:
            pass
        # The panel goes, and its commands with it.
        if _state.get("panel"):
            try:
                _state["panel"].deleteMe()
            except Exception:
                pass
        _state["panel"] = None
        for command_id, _name, _tip, _work, _confirm in COMMANDS:
            definition = ui.commandDefinitions.itemById(command_id)
            if definition:
                definition.deleteMe()
        del _handlers[:]
    except Exception:
        _report_failure("stopping")
