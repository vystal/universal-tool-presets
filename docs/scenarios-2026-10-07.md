# UTP — scenarios (archived, 7 October 2026)

> **This is a snapshot, not documentation. Do not read it as a description of
> the add-in as it is now.**
>
> It was written against 0.13.x and extended against 0.28.1. Since then version
> numbers and the stamping of the shop library were removed entirely, setups
> stopped being marked, three commands were renamed or dropped, the progress
> dialog became Fusion's corner busy bar, and the preset naming was rebuilt
> around "(latest)" with no versions in it. Roughly a tenth of the rows below
> describe machinery that no longer exists, and it names deleted modules --
> `versions.review`, `marks.setup_plan`, `passes._mark_setups`,
> `presets.claiming_latest` — as though they were live. Section F is headed
> "The seven switches"; there are eight, and the one it lists last is gone.
>
> It is kept because the *method* earned its keep. Working through every
> situation the add-in can be put in, and writing down what it costs when it
> gets each one wrong, is what found C44 — a Hub library duplicated at the
> shop un-marking every job — which was fixed on 8 October. It also spotted,
> independently, the stale fallback copy of the instructions and the
> contradictory claims about undo, both of which were still true findings a
> day later.
>
> If this is worth having again, regenerate it against the current code rather
> than patching these rows: more than half of them would move.

---

**Vocabulary.** *Wrong green* means an operation reads "nothing to do" while it
is actually out of date — the worst outcome, because it is the exact failure the
add-in exists to prevent and it is invisible. *Wrong blank* means a note
disappears; a missing note is documented as "never put on a shop preset", which
also reads as "nothing to do". *Data loss* means something a person made is gone
and there is no undo. *Noise* means the add-in says too much, or says something
un-actionable; noise ends with notes not being read, which turns into wrong
green later. *Slow* means Fusion pauses or greys out. *Cosmetic* is everything
else.

**How to test.** `unit` — pure logic, runnable with pytest, no Fusion.
`script` — drivable through Fusion's API from a job, i.e. addable to
`addin/UTP/tests/integration.py` or a `tests/utp_test_lib` group. `UI` — needs
someone (or something) clicking in Fusion's interface. `two machines` — needs a
second signed-in Fusion against the same Hub. `not testable` — can only be
reasoned about or watched for in the field.

Coverage names point at `addin/UTP/tests/test_decisions.py` (unit),
`addin/UTP/tests/integration.py` (integration), and the bench groups in
`tests/utp_test_lib/` (groups A–X).

---

## Start here: most dangerous, least covered

Ranked by (how bad if wrong) × (how likely) × (how little exists today).

1. **A settled document is skipped on a change the add-in never saw** (B7, F4,
   D9). The skip in `events.catch_up` is keyed on "swept complete against this
   library reading", not on whether the document has changed since. A new
   operation put on a shop preset, an operation duplicated, or an operation
   edited while the `edit` switch is off all leave the document settled and
   unmarked for up to fifteen minutes — and with `edit` off, until the next
   workspace entry *after* the reading goes stale. Wrong green and wrong blank,
   no coverage.
2. **One tool in two Hub libraries resolves to whichever was read last** (C4).
   `library.read` keys tools by guid into one dict, so the second library's copy
   overwrites the first with nothing reported. If the two carry different feeds,
   an operation can read green against the stale one. Wrong green, no coverage,
   and nothing in the reports would show it.
3. **`presets` off while `mark` is on** (F5). Every yellow note says "pick the
   one ending (latest)" and no such entry exists. People either pick the wrong
   preset from the dropdown or stop believing the notes. Nothing in the code
   notices the combination. Noise leading to wrong green, no coverage.
4. **A preset whose values will not all go into a copy reads yellow for ever**
   (C2). The `short`/`extra` branch in `state.reconcile` makes any parameter
   present on one side only mean BEHIND, while `presets.plan` correctly refuses
   to add another copy — so the operation is permanently "update available" with
   nothing to pick. Un-actionable yellow is how yellow stops being read. Unit
   testable, not covered.
5. **Version stamping on a fresh machine, by default** (G6, E9, F12). A new
   install has every switch on, so the first press of "Check this document"
   writes version numbers into the shop's shared library through
   `updateToolLibrary`, which rewrites the whole library from a snapshot. One
   machine today means no race today; two machines means a feed change can be
   reverted with no undo and nothing saying so. Data loss. The single-process
   half is covered by integration *a library preset that moved mid-pass is not
   written over*; the two-machine half is not covered at all.
6. **The event path never checks whether the file is writable** (D11).
   `passes._writable` is consulted by the button's pass only; `events._may_write`
   does not ask. Opening a read-only job runs a full marking pass whose every
   write fails. Noise and slow, no coverage.
7. **An edit that moves an operation off its record in one dialog visit** (C14).
   `state._record` withholds a record naming a different preset, so picking the
   newer preset *and* changing a feed before the note is rewritten lands on
   NOT_ADOPTED — no note — where it should be grey Custom. Wrong blank, unit
   testable, not covered.
8. **Saving while an automatic pass is running** (D7). The pass goes on writing
   after Fusion has taken its snapshot, which is precisely the double-save the
   add-in was reported for in its first week and which moving marking off the
   save was meant to end. Nothing guards it. Noise, no coverage.
9. **The edit path's undo promise is untrue** (H9). `settings.MEANS["edit"]` and
   the `events` module docstring both say a note written on an edit is part of
   the person's own edit, so one Ctrl+Z takes both. `config.MARKED_TAIL` records
   the measurement that the add-in's writes are not in Fusion's undo stack at
   all, and `config.EDIT_COMMANDS` says the write is now its own step after the
   command ends. Two of the three cannot be right. Cosmetic in effect, corrosive
   to trust; UI-testable, not covered.
10. **A tool whose library guid changed, with a description shared by another
    tool** (C5). `identity.match` calls the description ambiguous and returns no
    match, the verdict is "not a UTP tool", and a yellow note is deleted. Wrong
    blank, script-testable, not covered.

---

## A. Ordinary use — a day in a shop

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| A1 | Fusion starts, a job opens straight into Manufacture | `workspaceActivated` for `CAMEnvironment` reads the libraries (~3.4s), then `catch_up` sweeps for up to 2s; `documentOpened` also fires and finds nothing left to do | script — covered: integration *entering Manufacture reads the libraries*, *an opening pass marks the document and then settles* | slow |
| A2 | A job of 8 operations, 4 on shop presets, is opened | 4 notes and colours, a setup note, and nothing at all on the untracked 4 | script — covered: integration *an opening pass marks the document and then settles* | noise |
| A3 | A yellow note is read, the operation opened, the "(latest)" preset picked, OK pressed | `IronEditOperation` ends, `_mark_what_they_just_edited` runs, the note goes green with the new version | UI (the dropdown pick is not scriptable) — partially covered: integration *a warm cache marks the edit at once* | wrong green |
| A4 | "Check this document" is pressed on a job not opened before | One uncapped pass: notes, colours, records, presets brought in, spare copies tidied, version numbers stamped, a report written | script — covered: integration *a check settles, so a second one writes nothing* | data loss |
| A5 | It is pressed again straight away | Nothing is written; the dialog says 0 of N marked | script — covered: integration *a check settles, so a second one writes nothing* | noise |
| A6 | The job is saved | Nothing is written at all, and the document is clean the moment the save finishes | script — covered: integration *a save writes nothing, so the document does not dirty* | noise |
| A7 | The job is posted | The add-in does nothing. The note may reach the NC as a comment if the post has `showNotes` on | script — covered: group X | cosmetic |
| A8 | The job is closed without saving | Every note written this session is gone, as `MARKED_TAIL` promises | script | cosmetic |
| A9 | It is closed *with* saving, then reopened | Notes, colours and records all survive the round trip | script — covered: groups S and S2 | cosmetic |
| A10 | Several jobs are open and switched between | Each keys separately on its dataFile id, each gets its own budgeted pass, and no document is ever marked on another's behalf | script | wrong green |
| A11 | A job with several setups | Each setup gets a note counting only its own operations, written only after a complete pass | script — covered: integration *setups are marked by a pass, but only a complete one* | noise |
| A12 | Every setup collapsed, so no operation icon is visible | The setup notes are the only signal and have to be right: "2 of 7 need updating" yellow, "7 tracked, up to date" green | script, plus UI to confirm it is visible collapsed — partially covered: integration *setups are marked by a pass, but only a complete one* | wrong green |
| A13 | Operations organised into folders and patterns | `_within` descends into both; nothing is missed; children are counted in their setup's total | script — covered: group O (patterns) | wrong blank |
| A14 | A 400-operation job is opened | ~2s of work, then stop; the cursor is remembered; the next trigger carries on; the document converges over a few triggers | script — covered: integration *a pass keeps to its budget and carries on next time*, *a part-swept document carries on at the next trigger* | slow |
| A15 | A part-swept job's setups are reached | Setup notes are **not** written until a pass goes all the way round: a count from part of a document is a wrong number, not an old one | script — covered: integration *setups are marked by a pass, but only a complete one* | noise |
| A16 | The same job is opened twice in one session with nothing changed | The second open is skipped entirely (`_swept` complete, same reading) | script — covered: integration *a settled document is skipped, so switching workspace costs nothing* | cosmetic |
| A17 | A document with no Manufacture data is opened | `_cam_of` finds nothing, no pass runs, and the button says "Nothing to check" | script | cosmetic |
| A18 | A job where every operation is legacy, never on a shop preset | No notes, no colours, no setup notes, nothing said. Measured at 20 of 27 on a real file | script | noise |
| A19 | One document is worked in all day, editing operations | Each finished edit marks that operation, refreshes a reading older than 15 minutes, and carries the sweep on | script — covered: integration *a stale reading is refreshed without changing workspace* | wrong green |
| A20 | 50 operation edits in a day | One library read per 15 minutes, not one per edit | script — covered: integration *a stale reading is refreshed without changing workspace* | slow |
| A21 | "Check without changing anything" is pressed first | The same pass runs and writes nothing, records included; the report says what it would have done | script | cosmetic |
| A22 | "Pick up library changes" is pressed after a colleague edits a preset | Libraries re-read from scratch, sweeps forgotten, the open job fully re-swept with no budget, a count of changes reported | script | wrong green |
| A23 | "Open the reports folder" | The folder opens and nothing else happens | UI | cosmetic |
| A24 | "Instructions" | An HTML page is written to the reports folder and opened in a browser | UI | cosmetic |
| A25 | "Write a debug report" | One file with machine, document, library and panel detail; nothing changed | script | cosmetic |
| A26 | A tool that carries ten shop presets, in a job that uses one of them | `presets.missing` returns every library preset the document has never seen, for every tool any operation uses, so the first check brings in nine entries nobody asked for — all named "(latest)", one `documentToolLibrary.update` each, and a full shelf rebuild per tool afterwards, which costs a `toJson()` per tool in the document. I think bringing in presets should be limited to tools with a behind operation, or at least counted in the dialog | script (a tool with several shop presets) | noise |
| A27 | A setup is suppressed, or an operation inside one is | Nothing anywhere reads `isSuppressed` or `isActive`, so suppressed work is walked, judged, marked and counted exactly like live work. Defensible — it may be un-suppressed tomorrow — but a job half of whose setups are parked reads as tasks nobody will ever post | script | noise |
| A28 | An operation whose toolpath has never been generated at all | Marked green if its values match its preset. Nothing reads `isToolpathValid` or `operationState`, on purpose (C35 measured that neither moves when preset values do), so green means "the feeds agree with the library" and never "this is ready to post". The instructions page does not say that | script — group T reads toolpath states | cosmetic |
| A29 | A job is copied, by Save As or in the Data Panel | Everything comes across and all of it is still right, because every note, colour and record is derived from the document and the library rather than from anything about the file. The copy has its own dataFile id, so it is swept fresh; a copy taken mid-convergence is half marked and stays that way until its own triggers finish the job | script | cosmetic |
| A30 | A brand-new job is marked, then saved for the first time | `identify` changes its answer from `unsaved:<name>` to the dataFile id, so the sweep record and the cursor from before the save are orphaned and the document is swept again from operation 0. Harmless, and it is the one moment a converged document un-converges without anybody touching it | script | slow |

