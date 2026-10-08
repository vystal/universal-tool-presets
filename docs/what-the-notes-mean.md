# What the notes on your operations mean

Some operations in the Manufacture tree now have a small coloured note beside
them, wrapped in ` marks. This is what they are telling you.

You do not have to do anything about them. Nothing is blocked, nothing is
changed behind your back, and an operation with no note is not a problem.

---

## The colours

### 🟢 Green — nothing to do

```
`UTP Titanium T48 Roughing`
```

This operation is running the shop's current feeds and speeds for that tool.
The name tells you which set.

### 🟡 Yellow — there is something newer

```
`UTP Titanium T48 Roughing - update available`
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

## Setups, folders and patterns carry no note

Only operations are marked. A collapsed setup used to carry a count of what
was inside it, and that was dropped: folders and patterns hide their
operations in exactly the same way and never had one, so it was cover you
could not rely on. To see where a folded-up job stands, open it up or press
**Update presets** in the UTP panel.

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
out again the next time the operation is looked at — finishing the edit is
enough.

**I pressed Check and want it all back.** Press *Remove all notes*. Ctrl+Z will
not do it: measured on 6 October, a check wrote four notes, one undo was run,
and none of it reverted. What this add-in writes to notes,
colours and hidden records is not in Fusion's undo stack. Nothing is saved by a
check either, so closing the job without saving leaves it as it was.

**I wrote my own note on an operation.** It is still there, underneath the
line wrapped in ` marks. Your text is never touched.

**Two presets in the dropdown look almost the same.** The one ending
`(latest)` holds the shop's current feeds; the other is what your operations
are on now. Once every operation has moved across, the old entry disappears
by itself and the `(latest)` marker comes off, so you are back to one entry
per preset.

**An operation says yellow but I know the feeds are fine.** They probably
are. Yellow means the shop's numbers have moved on, not that yours are
wrong. Use your judgement — it is your job on the machine.

**I do not have this add-in on my machine.** Then you see the notes as they
were when the file was last saved by somebody who does, and nothing updates.
The notes are ordinary Fusion notes; they do not need the add-in to be read.

---

## If something looks wrong

Press **Write a debug report** in the UTP panel. It writes one file to
`Documents\UTP diagnostics` with everything worth knowing about this machine,
this document and the libraries. Send that file on.

If you want a report of every check instead, turn **Write a report each time**
on under *Switches*. It is off by default, because a folder filling up with
reports nobody reads is just clutter.
