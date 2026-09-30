"""What happened, written to disk as it happens.

Written line by line rather than all at the end, because Fusion crashes and a
report that only exists in memory is no report at all. This file is how a
complaint of "it marked the wrong thing" gets answered.
"""

import datetime
import json
import os
import traceback

from . import config, marks


class Report:
    """One pass over one document."""

    def __init__(self, document_name):
        self.document_name = document_name
        self.started = datetime.datetime.now()
        stamp = self.started.strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in " -_" else "_"
                       for c in (document_name or "unnamed"))[:60].strip()
        self.dir = config.REPORT_DIR
        self.base = os.path.join(self.dir, "%s - %s" % (stamp, safe or "unnamed"))
        self.lines = []
        self.operations = []
        self.counts = {}
        self.wrote = 0          # counted, so the header cannot claim otherwise
        try:
            os.makedirs(self.dir, exist_ok=True)
            self.stream = open(self.base + ".jsonl", "a", encoding="utf-8")
        except Exception:
            # A report that cannot be written must not stop the pass.
            self.stream = None

    # -- writing --------------------------------------------------------

    def _emit(self, kind, payload):
        entry = {"at": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                 "kind": kind}
        entry.update(payload)
        if self.stream is not None:
            try:
                self.stream.write(json.dumps(entry, default=str) + "\n")
                self.stream.flush()
            except Exception:
                pass
        return entry

    def note(self, message, **detail):
        self.lines.append((message, detail))
        self._emit("note", dict(detail, message=message))

    def failed(self, message):
        self.note(message, traceback=traceback.format_exc())

    def operation(self, verdict):
        """One operation's verdict, as state.reconcile returned it."""
        self.operations.append(verdict)
        self.counts[verdict["state"]] = self.counts.get(verdict["state"], 0) + 1
        self._emit("operation", verdict)

    # -- finishing ------------------------------------------------------

    def close(self):
        seconds = (datetime.datetime.now() - self.started).total_seconds()
        self._emit("finished", {"seconds": round(seconds, 2),
                                "counts": self.counts})
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
        path = self.base + ".md"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._markdown(seconds))
        except Exception:
            return None
        return path

    def _what_happened(self):
        if self.wrote:
            return ("%d change%s written to this document."
                    % (self.wrote, "" if self.wrote == 1 else "s"))
        if config.MAY_WRITE_ON_DEMAND:
            return "Writing was allowed; nothing needed changing."
        return "Nothing was changed."

    def _markdown(self, seconds):
        out = ["# UTP check - %s" % self.document_name,
               "",
               "%s, %.1fs. %s"
               % (self.started.strftime("%Y-%m-%d %H:%M:%S"), seconds,
                  self._what_happened()),
               ""]
        if self.counts:
            out += ["## Verdicts", ""]
            for state in sorted(self.counts):
                out.append("- **%s:** %d" % (state, self.counts[state]))
            out.append("")
        if self.operations:
            found = sum(1 for e in self.operations
                        if e.get("preset found in library") is True)
            missing = sum(1 for e in self.operations
                          if e.get("preset found in library") is False)
            matched = {}
            for entry in self.operations:
                key = entry.get("matched by") or "no tool"
                matched[key] = matched.get(key, 0) + 1
            out += ["## Identity", "",
                    "- **tools matched:** %s" % ", ".join(
                        "%s %s" % (matched[k], k) for k in sorted(matched)),
                    "- **preset found in the library by id:** %d of %d"
                    % (found, found + missing),
                    ""]
            would = [e for e in self.operations if e.get("would")]
            kinds = {}
            for entry in would:
                for key in entry["would"]:
                    kinds[key] = kinds.get(key, 0) + 1
            heading = ("## What it wrote"
                       if self.wrote or config.MAY_WRITE_ON_DEMAND
                       else "## What it would write, if writing were on")
            out += [heading, "", self._what_happened(), ""]
            for key in sorted(kinds):
                out.append("- **%s:** %d operations" % (key, kinds[key]))
            for message, detail in self.lines:
                if "did" in detail:
                    out.append("- **the document tool library:** %s"
                               % ", ".join(detail["did"]))
            if not kinds and not self.wrote:
                out.append("- nothing on any operation")
            out.append("")
        if self.lines:
            out += ["## What happened", ""]
            for message, detail in self.lines:
                out.append("- %s" % message)
                for key in sorted(detail):
                    if key == "traceback":
                        continue
                    out.append("    - %s: `%s`" % (key, detail[key]))
            out.append("")
        if self.operations:
            out += ["## Operations", "",
                    "| Operation | Verdict | Would do | Preset | What moved |",
                    "| --- | --- | --- | --- | --- |"]
            for entry in self.operations:
                changed = entry.get("changed") or {}
                moved = "<br>".join("`%s` %s" % (k, changed[k])
                                    for k in sorted(changed)) or entry.get("why", "")
                out.append("| %s | %s | %s | %s | %s |" % (
                    entry.get("operation", "?"),
                    entry.get("state", "?"),
                    marks.describe(entry.get("would") or {}),
                    entry.get("preset") or "none",
                    moved))
            out.append("")
        return "\n".join(out)

# ---------------------------------------------------------------------------
# The session log
# ---------------------------------------------------------------------------
#
# Events arrive while somebody works, so they cannot wait for a report to be
# assembled at the end. They append to one file per Fusion session, flushed
# every line, which is also what makes a crash leave evidence behind.

_session = {"stream": None, "path": None, "count": 0}


def session_path():
    return _session["path"]


def session_count():
    return _session["count"]


def session_log(kind, **detail):
    if _session["stream"] is None:
        try:
            os.makedirs(config.REPORT_DIR, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            _session["path"] = os.path.join(
                config.REPORT_DIR, "events-%s.jsonl" % stamp)
            _session["stream"] = open(_session["path"], "a", encoding="utf-8")
        except Exception:
            return
    entry = {"at": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
             "kind": kind}
    entry.update(detail)
    try:
        _session["stream"].write(json.dumps(entry, default=str) + "\n")
        _session["stream"].flush()
        _session["count"] += 1
    except Exception:
        pass


def close_session():
    if _session["stream"] is not None:
        try:
            _session["stream"].close()
        except Exception:
            pass
    _session["stream"] = None