## B. Triggers, timing and the staleness window

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| B1 | Manufacture is entered and the libraries have never been read | They are read (~3.4s, breathing with `doEvents` so Fusion does not grey), then the document is swept | script — covered: integration *entering Manufacture reads the libraries* | slow |
| B2 | Manufacture is entered with a reading 20 minutes old | It is taken again, and the log says why | script — covered: integration *a stale reading is refreshed without changing workspace* | wrong green |
| B3 | Manufacture is entered with a reading 3 minutes old | Nothing is read; on a settled document nothing happens at all | script — covered: integration *a settled document is skipped, so switching workspace costs nothing* | cosmetic |
| B4 | Design → Manufacture → Design → Manufacture in quick succession | Each entry costs a dict lookup on a settled document: no reading, no pass | script — covered: integration *a settled document is skipped, so switching workspace costs nothing* | slow |
| B5 | A document opens while the libraries have never been read this session | `catch_up` warms first, so the open now *does* pay for the read. The `_DocumentOpened` docstring still says it never reads the libraries, which is no longer true of the path it goes through. Decide which is wanted; the comment is stale either way | script | slow |
| B6 | A preset is changed at the shop at 09:00 and a machinist's reading is from 08:55 | Green notes stay wrong for up to 15 minutes, by design (`LIBRARY_STALE_AFTER`). This is the deliberate bound on wrong green and should be stated to the shop as a number | two machines | wrong green |
| B7 | A document is swept complete, then an operation is **created** on a shop preset | Nothing marks it: `operationBaseChanged` is for edits, `IronEditOperation` is not raised for a create, and the settled-skip stops the next workspace entry from looking. It should be marked; current behaviour is wrong | script (create an operation, pump events, re-enter Manufacture) | wrong blank |
| B8 | A document is swept complete, then an operation is deleted | The setup note's counts are stale until the reading changes. Low harm, but the count is visibly wrong | script | cosmetic |
| B9 | A save happens | Nothing is written. `documentSaving` logs whether the job was ever swept; `documentSaved` logs whether it came out modified | script — covered: integration *a save writes nothing, so the document does not dirty* | noise |
| B10 | A build names its save command something not in `SAVE_COMMANDS` | `documentSaving` still fires and logs "A SAVE THIS BUILD DOES NOT RECOGNISE" with the command ids from the previous three seconds | script (raise an unknown command id, then a save) | cosmetic |
| B11 | Cancel is pressed on an operation dialog | `_mark_what_they_just_edited` runs, finds nothing waiting, and returns before paying for a library read | script — covered in spirit: integration *a cold library cache puts the edit by instead of dropping it* | slow |
| B12 | The first edit of a session, libraries cold | The handler puts the operation by rather than reading the Hub inside the dialog; the read happens as the dialog closes; the operation is then marked | script — covered: integration *a cold library cache puts the edit by instead of dropping it* | wrong blank |
| B13 | An edit with the libraries warm | Marked inside the handler, at once | script — covered: integration *a warm cache marks the edit at once* | wrong green |
| B14 | An edit arrives for a document that is not the active one | `_document_of` walks the operation's own chain first and reports when it fell back to `activeDocument` | script | wrong green |
| B15 | `operationBaseChanged` fires because the add-in itself wrote a note | `marks.busy()`/`holding()` stands the handler down. Measured at 21 self-triggered calls per button press before this existed | script — covered: integration *a check settles, so a second one writes nothing* | noise |
| B16 | A trigger fires while an undo or redo is running | Every path checks `_running["undo"]` and stands down | script — covered: unit *nothing promises an undo that does not happen*, integration *a check's writes are not undoable, which is what the wording says* | data loss |
| B17 | The listener subscription is garbage collected | It must not be: the CAM event manager and the event wrapper are held in `_held`. The old symptom was a handler alive for minutes and then silent | script — covered: integration *the edit listener survives collection* | wrong green |
| B18 | An hour's work in which the edit listener never fires | `events.calls()` reads zero and the debug report must make that obvious; it is the only way to tell a dead listener from a quiet one | script — covered: integration *the edit listener fires* | wrong green |
| B19 | A sweep reaches the end of a document, so the setups are marked | `mark_document` calls `passes._mark_setups(cam, tools, _Quiet(), True)` and does **not** hand it the verdicts it worked out a moment earlier, so every operation in the document is reconciled a second time — outside the budget that has just been spent. On a four hundred operation job that is another second or more after the 2s cap was reached. The button's pass passes `decided` through; this one should too | script (time the trigger that completes a sweep on a large job) | slow |
| B20 | An edit arrives and `_document_of` cannot tell which document it belongs to | `_forget_sweep_of` clears **every** document's sweep rather than one, which is the right direction to be wrong in and is said so in the code. With five jobs open it means all five are re-swept at their next trigger on the strength of one unidentifiable edit | script | slow |
| B21 | An operation is dragged from one setup to another | Its own note stays right, because records key on the operation and never on the setup. Both setups' counts describe where it used to be, and if the move raises no operation event nothing un-settles the document, so neither count is corrected until the reading goes stale and a workspace entry happens | script (move an operation, pump events, re-enter Manufacture) | cosmetic |
| B22 | Somebody reads a job for twenty minutes without touching it | Nothing refreshes. The three triggers are the only heartbeats, so `LIBRARY_STALE_AFTER` bounds how old a reading can be when a note is *written*, not how old the note on screen can be. Those are different numbers and the shop is only ever told the first one | not testable | wrong green |

