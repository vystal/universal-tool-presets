"""What a document's tool dropdown should hold.

Three things, in this order, and the order is the whole of it:

  bring in presets the document has never seen
  remove copies no operation points at any more
  settle what every surviving copy is called

Names last, because whether a copy carries "(latest)" depends on whether an
older one survives beside it -- which is not known until the removals are
done. Adds first, because a copy being replaced is only spare once its
replacement exists. Both of those were learnt the hard way on 8 October, when
the naming ran before the adds and a pass took two goes to settle.

The one rule never bent: a preset an operation points at is not removed.
Removing it re-points that operation at different values, silently, and there
is no undo after a save. presets_in_use is where that protection comes from,
and it walks the operations itself rather than trusting a caller's verdicts.

Lifted out of passes.py, which is also what let events.py stop reaching into
a private function there: ensure_presets is the public way in.
"""

import adsk.cam

from . import config, presets, settings, state, survey
from .state import BEHIND


def _bring_in_unseen(cam, in_use, report, writing):
    """Bring in UTPs the document has never seen, and drop copies nothing needs.

    Returns True if anything was written, since update() leaves every tool
    reference taken before it stale.

    """
    wrote = False
    shelf = survey.document_tools(cam)
    for seen, (tool_id, library_tool) in enumerate(in_use.items()):
        survey.breathe(seen, 5)
        tool = shelf.get(tool_id)
        if tool is None:
            continue

        absent = presets.missing(tool, library_tool)
        if absent:
            allowed = writing and settings.on("presets")
            names = [presets.plain_name(p.name) for p in absent]
            if not allowed:
                report.note("would bring in presets this document has not seen",
                            tool=library_tool.description, presets=names)
            else:
                for library_preset in absent:
                    if tool is None:
                        break
                    try:
                        done = presets.apply(cam, tool, library_preset,
                                             {"add": library_preset.name})
                        report.note("brought in a preset from the library",
                                    did=done)
                        report.wrote += len(done)
                        wrote = True
                    except Exception:
                        report.failed("could not bring in %s"
                                      % library_preset.name)
                    # Inside the loop. apply() ends in update(), which leaves
                    # every tool reference stale, so this sat after the loop
                    # and the second and later presets on one tool were added
                    # through a dead object -- lost, while the report said
                    # they had been brought in.
                    shelf = survey.document_tools(cam)
                    tool = shelf.get(tool_id)
                if tool is None:
                    continue


    return wrote


def _tidy(cam, in_use, used_ids, report, writing):
    """Drop copies nothing uses. Its own pass, after everything is added.

    It used to run before presets were brought in, and that left a pass
    unable to finish the job: the copy being replaced is only spare once the
    replacement exists, so the tidy saw nothing to do, the add happened after
    it, and the dropdown carried a stale entry -- and a "(previous)" invented
    to name it -- until the next pass. Measured on the bench 8 October.

    Removing a preset is the one destructive thing in here and the whole
    protection is used_ids: the set of presets operations point at. A caller
    working from a slice of the document builds that set from a slice, so a
    preset an operation elsewhere is sitting on would look spare -- which is
    why this only runs on a whole pass.
    """
    wrote = False
    shelf = survey.document_tools(cam)
    for seen, (tool_id, library_tool) in enumerate(in_use.items()):
        survey.breathe(seen, 5)
        tool = shelf.get(tool_id)
        if tool is None:
            continue
        # Removal first, then names. The order is the whole of the new
        # behaviour: once the copy somebody has moved off is gone, the one
        # they moved onto is the only copy of its preset and gets the bare
        # name back. Naming first would leave it as "(latest)" for ever.
        # Removal first, then names, and every one of the reasons not to
        # remove has to fall through to the naming rather than skip it.
        #
        # They did not. "if not spare: continue" sent the commonest case of
        # all -- nothing to tidy, because the copy somebody is on is in use
        # and protected -- straight past the renaming, so a freshly added
        # copy kept the bare name the one beside it already had. Measured on
        # the bench 8 October: two entries, both "P Titanium", while
        # wanted_names was asking for one of them to be "(latest)" the whole
        # time. The decision was right and nothing carried it out.
        spare = presets.removable(tool, library_tool, used_ids)
        allowed = writing and settings.on("tidy")
        if spare and report.failures:
            # Nothing is deleted after a pass that went wrong. The operation
            # walk is defensive, so a collection that threw leaves an
            # operation invisible rather than raising, and an invisible
            # operation's preset is one nothing is protecting.
            report.note("not tidying: something went wrong in this pass",
                        failures=report.failures,
                        would_have_removed=[row[1] for row in spare])
        elif spare and not allowed:
            report.note("would remove copies nothing uses any more",
                        tool=library_tool.description,
                        presets=[row[1] for row in spare],
                        held_back=("tidying is switched off" if writing
                                   else "writing is switched off"),
                        kept="whatever operations point at")
        elif spare:
            try:
                report.note("tidied the document tool library",
                            did=presets.remove(cam, tool, spare))
                report.wrote += len(spare)
                wrote = True
                shelf = survey.document_tools(cam)   # update() invalidated them
                tool = shelf.get(tool_id)
            except Exception:
                report.failed("could not tidy %s" % library_tool.description)

    return wrote


