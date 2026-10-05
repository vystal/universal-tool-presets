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
    from tests import integration
    answer = integration.run(app, say)
finally:
    while where in sys.path:
        sys.path.remove(where)
