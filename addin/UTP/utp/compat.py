"""Telling versions of the add-in apart, so they cannot fight each other.

The add-in keeps nothing between sessions: every verdict is worked out from
the document and the library as they stand. So a newer version does not need
to pick up where an older one left off. It re-derives everything, which is the
same property that makes a crash harmless.

What is not free is two versions running at once on different machines, which
is the normal state of affairs in a shop for as long as it takes everybody to
update. If they disagree about what a note should say, each rewrites the
other's work on every save, and files are dirtied for ever. If they disagree
about preset naming, the older one stops recognising the newer one's copies
and starts adding duplicates of its own.

So everything written carries the schema it was written against, and the rule
is simple: an add-in that meets data newer than it understands stops writing
and says so. It never guesses, because guessing is what does the damage.

Reading older data belongs here too. Schema 1 wrote an operation's record as
three separate attributes; schema 2 writes one, because every write to a CAM
operation costs about 120 milliseconds. Both shapes are read, and an
operation is rewritten to the newer one the next time it is marked, so files
convert as they are worked on rather than in a migration nobody asked for.
"""

import json

from . import diagnostics

from . import config


def stamp(owner):
    """Record which schema wrote this, where it is not already in a record.

    An operation's record carries its own schema, so this is only for things
    that have no record of their own, like a preset the add-in creates.
    """
    try:
        owner.attributes.add(config.ATTRIBUTE_GROUP, config.KEY_SCHEMA,
                             str(config.SCHEMA))
        return True
    except Exception:
        return False


def schema_of(owner):
    """The schema something was written against, or None if nothing was.

    From inside the record where there is one, and from the separate
    attribute schema 1 wrote otherwise.

    A value that parses and names a schema this version does not know is
    newer, and standing down over it is right. A value that does not parse
    at all is damaged, and that is a different thing: it used to be reported
    as newer too, so a single corrupt record froze marking across an entire
    job and told the person to update an add-in that was already current.
    state._held reads the same bytes, gets nothing, and calls that operation
    never adopted -- so the two halves of this add-in read one byte sequence
    as opposite things, and only one of them stopped the whole document.

    Damaged reads as None: nothing can be learnt from it about what wrote
    it. The operation carrying it is still handled on its own merits, where
    an unreadable record means no record rather than "do not touch this job".
    Which preset the operation is sitting on is read from the operation
    itself, so losing the record costs the add-in nothing it cannot work out
    again.
    """
    try:
        record = owner.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                             config.KEY_RECORD)
    except Exception:
        record = None
    if record is not None:
        try:
            return int(json.loads(record.value).get("s", config.SCHEMA))
        except Exception:
            return None
    try:
        found = owner.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                            config.KEY_SCHEMA)
    except Exception:
        return None
    if found is None:
        return None
    try:
        return int(found.value)
    except Exception:
        return None


def survey(owners, breathe=None):
    """The newest schema anything here was written against.

    One attribute read per operation, which on a four hundred operation file
    is long enough to be worth handing the main thread back during.
    """
    newest = 0
    damaged = 0
    for index, owner in enumerate(owners):
        found = schema_of(owner)
        if found is None and _has_a_record(owner):
            # It has one and it will not parse. Counted rather than treated
            # as newer, which is what froze a whole job over one bad record
            # -- but counted, because silence about damage is how this got
            # written off as "nothing here was ever marked".
            damaged += 1
        if found and found > newest:
            newest = found
        if breathe is not None:
            breathe(index)
    if damaged:
        diagnostics.session_log(
            "records that could not be read", count=damaged,
            note=("not treated as newer -- one of those used to stop every "
                  "note in the job. Those operations read as never marked."))
    return newest


def _has_a_record(owner):
    try:
        return owner.attributes.itemByName(config.ATTRIBUTE_GROUP,
                                           config.KEY_RECORD) is not None
    except Exception:
        return False


def may_write(newest):
    """Whether this version is allowed to write, given what it found.

    Older or equal is fine: this version understands it, and migrates it
    forward if that ever becomes necessary. Newer is not, because writing
    would mean overwriting decisions made by rules this version does not
    have.
    """
    if newest > config.SCHEMA:
        return False, config.NEWER_ADDIN % (newest, config.SCHEMA)
    return True, None