## C. Wrong, missing and odd data

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| C1 | A library preset holds no readable values | Counted as `valueless`, reported in capitals, and every operation on it is UNKNOWN plus leave-alone, so existing notes stay put | unit — covered: unit *a verdict that cannot compare says so instead of matching*, *an operation is left alone when something could not be established* | wrong green |
| C2 | A preset holds a parameter a document copy will not accept | `presets.apply` records it as missing and the copy still stores the library snapshot, so no new copy is added each pass — **but** `state.reconcile`'s `short`/`extra` rule then calls the operation BEHIND for ever with nothing to pick. I think this is wrong: a parameter that cannot exist on the copy should not read as "update available" | unit — the churn half is covered: unit *a value that will not go in does not cause a new copy every pass*; the permanent-yellow half is not covered | noise |
| C3 | A shop preset *gains* a parameter, e.g. a stepdown is added | BEHIND through `short`/`extra`, and "changes the cut" must fire — this is the one scenario the shape machinery exists for and used to miss | unit — the value-moved case is covered: unit *a preset change that moves the cut says so*; the gained-parameter case rests on a code comment only | wrong green |
| C4 | The same tool (same guid) is in two Hub libraries | Today the library read last silently wins. It should be detected and reported, and the operation arguably left alone rather than judged against an arbitrary copy | script (put one tool in two Hub folders) | wrong green |
| C5 | A document tool's guid is in no library and its description is shared by two or more library tools | `identity.match` reports "description is ambiguous"; the verdict is NOT_UTP, which **removes** an existing note. It should leave the operation alone, as the unreadable-library case does | script — the ambiguity detection exists in `identity`, the consequence is untested | wrong blank |
| C6 | A document tool's guid is in no library but its description matches exactly one | Matched, and reported as a `description` fallback rather than passed off as an id match | script | wrong green |
| C7 | One library of eight will not open | `missed` is recorded, `library.incomplete()` is true, and every unmatched tool is left exactly as it is rather than called untracked | script — covered: integration *a reading covers every library, and is kept* | wrong blank |
| C8 | The Hub itself cannot be opened | `ok` is False, nothing is decided anywhere, and the buttons say so. Note `_cache["missed"]` is not updated on this early-return path — harmless today because nothing is decided, worth a line of code anyway | script | cosmetic |
| C9 | A tool is in no Hub library at all (a local library, or a one-off) | NOT_UTP, nothing said, no note | script | noise |
| C10 | A document tool has no counterpart because the shop deleted the tool | NOT_UTP, so any existing note and colour come off together. Correct, but nobody is told a tool they are using has gone | script | wrong blank |
| C11 | An operation has no tool | NOT_UTP, "the operation has no tool", nothing written | unit | cosmetic |
| C12 | An operation is on no preset | NOT_UTP, "the operation is on no preset". An *unreadable* preset is indistinguishable from this in the verdict, which is why `_presets_in_use` walks the operations itself and records a failure | unit and script — covered: integration *what the tidy may not delete is read from the operations, not the verdicts*, unit *the tidy never offers a preset an operation is running* | data loss |
| C13 | An operation is on Fusion's own "Default preset" | Not a UTP: left alone, never stamped, copied or tidied. 424 of 441 presets in this shop are these | unit and script — covered: unit *Fusion's own preset is not a shop preset*, integration *default presets are left alone* | noise |
| C14 | In one dialog visit, the newer preset is picked *and* a feed is changed | Should read grey Custom. As written, `state._record` withholds the record because it names the old preset, so the verdict is NOT_ADOPTED and the note is removed. Current behaviour looks wrong | unit (reconcile with a record naming the previous preset) | wrong blank |
| C15 | An operation is duplicated by copy and paste | The copied record's `operationId` does not match, so it is ignored; if the values match the preset the copy is adopted afresh (green); if they differ it goes silent rather than grey, losing a Custom marking | unit — the checking rule in `state._record` is untested | wrong blank |
| C16 | An operation's record attribute is hand-edited to invalid JSON | `state._held` returns `{}` (no record) **and** `compat.schema_of` treats it as newer than this version, so the whole document stands down from writing and says so. Safe; make sure the dialog text makes sense to a machinist | unit — covered: unit *a higher schema stops it writing and an unreadable one counts as higher* | wrong green |
| C17 | A document carries schema 4 on one operation and schema 3 on the rest | The button's pass surveys the whole document and stands down. The **event** path surveys only the operations it was handed, so an edit elsewhere still writes. Decide whether that is wanted; it is undocumented either way | unit and script — the whole-document case is covered: integration *it stands down on data from a newer add-in*, group W | data loss |
| C18 | A document written by schema 1, with three separate attributes | Read through `state._held`'s fallback and rewritten as one attribute the next time the operation is marked | unit — not covered | wrong blank |
| C19 | A document written by schema 2, with `[UTP] ` note lines | Read, and re-encased in backticks without leaving two lines behind | unit — the adjacent rule is covered by unit *a prefixed line without a closing mark is not ours*; the migration itself is not | noise |
| C20 | A library preset carries a version whose snapshot no longer describes its values | The version is withheld entirely (`LibraryPreset._describes`), so notes fall back to "update available" rather than naming a wrong version | unit — not covered | wrong green |
| C21 | A library preset carries a version with no snapshot at all | `versions.needed` keeps the number and re-records the values. It must never drop v5 back to v1, which would tell every document holding v5 it was ahead of the library | unit — not covered | wrong green |
| C22 | A document preset is named like one of the add-in's copies by hand, e.g. "Titanium v2 (latest)" | `claiming_latest` only recognises copies carrying `sourcePreset`, so the add-in adds its own and the dropdown gets two entries reading the same. Picking the wrong one gives wrong feeds under a green note | script | wrong green |
| C23 | A shop preset is deliberately named "Default preset v2" | `without_suffix` strips the version, `is_a_utp` says no, and every operation on it is silently ignored | unit — not covered | wrong blank |
| C24 | Tool or preset names carry non-ASCII characters (accents, °, ⌀) | Notes carry them correctly on screen; `NOTE_SEPARATOR` is ASCII on purpose; report filenames sanitise them to `_`. What reaches a control through a post is unknown | script, plus a bench post — partially covered: group X | cosmetic |
| C25 | A preset name is 200 characters long | The note is long but correct; the report filename truncates at 60 characters | unit | cosmetic |
| C26 | Two documents are open with the same name, one unsaved | `identify` uses the dataFile id and falls back to `unsaved:<name>`, so two unsaved documents with the same name would share one sweep key | script | wrong blank |
| C27 | An operation throws on a property read mid-walk | Counted per operation, the pass carries on, and the failure count stops the tidy deleting anything in that pass | script — covered: integration *what the tidy may not delete is read from the operations, not the verdicts* | data loss |
| C28 | A setup throws when `by_setup` reads it | Counted per setup, so "removed the notes from 6 of 6" can never be reported from half a document | script | data loss |
| C29 | `noteIconColor` is absent on this build (it is a preview API) | `_icon` returns None, no colour is planned, notes still work | unit — the positive case is covered: unit *an icon colour can be written and read back*; the absent case is not | cosmetic |
| C30 | A float differs only in its last bits after Fusion recomputes it | Not a difference: the tolerance is relative, `1e-6 × scale` | unit — covered: unit *floats get room but not too much* | noise |
| C31 | A preset and an operation share no parameter names at all | Not "the same": an empty intersection must never read as current | unit — covered: unit *nothing in common is not the same as agreeing* | wrong green |
| C32 | None of an operation's own values can be read | UNKNOWN plus leave-alone; whatever note it has stays | unit — covered: unit *a verdict that cannot compare says so instead of matching* | wrong green |
| C33 | A document preset carries `sourcePreset` pointing at a library preset that no longer exists | `removable` skips it, so it is never deleted; the operation on it reads "preset not in the library any more" and goes silent | unit — not covered | wrong blank |
| C34 | A copy was made before copies recorded what they stood for | `presets.plan` falls back to the copy's own values and says which comparison it used | unit — covered: unit *a copy that recorded nothing still gets compared* | noise |
| C35 | An operation sits on a preset that sets stepdown or stepover | "sets the cut" is said standing, on every pass, because Fusion leaves `isToolpathValid` True when preset values move | unit and script — covered: unit *an operation on a preset that governs the cut keeps saying so*, integration *an operation whose preset sets the depth of cut says so* | data loss |
| C36 | The update about to be picked moves a stepdown | The note says "changes the cut", and the check's dialog adds the regenerate tail | unit — covered: unit *a preset change that moves the cut says so* | data loss |
| C37 | The same operation is reached twice in one walk, e.g. a pattern listing its parent's operation | Judged twice, marked once (plan is idempotent). Worth confirming `_within` cannot double-count a setup's tracked total | script | cosmetic |
| C38 | A Hub library sits more than six folders deep | `library._walk` has `max_depth=6` and returns silently past it. Those libraries are not read, are not added to `missed`, and `library.incomplete()` stays False — so their tools are simply absent, and an absent tool is "not a UTP tool", which takes the note and the colour off. Exactly the failure the `missed` machinery was written to prevent, reached by a route it does not watch. Depth reached should be counted and reported | unit (walk a tree seven folders deep) | wrong blank |
| C39 | A folder in the Hub will not enumerate its children | `_walk` swallows both `childAssetURLs` and `childFolderURLs` failures with a bare `pass`. Everything under that folder is absent on the same terms as C38, with nothing recorded anywhere — not a failure, not a `missed` entry, not a count | unit | wrong blank |
| C40 | A library tool whose `toJson()` carries no guid, or that throws while being read | `library.read` skips it (`if tool.id:`, and `except Exception: continue`) and counts nothing. Documents using it lose their notes, and the report says the library was read and gives a tool count that is quietly one short. Both skips should be counted the way `unreadable` and `valueless` presets are | unit | wrong blank |
| C41 | The Hub opens and holds no tools, or every tool in it is skipped by C40 | `read` returns `ok = bool(tools)`, so an empty Hub is indistinguishable from one that could not be opened: the buttons say "The Hub library could not be read" and nothing is decided. The outcome is right and the sentence is wrong, which is how a shop spends an afternoon on the network | unit | cosmetic |
| C42 | A library preset's version attribute is not a whole number — "v3", "3.1", or anything typed by hand | `versions.stored_version` returns None, so `needed` reports "adopted as version 1" and the next stamp writes 1 over it. Every document holding v3 then reads as ahead of the library, and `presets._version_number` sorts it as 0, which degrades the tidy's "most recently retired" to highest-index (G5). C21's rule — never drop v5 back to v1 — guards a missing *snapshot* and not an unreadable *number*. A number that cannot be read should be left alone and reported | unit | wrong green |
| C43 | A tool matched by its description rather than by its id | The verdict is worked out and the note is written, but `_ensure_presets` and `_review_versions` both look the tool up as `tools.get(verdict["toolId"])` — the document tool's own guid, which by definition is not in the reading, because that is why the id match failed. So a description-matched tool never has a preset brought in and never has a version stamped: a yellow note sending somebody to a dropdown entry that will never be created | script | noise |
| C44 | A Hub library is duplicated, re-imported, or rebuilt at the shop | Storing a tool in a library gives it a fresh guid — `library.tool_id` says so in as many words — so every tool in the new library is a different tool to identity. Every existing document falls to the description fallback, and while the old library is still present two tools share each description, which `identity.match` calls ambiguous: NOT_UTP, and every note in every job is removed. One administrative action can un-mark the whole shop in an afternoon, and nothing warns before or after | script (copy a Hub library, then check a marked job) | FIXED 8 Oct: ambiguity is UNKNOWN + leave alone, not NOT_UTP. Notes survive; the pass says which descriptions are shared. Covered by test_a_duplicated_library_does_not_un_mark_the_shop and a bench check. What it cannot do is offer anything newer until the duplicate is gone |
| C45 | A tool's own definition is changed at the shop — a parameter added, a flute count or holder edited | Its presets' parameter sets move with it, so the `short`/`extra` rule reads every operation on that tool as behind, which is honest. The remedy is not in the dropdown though: it is the document's copy of the **tool** that lacks the parameter, so re-selecting the tool is the only fix, and the note cannot say so. An un-actionable yellow on every operation using a popular tool | script | noise |
| C46 | A document carries two tools answering to one guid, e.g. after an operation is pasted in from another job | `passes._document_tools` keys the shelf by guid into one dict, so the second overwrites the first — the same collapse C4 describes on the library side, inside the document. Whichever tool loses gets no preset brought in and no copies tidied, and its operations read "v3 available" with nothing to pick, for ever | script | noise |
| C47 | A shop preset the shop itself named with a version, e.g. "Alu 6082 v2" | `presets.without_suffix` strips a trailing " v<digits>" whether the add-in put it there or not. Copies come out as "Alu 6082 (latest)" with the shop's own revision dropped, and "Alu 6082 v2" and "Alu 6082 v3" both reduce to one base name, so their copies collide and their retired names are told apart only by date. A convention shops already use, quietly eaten | unit | wrong green |
| C48 | The schema survey only ever looks at operations | `compat.survey` is handed operations in both write paths, so a schema a newer add-in wrote on a **setup** record — `marks.setup_plan` writes `{"s": SCHEMA}` there — or on a preset it created (`compat.stamp`) is invisible. A document a newer version has touched everywhere except its operations is written to freely, which is the one case where standing down was the point | unit | data loss |
| C49 | A document migrated from schema 1 | The record is rewritten as one attribute, and `adoptedPreset`, `operationId` and the separate `schema` attribute are **never deleted** — `marks._apply` only adds. So a migrated operation carries both shapes for ever. Harmless, because `state._held` prefers the record, and only "Remove all notes" (which enumerates the whole group) takes them out. Worth knowing before anything else starts reading those keys again | unit | cosmetic |
| C50 | `noteIconColor` is absent, or reads back a value that is not one of the five names | C29 says no colour is planned in that case. That is not what the code does: `marks.plan` still asks for an icon change, because `_icon` answers None or a bare number and `now != colour`, and `_apply` then cannot write it because `getattr(adsk.cam.NoteIconColors, name, None)` is None. So the plan is non-empty on every pass for ever: the document never settles, every check reports "Marked N of N", and A5's promise that a second check writes nothing is false on such a build. C29 should be corrected and a colour that cannot be written should be planned once and then left | unit | noise |