def presets_in_use(cam, report):
    """Which presets the document's operations are actually sitting on.

    Walked from the operations, not taken from the verdicts, because a verdict
    is allowed not to look. state reads an operation's preset through a getattr
    that answers None on an exception, so a preset that could not be read is
    indistinguishable from an operation genuinely on no preset: the verdict
    comes back "the operation is on no preset" with presetId None, and NO
    failure is recorded, because reconcile returned a verdict rather than
    raising. _verdicts' except never fires.

    This set is the tidy's only protection. Built from verdicts, the copy an
    operation was actually running looked spare, and presets.removable would
    hand it over to be deleted -- after which the operation re-points at some
    other preset with its values unchanged, named after a preset it does not
    hold. Its note had been removed in the same pass.

    Walking the operations also covers the whole document rather than whatever
    prefix of it the verdicts reached, which matters because a cancelled pass
    leaves `decided` short and records a note, not a failure.

    Anything unreadable is reported as a failure, which is what stops the tidy.
    """
    ids = set()
    operations, shape = survey.walk(cam)
    if shape.get("could not be read"):
        report.failed("could not read %d thing(s) in the operation tree, so "
                      "what the operations are using is not fully known"
                      % shape["could not be read"])
    for operation in operations:
        try:
            preset = operation.toolPreset
        except Exception as exc:
            # Said, not swallowed. This is the read whose silence was the
            # whole fault.
            report.failed("could not read the preset an operation is on (%s), "
                          "so nothing is safe to remove" % exc)
            continue
        if preset is None:
            continue
        try:
            ids.add(preset.id)
        except Exception as exc:
            report.failed("could not read a preset's id (%s), so nothing is "
                          "safe to remove" % exc)
    return ids


def _name_copies(cam, in_use, used_ids, report, writing):
    """Settle what every copy is called, once nothing else will move.

    Its own pass, at the very end, because naming depends on what the dropdown
    finally holds: whether a copy is the only one of its preset decides
    whether it carries (latest) at all. It used to sit inside the function that brings in unseen presets,
    which runs BEFORE presets are added, so a copy added in a pass could not
    be named until the next one -- measured on the bench, two passes to settle
    where one should do.
    """
    wrote = False
    shelf = survey.document_tools(cam)
    for tool_id, library_tool in in_use.items():
        tool = shelf.get(tool_id)
        if tool is None:
            continue
        renames = presets.wanted_names(tool, library_tool, used_ids)
        if not renames:
            continue
        if not writing:
            report.note("would rename copies",
                        did=["%s to %s" % (p.name, w) for p, w in renames])
            continue
        try:
            report.note("named the copies",
                        did=presets.rename(cam, tool, renames))
            wrote = True
            shelf = survey.document_tools(cam)   # update() invalidated them
        except Exception:
            report.failed("could not rename copies on %s"
                          % library_tool.description)
    return wrote


