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
#
# 3: the add-in's line in a note is encased rather than merely prefixed, so it
# can be recognised wherever it sits. Raised because an older add-in meeting a
# note in the new form would not know the line was its own, and would add a
# second one above it. Standing down is exactly what the number is for. Old
# "[UTP] " lines are still recognised, so a document marked by an earlier
# version is rewritten rather than left with two.
SCHEMA = 3

# Was written on a document by Remove all notes, so a save would not put the
# notes straight back. The wrong answer twice over: a note says where an
# operation stands, so a save working it out again is the add-in doing its
# job, and a hidden flag inside somebody's file is not how an add-in gets
# turned off. The Switches dialog is. Nothing reads this any more, and Remove
# all notes deletes it where it finds one, so the documents that were given
# one get it taken out again.
KEY_LEAVE_ALONE = "leaveAlone"

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

# Adding presets to a document's tool library, and bringing in presets a tool
# has in the shop library that this document has never seen, so a UTP added at
# the shop can be picked in an existing job without re-selecting the tool. A
# bigger write than a note: presets are what operations read their feeds from.
#
# This is only the default now. The switch somebody can actually reach is
# "Add presets" in the Switches dialog, which covers both. MAY_SYNC_PRESETS
# used to sit beside this and was left behind when that happened: nothing read
# it, so turning it off changed nothing, in a file whose header promises one
# place to change things.
MAY_ADD_PRESETS = True

# Remove copies the add-in made that nothing uses any more. The only thing
# here that deletes anything, so it is narrow: never a preset an operation
# points at, never one somebody made or that arrived with the tool, and the
# most recently retired copy is kept because the library holds only today's
# values and that copy is the last record of what an operation used to run.
MAY_TIDY_PRESETS = True
# Only the default now. The switch somebody can reach is "Number the shop
# library" in the Switches dialog.
#
# It needed reaching. It is the one write in here that leaves the person's own
# document: version numbers go into the shop's shared library, and
# updateToolLibrary writes the whole library back from a shelf read earlier in
# the same pass, so two machines overlapping could have the second undo a feed
# change somebody made in between. One machine today, so no race today, but it
# is the only thing here with no undo and the only control for it was editing
# this file on every machine.
#
# Left on, because it has been running for weeks and it is what lets a note say
# "v2, v3 available" rather than just "something newer". Turn it off and the
# notes still say when something is newer; they cannot name which version.
MAY_BUMP_LIBRARY_VERSIONS = True

# Marking happens when the Save command starts, not while the save is under
# way. documentSaving fires once Fusion has already taken its snapshot, so
# notes written there land after it and the document is dirty the moment the
# save finishes: you save, and have to save again. commandStarting fires before
# the command runs, so what is written there is part of the save that follows.
#
# This was a switch, MARK_BEFORE_SAVE, with a second copy of the whole marking
# pass behind it for the False case. It had been True since the day it was
# added, so the copy was unreachable and had already drifted from the one it
# was copied from. Both are gone. documentSaving now does the job that copy
# could not: it fires for every save however Fusion named the command, so it
# can say when one happened that the hook below did not recognise.

# What Fusion calls saving a document. Matched exactly.
#
# It used to be ("save",) as a lowercased substring, on the reasoning that the
# exact ids differ between builds. Asked the running Fusion how many command
# ids contain "save" and the answer was forty, among them AutoSaveFilesCommand,
# SaveAsImageCommand, FusionSaveAsSTLCommand, SaveSketchAsDWG, SaveBOMDataCmd
# and IronSaveAsUserDefault. So exporting an STL, taking a screenshot, writing
# a BOM, or simply leaving Fusion alone until it autosaved each ran a whole
# marking pass over the document: seconds of frozen Fusion at a moment nobody
# asked for, and notes written in the middle of an export.
#
# Every export in Fusion is spelled "Save As something", which is what made a
# substring the wrong tool. These are the two that save the document, and the
# two Save All variants of the shell around it. If a build names them something
# else the saves stop being hooked, which is a quiet failure, so the id is now
# logged on every save and the debug report lists every command id seen.
SAVE_COMMANDS = ("SaveDocumentCommand", "SaveDocumentAsCommand",
                 "ElectronSaveAllCmd", "ElectronSaveAsAllCmd")