## D. Too-fast and concurrent actions

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| D1 | "Check this document" is pressed twice quickly | The second pass finds nothing to do; Fusion serialises commands so there is no true overlap | script — covered: integration *a check settles, so a second one writes nothing* | noise |
| D2 | "Check this document" then "Pick up library changes" immediately | The refresh forgets the reading and the sweeps, re-reads, and sweeps again with no budget. Nothing is written twice | script | slow |
| D3 | An operation is edited while an automatic pass is mid-flight | The pass holds `marks.holding()` for its whole length, so the edit handler stands down; the edit is picked up by the sweep itself or the next trigger | script — covered by construction: integration *a check settles, so a second one writes nothing* | wrong green |
| D4 | A document is closed during a pass, through a `doEvents` breath | Per-operation failures are counted, the tidy stands down, and the handler logs rather than raising. The cursor and `_swept` entry for the closed document are left behind in memory | script | noise |
| D5 | Workspaces are switched repeatedly during a part-swept pass | Each entry either resumes the sweep or is skipped, and nothing re-reads the libraries inside 15 minutes | script — covered: integration *a part-swept document carries on at the next trigger* | slow |
| D6 | Five documents are opened in quick succession | Five budgeted passes of up to 2s; the library read is paid once | script | slow |
| D7 | Ctrl+S is pressed while an automatic pass is running | As written the pass goes on writing after Fusion's snapshot, so the document is dirty the instant the save finishes — the double-save regression. A pass should stand down, or the save should wait | script (start a pass, raise a save command id mid-pass) | noise |
| D8 | Ctrl+Z immediately after a check | Nothing comes back: notes, colours and attributes are not in Fusion's undo stack. "Remove all notes" is the way back, and the dialog has to say so | script and UI — covered: unit *nothing promises an undo that does not happen*, integration *a check's writes are not undoable, which is what the wording says* | data loss |
| D9 | Ctrl+Z immediately after picking a preset | The preset goes back; the note does not follow, because the add-in's write was its own step after `IronEditOperation` ended. A green note then sits over the old preset, and the settled-skip may mean no trigger looks again for 15 minutes | UI | wrong green |
| D10 | Undo is pressed during an operation edit, raising `operationBaseChanged` | `_running["undo"]` stands the handler down, and the number of events seen during the undo is logged | script — the handler is covered by integration *the edit listener fires*; the undo guard itself is only logged | data loss |
| D11 | A read-only, or somebody else's checked-out, file is opened | Today a full marking pass runs and every write fails. The button's pass asks `_writable` and refuses; the event path should too | script | noise |
| D12 | A file is marked `isInUse` by another user | Reported, not obeyed — usually it is the person themselves. Correct, but a genuine second editor is then invisible | script | data loss |
| D13 | A shop preset is changed on another machine while a pass runs here | The pass judges against the reading it has, and the next stale refresh picks the change up. No corruption; up to 15 minutes of wrong green | two machines | wrong green |
| D14 | Two machines press "Check this document" in the same minute with stamping on | `versions.review` reopens the library immediately before writing and abandons any preset that moved in between, saying so. The window is narrowed, not closed: `updateToolLibrary` still writes the whole library | two machines — the single-process half is covered: integration *a library preset that moved mid-pass is not written over* | data loss |
| D15 | Somebody edits a feed in the shop library while this machine stamps versions | Exactly D14's loss case, measured: 1750 → 1751 reverted to 1750. The guard must catch it and report it rather than writing over | two machines, or script with two snapshots — covered: integration *a library preset that moved mid-pass is not written over* | data loss |
| D16 | Two machines open the same job and both mark it | Both write the same notes from the same inputs and the writes are idempotent, so the file converges. Only the library writes are dangerous | two machines | noise |
| D17 | A long pass risks Fusion deciding the add-in is unresponsive | A breath every 20 reads and after **every** write; `WRITES_PER_CHUNK` is 1 because a write costs ~150ms and 20 of them is six frozen seconds | script (time a 400-operation pass) — partially covered: integration *a pass keeps to its budget and carries on next time* | slow |
| D18 | The progress dialog is switched on and cancelled mid-pass | Whatever was written stays, the report says somebody cancelled, and `decided` is short — so the tidy must not treat the slice as the whole document | script (`SHOW_PROGRESS = True`) — the slice protection is covered: integration *what the tidy may not delete is read from the operations, not the verdicts* | data loss |
| D19 | The add-in writes a note, which raises an edit event, which writes a note | Cannot happen: `holding()` spans the whole pass, not one write. Before it, every check reported marking all 8 operations for ever | script — covered: integration *a check settles, so a second one writes nothing* | noise |
| D20 | Somebody changes a feed on a preset the stamping pass is **not** stamping, in the same library, inside the write window | Lost. `versions.review` re-checks only the presets it planned to stamp; `updateToolLibrary` then writes the whole library back from the shelf it read a moment before. Anything that changed in that library between the second read and the write — another preset, another tool, anything — is reverted with nothing said. D14 and D15 measure the guarded case; this is the half the guard does not cover, and no amount of narrowing closes it while the only write is whole-library | two machines, or script holding two shelves | data loss |
| D21 | Two Fusions are started on one machine at once | Both loaders work in one cache with nothing locking it: `_sync` renames `code` to `code.old`, moves a staging tree into its place and `rmtree`s the old one, while the other process may be importing from exactly those paths. The loser imports a half-moved tree or none at all, and both append to one `loader.log` with no way to tell the two apart | script (run `_sync` twice concurrently against a `file://` base) | noise |
| D22 | A release is published while two Fusions are open and only one is restarted | One session runs the old code and one the new, against the same jobs and the same shared library. That is E15's version skew arriving on a single machine, where nobody would think to look for it | script, or two Fusions | data loss |
| D23 | "Pick up library changes" on a four hundred operation job | `_refresh` calls `mark_document` with `budget=None` — right, because somebody is waiting — but that path has no progress dialog of its own: `_Progress` exists only inside `passes.run`. So Fusion freezes for as long as it takes with nothing on screen, even with `SHOW_PROGRESS` on | script (time it) | slow |
| D24 | "Remove all notes" on the same job | No budget and no progress either, and three writes per operation at about 150ms each. The one command somebody reaches for when they want the add-in to stop touching their file is the slowest thing it does | script | slow |

