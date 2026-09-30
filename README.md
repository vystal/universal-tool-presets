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
| `[UTP] Titanium v3` | green | on the newest version |
| `[UTP] Titanium v2 · v3 available` | yellow | a newer version exists |
| `[UTP] Custom` | grey | it was on a UTP and its values have since been changed |
| none | none | never on a UTP, or its tool is not in a shop library |

Files that predate the system stay silent. An operation joins when somebody
puts it on a UTP preset, which is why turning this on changes nothing until
people start using it.

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

## Switches

All in `addin/UTP/utp/config.py`.

| Switch | Does |
| --- | --- |
| `MAY_WRITE_ON_DEMAND` | the button may mark the document it is pressed in |
| `MAY_WRITE_ON_EVENTS` | edits and saves keep a document up to date |
| `MAY_ADD_PRESETS` | newer versions may be added to a document's tool library |
| `MAY_BUMP_LIBRARY_VERSIONS` | version numbers may be written to the Hub libraries |
| `ONLY_DOCUMENTS_ALREADY_MARKED` | a rollout guard: events only touch documents the button has been pressed in |

Every one of them starts off. Turn them on in that order, reading the report
each time: with writing off the add-in still works out and records exactly
what it would have done.

## Where it writes

Reports and a per-session event log go to `Documents\UTP diagnostics`, written
line by line as things happen so a crash still leaves evidence behind.