# Listen to operation edits and saves. Still writes nothing while the switch
# above is off; it records what it would have done to the session log.
LISTEN_TO_EVENTS = True

# ---------------------------------------------------------------------------
# What counts as a UTP
# ---------------------------------------------------------------------------

# Presets that are not somebody's decision. Fusion gives a tool a preset of its
# own accord, and it is the tool's baseline, not a Universal Tool Preset: the
# whole idea here is a named preset a shop made on purpose, "Titanium T48
# Roughing", not whatever the tool arrived holding.
#
# Measured: 390 tools and 441 presets across the Hub libraries, so nearly every
# preset found was this one. The consequence was notes reading "Default preset
# v1", which tells a machinist nothing, version numbers stamped onto defaults in
# the shared library, and "Default preset v1 (latest)" copies accumulating in
# dropdowns. All three of the presets in this shop that carry a depth of cut are
# this one too.
#
# Matched by name, because there is nothing else to match on: a ToolPreset
# exposes only attributes, id, name and parameters, and Fusion's own is
# indistinguishable in shape from one somebody made. That makes this list
# language-specific, so a Fusion in another language needs its name adding. The
# debug report lists what was found, which is how that gets noticed rather than
# guessed at. Excluding one too many is the safe direction: the add-in goes
# quiet about those operations rather than acting on them.
NOT_A_UTP_NAMES = ("default preset",)


def is_a_utp(name):
    """Whether a preset of this name is somebody's decision."""
    return (name or "").strip().lower() not in NOT_A_UTP_NAMES


# How old a reading of the shop libraries may be before a save takes another,
# in seconds. Half an hour.
#
# They used to be read once per Fusion session, full stop, and machinists leave
# Fusion open for days. So somebody changed a preset at nine, and every
# operation in every job carried a green "running the shop's current feeds"
# note until Fusion was next restarted. That is the precise failure this add-in
# exists to prevent, wearing a green dot that says it did not happen, which is
# worse than no add-in: before it, nobody believed anything.
#
# Only a save takes the new reading, never an edit: an edit must not pay three
# to eight seconds inside somebody's own command, which is the reason the cache
# exists at all. So the cost is one read per half hour of working, on a save,
# and the shop's changes reach a document within half an hour of saving it.
# Set it to 0 to go back to once a session.
LIBRARY_STALE_AFTER = 1800

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

# Writing is a different matter. A marked operation costs two writes at
# about 150 milliseconds each, so breathing every twenty of those would hand
# Fusion back the thread once every six seconds, which is what makes it go
# grey. Reading is cheap enough for twenty; writing is not.
WRITES_PER_CHUNK = 1

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

# How long marking may hold up a save, in seconds.
#
# A save marks the whole document, synchronously, before Fusion starts saving.
# Judging one operation costs about ten milliseconds and marking one costs two
# writes at about a hundred and fifty, so a four hundred operation job is four
# seconds to decide and could be a minute to write. On the one action a person
# performs twenty times a day. A save that hangs is the fastest way to get an
# add-in uninstalled, and nothing capped it.
#
# So a save does what it can in this long and remembers where it stopped, and
# the next save carries on from there. A document converges over a few saves
# instead of freezing on one, and the button still does the whole thing in one
# go because pressing it is asking for that.
#
# Two seconds because a save already takes about that, so the add-in at worst
# doubles something nobody times. Set it to 0 for no limit.
SAVE_SECONDS = 2.0

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

# The switches somebody has changed, kept here rather than hidden away, so
# the folder button reaches it and a machine set up the way the shop wants
# can have this one file copied onto the next one.
SETTINGS_FILE = os.path.join(REPORT_DIR, "UTP switches.json")

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

