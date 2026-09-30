"""UTP, run straight from the repo. For developing it.

This is the entry point used while working on the add-in: it imports the
package sitting next to it, so an edit is one Stop/Run away from taking
effect. Shop machines use the loader in addin/loader instead, which fetches
the same package from a release and keeps itself up to date.

Both end up calling utp.addin.start(), so what is being developed here is
what runs there.
"""

import os
import sys

import adsk.core

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _purge():
    """Fusion keeps imported modules for a whole session.

    Without this an add-in edited while Fusion is open keeps running the old
    code, which cost real time during testing.
    """
    for name in [n for n in sys.modules if n == "utp" or n.startswith("utp.")]:
        del sys.modules[name]


def run(context):
    _purge()
    from utp import addin
    addin.start(adsk.core.Application.get(), loaded_from_path=_HERE)


def stop(context):
    from utp import addin
    addin.shutdown(adsk.core.Application.get())