def ensure_presets(cam, decided, tools, report, writing):
    """Make the newer values pickable for every behind operation.

    Returns True if anything was written, since the caller must then re-read
    the operations: update() leaves the references it was given stale.

    One preset per library preset, not per operation. Six operations sharing a
    tool need one new entry in the dropdown between them, not six.
    """
    wanted = {}
    # Which presets operations actually sit on, and which tools this document
    # uses. Both are needed before anything can be removed: a preset an
    # operation points at must never go.
    # From the operations themselves. See presets_in_use.
    used_ids = presets_in_use(cam, report)
    in_use = {}
    for operation, verdict in decided:
        found = verdict.get("toolId")
        # The library by its own id, the document shelf by the document's.
        # One value was doing both jobs and they are only the same value when
        # the match was exact.
        in_library = verdict.get("libraryToolId") or found
        library_tool = tools.get(in_library) if in_library else None
        if library_tool is not None:
            in_use[found] = library_tool
        if verdict["state"] != state.BEHIND:
            continue
        if library_tool is None:
            continue
        # By the library preset the verdict resolved, not by the id of the
        # preset the operation sits on. Once an operation is on a copy the
        # add-in made, that id is the copy's own and the library has never
        # heard of it, so newer versions would silently stop being offered.
        library_preset = library_tool.presets.get(verdict["libraryPresetId"])
        if library_preset is None:
            continue
        # Tools are remembered by id, not by reference: the first update()
        # below invalidates every tool object gathered here.
        wanted.setdefault(library_preset.id, (found, library_preset))

    wrote = _bring_in_unseen(cam, in_use, report, writing)

    # "if not wanted: return" used to sit here, and it skipped the tidy and the
    # naming below for the one case they exist to handle. Nothing is "wanted"
    # precisely when every operation is already up to date -- which is what
    # somebody moving onto the newer preset has just made true -- so the copy
    # they moved OFF stayed in the dropdown for ever and the newer one kept
    # its (latest) marker. Measured on the bench, 8 October, with removable()
    # naming the spare copy on every pass and nothing asking it.
    allowed = writing and settings.on("presets")
    shelf = survey.document_tools(cam)
    for tool_id, library_preset in wanted.values():
        tool = shelf.get(tool_id)
        if tool is None:
            report.failed("the tool for %s is no longer in the document"
                          % library_preset.name)
            continue
        intended = presets.plan(tool, library_preset)
        if not intended:
            report.note("the newer values are already pickable",
                        preset=presets.plain_name(library_preset.name))
            continue
        if not allowed:
            report.note("would add a preset to the document", plan=intended,
                        preset=presets.plain_name(library_preset.name),
                        held_back=("adding presets is switched off"
                                   if writing else "writing is switched off"))
            continue
        try:
            done = presets.apply(cam, tool, library_preset, intended)
            # The plan as well as what was done. plan() says which values made
            # the existing copy stale, and that was reported on the dry run
            # and thrown away here — which is the one path where it matters,
            # because a copy that is stale again on the next pass means a new
            # one is added every time and only this field says why.
            report.note("added to the document tool library", did=done,
                        plan=intended)
            report.wrote += len(done)
            shelf = survey.document_tools(cam)   # update() invalidated them
            wrote = True
        except Exception:
            report.failed("could not add a preset for %s" % library_preset.name)
    # Always, on every path. These used to be held back for a caller that had
    # looked at only part of the document, because used_ids was once built
    # from the verdicts that caller had -- a slice -- so a preset an operation
    # elsewhere was sitting on could look spare. It is read from a full walk
    # of every operation now (see presets_in_use), so the protection is
    # complete however little of the document the caller swept, and holding
    # them back only meant an edit never finished its own tidying up.
    wrote = _tidy(cam, in_use, used_ids, report, writing) or wrote
    wrote = _name_copies(cam, in_use, used_ids, report, writing) or wrote
    return wrote
