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
            where = "\n\nReport:\n%s" % path if path else ""
            app.userInterface.messageBox(message + where, "UTP")
        except Exception:
            _report_failure("checking the document")


def _report_failure(what):
    app = adsk.core.Application.get()
    try:
        app.userInterface.messageBox(
            "UTP could not finish %s.\n\n%s" % (what, traceback.format_exc()),
            "UTP")
    except Exception:
        pass


def _add_button(ui, definition):
    """Put the button wherever this build keeps its Manufacture panels."""
    for workspace_id, panel_id in config.CANDIDATE_PANELS:
        try:
            workspace = ui.workspaces.itemById(workspace_id)
            if workspace is None:
                continue
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is None:
                continue
            existing = panel.controls.itemById(config.COMMAND_ID)
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

        _state["control"] = _add_button(ui, definition)
        diagnostics.session_log("started", version=version.VERSION,
                                loaded_from=loaded_from_path or "in place",
                                schema=config.SCHEMA)
        if _state["control"] is None:
            ui.messageBox(
                "UTP started, but no panel would take the button.\n\n"
                "Run it from Utilities > Add-Ins > Scripts and Add-Ins "
                "instead.", "UTP")
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
        if _state.get("control"):
            _state["control"].deleteMe()
        _state["control"] = None
        definition = ui.commandDefinitions.itemById(config.COMMAND_ID)
        if definition:
            definition.deleteMe()
        del _handlers[:]
    except Exception:
        _report_failure("stopping")
