"""Deciding that a tool in a document is a given library tool.

A copy taken out of a library keeps the library tool's id, so matching is
exact and needs nothing written anywhere. That was measured, not assumed: the
same id came back on both sides.

The description fallback exists to find out how often the exact match fails
on real files, which is one of the things phase 1 is for. It is reported
separately and never quietly treated as a success.
"""

from . import library

# Said in one place so a caller can recognise it without matching on prose.
# The difference matters: "no match" means this tool is not in any shop
# library, which is a fact. Ambiguous means the question could not be
# answered, which is not the same thing and must not be treated as one.
AMBIGUOUS = "description is ambiguous"


def match(tool, library_tools, tool_id=None):
    """Returns (LibraryTool or None, how it was found, the tool's own id).

    The id is handed back because working it out costs a toJson() of the
    whole tool, and it was being worked out again by everything that wanted
    it: measured at 780 serialisations on a 390 operation file, for 390
    answers.
    """
    found = tool_id or library.tool_id(tool)
    if found and found in library_tools:
        return library_tools[found], "id", found

    # Descriptions collide: four tools in one test document shared one. So a
    # description match is only reported when it is unambiguous, and even
    # then it is called out as a fallback rather than trusted.
    description = (tool.description or "").strip()
    if description:
        hits = [t for t in library_tools.values()
                if (t.description or "").strip() == description]
        if len(hits) == 1:
            return hits[0], "description", found
        if len(hits) > 1:
            return (None,
                    "%s (%d tools share it)" % (AMBIGUOUS, len(hits)),
                    found)
    return None, "no match", found
