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
import tempfile

from . import config


# key, what the dialog calls it, which group it sits in, and where its
# default comes from in config. The order is the order they are shown.
#
# The labels are short on purpose. Fusion puts a checkbox's name in the label
# column on the left and the box itself on the right, so a long label leaves
# the box stranded at the far side of the dialog with nothing beside it. The
# group heading carries the context and the tooltip carries the detail, which
# leaves two or three words to say which one this is.
CONTROLS = (
    ("on", "Add-in is on", None, None),

    ("save", "When I save", "when", "MAY_WRITE_ON_EVENTS"),
    ("edit", "When I edit", "when", "MAY_WRITE_ON_EVENTS"),

    ("mark", "Notes and colours", "what", None),
    ("presets", "Add presets", "what", "MAY_ADD_PRESETS"),
    ("tidy", "Remove unused presets", "what", "MAY_TIDY_PRESETS"),
)

GROUPS = (("when", "When it checks on its own"),
          ("what", "What it may write"))

# The tooltip on each box. These carry what the labels no longer have room
# for, so each one has to make sense on its own.
MEANS = {
    "on": "Universal Tool Presets itself. Off, and nothing happens on its "
          "own and the buttons that change things say so instead of doing "
          "it. Checking without changing anything still works, and so does "
          "Remove all notes.",
    "save": "Saving a document brings the whole document's notes up to date "
            "first, so they are part of that save rather than left over "
            "after it.",
    "edit": "Changing an operation updates that one operation's note "
            "straight away, inside your own edit, so one undo takes back "
            "both.",
    "mark": "The notes and icon colours on your operations and setups. Off, "
            "and it reads and reports but writes nothing to them at all, "
            "down to the hidden record of which preset they came from.",
    "presets": "Presets a tool has in the shop library that this document "
               "has never seen, so one added at the shop can be picked in a "
               "job that was saved before it existed.",
    "tidy": "Copies the add-in made that no operation points at any more. "
            "Never a preset somebody made, and the most recently retired "
            "copy is kept.",
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


damaged = {"file": False}


def _read():
    held = {key: default(key) for key, _l, _g, _s in CONTROLS}
    damaged["file"] = False
    if not os.path.exists(config.SETTINGS_FILE):
        # Nobody has chosen anything yet. The defaults are what a fresh
        # install does, which is everything on.
        return held
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if not isinstance(saved, dict):
            raise ValueError("not a set of switches")
        for key in held:
            if key not in saved:
                # A switch this version has and the file does not, because
                # the file was written by an older one. Its default stands.
                continue
            if not isinstance(saved[key], bool):
                # Something is there and it is not true or false. 0 probably
                # means off and "false" certainly does, but guessing which
                # way somebody meant a switch that governs writing to their
                # jobs is not a thing to be clever about.
                raise ValueError("%s is not true or false" % key)
            held[key] = saved[key]
        return held
    except Exception:
        # There is a file, so somebody chose something, and we cannot read
        # what. Falling back to the defaults would turn everything back on,
        # which is the one direction that must not happen by accident: the
        # person who switched this off is the person it must stay off for.
        # So nothing happens until they say otherwise, and the add-in says
        # why rather than looking broken.
        damaged["file"] = True
        return {key: False for key, _l, _g, _s in CONTROLS}


def save(new):
    """Write what somebody chose. Returns what changed, as lines of text."""
    was = dict(values())
    held = {key: bool(new.get(key, was.get(key, default(key))))
            for key, _l, _g, _s in CONTROLS}
    changed = ["%s: %s" % (label, "on" if held[key] else "off")
               for key, label, _g, _s in CONTROLS if held[key] != was.get(key)]
    folder = os.path.dirname(config.SETTINGS_FILE)
    os.makedirs(folder, exist_ok=True)
    # Written beside the real file and moved into place, so a crash or a full
    # disk leaves the old switches rather than half a line of JSON. The old
    # way could produce exactly the damaged file read() now has to refuse,
    # and this folder sits under Documents, which in a lot of shops is being
    # synced to the cloud underneath us.
    handle, temporary = tempfile.mkstemp(dir=folder, suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(held, out, indent=2, sort_keys=True)
        os.replace(temporary, config.SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(temporary)
        except Exception:
            pass
        raise
    forget()
    return changed


def summary():
    """Lines for a report, saying which are not at their default."""
    held = values()
    lines = []
    if damaged["file"]:
        lines.append("THE SWITCHES FILE COULD NOT BE READ, so everything is "
                     "off until it is set again: " + config.SETTINGS_FILE)
    for key, label, _group, _switch in CONTROLS:
        mark = "" if held[key] == default(key) else "   (changed here)"
        lines.append("%s   %s%s" % ("yes" if held[key] else " no", label, mark))
    return lines
