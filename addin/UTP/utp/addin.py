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


class _DebugCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            execute = _DebugExecute()
            args.command.execute.add(execute)
            _handlers.append(execute)
            args.command.isAutoExecute = True
        except Exception:
            _report_failure("preparing the command")


class _DebugExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            from . import debug
            path = debug.collect(app)
            _say(app, config.DEBUG_WRITTEN if path else config.DEBUG_FAILED,
                 path)
        except Exception:
            _report_failure("writing a debug report")


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


def _menu(ui):
    """The dropdown everything hangs off, in the first panel that takes it.

    A dropdown of its own rather than buttons loose among Fusion's, which is
    both tidier and means one place to look. Where it ends up is a list
    rather than a guess, because panel ids differ between builds, and the
    debug report lists what this build actually has.
    """
    for workspace_id, panel_id in config.CANDIDATE_PANELS:
        try:
            workspace = ui.workspaces.itemById(workspace_id)
            if workspace is None:
                continue
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is None:
                continue
            existing = panel.controls.itemById(config.MENU_ID)
            if existing:
                existing.deleteMe()
            menu = panel.controls.addDropDown(
                config.MENU_NAME, "", config.MENU_ID)
            if menu is not None:
                _state["where"] = "%s / %s" % (workspace_id, panel_id)
                return menu
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

        report = definitions.itemById(config.DEBUG_COMMAND_ID)
        if report:
            report.deleteMe()
        report = definitions.addButtonDefinition(
            config.DEBUG_COMMAND_ID, config.DEBUG_COMMAND_NAME,
            config.DEBUG_COMMAND_TOOLTIP)
        report_created = _DebugCreated()
        report.commandCreated.add(report_created)
        _handlers.append(report_created)

        menu = _menu(ui)
        _state["menu"] = menu
        if menu is not None:
            for each in (definition, unmark, report):
                menu.controls.addCommand(each)
        diagnostics.session_log("started", version=version.VERSION,
                                loaded_from=loaded_from_path or "in place",
                                schema=config.SCHEMA,
                                menu=_state.get("where") or "nowhere")
        if menu is None:
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
        # The dropdown goes, and its commands with it.
        if _state.get("menu"):
            _state["menu"].deleteMe()
        _state["menu"] = None
        for command_id in (config.COMMAND_ID, config.UNMARK_COMMAND_ID,
                           config.DEBUG_COMMAND_ID):
            definition = ui.commandDefinitions.itemById(command_id)
            if definition:
                definition.deleteMe()
        del _handlers[:]
    except Exception:
        _report_failure("stopping")
