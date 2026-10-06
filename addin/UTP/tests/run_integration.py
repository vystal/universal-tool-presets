# The job that runs the integration suite inside Fusion.
#
#     python tools/ask_fusion.py addin/UTP/tests/run_integration.py --writes
#
# A shim, because the suite belongs in a file that can be read and diffed rather
# than in a string passed through a queue. The repo's path is appended rather
# than inserted: utp is already in sys.modules from the running add-in, and
# putting the repo first invites a second copy of the package, which is how an
# afternoon went missing once.

import os
import sys

where = os.path.join(guard.REPO, "addin", "UTP")
sys.path.append(where)
try:
    # Dropped first, so an edited suite is the suite that runs. Without this the
    # copy imported by the first run of a session stays in sys.modules and every
    # later run silently re-runs it -- measured 6 October, two runs apart by a
    # new check and a fixed one, both reporting the same twenty verdicts. Only
    # the suite's own modules: utp belongs to the running add-in and a second
    # copy of that is a different afternoon lost.
    for name in [n for n in sys.modules
                 if n == "tests" or n.startswith("tests.")]:
        del sys.modules[name]
    from tests import integration
    answer = integration.run(app, say)
finally:
    while where in sys.path:
        sys.path.remove(where)
