"""What a job may and may not touch.

Be clear about what is actually enforced here, because a guard that is believed
to do more than it does is worse than none.

Enforced: a job that asks to write is refused unless the document in front of
Fusion is the test document, by name. That is a real check against a real
property, and it is the one that matters, because every mark the add-in writes
goes to the open document.

Enforced: the add-in's writes into a shop tool library are held off for the
whole of a job unless the job asks for them by name. That is the one thing it
writes that is neither the document nor undoable, and holding it is a matter of
switching off the constant the code already reads.

Not enforced, and cannot be: a job is Python, and Python can call anything the
API exposes. Nothing here can stop a job I write badly from writing somewhere
it should not. What keeps that safe is that the test document's tools come from
the TEST library, so there is nothing else for the add-in to reach, plus the
fact that every job and every answer is left on disk to be read afterwards.
"""

TEST_DOCUMENT = "UTP TEST"
TEST_LIBRARY = "TEST"

# Where the working copy lives, for a job that wants to test an edit before it
# is released. Machine-specific, which is fair for a tool that only ever runs
# on the machine it is developed on.
REPO = "C:/code/active/fusion-utp"




def may_write(app):
    """Whether a writing job may run. Returns (allowed, why not)."""
    try:
        document = app.activeDocument
    except Exception:
        return False, "no document is open"
    if document is None:
        return False, "no document is open"
    try:
        name = document.name or ""
    except Exception:
        return False, "the open document would not give its name"
    if TEST_DOCUMENT.lower() not in name.lower():
        return False, ("the open document is %r, and a writing job only runs "
                       "in a document with %r in its name" % (name, TEST_DOCUMENT))
    try:
        if document.dataFile and document.dataFile.isReadOnly:
            return False, "the test document is read-only"
    except Exception:
        pass
    return True, None


def hold_library_writes():
    """Nothing to hold any more. Kept so the runner needs no change.

    This used to switch config.MAY_BUMP_LIBRARY_VERSIONS off for the duration
    of a job, because the add-in stamped version numbers into the shop's
    shared library and a test job had no business writing there. Version
    stamping was removed on 8 October, and with it the only write the add-in
    ever made outside the person's own document, so there is nothing left for
    a job to be held back from.
    """


def let_library_writes_go():
    """The other half of the pair above, and equally empty now."""


def allow_library_writes():
    """Was how a job testing the stamping opted into it. Nothing to opt into."""


def libraries_used(app):
    """Which Hub libraries the open document's tools come from.

    For a job to assert on before it writes anything: if this is not just the
    TEST library, the document is not the one to be writing in.
    """
    from utp import library, passes
    import adsk.cam
    cam = app.activeDocument.products.itemByProductType("CAMProductType")
    shelf = passes._document_tools(cam)

    class Quiet:
        def note(self, *a, **k): pass
        def failed(self, *a, **k): pass

    tools, ok = library.cached(Quiet())
    if not ok:
        return {"read the libraries": False}
    found = {}
    for key in shelf:
        tool = tools.get(key)
        if tool is not None:
            found[tool.library] = found.get(tool.library, 0) + 1
    return found
