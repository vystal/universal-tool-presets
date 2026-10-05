"""Entry point for the test agent.

Separate from the UTP add-in on purpose. It is a development tool, it runs code
sent from outside, and nothing that does that belongs in what goes to a shop
machine. The loader never fetches it; it is installed by hand, here, and the
manifest's runOnStartup only applies to whoever has installed it.

It puts the repo's own utp package on the path, so a job can import the module
under development rather than a copy, and reloads both packages on every Run so
an edit is one Stop/Run away.
"""

import os
import sys
import traceback

import adsk.core

_HERE = os.path.dirname(os.path.abspath(__file__))
# The add-in being tested lives next door. A job says "from utp import marks"
# and gets the working copy, which is the whole point of testing from here.
_UTP = os.path.join(os.path.dirname(_HERE), "UTP")
for path in (_HERE, _UTP):
    if path not in sys.path:
        sys.path.insert(0, path)


def _purge():
    """Drop this agent's own modules so a Stop/Run picks up an edit.

    Only the agent's. It used to take utp with it, which quietly broke the
    thing the agent is for: the add-in had already imported utp, and purging it
    meant the next job's "from utp import events" built a second, separate copy
    of the package. Module-level state then read from a job was not the running
    add-in's state at all -- it reported no event handlers attached while the
    add-in had five, and a switch as off while the file said nothing about it.

    That mattered the day the edit listener broke: the one tool that could have
    confirmed the fix was reporting a different module's variables. A job that
    wants the working copy from the repo asks for it by name, through
    use_repo(), which does its own purge at that point.
    """
    for name in [n for n in sys.modules
                 if n == "agent" or n.startswith("agent.")]:
        del sys.modules[name]


def run(context):
    try:
        _purge()
        from agent import runner
        where = runner.start()
        app = adsk.core.Application.get()
        app.log("UTP test agent watching %s" % where)
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                "The UTP test agent could not start.\n\n%s"
                % traceback.format_exc())


def stop(context):
    try:
        from agent import runner
        runner.stop()
    except Exception:
        pass