# The add-in's whole line is encased, opening mark to closing mark:
#
#     `UTP Titanium v2 - v3 available`
#     CHECK Z OFFSET
#
# The encasing is what makes the line recognisable, which is what lets every
# other line in a note be somebody's own words wherever they put them. The
# first version of this owned any line starting with "[UTP] ", which deleted a
# note a person had typed in the same style; the second owned only the first
# line, which still ate one written above.
#
# A backtick because a machinist does not type one. The characters that would
# read more naturally are all taken: an operation's note is emitted into the NC
# as a comment when a post has showNotes on, measured in group X, and there
# ( ) delimit the comment itself, [ ] are macro-B brackets on Fanuc controls,
# # is a macro variable, ; is a comment on Haas and Siemens, and % starts and
# ends a program. Whether a particular control accepts a backtick in a comment
# is worth posting one program to find out.
NOTE_PREFIX = "`UTP "
NOTE_SUFFIX = "`"

# What the add-in used to open its line with. Still recognised as its own, so
# a job marked by an earlier version is rewritten in the new style rather than
# gaining a second line. First line only for this one, which is as far as the
# old shape can be trusted.
NOTE_PREFIX_WAS = "[UTP] "

# How a version is shown wherever one appears: in a note and in the dropdown.
VERSION_LABEL = "%s v%s"

# Plain ASCII, because this goes into the NC as well. A middle dot read nicely
# on screen and arrived at the control as whatever its codepage made of it.
NOTE_SEPARATOR = "-"
NOTE_CUSTOM = "Custom"

# Until version numbers exist there is no "v4" to name, so a behind operation
# says only that there is something newer. Less informative, never wrong.
NOTE_UPDATE = "update available"

# Values a preset can carry that change the shape of the cut rather than the
# rate of it. Measured, not guessed: of 441 presets across the eight Hub
# libraries, three carry tool_stepdown and tool_stepover, and tool_rampAngle is
# in the ordinary fifteen that nearly every preset holds.
#
# This matters because every other surface here says the add-in is about feeds
# and speeds. It is, in that it never writes to an operation. But the remedy it
# tells somebody to use — pick the newer preset — can move a depth of cut, and
# then a toolpath that is not regenerated posts the old shape at the new feeds.
# The file looks ready and is not. So when one of these is what moved, the note
# says so rather than letting it be found at the machine.
SHAPE_PARAMETERS = ("tool_stepdown", "tool_stepover", "tool_rampAngle",
                    "tool_finishingStepdown", "tool_finishingStepover",
                    "tool_threadPitch")

# The ones that decide where the tool goes for the whole path, rather than for
# one entry move. A ramp angle changes the shape of a ramp into the cut; a
# stepdown changes every pass in it.
#
# Two lists because the two warnings have to answer different questions. "This
# update changes the cut" is about a value that moved, and a ramp angle moving
# is worth saying. "This operation is on a preset that sets the cut" is about a
# value merely being present, and tool_rampAngle is in the ordinary fifteen that
# nearly every preset holds -- so the standing warning landed on every tracked
# operation in the shop, which is noise, and noise is how a warning stops being
# read. Measured: with rampAngle in it, 4 of 4 tracked operations on the bench
# said "sets the cut"; without, none do.
CUT_DEPTH_PARAMETERS = ("tool_stepdown", "tool_stepover",
                        "tool_finishingStepdown", "tool_finishingStepover",
                        "tool_threadPitch")
NOTE_CHANGES_THE_CUT = "changes the cut"

# And what an operation already on one of those says. Not the same sentence:
# "changes the cut" is about an update that has not happened yet, this is about
# a toolpath that may already be wrong.
#
# It has to be said standing, not once, because the add-in cannot tell a
# regenerated toolpath from a stale one. Measured on 6 October: switching an
# operation's preset moved its feed from 2000 to 700 and left isToolpathValid
# True and operationState 0, so Fusion does not treat a toolpath as stale when
# the values behind it change. There is nothing to read, so there is nothing to
# clear the warning on, so it stays while the operation is on a preset that
# governs the shape of the cut.
#
# Rare by construction: of 441 presets in these libraries three carried a
# stepdown or stepover, and all three were the preset Fusion makes by itself,
# which 0.13.0 stopped treating as a UTP. So this is dormant here until somebody
# puts a depth of cut on a preset they made. That is the right time for it to
# start speaking.
NOTE_SETS_THE_CUT = "sets the cut"

