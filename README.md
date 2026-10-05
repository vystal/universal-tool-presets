# Universal Tool Presets

A Fusion add-in that keeps operations honest about the shop's tool presets.

Fusion copies a tool into a document when an operation uses it. Change the
feeds in the shop library afterwards and nothing already in a document hears
about it, so a preset fixed once has to be fixed again in every file that used
it. This marks each operation with where it stands, and lets somebody bring
one up to date by picking the newer preset from the dropdown they already use.

Nothing is imposed. There is no panel, no dialog and no nagging: an operation
either carries a note or it does not.

## What an operation's note says

| Note | Icon | Means |
| --- | --- | --- |
| ``UTP Titanium v3`` | green | on the newest version |
| ``UTP Titanium v2 - v3 available`` | yellow | a newer version exists |
| ``UTP Custom`` | grey | it was on a UTP and its values have since been changed |
| none | none | never on a UTP, or its tool is not in a shop library |

Files that predate the system stay silent. An operation joins when somebody
puts it on a UTP preset, which is why turning this on changes nothing until
people start using it.

For the people who will see these notes without knowing any of this exists,
there is a page written for them: [what the notes
mean](docs/what-the-notes-mean.md).

## Installing

Copy `addin/loader/UTP` into Fusion's add-ins folder:

```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
```

Once per machine. The loader fetches the add-in itself from the latest
release and keeps it up to date, so updating the shop means publishing a
release rather than visiting every computer.

It always runs from a local cache, so a machine with no connection runs the
copy it already has. Updates take effect at the next Fusion start.

## Releasing

```
python tools/package.py
```

Writes `dist/utp.zip` and `dist/VERSION`. Publish a GitHub release with both
as assets; the loader reads `releases/latest/download/`, so that is what puts
it in service. The version comes from `addin/UTP/utp/version.py` and nowhere
else.

GitHub serves release assets through a cache, measured at around a minute and
a half, so a machine starting Fusion immediately after a release may not see
it until the next restart. The loader records the version it reads out of the
downloaded code rather than the one the `VERSION` file claimed, so a machine
never reports running something it is not.

**The loader itself does not update this way**, being the thing that does the
updating. A change to `addin/loader/UTP/UTP.py` has to be copied to each
machine by hand, which is why it is kept small and boring.

Raise `SCHEMA` in `addin/UTP/utp/config.py` when the meaning of anything
written changes — a note's wording, a preset naming convention, what an
attribute means. An add-in that meets data written by a higher schema than it
understands stops writing and says so, rather than fighting a version whose
rules it does not have. That is what keeps a half-updated shop from corrupting
its own files.

## Working on it

Run the add-in straight from the repo: add `addin/UTP` through **Utilities →
Add-Ins → the green +**. An edit then needs one Stop/Run.

To exercise the loader as well, point it at the build folder instead of
GitHub by putting this in `addin/loader/UTP/source.json`:

```json
{ "base": "file:///C:/path/to/repo/dist", "asset": "utp.zip" }
```

Then `python tools/package.py` and restart the add-in. Everything the loader
does on a shop machine — fetch, unpack, check, swap, import — happens the
same way, so the release path is used daily rather than trusted once.

Install either the repo copy or the loader on a given machine, not both: they
register the same command and would fight over the button.

## Changing what it says

Everything a person sees in Fusion is in `addin/UTP/utp/config.py`: what a
note says, its colour, how a version is written, what the presets in a
dropdown are called, every dialog message, and every switch. Nothing in that
file is a decision — what counts as behind, current or custom is settled by
comparing values, whatever the wording says.

The prose in the reports and the session log is deliberately not there. It
explains what happened to whoever reads a report when something looks odd,
and it lives beside the code that produces it.

If you change `NOTE_PREFIX`, raise `SCHEMA` as well: it is how the add-in
recognises its own line in a note somebody has also written in, and files
already carrying the old prefix would have those lines treated as a person's
text and left alone.

## Taking it back out

**Remove all notes** takes every note, colour and record out of a document.
It asks first, lands as one undo step, and leaves presets alone — an
operation may be sitting on one it added, and removing that would re-point
the operation at another preset without changing its values.

It also sets a flag on the document saying leave this one alone, so saving
and editing do not put the marks straight back. Without that the way out was
not a way out: the next save re-marked everything, because an operation whose
values match the library is adopted on sight. **Check this document** clears
the flag, since pressing it is asking for the marks.

**Clearing the text of a single note keeps it gone**, for that operation
only. Clearing a note is itself an operation change, so it raised the same
event as any other edit and the line was written back within milliseconds of
being deleted: there was no way to be rid of one. The record now carries a
note saying this one was declined, every pass honours it, and pressing
**Check this document** clears it because that is asking for the notes.

Only the edit handler may decide a note was declined, because that is the one
that runs inside somebody's own edit. A pass over a whole document also finds
operations with a record and no note, for every other reason a note can go
missing, and treating those as declined would quietly stop marking them.

## Switches

All in `addin/UTP/utp/config.py`.

| Switch | Does |
| --- | --- |
| `MAY_WRITE_ON_DEMAND` | the button may mark the document it is pressed in |
| `MAY_WRITE_ON_EVENTS` | edits and saves keep a document up to date |
| `MAY_ADD_PRESETS` | newer versions may be added to a document's tool library |
| `MAY_BUMP_LIBRARY_VERSIONS` | version numbers may be written to the Hub libraries. Not in the Switches dialog, so the only way to turn it off is editing config.py on each machine |
| `MAY_TIDY_PRESETS` | copies nothing uses any more may be removed |
| `ONLY_DOCUMENTS_ALREADY_MARKED` | a rollout guard: events only touch documents the button has been pressed in |
| `SHOW_PROGRESS` | show a progress bar with a cancel button while the button's pass runs |

`SHOW_PROGRESS` is off because Fusion's only on-screen progress is a dialog,
and a dialog blocks working in Fusion while it is up. With it off, progress
goes to the session log every twenty operations instead, which gets in
nobody's way but has to be looked at to be seen. Turn it on if you would
rather watch a bar, or want a cancel button on a very large file.

All of them are on, and `ONLY_DOCUMENTS_ALREADY_MARKED` is off, which is the
ordinary working state. They were turned on one at a time, reading the report
in between: with any of them off the add-in still works out and records
exactly what it would have done, which is how to introduce this somewhere
new or to look into something without changing anything.

## Where it writes

Reports and a per-session event log go to `Documents\UTP diagnostics`, written
line by line as things happen so a crash still leaves evidence behind.
