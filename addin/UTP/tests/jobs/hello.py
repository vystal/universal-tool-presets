# Smoke test. Read-only: proves the agent runs, reaches the API, and can
# import the working copy of the add-in rather than a release.
#
#     python tools/ask_fusion.py tests/jobs/hello.py

from utp import config, version

say("Fusion", app.version)
say("UTP", version.VERSION, "schema", config.SCHEMA)

try:
    document = app.activeDocument
    say("document:", document.name)
    cam = document.products.itemByProductType("CAMProductType")
    say("has Manufacture data:", cam is not None)
    if cam is not None:
        say("setups:", cam.setups.count)
except Exception as exc:
    say("no document:", exc)

allowed, refusal = guard.may_write(app)
say("a writing job would be:", "allowed" if allowed else "refused - " + refusal)

answer = {"fusion": app.version, "utp": version.VERSION,
          "schema": config.SCHEMA, "writing allowed": allowed}