# Said once after a check, rather than relying on somebody reading every note.
REGENERATE_TAIL = ("\n\n%d operation(s) are on presets that set the depth of "
                   "cut or stepover. Regenerate those before posting: picking a "
                   "preset does not rebuild the toolpath, and Fusion does not "
                   "mark it as needing it.")

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

UNMARKED = ("Removed the UTP notes from %d of %d operations and setups.\n\n"
            "One Ctrl+Z puts them back. Presets were left alone, because an "
            "operation may be using one.\n\nSaving or checking this document "
            "works the notes out again. To stop that, turn the add-in off "
            "under Switches.")
READ_ONLY = "This file is read-only, so nothing was changed."
UNMARK_CONFIRM = ("Remove every UTP note and colour from this "
                  "document?\n\nPresets are left alone. One Ctrl+Z puts it "
                  "all back, and the document is not saved.")

# ---------------------------------------------------------------------------
# The buttons
# ---------------------------------------------------------------------------

COMMAND_ID = "UTPCheckDocument"
COMMAND_NAME = "Check this document"
# "Changes nothing" was left on this from when the add-in genuinely changed
# nothing. It is the first button in the panel, it is named the obvious thing,
# it runs without a confirmation, and it writes notes, colours and records to
# every tracked operation, adds presets to this document's tool library, removes
# copies nothing uses, and writes version numbers into the shop's shared
# library. A tooltip promising the opposite of all that is the likeliest way
# somebody comes to grief here.
COMMAND_TOOLTIP = ("Brings this document up to date: notes and colours on every "
                   "operation, and the newer presets added to its dropdowns. "
                   "Writes version numbers to the shop library too, unless you "
                   "turn that off under Switches. One Ctrl+Z takes the document "
                   "side back. Use Check without changing anything to look "
                   "first.")

UNMARK_COMMAND_ID = "UTPRemoveMarks"
UNMARK_COMMAND_NAME = "Remove all notes"
UNMARK_COMMAND_TOOLTIP = ("Takes every UTP note, colour and record back out "
                          "of this document. Presets are left alone.")

DEBUG_WRITTEN = ("Written down everything worth knowing about this machine, "
                 "this document and the libraries. Send this file on.")
DEBUG_FAILED = "The debug report could not be written."

DEBUG_COMMAND_ID = "UTPDebug"
DEBUG_COMMAND_NAME = "Write a debug report"
DEBUG_COMMAND_TOOLTIP = ("Writes down everything worth knowing about this "
                         "machine, this document and the libraries, in one "
                         "file to send on. Changes nothing.")

# Everything lives under one dropdown of its own rather than loose among
# Fusion's buttons.
# A panel of this add-in's own, rather than squeezing into one of Fusion's.
# Put into a dropdown inside somebody else's panel it came out nested in
# their menu, which is not a dropdown of its own.
PANEL_ID = "UTPPanel"
PANEL_NAME = "UTP"

# The tab to put that panel on, matched on id or name containing this.
PREFERRED_TAB = "utilit"

DRY_COMMAND_ID = "UTPCheckOnly"
DRY_COMMAND_NAME = "Check without changing anything"
DRY_COMMAND_TOOLTIP = ("Works out what it would do and writes none of it. "
                       "For looking at a job before letting anything near it.")

REFRESH_COMMAND_ID = "UTPRefresh"
REFRESH_COMMAND_NAME = "Pick up library changes"
REFRESH_COMMAND_TOOLTIP = ("Reads the Hub libraries again. For when somebody "
                           "has changed a preset while Fusion was open.")
REFRESHED = "Read %d tools and %d presets from %d libraries."

