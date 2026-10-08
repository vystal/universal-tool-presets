# Universal Tool Presets

A Fusion add-in that keeps operations honest about the shop's tool presets.

Fusion copies a tool into a document when an operation uses it. Change the
feeds in the shop library afterwards and nothing already in a document hears
about it, so a preset fixed once has to be fixed again in every file that used
it. This marks each operation with where it stands, and lets somebody bring
one up to date by picking the newer preset from the dropdown they already use.

Nothing is imposed. An operation either carries a note or it does not, and
nothing blocks anybody from posting a job.

## What an operation's note says

| Note | Icon | Means |
| --- | --- | --- |
| ``UTP Titanium`` | green | on the shop's current values |
| ``UTP Titanium - update available`` | yellow | the shop library holds something newer |
| ``UTP Custom`` | grey | it was on a UTP and its values have since been changed |
| none | none | never on a UTP, or its tool is not in a shop library |

Files that predate the system stay silent. An operation joins when somebody
puts it on a UTP preset, which is why turning this on changes nothing until
people start using it.

For the people who will see these notes without knowing any of this exists,
there is a page written for them: [what the notes
mean](docs/what-the-notes-mean.md).

## Installing

On the machine, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/vystal/universal-tool-presets/main/tools/install.ps1 | iex
```

Once per machine, no admin rights, nothing written outside your own Fusion
add-ins folder. Then start Fusion; UTP is in the Milling tab of the
Manufacture workspace, between Setup and 2D.

That installs three small files that never change. They fetch the add-in
itself from the latest release and keep it up to date, so updating the shop
afterwards means publishing a release rather than visiting every computer.
Re-run the same line to pick up a change to the loader, which is the only part
that does not update itself.

It always runs from a local copy, so a machine with no connection runs what it
already has. Updates take effect at the next Fusion start.

By hand instead, if you would rather see what you are installing: copy
`addin/loader/UTP` into

```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
```

Either way you are trusting this repository, which is the same thing you trust
by running the add-in at all: the loader fetches from it on every start.

## Releasing

```
python tools/package.py
```

Writes `dist/utp.zip`, `dist/VERSION` and `dist/SHA256`. Publish a GitHub
release with all three
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

## Testing it

Two suites, because there are two kinds of thing to be wrong.

The decisions run anywhere, in a twentieth of a second, with no Fusion:

```bash
python -m pytest addin/UTP/tests -q
```

What the add-in does *to* Fusion only Fusion can answer for, so that suite runs
inside it, through a small agent add-in that executes jobs on Fusion's main
thread. Install `addin/UTPAgent` the same way as the add-in, open a throwaway
document with `UTP TEST` in its name, and:

```bash
python tools/ask_fusion.py addin/UTP/tests/run_integration.py --writes
```

Twenty-nine checks: the listeners are attached and survive a garbage collection,
an edit is marked whether the library cache is cold or warm, a save marks and
then settles and keeps to its budget, a check settles, a check adds one preset
when the library moves and never a second, removing the notes removes everything
and a check puts it back, a newer schema is refused rather than written over,
somebody's own note text survives, a part-read of the libraries is not kept.

Every one of those is a fault that has actually happened. The decisions were
well tested long before any of this was, and not one of the faults found in the
first days of real use was a decision: they were object lifetimes, which events
fire and when, what is still valid after an update, and what a cache holds.
Run the second suite before releasing anything.

Single questions are quicker than a suite:

```bash
python tools/ask_fusion.py -c 'say(app.version)'
```

## Changing what it says

Everything a person sees in Fusion is in `addin/UTP/utp/config.py`: what a
note says, its colour, what the presets in a dropdown are called, every
dialog message, and every switch. Nothing in that
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

**Clearing the text of a single note keeps it gone**, for that operation
only, until the job is next opened. Clearing a note is itself an operation
change, so it raised the same event as any other edit and the line was written
back within milliseconds of being deleted. The edit handler now remembers the
one note it has just seen cleared and leaves it alone; that memory does not
persist, because a note says where an operation stands and opening a job works
that out again. To stop the notes altogether, use *Switches*.

Only the edit handler may decide a note was declined, because that is the one
that runs inside somebody's own edit. A pass over a whole document also finds
operations with a record and no note, for every other reason a note can go
missing, and treating those as declined would quietly stop marking them.

## Switches

Eight checkboxes under **Switches** in the UTP panel, saved per machine. The
defaults below are what a fresh install does.

| Switch | Does | Default |
| --- | --- | --- |
| Add-in is on | everything else hangs off this | on |
| When I open a job | a job brings itself up to date as it opens | on |
| When I edit | finishing an operation updates that operation | on |
| Notes and colours | the notes and icon colours themselves | on |
| Add presets | newer shop presets are added to the document's dropdowns | on |
| Remove unused presets | copies no operation points at are removed | on |
| Summary when it finishes | the box listing what *Update presets* found | **off** |
| Write a report each time | a report file for every pass | **off** |

Off means off: nothing happens on its own, and the buttons that change things
say so instead of doing it. *Check only* and *Remove all notes* work whatever
the switches say.

Two of them are off by default because the notes on the operations are the
answer: a box to dismiss and a folder filling with reports are both noise once
the thing works. Turn *Write a report each time* on first if something looks
wrong.

**Removing unused presets is the one thing here that cannot be taken back**,
so it is the one switch that never comes back on by itself if the saved file
goes missing. Nothing this add-in does writes outside your own document.

There are also build switches in `addin/UTP/utp/config.py` —
`MAY_WRITE_ON_DEMAND`, `MAY_WRITE_ON_EVENTS`, `LISTEN_TO_EVENTS`,
`SHOW_PROGRESS` and `ONLY_DOCUMENTS_ALREADY_MARKED` — which are defaults and
rollout guards rather than things a person changes. With any of them off the
add-in still works out and records exactly what it would have done, which is
how to introduce this somewhere new or look into something without changing
anything.

## Where it writes

Reports and a per-session event log go to `Documents\UTP diagnostics`, written
line by line as things happen so a crash still leaves evidence behind.
