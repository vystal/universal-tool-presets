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

Migrating older data forward belongs here too. There is nothing to migrate
yet, schema 1 being the first, but the place for it is decided.
"""

from . import config


def stamp(owner):
    """Record which schema wrote this. Called wherever the add-in writes."""
    try:
        owner.attributes.add(config.ATTRIBUTE_GROUP, config.KEY_SCHEMA,
                             str(config.SCHEMA))
        return True
    except Exception:
        return False


def schema_of(owner):
    """The schema something was written against, or None if nothing was."""
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
        # Unreadable is treated as newer, not as absent: something wrote a
        # value this version cannot make sense of.
        return config.SCHEMA + 1


def survey(owners, breathe=None):
    """The newest schema anything here was written against.

    One attribute read per operation, which on a four hundred operation file
    is long enough to be worth handing the main thread back during.
    """
    newest = 0
    for index, owner in enumerate(owners):
        found = schema_of(owner)
        if found and found > newest:
            newest = found
        if breathe is not None:
            breathe(index)
    return newest


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
