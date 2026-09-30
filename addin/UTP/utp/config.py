"""Names, keys and switches. No logic lives here.

Everything that might need changing without reading any other file is in
this module, so none of it ends up buried in a decision somewhere.
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
SCHEMA = 1

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

# A rollout guard, not part of the design. Edits and saves only write to a
# document the button has already been pressed in, so opening a real job and
# saving it cannot quietly mark it. Turn this off once the system is in
# ordinary use, when a save should bring any document up to date.
ONLY_DOCUMENTS_ALREADY_MARKED = True

# Adding presets to a document's tool library. A bigger write than a note:
# presets are what operations read their feeds from. Off until the reports
# from real files say the additions are right.
MAY_ADD_PRESETS = True
MAY_BUMP_LIBRARY_VERSIONS = False

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

# ---------------------------------------------------------------------------
# Where the report goes
# ---------------------------------------------------------------------------

REPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "UTP diagnostics")

# ---------------------------------------------------------------------------
# What a note says
# ---------------------------------------------------------------------------

# The add-in owns the first line of a note; this is how it knows which line.
NOTE_PREFIX = "[UTP] "
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

# ---------------------------------------------------------------------------
# The button
# ---------------------------------------------------------------------------

COMMAND_ID = "UTPCheckDocument"
COMMAND_NAME = "UTP: check this document"
COMMAND_TOOLTIP = ("Works out what the UTP add-in would say about every "
                   "operation here, and writes it to a file. Changes nothing.")

# Whichever of these panels exists on this build gets the button. Panel ids
# move between Fusion releases, so this is a list rather than a guess.
CANDIDATE_PANELS = [
    ("CAMEnvironment", "CAMManagePanel"),
    ("CAMEnvironment", "CAMUtilitiesPanel"),
    ("CAMEnvironment", "CAMActionPanel"),
    ("FusionSolidEnvironment", "SolidScriptsAddinsPanel"),
]
