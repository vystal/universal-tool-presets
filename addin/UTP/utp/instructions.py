"""The instructions, as a page rather than a dialog.

A Fusion message box renders in a proportional font and ignores blank lines,
so a plain-text sheet with aligned columns came out as a wall. A page opens
in the browser, reads properly, prints, and can be sent to somebody who does
not have Fusion open.

The words live in config, so they stay in the one file everything readable
lives in; this only decides how they are laid out.
"""

import os
import subprocess
import sys

from . import config

_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>UTP</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font: 16px/1.6 "Segoe UI", system-ui, sans-serif;
    max-width: 44rem; margin: 3rem auto; padding: 0 1.5rem;
    background: #fbfbfc; color: #1b1b1d;
  }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .3rem; }}
  h2 {{ font-size: 1.1rem; margin: 2.4rem 0 .6rem; }}
  p, li {{ margin: .6rem 0; }}
  .lede {{ color: #5a5a62; margin-bottom: 2rem; }}
  table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
  td {{ padding: .5rem .6rem; border-top: 1px solid #e3e3e8;
        vertical-align: top; }}
  td.note {{ font-family: Consolas, ui-monospace, monospace;
             white-space: nowrap; }}
  .dot {{ display: inline-block; width: .7rem; height: .7rem;
          border-radius: 50%; margin-right: .5rem; }}
  .green {{ background: #3f9c4a; }} .yellow {{ background: #d9a521; }}
  .grey {{ background: #9a9aa2; }} .none {{ background: transparent;
          border: 1px solid #c6c6cf; }}
  .do {{ background: #eef5ee; border-left: 3px solid #3f9c4a;
         padding: .8rem 1rem; margin: 1.2rem 0; }}
  footer {{ margin-top: 3rem; color: #76767f; font-size: .85rem; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1c1c1f; color: #e8e8ea; }}
    .lede, footer {{ color: #9a9aa2; }}
    td {{ border-top-color: #34343a; }}
    .do {{ background: #1e2a20; }}
  }}
</style>

<h1>Universal Tool Presets</h1>
<p class="lede">What the notes on your operations mean, and what to do
about them.</p>

<h2>What this does</h2>
<p>Your tools' feeds and speeds live in the shop libraries. When somebody
changes them there, documents already made know nothing about it. This marks
each operation with where it stands, so you can see it and update it.</p>
<p><strong>It never changes an operation's feeds.</strong> Only you do that,
by picking a preset.</p>

<h2>The notes on your operations</h2>
<table>
  <tr><td class="note"><span class="dot green"></span>[UTP] Titanium v3</td>
      <td>On the current feeds. Nothing to do.</td></tr>
  <tr><td class="note"><span class="dot yellow"></span>[UTP] Titanium v2
      &middot; v3 available</td>
      <td>Something newer exists in the shop library.</td></tr>
  <tr><td class="note"><span class="dot grey"></span>[UTP] Custom</td>
      <td>Its feeds were changed in this document on purpose.</td></tr>
  <tr><td class="note"><span class="dot none"></span>no note</td>
      <td>Never put on a shop preset, or its tool is not a shop tool.</td></tr>
</table>

<div class="do">
  <strong>To update a yellow one:</strong> open the operation, go to the tool
  preset dropdown, and pick the one ending <strong>(latest)</strong>. The note
  turns green. Ctrl+Z puts it back.
</div>

<p>If you would rather leave it, leave it. Nothing will chase you, and
nothing is blocked.</p>

<h2>The note on a setup</h2>
<p>A collapsed setup hides its operations, so each setup says what is inside
it: <em>2 of 7 need updating</em> in yellow, or <em>7 tracked, up to
date</em> in green. The count is only of operations being tracked, so a setup
of twenty older operations and one tracked one says <em>1 tracked</em>.</p>

<h2>When it runs</h2>
<p>When you save a document, and when you change an operation. Nothing on
opening a file, and nothing in the background.</p>
<p>The first change you make after starting Fusion is not marked straight
away: it has to read the shop libraries first, and doing that in the middle
of your edit would stall Fusion for several seconds. Saving reads them and
catches the whole document up, and everything after that is marked as it
happens.</p>

<h2>Turning it off</h2>
<p>Press <em>Switches</em> in the UTP panel. There is a checkbox for each of
the two times it runs, one for the notes themselves, two for the presets, and
one at the top for the whole add-in. Off means off: nothing happens on its
own, and the buttons that change things say so instead of doing it.</p>
<p>Those are for your machine, not for the document, and they stay how you
set them until you change them.</p>

<h2>If you do not want a particular note</h2>
<p><strong>Clear its text.</strong> Nothing will put it back while you are
still editing, so you can get it out of your way.</p>
<p>It does come back on the next save, and that is on purpose: a note says
where the operation stands, so saving works it out again like everything
else. To stop the notes altogether, use <em>Switches</em>.</p>
<p><em>Remove all notes</em> takes every note and colour out of the whole
document at once. Same thing applies: saving or checking works them out
again, so turn the notes off under <em>Switches</em> first if you want them
to stay gone.</p>

<h2>Worth knowing</h2>
<ul>
  <li><strong>Your own notes are kept.</strong> It only owns the line starting
      <code>[UTP]</code>; anything else you write stays exactly as it is.</li>
  <li><strong>Your own icon colours are kept</strong> and put back if the
      marks are removed.</li>
  <li><strong>Older jobs stay silent.</strong> Nothing is marked until
      somebody puts an operation on a shop preset.</li>
  <li>Every check writes a report saying what it found.
      <em>Open the reports folder</em> in the UTP panel.</li>
  <li>If something looks wrong, <em>Write a debug report</em> makes one file
      to send on.</li>
</ul>

<footer>UTP {version}, in the Utilities tab of the Manufacture workspace.</footer>
"""


def page(version_text):
    """Write the page and return where it is."""
    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR, "UTP instructions.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_PAGE.format(version=version_text))
    return path


def show(version_text):
    """Open it in whatever reads a web page. Returns the path, or None."""
    try:
        path = page(version_text)
    except Exception:
        return None
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["open", path])
    except Exception:
        pass
    return path