## E. Fusion lifecycle

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| E1 | Cold Fusion start, add-in auto-runs | Commands built, a panel of its own made on the Utilities tab, listeners armed, "started" logged with version and schema. No library read until Manufacture is entered | script — covered: integration *the add-in running in Fusion is the one in this repository*, *the listeners are attached* | cosmetic |
| E2 | No panel on this build will take the buttons | `NO_PANEL` tells the person to run it from Scripts and Add-Ins, and the debug report lists every tab and panel found | script | cosmetic |
| E3 | The add-in loads before the person has signed in | `urlByLocation` gives no Hub url: "no Hub library on this account", nothing decided. Once signed in the next trigger reads successfully, because the cache is still empty | script — partially covered: group A | wrong green |
| E4 | Signed in but offline | Whatever Fusion can serve is read; a library that will not open is `missed`, and operations using it are left alone | script (disconnect) — partly covered: integration *a reading covers every library, and is kept* | wrong blank |
| E5 | Network lost mid-pass, after the libraries were read | Judging continues from the reading in hand; a `updateToolLibrary` write fails and is reported as "the library refused the version write"; nothing in the document is corrupted | script | data loss |
| E6 | Network lost while the libraries are being read | A partial reading: `missed` set, kept for 15 minutes, unmatched tools left alone. Caching a partial reading is deliberate — worth re-checking that 15 minutes of partial beats re-reading sooner | script | wrong blank |
| E7 | Fusion crashes mid-pass | Nothing is held outside the document, so the next run re-derives everything; records are written last, so a half-marked operation looks unadopted rather than adopted with no note | script — covered: groups R and R2 | data loss |
| E8 | Fusion crashes and offers document recovery | The recovered document has no dataFile id, so it keys as `unsaved:` and is swept fresh. Marks written but never saved are gone, which is correct | UI | wrong blank |
| E9 | A brand-new machine, first run | The loader fetches the release, checks the SHA256, unpacks and hands over. No switches file exists, so **everything is on** — including stamping the shared library and deleting presets | script — covered: group V for the loader, unit *no switches file at all is a fresh install* for the all-on default | data loss |
| E10 | A machine with no connection on its first ever run | The loader has no cache, has to fetch, and gives up after a timeout rather than hanging Fusion | script — covered: group V | slow |
| E11 | The add-in is stopped and re-run from Scripts and Add-Ins | `shutdown` detaches every handler from the event it was attached to and deletes the panel; `start` rebuilds. The module-level `library._cache` survives, so no re-read happens — a reload is *not* a way to pick up library changes, and people will assume it is | script — covered: integration *the add-in running in Fusion is the one in this repository* | wrong green |
| E12 | The add-in is re-run **without** being stopped first | Handlers are added a second time and every event is handled twice. Writes are idempotent so nothing breaks, but every pass is double-worked | script | slow |
| E13 | A new release is published while Fusion is open | Nothing changes this session; the loader picks it up at the next start, on purpose, because swapping code under running handlers is how an add-in crashes Fusion | script — covered: group V | cosmetic |
| E14 | Fusion is left open for a week | Libraries re-read every 15 minutes on triggers; `_recent` is capped at 40. The session log, `_commands`, `_swept` and the save cursors all grow unbounded, and the session log is one flushed line per event for a week | not testable in a suite; watch the file sizes | slow |
| E15 | Two versions of the add-in are in the shop while machines are updated | The older refuses to write to data from the newer, and preset naming stays recognisable both ways | script — covered: group W, integration *it stands down on data from a newer add-in* | data loss |
| E16 | The reports folder is inside a synced Documents folder | The switches file is written beside the real one and moved into place, so a sync or a crash cannot leave half a line of JSON | unit — the consequence is covered by unit *a switches file that cannot be read turns everything off*; the atomic write itself is untested | data loss |
| E17 | The reports folder cannot be written (full disk, permissions) | A report that cannot be written must not stop the pass: the stream is None and the pass carries on | unit | cosmetic |
| E18 | Fusion is running in a language other than English | `NOT_A_UTP_NAMES` matches "default preset" by name, so in another language Fusion's own presets are treated as shop presets: version numbers stamped onto them, "(latest)" copies made, and notes reading "Default preset v1". The most language-dependent assumption in the add-in | script (a non-English Fusion) | noise |
| E19 | The add-in is uninstalled, or its cache emptied, while Fusion is running | The modules are already imported, so it keeps listening and keeps writing until Fusion is restarted. Nothing in a document records which version wrote its notes, so a note written by a copy that no longer exists on the machine cannot be told from one written now | script | cosmetic |
| E20 | Two copies of the loader are installed, e.g. one in `API/AddIns` and one in `ApplicationPlugins` | Worse than E12, and for a reason nothing would predict. Each loader deletes `utp` and `utp.*` from `sys.modules` and imports again, so the second copy gets **different module objects**: `marks._writing`, `library._cache`, `events._swept` and `settings._held` all exist twice. The self-write guard is per module instance, so the first copy's listeners cannot see that the second copy is mid-pass, and the add-in starts reacting to its own notes again — the 21-handler-calls-per-press regression, reintroduced by how it was installed rather than by any change to the code. Each `start` also deletes the other's panel | script (import the package twice and check `marks.busy()` across the two) | noise |
| E21 | Fusion's own autosave fires | `AutoSaveFilesCommand` is deliberately not in `SAVE_COMMANDS` — that substring is what used to run a whole pass on every export. But `documentSaving` fires for every save however Fusion named it, so each autosave logs "A SAVE THIS BUILD DOES NOT RECOGNISE" with its full explanation. On a timer, all day. The detector written to catch a genuinely unrecognised save is drowned by the one case that was excluded on purpose, and it should know the difference | script (shorten the autosave interval and watch the log) | noise |
| E22 | An autosave lands while an automatic pass is running | D7 without anybody pressing anything, and on a timer, which makes it the likeliest way D7 is ever met. Nothing stands the pass down and nothing delays the save | script | noise |
| E23 | The machine's clock is wrong, or moves backwards during a session | `library.read_at()` and `LIBRARY_STALE_AFTER` are wall-clock. A clock that jumps forward forces a re-read, which is harmless; one that jumps back leaves a reading apparently fresh for as long as the jump, so the fifteen-minute bound on wrong green silently becomes whatever the jump was. Retired copies also keep a wrong date in their names for ever | not testable | wrong green |

## F. The seven switches

The controls are `on`, `open`, `edit`, `mark`, `presets`, `tidy`, `stamp`
(`settings.CONTROLS`). The instructions page describes six — "a checkbox for
each of the two times it runs, one for the notes themselves, two for the
presets, and one at the top" — and leaves `stamp` out of the count, which is the
one switch with no undo.

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| F1 | `on` off | Nothing automatic; "Check this document" and "Pick up library changes" say why rather than doing nothing; "Check without changing anything" and "Remove all notes" still work, on purpose | unit and script — covered: unit *switching the add-in off turns the early read off too* | noise |
| F2 | `on` off, and the person expects the notes to vanish | They do not: existing notes stay until "Remove all notes" is pressed. The instructions say so; it is still the likeliest misunderstanding | UI | noise |
| F3 | `open` off, `edit` on | No open or workspace passes at all. Only operations somebody actually edits get marked, and the first edit of the session pays the whole ~3.4s library read inside `_mark_what_they_just_edited`. The rest of the document is never swept | script | wrong blank |
| F4 | `edit` off, `open` on | An operation edited by hand keeps its old note, and the settled-skip stops any later trigger looking at it until the reading goes stale *and* a workspace entry happens. A feed changed by hand can read green for 15 minutes or more | script | wrong green |
| F5 | `mark` on, `presets` off | Yellow notes tell people to pick the "(latest)" entry and no such entry exists. Either the notes should say something else or the combination should be refused | script | wrong green |
| F6 | `mark` off, `presets` on | Dropdowns gain and lose entries with nothing anywhere explaining why: `plan()` returns nothing, records included, but `_ensure_presets` and the tidy still run | script | noise |
| F7 | `mark` off, `stamp` on | Version numbers go into the shared library while the person sees no change at all in their own document | script | data loss |
| F8 | `tidy` on, `presets` off | No new copies are made and old ones are removed, so a document's copies shrink towards one. Harmless, but the dropdown changes quietly | script | cosmetic |
| F9 | `stamp` off | Notes still say when something is newer but cannot name a version — "update available" rather than "v3 available" — and nothing is written outside the document | script — partially covered: unit *every switch the code asks about is a switch that exists* | cosmetic |
| F10 | `tidy` off | Retired copies accumulate in dropdowns and nothing is ever deleted | script | noise |
| F11 | Every switch off except `on` | A pass reads, decides, reports, and writes nothing anywhere | script | cosmetic |
| F12 | All seven on, which is the default | Full behaviour, including the two writes with no undo: stamping the shared library and deleting presets | script — covered: unit *no switches file at all is a fresh install* | data loss |
| F13 | The switches file is corrupt or hand-edited into nonsense | **Everything** goes off and the Switches dialog says so. It must never fall back to defaults, because that turns things back on for the person who turned them off | unit — covered: unit *a switches file that cannot be read turns everything off* | data loss |
| F14 | The switches file holds `0` or `"false"` rather than `false` | Treated as damaged, not guessed at | unit — covered: unit *a switches file that cannot be read turns everything off* | data loss |
| F15 | A switches file from an older version, which had `save` where this has `open` | `save: false` carries over to `open: false`; every other missing key takes this version's default | unit — covered: unit *a file from an older version keeps this version's defaults* | noise |
| F16 | Code asks about a switch name that is not in `CONTROLS` | `settings.on` answers True for an unknown name, so a typo reads as "switched on". Guarded by a test that walks the source | unit — covered: unit *every switch the code asks about is a switch that exists* | data loss |
| F17 | Switches are changed mid-session | `settings.save` forgets the cache, so the next pass reads the new values; a pass already running keeps the values it started with | script | cosmetic |
| F18 | The switches file is copied from one machine to the next, the documented setup route | That one JSON file beside the reports is the whole configuration | UI | cosmetic |
| F19 | "Pick up library changes" is pressed with `open` off | Nothing is written. `_refresh` goes through `events.mark_document`, which asks `_may_write(document, operations)` — and `_may_write`'s trigger defaults to `"open"`. So a deliberate button press is held back by a switch about *automatic* triggers, and the dialog then reports "Read 390 tools … 0 change(s)" over a document it has just decided is out of date. The button should name its own trigger, or not consult those switches at all. This is the same class of fault as the commit that left the default at `"save"` | unit (`_may_write`'s default) and script | wrong green |
| F20 | `mark` off on a document that is already marked | Every note and colour freezes exactly as it stands and goes on being read while the library moves on. Different from F2: there the add-in is off and every button says so. Here it reads, reports, brings presets in and stamps the shared library, and the only thing it will not do is correct the one thing somebody is looking at. Turning `mark` off should offer to take the existing notes out, as "Remove all notes" does | script | wrong green |
| F21 | The switches file cannot be written — read-only, full disk, or a sync client holding it open | `settings.save` lets the exception out, `_Execute` catches it and shows "UTP could not finish doing that" with a traceback, and the switches stay as they were. The one dialog whose entire job is to change a setting is the one that does not say plainly that it failed | unit | cosmetic |
| F22 | The switches file is renamed or moved aside, which is what a cloud sync conflict does to it | Everything comes back **on**. `settings._read` refuses only when the file exists and cannot be read; a file that is gone is a fresh install, so the defaults apply — including stamping the shared library and deleting presets, for the person who turned those off. That is the exact direction `_read`'s own comment says must never happen, reached by the file disappearing rather than by it being damaged. The reports folder is under Documents, which in a lot of shops is synced | unit, plus UI on a synced folder | data loss |

