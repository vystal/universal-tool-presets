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
    def __init__(self, work, confirm=None, ask=None):
        super().__init__()
        self.work, self.confirm, self.ask = work, confirm, ask

    def notify(self, args):
        try:
            run = _Execute(self.work, self.confirm, self.ask)
            args.command.execute.add(run)
            _handlers.append(run)
            if self.ask is None:
                # Nothing to configure, so skip the OK/Cancel dialog and just
                # do it. Anything that needs asking asks for itself.
                args.command.isAutoExecute = True
            else:
                self.ask(args.command.commandInputs)
                args.command.isAutoExecute = False
        except Exception:
            _report_failure("preparing a command")


class _Execute(adsk.core.CommandEventHandler):
    def __init__(self, work, confirm=None, ask=None):
        super().__init__()
        self.work, self.confirm, self.ask = work, confirm, ask

    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            if self.confirm:
                answer = app.userInterface.messageBox(
                    self.confirm, config.DIALOG_TITLE,
                    adsk.core.MessageBoxButtonTypes.YesNoButtonType)
                if answer != adsk.core.DialogResults.DialogYes:
                    return
            if self.ask is None:
                message, path = self.work(app)
            else:
                message, path = self.work(app, args.command.commandInputs)
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
    from . import passes, settings
    # Which switch stopped it, rather than running and quietly changing
    # nothing. Remove all notes is deliberately not guarded this way:
    # switching the add-in off and then taking its notes out is how somebody
    # stops using it, and a guard there would trap them.
    if not settings.on("on"):
        return config.IS_OFF, None
    path, _counts, message = passes.run(app)
    if not settings.on("mark"):
        # The pass still ran, so there is a report saying what it would have
        # done, and the preset switches still mean what they say. Returning
        # before the pass made this button a dead end that promised a report
        # it had not written, and silently refused preset work the Switches
        # dialog offers as its own control.
        message = config.MARKING_OFF + "\n\n" + message
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


def _ask_switches(inputs):
    """The only command with a dialog: checkboxes for what it may do.

    It used to print the switches and leave you to edit config.py, which is
    no use to anybody who did not write it. Same button, same list, now you
    can change it.
    """
    from . import settings
    held = settings.values()
    if settings.damaged["file"]:
        # Said here because this is where somebody comes to find out, and
        # pressing OK writes a good file, so the dialog is the cure as well
        # as the explanation.
        inputs.addTextBoxCommandInput(
            "utp_damaged", "", config.SWITCHES_DAMAGED, 2, True)
    boxes = {None: inputs}
    for key, title in settings.GROUPS:
        group = inputs.addGroupCommandInput("utp_" + key, title)
        group.isExpanded = True
        boxes[key] = group.children
    for key, label, group, _switch in settings.CONTROLS:
        box = boxes[group].addBoolValueInput(
            "utp_" + key, label, True, "", held[key])
        # The label is two or three words, so the sentence saying what it
        # actually does goes here: tooltip is the heading Fusion shows in
        # bold, tooltipDescription the paragraph under it.
        box.tooltip = label
        box.tooltipDescription = settings.MEANS.get(key, "")
    inputs.addTextBoxCommandInput(
        "utp_footer", "", config.SWITCHES_FOOTER, 2, True)


def _switches(app, inputs):
    from . import settings
    chosen = {}
    for key, _label, _group, _switch in settings.CONTROLS:
        found = inputs.itemById("utp_" + key)
        if found is not None:
            chosen[key] = found.value
    changed = settings.save(chosen)
    if not changed:
        return config.SWITCHES_UNCHANGED, None
    return config.SWITCHES_SAVED % "\n".join(changed), None


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
     _check, None, None),
    (config.DRY_COMMAND_ID, config.DRY_COMMAND_NAME,
     config.DRY_COMMAND_TOOLTIP, _check_only, None, None),
    (config.REFRESH_COMMAND_ID, config.REFRESH_COMMAND_NAME,
     config.REFRESH_COMMAND_TOOLTIP, _refresh, None, None),
    (config.UNMARK_COMMAND_ID, config.UNMARK_COMMAND_NAME,
     config.UNMARK_COMMAND_TOOLTIP, _unmark, config.UNMARK_CONFIRM, None),
    (config.SWITCHES_COMMAND_ID, config.SWITCHES_COMMAND_NAME,
     config.SWITCHES_COMMAND_TOOLTIP, _switches, None, _ask_switches),
    (config.FOLDER_COMMAND_ID, config.FOLDER_COMMAND_NAME,
     config.FOLDER_COMMAND_TOOLTIP, _folder, None, None),
    (config.DEBUG_COMMAND_ID, config.DEBUG_COMMAND_NAME,
     config.DEBUG_COMMAND_TOOLTIP, _debug, None, None),
    (config.HELP_COMMAND_ID, config.HELP_COMMAND_NAME,
     config.HELP_COMMAND_TOOLTIP, _help, None, None),
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
    from . import settings
    settings.forget()
    try:
        definitions = ui.commandDefinitions
        built = []
        for command_id, name, tooltip, work, confirm, ask in COMMANDS:
            existing = definitions.itemById(command_id)
            if existing:
                existing.deleteMe()
            definition = definitions.addButtonDefinition(
                command_id, name, tooltip)
            created = _Created(work, confirm, ask)
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
        for command_id, _name, _tip, _work, _confirm, _ask in COMMANDS:
            definition = ui.commandDefinitions.itemById(command_id)
            if definition:
                definition.deleteMe()
        del _handlers[:]
    except Exception:
        _report_failure("stopping")
