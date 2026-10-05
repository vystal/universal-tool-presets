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

_held = {"bumping": None}


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
    """Stop the add-in stamping versions into a shop library during a job."""
    from utp import config
    _held["bumping"] = config.MAY_BUMP_LIBRARY_VERSIONS
    config.MAY_BUMP_LIBRARY_VERSIONS = False


def let_library_writes_go():
    from utp import config
    if _held["bumping"] is not None:
        config.MAY_BUMP_LIBRARY_VERSIONS = _held["bumping"]
        _held["bumping"] = None


def allow_library_writes():
    """For a job that is deliberately testing the version stamping.

    Called by the job itself, so it appears in the job text rather than in a
    setting somewhere, and reading the job tells you it did this.
    """
    from utp import config
    config.MAY_BUMP_LIBRARY_VERSIONS = True


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
