"""Names, keys, wording and switches. No logic lives here.

Everything a person sees in Fusion is in this file: what a note says, what
colour it is, how a version is written, what the presets in a dropdown are
called, every dialog message, and every switch. Change any of it here and
nowhere else.

What is deliberately not here is the prose in the reports and the session
log, the "could not read library" and "the newer values are already
pickable" lines. Those explain what happened to whoever reads a report when
something looks wrong, and they live beside the code that produces them,
because hoisting sixty of them into this file would make both harder to
read. Nothing in the reports is seen in the course of ordinary work.

Nothing in this file is a decision either. What counts as behind, current or
custom is settled by comparing values, whatever the wording says.
"""

import os

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

# Attribute group. People never see this in Fusion, so it cannot be broken by
# accident. Phase 1 only reads these; it writes nothing anywhere.
ATTRIBUTE_GROUP = "UTP"

# Keys inside that group. Both live on the operation, in the document.
# Measured on real files: a document tool keeps its library tool's id and a
# document preset keeps its library preset's id, so identity needs nothing
# stored. utpId, sourceTool and a per-document version were all dropped once
# that was known.
# One attribute holding the whole record, because every write to a CAM
# operation costs about 120 milliseconds whatever it is: measured, 49 writes
# took 5.9 seconds. Three attributes were three writes where one does.
KEY_RECORD = "record"

# Schema 1 wrote these three separately. Still read, never written.
KEY_ADOPTED_PRESET = "adoptedPreset"
KEY_OPERATION_ID = "operationId"

# On a preset the add-in creates inside a document, holding the id of the
# library preset it was copied from. presets.add() gives a fresh id, so
# without this a copy cannot be tied back to the library at all.
KEY_SOURCE_PRESET = "sourcePreset"

# What every write is stamped with. Raise it when the meaning of anything
# written changes: a note's wording, a preset naming convention, the meaning
# of an attribute. An add-in that meets a higher number than this stops
# writing rather than fighting a version whose rules it does not have.
KEY_SCHEMA = "schema"

# 2: the record became one attribute instead of three. Schema 1 files are
# still read, and rewritten to the new shape when an operation is next
# marked.
SCHEMA = 2

# On a library preset. A label, never a decision: what is behind and what is
# current is settled by comparing values, with or without these.
KEY_VERSION = "version"
KEY_VALUES = "values"

# ---------------------------------------------------------------------------
# What may be written
# ---------------------------------------------------------------------------

# Phase 1 changes nothing at all. Both of these stay False until the
# diagnostics from real files say the decisions are right.
MAY_WRITE_ON_DEMAND = True      # the button: one document, one deliberate press
MAY_WRITE_ON_EVENTS = True      # edits and saves keep a document honest

# Was a rollout guard: edits and saves only wrote to a document the button
# had already been pressed in, so a first deployment could not quietly mark a
# real job. Turned off on 2 October, once three jobs had behaved, because in
# ordinary use a save should bring any document up to date without somebody
# having to remember to press anything. Set it back to True to make the
# add-in wait for a deliberate press in each document again.
ONLY_DOCUMENTS_ALREADY_MARKED = False

# Adding presets to a document's tool library. A bigger write than a note:
# presets are what operations read their feeds from. Off until the reports
# from real files say the additions are right.
MAY_ADD_PRESETS = True

# Bring in presets a tool has in the library but this document has never
# seen, so a UTP added at the shop can be picked in an existing job without
# re-selecting the tool.
MAY_SYNC_PRESETS = True

# Remove copies the add-in made that nothing uses any more. The only thing
# here that deletes anything, so it is narrow: never a preset an operation
# points at, never one somebody made or that arrived with the tool, and the
# most recently retired copy is kept because the library holds only today's
# values and that copy is the last record of what an operation used to run.
MAY_TIDY_PRESETS = True
MAY_BUMP_LIBRARY_VERSIONS = True

# Listen to operation edits and saves. Still writes nothing while the switch
# above is off; it records what it would have done to the session log.
LISTEN_TO_EVENTS = True

# ---------------------------------------------------------------------------
# Where UTPs live
# ---------------------------------------------------------------------------

# Only Hub libraries hold UTPs. Local libraries are somebody's own business:
# a tool from one reads as "not a UTP tool" and is left alone.
LIBRARY_LOCATION = "hub"

# ---------------------------------------------------------------------------
# Comparing values
# ---------------------------------------------------------------------------

# Fusion recomputes linked values and they do not come back bit for bit, so
# floats are compared with a little room.
TOLERANCE = 1e-6

# Parameters holding geometry or view references hand back a new object on
# every read, so they always look changed. Only plain values are compared,
# which is what this filter means in practice.
COMPARABLE_TYPES = (int, float, str, bool)

# ---------------------------------------------------------------------------
# Staying responsive
# ---------------------------------------------------------------------------

# Fusion can be pushed into "not responding" by a burst of API calls, so the
# pass gives it a breath every this many operations.
OPERATIONS_PER_CHUNK = 20

# Show a progress bar while the button's pass runs, with a cancel button.
#
# Off, because Fusion has no out-of-the-way way to show progress: a dialog
# sits on top of everything and takes focus, and a palette is a panel
# appearing uninvited. "It blocks either way" was used to argue for the
# dialog and it does not hold up: blocking you can see is still in the way.
#
# So the answer is a pass quick enough not to need one. Progress goes to the
# session log every twenty operations meanwhile, which gets in nobody's way
# but has to be looked at. Turn this on for a bar with a cancel button when
# a particular file is worth waiting on.
SHOW_PROGRESS = False

# Below this many operations a pass is quick enough that a progress bar is
# only a flicker, so it is not shown even when the switch is on.
PROGRESS_FROM = 40
PROGRESS_MESSAGE = "Checking operation %v of %m"
PROGRESS_MARKING = "Marking operation %v of %m"

