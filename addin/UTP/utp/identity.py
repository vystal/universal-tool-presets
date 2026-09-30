"""Deciding that a tool in a document is a given library tool.

A copy taken out of a library keeps the library tool's id, so matching is
exact and needs nothing written anywhere. That was measured, not assumed: the
same id came back on both sides.

The description fallback exists to find out how often the exact match fails
on real files, which is one of the things phase 1 is for. It is reported
separately and never quietly treated as a success.
"""

from . import library


def match(tool, library_tools):
    """Returns (LibraryTool or None, how it was found)."""
    found = library.tool_id(tool)
    if found and found in library_tools:
        return library_tools[found], "id"

    # Descriptions collide: four tools in one test document shared one. So a
    # description match is only reported when it is unambiguous, and even
    # then it is called out as a fallback rather than trusted.
    description = (tool.description or "").strip()
    if description:
        hits = [t for t in library_tools.values()
                if (t.description or "").strip() == description]
        if len(hits) == 1:
            return hits[0], "description"
        if len(hits) > 1:
            return None, "description is ambiguous (%d tools share it)" % len(hits)
    return None, "no match"
