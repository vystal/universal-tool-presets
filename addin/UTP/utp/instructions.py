"""The instructions, as a page rather than a dialog.

A Fusion message box renders in a proportional font and ignores blank lines,
so a plain-text sheet with aligned columns came out as a wall. A page opens
in the browser, reads properly, prints, and can be sent to somebody who does
not have Fusion open.

Written for somebody standing at a machine who wants to know what a coloured
note means and what to press. It was twice this length and most of that was
explaining why things are the way they are -- which belongs in the code, and
in this file's own comments, not in front of a machinist.
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
    font: 16px/1.55 "Segoe UI", system-ui, sans-serif;
    max-width: 40rem; margin: 2.5rem auto; padding: 0 1.5rem;
    background: #fbfbfc; color: #1b1b1d;
  }}
  h1 {{ font-size: 1.5rem; margin: 0 0 1.6rem; }}
  h2 {{ font-size: 1.05rem; margin: 2rem 0 .5rem; }}
  p, li {{ margin: .5rem 0; }}
  table {{ border-collapse: collapse; margin: .8rem 0; width: 100%; }}
  td {{ padding: .45rem .6rem; border-top: 1px solid #e3e3e8;
        vertical-align: top; }}
  td.note {{ font-family: Consolas, ui-monospace, monospace;
             white-space: nowrap; }}
  .dot {{ display: inline-block; width: .7rem; height: .7rem;
          border-radius: 50%; margin-right: .5rem; }}
  .green {{ background: #3f9c4a; }} .yellow {{ background: #d9a521; }}
  .grey {{ background: #9a9aa2; }} .none {{ background: transparent;
          border: 1px solid #c6c6cf; }}
  .do {{ background: #eef5ee; border-left: 3px solid #3f9c4a;
         padding: .7rem 1rem; margin: 1rem 0; }}
  .warn {{ background: #fdf4e6; border-left: 3px solid #d9a521;
           padding: .7rem 1rem; margin: 1rem 0; }}
  footer {{ margin-top: 2.5rem; color: #76767f; font-size: .85rem; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1c1c1f; color: #e8e8ea; }}
    footer {{ color: #9a9aa2; }}
    td {{ border-top-color: #34343a; }}
    .do {{ background: #1e2a20; }} .warn {{ background: #2b2518; }}
  }}
</style>

<h1>Universal Tool Presets</h1>

<p>Feeds and speeds live in the shop libraries. A document made before
somebody changed them knows nothing about it. UTP puts a note on each
operation saying where it stands.</p>
<p><strong>It never changes an operation's feeds. Only you do, by picking a
preset.</strong></p>

<h2>What the notes mean</h2>
<table>
  <tr><td class="note"><span class="dot green"></span>`UTP Titanium`</td>
      <td>Up to date. Nothing to do.</td></tr>
  <tr><td class="note"><span class="dot yellow"></span>`UTP Titanium
      - update available`</td>
      <td>The shop library has something newer.</td></tr>
  <tr><td class="note"><span class="dot grey"></span>`UTP Custom`</td>
      <td>Its feeds were changed here on purpose.</td></tr>
  <tr><td class="note"><span class="dot none"></span>no note</td>
      <td>Not on a shop preset, or not a shop tool.</td></tr>
</table>

<div class="do">
  <strong>To update a yellow one:</strong> open the operation, go to the tool
  preset dropdown, and pick the entry that <strong>starts with the name in the
  note</strong> and ends <strong>(latest)</strong>. The note turns green.
  Ctrl+Z puts the preset back.
  <p style="margin:.5rem 0 0">A tool used for two materials has a
  <em>(latest)</em> for each, so match the name: for
  <code>`UTP P Copper - update available`</code> pick the P Copper one.</p>
  <p style="margin:.5rem 0 0">Once you have moved, the old entry disappears by
  itself and the new one loses its <em>(latest)</em>, so the dropdown goes back
  to one entry per preset.</p>
</div>

<div class="warn">
  <strong>If a note says "changes the cut"</strong>, the newer preset moves a
  depth of cut or a stepover, not just a feed. Pick it, then
  <strong>regenerate the operation before posting</strong> &mdash; picking a
  preset does not rebuild the toolpath, and Fusion will not tell you. Most
  presets never say this.
</div>

<p>If you would rather leave a yellow one, leave it. Nothing is blocked.</p>

<h2>The buttons</h2>
<table>
  <tr><td><strong>Update presets</strong></td>
      <td>Does the whole job at once: notes, colours, and the newer presets
          added to the dropdowns.</td></tr>
  <tr><td><strong>Check only</strong></td>
      <td>Works out what it would do and writes none of it.</td></tr>
  <tr><td><strong>Remove all notes</strong></td>
      <td>Takes every note and colour out. Presets are left alone.</td></tr>
  <tr><td><strong>Switches</strong></td>
      <td>What it is allowed to do, on this machine. Off means off.</td></tr>
  <tr><td><strong>Open the reports folder</strong></td>
      <td>Every check writes a report of what it found.</td></tr>
  <tr><td><strong>Write a debug report</strong></td>
      <td>One file to send on if something looks wrong.</td></tr>
</table>

<h2>When it runs on its own</h2>
<p>When you open a job, when you enter Manufacture, and when you change an
operation. Never in the background, and saving writes nothing.</p>
<p>Each of those is capped at about two seconds, so a big job may finish over
several of them. <em>Update presets</em> does it all in one go.</p>
<p>The shop libraries are read when you first enter Manufacture, and again
when that reading is over fifteen minutes old. That read is the only real
pause this adds.</p>

<h2>Worth knowing</h2>
<ul>
  <li><strong>Only operations are marked.</strong> Not setups, folders or
      patterns. To see where a folded-up job stands, press
      <em>Update presets</em> and read the report.</li>
  <li><strong>Your own text is kept.</strong> UTP owns one line &mdash; the
      one wrapped in <code>`</code> marks. Write anything you like above or
      below it.</li>
  <li><strong>Your own icon colours are kept</strong> and put back if the
      notes are removed.</li>
  <li><strong>Clear a note's text</strong> to get it out of your way. It comes
      back next time the job opens; to stop that, use <em>Switches</em>.</li>
  <li><strong>Older jobs stay silent</strong> until somebody puts an operation
      on a shop preset.</li>
</ul>

<footer>UTP {version} &mdash; Milling tab, between Setup and 2D.</footer>
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
