# Is the edit listener still attached, and does it survive a collection?
#
#     python tools/ask_fusion.py tests/jobs/listener-alive.py --writes
#
# This is the test that should have existed. The edit listener subscribed
# through a CAMEventManager held in a local, so the manager was collected when
# arm() returned and the subscription went with it. The handler object survived,
# five handlers were listed as attached, "listening" was in the log, and nothing
# fired. From the shop floor: change a feed, and the note does not move.
#
# Three reviews read arm() and none asked whether the subscription outlives the
# function. Twenty-four unit tests could not: they are pure functions over
# dicts, and this was never a decision. What catches it is poking the live thing
# and insisting it answers -- and then forcing a garbage collection and
# insisting again, because "works at first and stops later" was the whole shape
# of the fault.
#
# Needs a document with at least one operation open. Writes to one note and puts
# it back.

import gc

from utp import events, passes

cam = app.activeDocument.products.itemByProductType("CAMProductType")
ops, _shape = passes._walk(cam)
if not ops:
    raise SystemExit("no operations in this document to poke")
op = ops[0]
held = op.notes


def fired_by(poke, label):
    """Poke the operation and say whether the listener noticed."""
    before = events.calls()["edits"]
    poke()
    for _ in range(40):
        adsk.doEvents()
    after = events.calls()["edits"]
    say("   %-34s edits seen %d -> %d  %s"
        % (label, before, after, "FIRED" if after > before else "NOTHING"))
    return after > before


def write_a_note():
    op.notes = "listener probe"


def change_a_feed():
    found = op.parameters.itemByName("tool_feedCutting")
    if found is not None:
        found.value.value = found.value.value + 13.0


say("the listener, as things stand:")
first = fired_by(write_a_note, "writing to .notes")
feed = fired_by(change_a_feed, "changing a feed")

# The fault, exactly: everything above can pass and the subscription still be
# one collection away from gone.
say("")
say("after forcing a garbage collection:")
gc.collect()
gc.collect()
survived = fired_by(write_a_note, "writing to .notes")

op.notes = held
for _ in range(20):
    adsk.doEvents()

say("")
say("what is being kept alive for it:", sorted(events._held.keys()) or "NOTHING")
say("handlers attached:", len(events._handlers))
say("every listener's count:", events.calls())

verdict = "PASS" if (first and survived) else "FAIL"
say("")
say("%s - the edit listener %s" % (verdict,
    "fires and survives collection" if verdict == "PASS"
    else "is not answering; notes will not move as somebody edits"))
if first and not feed:
    say("NOTE: a note write fires it and a feed change does not, so the event "
        "is raised for some changes and not others. What the add-in promises "
        "about editing an operation depends on which.")
answer = {"verdict": verdict, "note write fired": first,
          "feed change fired": feed, "survived collection": survived,
          "kept alive": sorted(events._held.keys()),
          "counts": events.calls()}