FOLDER_COMMAND_ID = "UTPFolder"
FOLDER_COMMAND_NAME = "Open the reports folder"
FOLDER_COMMAND_TOOLTIP = "Opens the folder every report is written to."

SWITCHES_COMMAND_ID = "UTPSwitches"
SWITCHES_COMMAND_NAME = "Switches"
SWITCHES_COMMAND_TOOLTIP = ("Turn the add-in, or any one thing it does, on "
                            "or off.")
SWITCHES_SAVED = "Switches saved.\n\n%s"
SWITCHES_UNCHANGED = "Nothing changed."
SWITCHES_FOOTER = ("These are for this machine, not for the document. They "
                   "stay set until you change them.")
SWITCHES_DAMAGED = ("The saved switches could not be read, so everything "
                    "is off. Set them how you want them and press OK.")

# Said by the buttons that write, when the add-in is switched off. Rather than
# doing nothing and leaving somebody wondering which of the two it was.
IS_OFF = ("Universal Tool Presets is switched off, so nothing was changed."
          "\n\nTurn it on under Switches.")
MARKING_OFF = ("Putting notes on operations is switched off under Switches, "
               "so no notes or colours were written. The report below says "
               "what they would have been.")

HELP_COMMAND_ID = "UTPHelp"
HELP_COMMAND_NAME = "Instructions"
HELP_COMMAND_TOOLTIP = "What the notes mean and what to do about them."

INSTRUCTIONS = """What this does

Your tools' feeds and speeds live in the shop libraries. When somebody
changes them there, documents already made know nothing about it. This marks
each operation with where it stands, so you can see it and update it.

It never changes an operation's feeds. Only you do that, by picking a preset.

If a note says "changes the cut", the newer preset moves a depth of cut or a
stepover and not just a feed. Pick it as usual, then regenerate the operation
before posting.


The notes on your operations

   `UTP Titanium v3`                    green    on the current feeds
   `UTP Titanium v2 - v3 available`     yellow   something newer exists
   `UTP Custom`                         grey     its feeds were changed here
   no note                              never put on a shop preset

To update a yellow one: open the operation, go to the preset dropdown, pick
the one ending (latest). The note turns green. Ctrl+Z puts it back.

If you would rather leave it, leave it. Nothing will chase you.


The note on a setup

A collapsed setup hides its operations, so each setup says what is inside:
"2 of 7 need updating" in yellow, or "7 tracked, up to date" in green. The
count is only of operations being tracked.


When it runs

When you save a document, and when you change an operation. Nothing else:
nothing on opening a file, nothing in the background.


Turning it off

Switches has a checkbox for each of those, and one at the top for the whole
add-in. Off means off: nothing happens on its own, and the buttons that
change things say so instead of doing it.

Those are for your machine, not for the document, and they stay how you set
them.

Clearing a note by hand is not a switch. A note says where an operation
stands, so the next save works it out and writes it again. If you clear one
while you are editing it will stay clear until then. To stop the notes for
good, use Switches.


Things worth knowing

Your own notes are kept. It owns only the line wrapped in ` marks. Write
what you like above or below it, in any words you like, and it stays exactly
as you typed it.
Your own icon colours are kept, and put back if you remove the marks.
Older jobs stay silent. Nothing is marked until somebody uses a shop preset.
Every check writes a report to the reports folder, saying what it found.
If something looks wrong, "Write a debug report" makes a file to send on."""

# Where that dropdown goes, first of these that exists on this build. The
# Utilities tab is wanted; the rest are there so a build that names its
# panels differently still gets the menu somewhere rather than nowhere. The
# debug report lists every panel this Fusion actually has, which is how this
# list gets corrected rather than guessed at again.
CANDIDATE_PANELS = [
    ("CAMEnvironment", "CAMUtilityPanel"),
    ("CAMEnvironment", "CAMUtilitiesPanel"),
    ("CAMEnvironment", "UtilityPanel"),
    ("CAMEnvironment", "CAMManagePanel"),
    ("CAMEnvironment", "CAMActionPanel"),
    ("FusionSolidEnvironment", "SolidScriptsAddinsPanel"),
]
