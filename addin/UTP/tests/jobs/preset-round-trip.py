# Does a value written into a new preset come back out?
#
#     python tools/ask_fusion.py tests/jobs/preset-round-trip.py --writes
#
# This is the question behind the bug in the Atom A49 report: every writing
# Check added another "Default preset v1 (latest)" and the verdicts flipped
# back, which means the copy the add-in makes does not hold what the library
# preset holds. presets.apply reported no failure setting the values, so either
# a write is being accepted and discarded, or it does not survive update().
#
# The one value in play there was tool_coolant, which is a choice rather than a
# number, so it is the first suspect. This checks every value the preset has
# and names the ones that do not come back, reading twice: straight after
# writing, and again after update(), because update() is what makes a change to
# a tool real and it invalidates the tool reference as it goes.
#
# It cleans up the preset it made. Writes only to the document's own tool
# library, never the shop's.

from utp import library, passes, values

PROBE = "UTP agent probe"


class Quiet:
    def note(self, *a, **k): pass
    def failed(self, *a, **k): pass


say("libraries the document's tools come from:", guard.libraries_used(app))

cam = app.activeDocument.products.itemByProductType("CAMProductType")
tools, ok = library.cached(Quiet())
if not ok:
    raise SystemExit("the Hub libraries could not be read")

# A tool in this document whose library twin has a preset to copy. Preferring
# one that has tool_coolant, since that is the suspect.
chosen = None
for key, tool in passes._document_tools(cam).items():
    twin = tools.get(key)
    if twin is None:
        continue
    for preset in twin.presets.values():
        if not preset.values:
            continue
        if chosen is None or "tool_coolant" in preset.values:
            chosen = (key, tool, preset)
        if "tool_coolant" in preset.values:
            break
    if chosen and "tool_coolant" in chosen[2].values:
        break

if chosen is None:
    raise SystemExit("no tool in this document has a library preset to copy")

key, tool, preset = chosen
wanted = dict(preset.values)
say("tool:", tool.description or "?", "| preset:", preset.name,
    "|", len(wanted), "values")

# Written exactly as presets.apply does it, so what is measured is what ships.
fresh = tool.presets.add()
fresh.name = PROBE
refused = {}
absent = []
for name in sorted(wanted):
    parameter = fresh.parameters.itemByName(name)
    if parameter is None:
        absent.append(name)
        continue
    try:
        parameter.value.value = wanted[name]
    except Exception as exc:
        refused[name] = str(exc)

before = values.scalars(fresh)
cam.documentToolLibrary.update(tool, False)

# The tool reference is stale now, so the preset is found again by name.
after = {}
for _key, again in passes._document_tools(cam).items():
    for index in range(again.presets.count):
        copy = again.presets.item(index)
        if copy.name == PROBE:
            after = values.scalars(copy)
            break

def moved(held):
    return {name: [wanted[name], held.get(name, "<not there>")]
            for name in sorted(wanted)
            if name not in held or values.differences({name: wanted[name]},
                                                     {name: held[name]})}

say("parameters the new preset does not have:", absent or "none")
say("writes that raised:", refused or "none")
say("values wrong straight after writing:", list(moved(before)) or "none")
say("values wrong after update():", list(moved(after)) or "none")

answer = {"tool": tool.description, "preset": preset.name,
          "values": len(wanted), "absent": absent, "refused": refused,
          "wrong before update": moved(before),
          "wrong after update": moved(after)}

# Taken back out, so running this twice does not leave the dropdown full of
# probes. Safe to remove: nothing can be pointing at a preset made just now.
for _key, again in passes._document_tools(cam).items():
    for index in reversed(range(again.presets.count)):
        if again.presets.item(index).name == PROBE:
            again.presets.remove(index)
    cam.documentToolLibrary.update(again, False)
say("probe removed")