## G. Destructive paths

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| G1 | The tidy finds two retired copies nothing points at | The older goes and the most recently retired stays: it is the only surviving record of what an operation used to run | unit — covered: unit *the tidy never offers a preset an operation is running* | data loss |
| G2 | The tidy considers a preset an operation is sitting on | Never removable. The protecting set is built by walking the operations, not from the verdicts, because a verdict is allowed not to look | unit and script — covered: unit *the tidy never offers a preset an operation is running*, integration *what the tidy may not delete is read from the operations, not the verdicts* | data loss |
| G3 | The tidy runs after a pass that recorded a failure | It stands down entirely and reports what it would have removed | script | data loss |
| G4 | The tidy is reached on a part-swept document | It does not run: automatic passes pass `tidying=False`, because a used-preset set built from a slice is incomplete | script | data loss |
| G5 | The tidy meets copies with no version numbers | They all sort as 0, so ordering falls back to index and "most recently retired" becomes "highest index". If presets have been renamed by hand that may keep the wrong one | unit | data loss |
| G6 | Version numbers are written into the shared shop library | Only presets this document uses, only after a second open of the library, only where nothing moved in between, and never when `stamp` is off. There is no undo | script and two machines — covered: integration *a library preset that moved mid-pass is not written over*, groups L and P | data loss |
| G7 | A library refuses the version write | Reported as "the library refused the version write"; nothing in the document depended on the number landing | script | cosmetic |
| G8 | "Remove all notes" on a marked document | Every note line, colour and attribute of the add-in's comes out, per setup and per operation; colours go back to what they were before the add-in touched them; presets are deliberately left alone, because an operation may be using one | script — covered: integration *removing the notes removes everything, and a check puts it back* | data loss |
| G9 | "Remove all notes" on a document carrying attributes from a newer version | `_group_keys` enumerates the attribute group rather than using a known list, so keys this version has never heard of come out too | unit | cosmetic |
| G10 | "Remove all notes" on a read-only file | Refused with `READ_ONLY`, nothing changed | script | cosmetic |
| G11 | "Remove all notes" with `on` off | Still works, deliberately: that is how somebody stops using the add-in, and a guard there would trap them | script | cosmetic |
| G12 | "Remove all notes", then the job is reopened | The notes come back, because a note is derived rather than stored. `mark` has to be turned off under Switches to make it stick, and both the dialog and the instructions say so | UI | noise |
| G13 | "Remove all notes" where a setup throws half way | Per-setup counting means it cannot report "6 of 6" from the half it could see | script | data loss |
| G14 | A document carries the old `leaveAlone` flag from 0.8.x | It is deleted wherever it is found; nothing reads it any more | script | cosmetic |
| G15 | `presets.remove` is given rows whose indices have shifted under it | Rows are applied highest-index-first and each name is checked before the delete; a mismatch is skipped and said out loud | unit | data loss |
| G16 | An operation ends up pointing at a preset the add-in then deletes | Must be impossible (G2). If it happened the operation keeps its values and silently names another preset: wrong feeds at the machine with nothing showing, and its note removed in the same pass | unit — covered by the same two tests as G2 | data loss |
| G17 | "Remove all notes" on a document a newer add-in has marked | It goes ahead. `passes.remove_marks` asks `_writable` and nothing else: there is no `compat.may_write` on that path. So the version that refuses to *write* to data it does not understand will happily *delete* all of it, including a newer version's record and whatever that record held beyond `i` and `s`. Standing down should extend to removal, or the dialog should say which version's work is about to go | unit | data loss |
| G18 | A version stamp half lands: the number is written to the shelf and the snapshot is not | This is the only route to C21 that does not involve another add-in. `versions.review` writes `version` then `values` as two `attributes.add` calls, and `updateToolLibrary` then writes the whole shelf — so an exception between the two leaves a preset in the shop library carrying a number with no snapshot. `needed` keeps the number and re-records the values, which is why C21 matters; worth saying where it comes from | script | cosmetic |
| G19 | A preset the add-in created is deleted by hand while an operation sits on it | G16 arriving at somebody's own hand rather than the tidy's. Fusion re-points the operation at whatever is left without changing its values, so the verdict is then worked out against a preset the operation never came from: custom or behind, and the note is honest about nothing. Nothing in the add-in can prevent this and nothing detects it | script | wrong green |
| G20 | The tidy meets a document with two tools answering to one guid (C46) | `used_ids` is walked from the operations, so every preset an operation points at is still protected whichever tool is which. What is not reached is the losing tool at all: `_sync_and_tidy` iterates `in_use` keyed by guid, so that tool's spare copies are never offered and accumulate for ever. Safe, and permanently untidy | script | noise |

## H. The person

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| H1 | Somebody writes their own note above and below the add-in's line | Their text survives exactly, blank lines and all; only the encased line is the add-in's | unit and script — covered: unit *somebody else's text survives wherever they put it*, integration *somebody's own note text survives a pass* | data loss |
| H2 | Somebody writes a line that looks like the add-in's but does not close it | It is theirs and is kept. Checking only the opening mark is the harm encasing was introduced to stop | unit — covered: unit *a prefixed line without a closing mark is not ours* | data loss |
| H3 | Somebody writes a line in the add-in's exact style, backticks and all | It is claimed as the add-in's and replaced. Unavoidable, and the reason a backtick was chosen; worth saying in the instructions | unit — the adjacent rule is covered: unit *their line in our style below ours is not ours* | data loss |
| H4 | Somebody writes a `[UTP] ` line in a note the add-in has never marked | Claimed as the old form and rewritten. A known ambiguity that narrows as documents are re-marked | unit — not covered | data loss |
| H5 | Somebody clears the add-in's note while editing the operation | It stays cleared for that visit; nothing fights them | unit — covered: unit *clearing a note during their own edit leaves it cleared* | noise |
| H6 | They clear it and then reopen the job | It comes back, on purpose, and the instructions say so | script — covered in part: integration *an opening pass marks the document and then settles* | noise |
| H7 | They clear the note and pick a new preset in the same visit | The note still stays cleared: the rule asks the record attribute rather than the verdict, so moving preset does not defeat it | unit — covered: unit *clearing a note during their own edit leaves it cleared* | noise |
| H8 | Somebody colours an operation red by hand and the add-in then adopts it | Red is recorded as "the colour it had before", the add-in paints its own, and "Remove all notes" puts red back | unit — covered: unit *the colour they chose survives being adopted and updated*, *a setup remembers the colour it had* | data loss |
| H9 | Somebody presses Ctrl+Z expecting the add-in's note to go back | It will not. The button's dialog says so; `settings.MEANS["edit"]` and the `events` docstring still promise the opposite for the edit path. One of them is wrong and it should be settled by measurement, not by argument | UI — the button half is covered: integration *a check's writes are not undoable, which is what the wording says* | cosmetic |
| H10 | A dropdown shows several entries ending "(latest)" | Only one per library preset should exist, but two library presets on one tool, a tool in two libraries (C4) or a hand-named copy (C22) can each produce more. Picking the wrong one gives wrong feeds under a green note | UI | wrong green |
| H11 | Somebody picks a retired "(until 30 Sep 2026)" copy by mistake | The operation goes yellow or custom against it, so the note stays honest — but nothing warns at the moment of picking | UI | wrong green |
| H12 | Two UTPs retire on the same day | The second gets the time as well as the date, so no two dropdown entries read the same | unit — covered: unit *a retired name does not collide with one already there*, *the newest copy says so and the retired one does not* | cosmetic |
| H13 | Somebody never looks at notes at all | Nothing blocks them and nothing reaches the control: notes only enter the NC with `showNotes` on, and the Fanuc post strips backticks. The add-in is advisory by design, which the shop needs told plainly — it is not a guard | script — covered: group X | wrong green |
| H14 | Somebody ignores "changes the cut" and posts without regenerating | The toolpath posts the old shape at the new numbers. The check's dialog says it once; an automatic pass never does, because the regenerate tail exists only on the button's path | script | data loss |
| H15 | A new machinist, cold, opens a job and sees grey "Custom" everywhere | Grey means somebody changed the feeds here on purpose and is not a task. The instructions page is the only place that says so | UI | noise |
| H16 | Somebody reads a green note on an operation whose toolpath predates the preset moving | Green plus "sets the cut" is the only signal, and it is said standing because Fusion does not mark the toolpath stale | unit and script — covered: unit *an operation on a preset that governs the cut keeps saying so* | data loss |
| H17 | Somebody renames a document between sessions | Sweeps and records key on the dataFile id rather than the name, so nothing is lost or confused | script | cosmetic |
| H18 | Somebody sends in a debug report after something looked wrong | It must carry the library readings, the panel list, the command ids seen and the listener call counts — the four things that have each hidden a bug | script | cosmetic |
| H19 | Somebody asks what the add-in did and the reports folder holds 200 files | Reports are named `<timestamp> - <document>`; non-ASCII becomes underscores and names truncate at 60 characters, so two similar long names can look alike | unit | cosmetic |
| H20 | Somebody sets a new machine up by copying one file | The switches JSON beside the reports is the whole configuration, deliberately | UI | cosmetic |
| H21 | Somebody reads a yellow note, opens the dropdown, and the "(latest)" entry is not there | Four routes reach this and they are indistinguishable to the person: `presets` switched off (F5), a tool matched by description (C43), the losing half of a duplicated guid (C46), and a value the document's copy of the tool cannot hold. Whatever else is done, yellow has to mean "there is something here to pick" or say why there is not | UI | noise |
| H22 | Somebody deletes the add-in's panel, or drags its buttons somewhere else | `_own_panel` deletes and rebuilds the panel on every start, so the next restart puts it back exactly where it was. There is no way to keep it out of the way except to stop the add-in, which is probably right and is nowhere written down | UI | cosmetic |
| H23 | One machine has `stamp` off and a colleague's has it on | The colleague's machine numbers the shop library and this one reads those numbers and names them in notes. Nothing is wrong, and it is worth saying out loud, because the switch reads as "whether versions exist" and means "whether this machine is one of the ones that writes them" | two machines | cosmetic |
| H24 | Somebody edits the version inside the add-in's own line, rather than writing their own line | The line is encased, so it is claimed and rewritten at the next pass. Their edit lasts until then and nothing says it was overwritten — H3's rule met by editing instead of by writing, which is the more likely of the two | unit | cosmetic |
| H25 | Somebody works in a job all week and never saves it | A8 is right that every note goes. What nobody is told is that the **records** go with them, so operations that read grey Custom come back as never tracked, with no note — the same loss `UNMARK_CONFIRM` warns about at length, arriving by not saving rather than by pressing anything | script | wrong blank |
| H26 | Somebody asks which version of the add-in wrote the notes in a job | Nothing in the document says. The record carries the schema, not the version, and the report that does carry it is on whichever machine ran the pass. With two versions in the shop (E15) that is the first question a wrong note raises, and there is no way to answer it from the file | script | cosmetic |

