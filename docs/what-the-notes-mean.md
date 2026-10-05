# What the notes on your operations mean

Some operations in the Manufacture tree now have a small coloured note beside
them, wrapped in ` marks. This is what they are telling you.

You do not have to do anything about them. Nothing is blocked, nothing is
changed behind your back, and an operation with no note is not a problem.

---

## The colours

### 🟢 Green — nothing to do

```
`UTP Titanium T48 Roughing v3`
```

This operation is running the shop's current feeds and speeds for that tool.
The name tells you which set, and `v3` is which version of it.

### 🟡 Yellow — there is a newer version

```
`UTP Titanium T48 Roughing v2 - v3 available`
```

Somebody has changed the shop's feeds for that tool since this operation was
set up. It is still cutting on the old ones, which is not wrong — just old.

**To update it:** open the operation, go to the tool's preset dropdown, and
pick the one ending **(latest)**. That is all. The note turns green.

If you would rather leave it alone, leave it alone. Nothing will chase you.

### ⚪ Grey — somebody changed this one on purpose

```
`UTP Custom`
```

This operation was on a shop preset and its feeds have since been edited in
this document. That is a normal thing to do for a particular job. The note
is only there so it is obvious the numbers are this file's own, not the
shop's.

### No note at all

The operation was never put on a shop preset — most older jobs are like
this — or its tool does not come from a shop library. Either way there is
nothing to say about it, so nothing is said.

---

## The note on a setup

A collapsed setup hides its operations, so each setup carries a summary:

| | |
| --- | --- |
| 🟡 ``UTP 2 of 7 need updating`` | worth opening up and looking |
| 🟢 ``UTP 7 tracked, up to date`` | nothing inside needs attention |
| no note | nothing in it is on a shop preset |

The count is only of operations the system is tracking. A setup with twenty
older operations and one tracked one says `1 tracked`.

---

## Questions you might reasonably have

**Did it change my feeds?** No. Nothing changes an operation's feeds except
you picking a preset. The notes and colours are all it writes.

**Can picking a preset change more than the feeds?** Occasionally, yes. A
preset usually carries feeds, speeds and coolant, but a few carry a depth of
cut or a stepover as well — three of the 441 presets in our libraries do. When
the newer values include one of those, the note says **changes the cut**, and
you should regenerate the operation before posting. Without that, the toolpath
keeps the old shape while the numbers are new, and the file looks ready when it
is not.

**I picked the wrong preset.** Ctrl+Z puts the preset back. The note is worked
out again the next time the operation is looked at, so it catches up on the next
save.

**I pressed Check and want it all back.** Press *Remove all notes*. Ctrl+Z will
not do it: measured on 6 October, a check wrote four notes and two setup notes,
one undo was run, and none of it reverted. What this add-in writes to notes,
colours and hidden records is not in Fusion's undo stack. Nothing is saved by a
check either, so closing the job without saving leaves it as it was.

**I wrote my own note on an operation.** It is still there, underneath the
line wrapped in ` marks. Your text is never touched.

**Why does one say `v2` and another just have a name?** The version numbers
only exist for presets the shop has started tracking. Where there is no
number, the note says `update available` instead of naming a version.

**Two presets in the dropdown look almost the same.** The one ending
`(latest)` is the current shop version. Others are older versions kept
because something in this file is still using them, or in case you want to
go back. `Titanium v2` was the shop's feeds before the current ones.

**An operation says yellow but I know the feeds are fine.** They probably
are. Yellow means the shop's numbers have moved on, not that yours are
wrong. Use your judgement — it is your job on the machine.

**I do not have this add-in on my machine.** Then you see the notes as they
were when the file was last saved by somebody who does, and nothing updates.
The notes are ordinary Fusion notes; they do not need the add-in to be read.

---

## If something looks wrong

Every check writes a report to `Documents\UTP diagnostics`, saying what it
found and what it changed, one line at a time. If an operation is marked in
a way that makes no sense, that file will say why it was marked.
