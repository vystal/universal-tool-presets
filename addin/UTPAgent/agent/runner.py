"""Runs code sent from outside, on Fusion's main thread, and says what happened.

Why this exists: nearly every question about this add-in that mattered turned
out to be a question about how Fusion behaves, and those cannot be answered by
reading code. They were answered by writing a test, waiting for somebody to
press Run in Fusion, and reading a file. That loop is a day long. This makes it
seconds.

How it works, and why it has to work this way. Fusion has no headless mode and
no way to run a script from a command line: it must be running, with its
window. And the API is main-thread only, so nothing outside the process can
call it. The one documented way in is Application.registerCustomEvent, which
exists for exactly this: a worker thread calls fireCustomEvent, and the handler
runs on the main thread next time Fusion is idle.

So: a worker thread watches a folder. A job file appears. It fires the event.
The handler runs the job on the main thread and writes the answer next to it.

The queue folder is the trust boundary, and it is a real one: anything that can
write a file there runs code inside Fusion. It lives under the user's own
profile, there is no socket and nothing listening on the network, and the agent
only runs when its add-in is loaded. Deleting the add-in, or dropping a file
called STOP in the queue, ends it.
"""

import json
import os
import threading
import time
import traceback

import adsk.core

from . import guard

EVENT_ID = "utpAgentJob"

HOME = os.path.expanduser("~")
QUEUE = os.path.join(HOME, "Documents", "UTP diagnostics", "agent")
HEARTBEAT = os.path.join(QUEUE, "ready.json")
STOP = os.path.join(QUEUE, "STOP")

# How often the worker looks. Short enough to feel immediate, long enough to
# cost nothing: this thread does one listdir and goes back to sleep.
EVERY = 0.4

_state = {"event": None, "handler": None, "thread": None, "running": False,
          "jobs": 0}


# ---------------------------------------------------------------------------
# The worker thread: watches, and does nothing else
# ---------------------------------------------------------------------------

def _watch():
    """Looks for jobs and hands each to the main thread. Touches no API."""
    app = adsk.core.Application.get()
    while _state["running"]:
        try:
            if os.path.exists(STOP):
                _beat("stopping", note="a STOP file is in the queue")
                _state["running"] = False
                return
            for name in sorted(os.listdir(QUEUE)):
                if not name.endswith(".job.json"):
                    continue
                path = os.path.join(QUEUE, name)
                # Claimed by renaming before it is fired, so a job cannot be
                # picked up twice if the handler is slow or Fusion is busy.
                taken = path[: -len(".job.json")] + ".taken.json"
                try:
                    os.replace(path, taken)
                except Exception:
                    continue
                app.fireCustomEvent(EVENT_ID, taken)
            _beat("ready")
        except Exception:
            # The watcher must not die: if it does, nothing says so and the
            # whole arrangement looks like Fusion hanging.
            try:
                _beat("watcher error", error=traceback.format_exc())
            except Exception:
                pass
        time.sleep(EVERY)


def _beat(what, **detail):
    """Say the agent is alive, so a caller can tell waiting from dead."""
    detail.update({"state": what, "at": time.time(),
                   "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "jobs run": _state["jobs"], "pid": os.getpid()})
    _write(HEARTBEAT, detail)


# ---------------------------------------------------------------------------
# The main thread: runs the job
# ---------------------------------------------------------------------------

class _Handler(adsk.core.CustomEventHandler):
    def notify(self, args):
        path = None
        try:
            path = args.additionalInfo
            _run(path)
        except Exception:
            # Even a failure to report has to be reported, or a job that broke
            # the agent is indistinguishable from one still running.
            if path:
                _write(_result_path(path),
                       {"ok": False, "error": traceback.format_exc()})


def _result_path(taken):
    return taken[: -len(".taken.json")] + ".result.json"


def _run(taken):
    app = adsk.core.Application.get()
    started = time.time()
    said = []
    result = {"ok": False, "said": said}
    try:
        job = json.loads(open(taken, "r", encoding="utf-8").read())
    except Exception:
        _write(_result_path(taken),
               {"ok": False, "error": "the job file could not be read:\n"
                                      + traceback.format_exc()})
        return

    result["id"] = job.get("id")
    wants_writing = bool(job.get("writes"))
    allowed, refusal = guard.may_write(app) if wants_writing else (False, None)
    if wants_writing and not allowed:
        # Refused rather than run read-only: a writing job whose writes were
        # silently dropped reports a pass for the wrong reason, which is worse
        # than not running.
        result["error"] = "held back: " + refusal
        result["held back"] = refusal
        _finish(taken, result, started)
        return
    result["writing"] = allowed

    def say(*parts):
        """What the job wants in the answer. print() goes nowhere in Fusion."""
        said.append(" ".join(str(p) for p in parts))

    room = {"adsk": adsk, "app": app, "ui": app.userInterface, "say": say,
            "guard": guard, "json": json, "os": os, "time": time}
    if allowed:
        guard.hold_library_writes()
    try:
        exec(job.get("code") or "", room)      # noqa: S102 - the whole point
        result["ok"] = True
        value = room.get("answer")
        if value is not None:
            result["answer"] = _plain(value)
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        if allowed:
            guard.let_library_writes_go()
    _finish(taken, result, started)


def _finish(taken, result, started):
    result["seconds"] = round(time.time() - started, 3)
    _state["jobs"] += 1
    _write(_result_path(taken), result)
    try:
        os.remove(taken)
    except Exception:
        pass


def _plain(value):
    """Whatever the job left in `answer`, as something JSON can hold."""
    try:
        json.dumps(value)
        return value
    except Exception:
        return repr(value)


def _write(path, payload):
    temporary = path + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=repr)
    os.replace(temporary, path)


# ---------------------------------------------------------------------------

def start():
    app = adsk.core.Application.get()
    os.makedirs(QUEUE, exist_ok=True)
    try:
        os.remove(STOP)
    except Exception:
        pass
    # Registered fresh: a stale registration from a previous load of the
    # add-in would send jobs to a handler that no longer exists.
    try:
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    event = app.registerCustomEvent(EVENT_ID)
    handler = _Handler()
    event.add(handler)
    _state["event"], _state["handler"] = event, handler
    _state["running"] = True
    thread = threading.Thread(target=_watch, daemon=True)
    _state["thread"] = thread
    thread.start()
    _beat("ready", note="agent loaded")
    return QUEUE


def stop():
    app = adsk.core.Application.get()
    _state["running"] = False
    try:
        if _state["event"] and _state["handler"]:
            _state["event"].remove(_state["handler"])
        app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
    _beat("stopped")