## I. The loader, the cache and a release

The loader is installed once per machine and never changes, so every one of
these is a fault that cannot be fixed by publishing a release — which is the
one reason to go through them carefully.

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| I1 | A machine is off the network, or off site | `_sync` gives up after `_PROBE_TIMEOUT` (3s) and the cache runs. Every Fusion start pays those three seconds and the only record is a line in `loader.log`. Correct, and a laptop user should be told the number rather than discovering it | script against an unreachable base | slow |
| I2 | `VERSION` and `utp.zip` disagree, which GitHub's cache has been measured doing for 85 seconds | The code's own version wins and is recorded, which is right and is already handled. What is not handled is the consequence: `_sync` compares the **advertised** version against the **installed** one, so while the two disagree, every single Fusion start downloads the whole zip again, hashes it, unpacks it, swaps the cache and records the same version as last time. A stale CDN entry is a twenty-second install on every start until it clears, and the log says "installed" each time | script (serve a stale VERSION from a `file://` base) | slow |
| I3 | A download does not match the published SHA256 | Discarded, nothing unpacked, the working copy stands, a full sentence in `loader.log`. Nobody is told: no message box, nothing in the panel, and the add-in starts normally on the old code. A machine can sit several releases behind for weeks, which is precisely the version skew E15 and the schema number exist to survive. The loader should say so somewhere a person looks | script — partly covered: group V | wrong green |
| I4 | The `SHA256` file itself cannot be fetched — a proxy, a transient failure, a slow link | `_expected_digest` returns None and the zip is installed **unverified**, with a log line in the same shape as the deliberate case below. A check that silently did not happen and a policy decision not to check should not look alike. Treating a failed hash fetch as a reason to keep the working copy would cost nothing, since the next start tries again | unit (`_expected_digest` against a failing fetch) | data loss |
| I5 | A release older than 0.17.0, which has no SHA256 at all | Installed with a line saying it was unverified, on purpose, so a machine can deliberately be put back on an old release. The reason is good and it is the reason I4 is dangerous | unit | data loss |
| I6 | `source.json` is missing, unreadable, or names neither a repo nor a base, on a machine that already has a cache | `run` skips `_sync` entirely and starts the cached copy. That machine never updates again, and nothing on screen says so: the evidence is one line in `loader.log` and the loader section of a debug report. A machine that cannot update is a machine running rules nobody in the shop thinks is running | script | wrong green |
| I7 | A release is built from a tree missing a module | `tools/package.py` and the loader's `_usable` check the same two filenames, `utp/__init__.py` and `utp/addin.py`, so a zip without `events.py` passes the hash, the zip test and the shape check, replaces a working cache, and then fails on import with a message box. The cache has already been swapped, so the next start fails identically: there is no route back to the copy that worked. Either the shape check should list what the package actually needs, or the old copy should be kept until one import has succeeded | script (build a zip without a module) | noise |
| I8 | A rollback: an older release is published as the latest | `_sync` compares for difference, not for order, so machines downgrade themselves — which is what makes rollback work at all and is worth knowing deliberately. What does not come back is the documents. Anything the newer version marked carries its schema, and the older add-in stands down from writing to it (E15, C16), so a rollback across a schema bump leaves every touched job read-only to the whole shop until somebody rolls forward again | script | data loss |
| I9 | A crash, or a sync client, between the rename and the move inside `_sync` | `code` has already become `code.old` and the new tree is not in place, so `_usable(_CODE)` is False at the next start and the loader fetches again — the right answer, but only because there is a network. Offline, `code.old` is never looked at and the machine has no add-in at all, with a message box pointing at a log file. The working copy is one `os.rename` away and nothing tries it | script (interrupt `_sync`) | noise |
| I10 | `code.old` cannot be deleted, because a scanner or an indexer has a file in it open | `shutil.rmtree(..., ignore_errors=True)` leaves it, and `os.rename(_CODE, replaced)` then fails on Windows because the destination exists. The install is abandoned with "installing failed" in the log and the machine goes on running the cache — and will fail the same way at every start until somebody clears the folder by hand. A unique staging name would make this impossible | script | wrong green |
| I11 | Fusion's add-ins folder is on a network share or a roaming profile | Only `source.json` is read from beside the loader; the cache is under `LOCALAPPDATA`, which a roaming profile does not carry, so every machine updates itself independently. That is the right choice and it is the mechanism by which two machines run two versions although the shop published one release | script | cosmetic |
| I12 | A debug report names the version | `_installed()` reads `version.txt`, which describes the **cache**, not necessarily the modules in memory: a second Fusion's `_sync` can replace both after this session imported. So a report can name a version this session is not running — the exact failure `_version_in` was written to prevent, by a different route | script | cosmetic |
| I13 | `loader.log` after a year | Appended to on every start, never rotated or trimmed. The debug report reads its last eight lines, so everything before that exists only to be found by hand | unit | cosmetic |

## J. Posting, and what reaches the control

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| J1 | A setup's note goes into the NC | Setup notes are newer than the posting measurements in group X, which covered operation notes only. If a post emits setup or program comments, "`UTP 2 of 7 need updating`" lands in the program header, where it is neither true for long nor meant for a machine. Worth measuring on the bench before it is found at a control | script — group X covers operation notes | noise |
| J2 | A post uppercases and sanitises comments, as this shop's Fanuc post does | `(UTP P COPPER V1)` arrives with the backticks gone, so the line is no longer in the form the add-in recognises as its own. Harmless in the NC, and it means an NC comment can never be read back as a note by anything | script — covered: group X | cosmetic |
| J3 | `showNotes` is switched on for the Okuma post | A backtick reaches a control and nobody here knows whether it minds. `config.NOTE_PREFIX` records that this must be checked first, and that changing the marks means raising `SCHEMA` — so the cheap-looking fix carries a cost nobody would guess at from the dialog | not testable until a control is tried | cosmetic |
| J4 | A job is posted mid-convergence, half its operations marked | Nothing stops it and nothing says so. The setup note is the only whole-document signal and it is deliberately withheld until a pass goes all the way round (A15), so what a collapsed setup shows during convergence is the count from the last complete pass — possibly hours old, possibly from before the preset changed — with nothing marking it stale | script | wrong green |
| J5 | A job is posted while its notes are right and its toolpaths are not | H14 and C35 cover the saying of it. What nothing does is stop it: a yellow operation, an un-regenerated toolpath and a successful post are all compatible, because the add-in is advisory by construction. If the shop ever wants that stopped it is a different add-in, hooked on the post command, and that should be a decision rather than a discovery | not testable | data loss |

