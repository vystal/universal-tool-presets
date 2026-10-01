"""Wiring: the button, the listeners, and taking them down again.

Inside the package rather than in the entry point, so the copy a machine
downloads runs exactly the same code as the copy sitting in the repo. The
entry points are two thin files that do nothing but call start() and
shutdown().
"""

import traceback

import adsk.core

from . import config, diagnostics, version

_handlers = []
_state = {"control": None, "loaded_from": None}


def loaded_from():
    """Where this copy of the code came from, for the report to say."""
    return _state.get("loaded_from")


class _CommandCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            execute = _CommandExecute()
            args.command.execute.add(execute)
            _handlers.append(execute)
            # Nothing to configure, so skip the OK/Cancel dialog and just run.
            args.command.isAutoExecute = True
        except Exception:
            _report_failure("preparing the command")


class _CommandExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            from . import passes
            path, _counts, message = passes.run(app)
            _say(app, message, path)
        except Exception:
            _report_failure("checking the document")


class _UnmarkCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            execute = _UnmarkExecute()
            args.command.execute.add(execute)
            _handlers.append(execute)
            args.command.isAutoExecute = True
        except Exception:
            _report_failure("preparing the command")


class _UnmarkExecute(adsk.core.CommandEventHandler):
    """Taking it all back out.

    Asked about first: it is the one command whose whole purpose is to
    remove things somebody may want to keep.
    """

    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            answer = app.userInterface.messageBox(
                config.UNMARK_CONFIRM, config.DIALOG_TITLE,
                adsk.core.MessageBoxButtonTypes.YesNoButtonType)
            if answer != adsk.core.DialogResults.DialogYes:
                return
            from . import passes
            path, _counts, message = passes.remove_marks(app)
            _say(app, message, path)
        except Exception:
            _report_failure("removing the marks")


def _say(app, message, path):
    where = "\n\nReport:\n%s" % path if path else ""
    app.userInterface.messageBox(message + where, config.DIALOG_TITLE)


def _report_failure(what):
    app = adsk.core.Application.get()
    try:
        app.userInterface.messageBox(
            config.FAILED % (what, traceback.format_exc()),
            config.DIALOG_TITLE)
    except Exception:
        pass


def _add_button(ui, definition, command_id=None):
    """Put the button wherever this build keeps its Manufacture panels."""
    command_id = command_id or config.COMMAND_ID
    for workspace_id, panel_id in config.CANDIDATE_PANELS:
        try:
            workspace = ui.workspaces.itemById(workspace_id)
            if workspace is None:
                continue
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is None:
                continue
            existing = panel.controls.itemById(command_id)
            if existing:
                existing.deleteMe()
            return panel.controls.addCommand(definition)
        except Exception:
            continue
    return None


def start(app, loaded_from_path=None):
    ui = app.userInterface
    _state["loaded_from"] = loaded_from_path
    try:
        definitions = ui.commandDefinitions
        existing = definitions.itemById(config.COMMAND_ID)
        if existing:
            existing.deleteMe()
        definition = definitions.addButtonDefinition(
            config.COMMAND_ID, config.COMMAND_NAME, config.COMMAND_TOOLTIP)
        created = _CommandCreated()
        definition.commandCreated.add(created)
        _handlers.append(created)

        if config.LISTEN_TO_EVENTS:
            from . import events
            events.arm(app)

        unmark = definitions.itemById(config.UNMARK_COMMAND_ID)
        if unmark:
            unmark.deleteMe()
        unmark = definitions.addButtonDefinition(
            config.UNMARK_COMMAND_ID, config.UNMARK_COMMAND_NAME,
            config.UNMARK_COMMAND_TOOLTIP)
        unmark_created = _UnmarkCreated()
        unmark.commandCreated.add(unmark_created)
        _handlers.append(unmark_created)

        _state["control"] = _add_button(ui, definition)
        _state["unmark"] = _add_button(ui, unmark, config.UNMARK_COMMAND_ID)
        diagnostics.session_log("started", version=version.VERSION,
                                loaded_from=loaded_from_path or "in place",
                                schema=config.SCHEMA)
        if _state["control"] is None:
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
        for key in ("control", "unmark"):
            if _state.get(key):
                _state[key].deleteMe()
            _state[key] = None
        for command_id in (config.COMMAND_ID, config.UNMARK_COMMAND_ID):
            definition = ui.commandDefinitions.itemById(command_id)
            if definition:
                definition.deleteMe()
        del _handlers[:]
    except Exception:
        _report_failure("stopping")