# ---------------------------------------------------------------------------
# Where the report goes
# ---------------------------------------------------------------------------

REPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "UTP diagnostics")

# ---------------------------------------------------------------------------
# What a note says
# ---------------------------------------------------------------------------

# Everything below is wording or colour, and changing any of it changes only
# what people read. Nothing here is a decision: what counts as behind,
# current or custom is settled by comparing values, whatever these say.
#
# One exception worth knowing: NOTE_PREFIX is how the add-in recognises its
# own line in a note somebody else has also written in. Changing it while
# files already carry notes leaves those old lines orphaned, so they would be
# treated as a person's text and kept. Raise SCHEMA above if you change it.

# The add-in owns the first line of a note; this is how it knows which line.
NOTE_PREFIX = "[UTP] "

# How a version is shown wherever one appears: in a note and in the dropdown.
VERSION_LABEL = "%s v%s"
NOTE_SEPARATOR = "·"
NOTE_CUSTOM = "Custom"

# Until version numbers exist there is no "v4" to name, so a behind operation
# says only that there is something newer. Less informative, never wrong.
NOTE_UPDATE = "update available"

# What the newest copy of a preset is called in the dropdown, so the two
# entries can be told apart by somebody who knows nothing about any of this.
LATEST_SUFFIX = "(latest)"

# What a copy is called once something newer exists. The date matters: the
# preset the tool arrived with already holds the plain name, so dropping the
# suffix alone leaves two identical entries in the dropdown.
RETIRED_SUFFIX = "(until %s)"
RETIRED_FORMAT = "%d %b %Y"

# Used only when two copies retire on the same day, which happens if somebody
# adjusts a UTP twice while a job is running.
RETIRED_FORMAT_EXACT = "%d %b %Y %H:%M"

# A setup's note. A collapsed setup hides its operations' icons entirely, so
# without this somebody working with everything folded up sees nothing at all.
# The colour answers "do I need to look in here", the text says what is in it.
# Only "behind" is a task, so only "behind" turns it yellow: custom is
# somebody's decision, and operations that were never on a UTP are counted out
# rather than counted against.
SETUP_BEHIND = "%d of %d need updating"
SETUP_CUSTOM = "%d tracked, %d custom"
SETUP_CLEAN = "%d tracked, up to date"

ICON_FOR_STATE = {
    "current": "Green",
    "behind": "Yellow",
    "custom": "Gray",
}

# Every colour Fusion offers, used to turn a noteIconColor value back into a
# name so an unchanged icon is not reported as a change.
ICON_NAMES = ("Gray", "Red", "Blue", "Green", "Yellow")

# What an unmarked operation shows. Measured: every operation with no note
# reports Gray, so this is the absence of a colour rather than a choice.
ICON_DEFAULT = "Gray"

# ---------------------------------------------------------------------------
# What a dialog says
# ---------------------------------------------------------------------------

DIALOG_TITLE = "UTP"
MARKED = "Marked %d of %d operations."
MARKED_TAIL = "One Ctrl+Z undoes the lot; the document is not saved."
CHECKED = "Checked %d operations. Nothing was changed."
CHECKED_TAIL = ("Writing is off. %d operations would have been marked; the "
                "report says exactly how.")
STOOD_DOWN_TAIL = ("%d operations were still worked out; the report says what "
                   "it found.")
EVENTS_SEEN = "%d events recorded this session:\n%s"
NOTHING_TO_CHECK = "Nothing to check: no Manufacture data here."
NO_LIBRARY = "The Hub library could not be read, so nothing was decided."
STOPPED_EARLY = "The check stopped early; see the report."
FAILED = "UTP could not finish %s.\n\n%s"
NO_PANEL = ("UTP started, but no panel would take the button.\n\n"
            "Run it from Utilities > Add-Ins > Scripts and Add-Ins instead.")

# Shown when a file was written by a newer add-in than this one.
NEWER_ADDIN = ("this file was written by a newer UTP add-in (schema %d, this "
               "one understands %d). It will be read and reported on, but "
               "not changed. Update the add-in on this machine.")

# ---------------------------------------------------------------------------
# The button
# ---------------------------------------------------------------------------

UNMARKED = ("Removed every UTP mark from %d of %d operations and setups.\n\n"
            "One Ctrl+Z puts them back. Presets were left alone, because an "
            "operation may be using one.")
READ_ONLY = "This file is read-only, so nothing was changed."
UNMARK_CONFIRM = ("Remove every UTP note, colour and record from this "
                  "document?\n\nPresets are left alone. One Ctrl+Z puts it "
                  "all back, and the document is not saved.")

# ---------------------------------------------------------------------------
# The buttons
# ---------------------------------------------------------------------------

COMMAND_ID = "UTPCheckDocument"
COMMAND_NAME = "UTP: check this document"
COMMAND_TOOLTIP = ("Works out what the UTP add-in would say about every "
                   "operation here, and writes it to a file. Changes nothing.")

UNMARK_COMMAND_ID = "UTPRemoveMarks"
UNMARK_COMMAND_NAME = "UTP: remove all marks from this document"
UNMARK_COMMAND_TOOLTIP = ("Takes every UTP note, colour and record back out "
                          "of this document. Presets are left alone.")

# Whichever of these panels exists on this build gets the button. Panel ids
# move between Fusion releases, so this is a list rather than a guess.
CANDIDATE_PANELS = [
    ("CAMEnvironment", "CAMManagePanel"),
    ("CAMEnvironment", "CAMUtilitiesPanel"),
    ("CAMEnvironment", "CAMActionPanel"),
    ("FusionSolidEnvironment", "SolidScriptsAddinsPanel"),
]