## K. Reports, logs and the folder they live in

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| K1 | The reports folder is inside OneDrive, which `~/Documents` usually is | Every pass writes two files and every session writes a third that is flushed line by line, so a sync client spends the day uploading a file that changes on every event. Nothing is ever deleted. The folder grows for as long as the add-in is installed, and the configuration lives in it (F22) | UI, plus a count of the folder after a week | slow |
| K2 | The reports folder cannot be written at all | `Report` carries on with no stream, which E17 covers. `diagnostics.session_log` does not: the stream is left None and nothing remembers that opening it failed, so every event for the rest of the session retries `makedirs` and `open`. On a read-only or missing folder that is two filesystem calls per operation event, and operation events come in bursts of twenty-five | unit | slow |
| K3 | Two passes over one document inside the same second | The report base is `<timestamp to the second> - <document>`, so the `.jsonl` is appended to — two passes in one file, with no divider — and the `.md` is overwritten by the second. Pressing a button twice quickly (D1) is exactly how | unit | cosmetic |
| K4 | A report comes in and the question is which library reading produced it | The report names the libraries, the counts and every verdict, and the session log names a reading's age in seconds. Neither records **which** reading: `read_at` is a session clock and nothing carries it into a report, so two reports from one session cannot be ordered against a preset change made between them. One line would fix it and it is the first thing a wrong-green complaint needs | script | cosmetic |
| K5 | The shape of the operation tree is reported, and its depth is not | `_within` sets `seen["deepest"] = max(seen["deepest"], 1)`, so it is 1 whenever anything is nested at all and 0 otherwise, and `_walk`'s shape dict does not carry it. A job five folders deep reports the same shape as one with a single folder — and depth is the one number that would show a walk quietly failing to descend, which is what `_within` was counted for in the first place | unit | cosmetic |

## L. Units, locale and names

| # | What happens | What should happen | Test | Risk |
| --- | --- | --- | --- | --- |
| L1 | An inch document, or a document whose units are changed | Both sides of every comparison are read the same way, through `parameter.value.value`, so no verdict can be unit-skewed by the document's display units. What is **not** established is whether a value copied into a preset in an inch document comes back through Fusion's own conversion slightly moved, which would show as a difference just inside or just outside a relative 1e-6 — the difference between silence and permanent yellow | script (an inch job on a tracked tool) | noise |
| L2 | Fusion running under a locale that uses a comma for decimals | Nothing formats or parses a number through the locale: snapshots go through `json.dumps`, versions through `int()`, note text through `%s` of a float. So this is safe today, and it stops being safe the moment anything reads a parameter's *expression* instead of its value | unit | cosmetic |
| L3 | A copy is retired on a non-English Fusion | `RETIRED_FORMAT` uses `%b`, which `strftime` renders in the system locale, so "until 30 Sep 2026" becomes "30 sept." or "30 Okt" and can carry an accent and a full stop. Those names are permanent — a copy keeps the name it was given — so one shop's dropdowns can end up in two languages, and all the care `NOTE_SEPARATOR` takes over ASCII is undone by the one name that is generated rather than written down | unit | cosmetic |
| L4 | The non-English Fusion of E18, before anybody notices | There is one available early warning and nothing reads it. `library.read` reports `presets Fusion created rather than somebody in the shop` with a count — 424 of 441 on these libraries — and on a non-English Fusion that count is 0 while the tracked count jumps from 17 to hundreds. Nothing compares it against anything, so the first sign is "(latest)" copies of Fusion's own presets appearing in the shared library. A pass that finds no ignored presets at all should say so loudly | script | noise |
| L5 | A Windows user profile with non-ASCII characters in its name | `REPORT_DIR` comes from `os.path.expanduser("~")`, so the path itself carries them while the contents are written `encoding="utf-8"` and the report's own name is sanitised to `_` (H19). Fine on Windows as far as anybody knows, which is the problem with it being an assumption rather than a test | unit | cosmetic |

---

## Gaps worth closing first, as tests

In rough order of value per hour:

1. **Unit:** a parameter present on one side only, in both directions — the
   gained-stepdown case (C3) and the won't-go-in case (C2). One test fixes a
   confirmed hole and one confirmed over-report.
2. **Unit:** `state._record` under a preset change (C14), under a duplicated
   operation (C15), and against a schema-1 record (C18). Three small tests over
   `_held`/`_record`, which nothing currently exercises.
3. **Script:** a settled document changed in a way no listener sees — a new
   operation, a duplicated one, an edit with `edit` off (B7, F4). The biggest
   wrong-green surface in the add-in, with no coverage at all.
4. **Script:** a read-only document opened with events on (D11), and a save
   raised mid-pass (D7).
5. **Script:** one tool in two Hub libraries (C4), and a tool whose guid is
   absent with an ambiguous description (C5).
6. **Two machines:** the only honest test of G6, D14 and D15. Until that exists,
   consider whether `MAY_BUMP_LIBRARY_VERSIONS` should default off rather than on
   for a fresh install.
7. **Not a test, but cheaper than any of them:** reconcile `config.INSTRUCTIONS`
   — which still says the add-in runs on a save and describes a switch list that
   no longer matches — with the HTML page in `instructions.py`, and settle the
   edit-path undo claim in `settings.MEANS["edit"]` and the `events` docstring
   against the measurement recorded in `config.MARKED_TAIL`.

---

## Added in a second pass: the new ground, most dangerous first

Everything in this section is new in A26–A30, B19–B22, C38–C50, D20–D24,
E19–E23, F19–F22, G17–G20, H21–H26 and groups I, J, K and L. Written against
0.28.1, so where it disagrees with the 0.13.x prose above, this is the later
reading. Ranked the same way: (how bad if wrong) × (how likely) × (how little
exists today).

1. **A Hub library duplicated, re-imported or rebuilt un-marks the whole shop**
   (C44). Storing a tool in a library gives it a fresh guid, so every tool in
   the new library is a different tool to `identity.match`; every document falls
   to the description fallback, and while the old library is still there the
   descriptions collide and are called ambiguous. That is NOT_UTP, which
   *removes* notes. One ordinary library-housekeeping action, no warning before
   or after, nothing in any report that would name the cause, no coverage. The
   cheapest mitigation is not a test: it is writing down that Hub libraries must
   be edited in place and never copied.
2. **A sync conflict on the switches file turns everything back on** (F22).
   `settings._read` refuses to guess only when the file *exists*; a file that has
   been renamed to `UTP switches-DESKTOP-ABC.json` is a fresh install, and a
   fresh install stamps the shared library and deletes presets. The folder is
   under `~/Documents` on purpose, and the code already knows that folder is
   synced. One unit test and a check for "a settings file that used to be there".
3. **The library write reverts anything else that moved in its window** (D20).
   `versions.review` re-validates only the presets it planned to stamp, and then
   writes the whole library back from one shelf. A feed change to any *other*
   preset in that library, made between the second read and
   `updateToolLibrary`, is gone with nothing said — the same loss D15 measured,
   through the half of the door the guard does not cover. Until two machines can
   be tested together, this is the strongest argument for
   `MAY_BUMP_LIBRARY_VERSIONS` defaulting off.
4. **A six-folder ceiling and two silent `pass` statements can hide a whole
   library** (C38, C39, C40). Three separate routes by which tools go absent
   without `missed` being set, without `library.incomplete()` becoming true, and
   therefore with every operation using them reading "not a UTP tool" and losing
   its note. The `missed` machinery exists for exactly this consequence and
   watches only the fourth way in, a library that refuses to open (C7). All
   three are unit-testable in an hour.
5. **"Remove all notes" does not stand down on newer data** (G17). The version
   that refuses to write a note to a document it does not understand will delete
   every record in it, including fields it has never heard of. The asymmetry is
   not deliberate anywhere in the code or the prose; `_group_keys` enumerating
   the group (G9) is what makes the deletion thorough.
6. **Two installed copies break the self-write guard** (E20). The loader purges
   `utp.*` from `sys.modules`, so a second install gets its own `marks._writing`,
   `library._cache` and `events._swept`. Two live sets of listeners that cannot
   see each other's writes is the 21-calls-per-press regression back, caused by
   installation rather than by code, and nothing in the debug report would show
   it. Testable without Fusion: import the package twice and ask both copies
   `marks.busy()`.
7. **A button held back by a switch about automatic triggers** (F19). "Pick up
   library changes" writes nothing when `open` is off, because
   `events._may_write` defaults its trigger to `"open"`, and then reports a
   confident count of changes it did not make. Same shape as the commit that
   left that default at `"save"`; one unit test over `_may_write` pins both.
8. **A document that can never settle on a build without `noteIconColor`**
   (C50). C29 says no colour is planned when the API is absent. The code plans
   one on every pass and cannot write it, so every check reports marking
   everything, for ever. Unit-testable, and it also means A5 and the integration
   check behind it are build-dependent in a way nothing records.
9. **Version numbers reset to 1 by anything that is not an integer** (C42).
   `stored_version` answers None on a `ValueError`, and `needed` reads None as
   "never stamped". C21 took care that a missing snapshot cannot drop v5 to v1;
   a missing or hand-edited *number* does exactly that, and then tells every
   document holding v5 that it is ahead of the library.
10. **Un-actionable yellow, four ways** (H21, C43, C45, C46). A description-
    matched tool never gets a preset brought in; a duplicated guid leaves one
    tool invisible to the preset step; a tool whose own definition changed needs
    the tool re-selected and the note cannot say so. All three read to a
    machinist as "the note is lying", which is how yellow stops being read, which
    is how wrong green arrives later. The fix is one rule rather than four: a
    BEHIND verdict that cannot name something pickable has to say why.
11. **The loader fails quietly in five different ways** (I3, I4, I6, I7, I10).
    A bad hash, a hash that could not be fetched, a missing `source.json`, a zip
    that passes a two-filename shape check, and a `code.old` that will not
    delete. Each leaves the machine running something other than what the shop
    published, each writes one line into a file nobody opens, and the panel looks
    identical in all five. Group V covers whether a loader *can* work here, not
    what it does when it does not.

Two things worth doing that are not tests at all. `_mark_setups` should be
handed the verdicts the sweep already worked out (B19) — it is a one-argument
change that currently doubles the cost of every completing pass. And the
autosave line in the session log (E21) should know that an autosave is not an
unrecognised save, before the warning that exists to catch a real one is read
as routine.
