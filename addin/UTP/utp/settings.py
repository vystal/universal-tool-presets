"""What this install is allowed to do, decided by the person using it.

The switches in config.py are the defaults: what a fresh install does before
anybody has said otherwise. This module holds what somebody has said since,
in a small JSON file next to the reports, and every switch that is a person's
business to change is read through here rather than from config directly.

Six controls, not sixteen. config.py has more switches than this and most of
them are not a decision anybody in a shop should have to make: they are notes
to whoever is working on the add-in. These six are the ones somebody has a
real reason to want: whether it runs at all, when it runs on its own, and
which of the two kinds of writing it may do.

Per machine, not per document. "I do not want this running on my machine" is
about the machine; a setting that travelled inside a file would mean a job
behaving differently depending on who opened it last.
"""

import json
import os

from . import config


# key, what the dialog calls it, which group it sits in, and where its
# default comes from in config. The order is the order they are shown.
CONTROLS = (
    ("on", "Universal Tool Presets is on", None, None),

    ("save", "Check when I save a document", "when",
     "MAY_WRITE_ON_EVENTS"),
    ("edit", "Check when I change an operation", "when",
     "MAY_WRITE_ON_EVENTS"),

    ("mark", "Put notes and colours on operations", "what", None),
    ("presets", "Add presets to documents that are missing them", "what",
     "MAY_ADD_PRESETS"),
    ("tidy", "Remove presets that nothing is using", "what",
     "MAY_TIDY_PRESETS"),
)

GROUPS = (("when", "When it runs on its own"),
          ("what", "What it may write"))

# What each one means, for the instructions and the report.
MEANS = {
    "on": "Off, and nothing happens on its own and the buttons that write "
          "say so. Checking without changing anything still works.",
    "save": "Saving a document brings its notes up to date first, so the "
            "notes are part of the save.",
    "edit": "Changing an operation updates that one operation's note at "
            "once, inside your own edit, so one undo takes back both.",
    "mark": "Off, and it reads and reports but writes nothing to your "
            "operations at all, notes, colours and records alike.",
    "presets": "A preset added to a tool at the shop can be picked in a "
               "job that was saved before it existed.",
    "tidy": "Copies the add-in made that no operation points at. Never one "
            "somebody made, and the most recently retired copy is kept.",
}


def default(key):
    """What a fresh install does, from the switches in config."""
    for name, _label, _group, switch in CONTROLS:
        if name == key:
            return True if switch is None else bool(getattr(config, switch))
    return True


_held = {"values": None}


def forget():
    """Read the file again next time. Called at startup and after saving."""
    _held["values"] = None


def values():
    """Every control, as a plain dict of key to True or False."""
    if _held["values"] is None:
        _held["values"] = _read()
    return _held["values"]


def on(key):
    """Whether one thing is switched on.

    Read inside the pass for every operation, so it is a dict lookup after
    the first call rather than a look at the file.
    """
    return values().get(key, default(key))


def _read():
    held = {key: default(key) for key, _l, _g, _s in CONTROLS}
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        for key in held:
            if isinstance(saved.get(key), bool):
                held[key] = saved[key]
    except Exception:
        # No file yet is the usual reason, and a damaged one should not stop
        # the add-in loading: the defaults are a working add-in either way.
        pass
    return held


def save(new):
    """Write what somebody chose. Returns what changed, as lines of text."""
    was = dict(values())
    held = {key: bool(new.get(key, was.get(key, default(key))))
            for key, _l, _g, _s in CONTROLS}
    changed = ["%s: %s" % (label, "on" if held[key] else "off")
               for key, label, _g, _s in CONTROLS if held[key] != was.get(key)]
    os.makedirs(os.path.dirname(config.SETTINGS_FILE), exist_ok=True)
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
        json.dump(held, handle, indent=2, sort_keys=True)
    forget()
    return changed


def summary():
    """Lines for a report, saying which are not at their default."""
    held = values()
    lines = []
    for key, label, _group, _switch in CONTROLS:
        mark = "" if held[key] == default(key) else "   (changed here)"
        lines.append("%s   %s%s" % ("yes" if held[key] else " no", label, mark))
    return lines
