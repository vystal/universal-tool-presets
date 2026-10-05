"""Send a job to Fusion and wait for the answer.

    python tools/ask_fusion.py job.py              # read-only
    python tools/ask_fusion.py job.py --writes     # may write to the test document
    python tools/ask_fusion.py --ready             # is the agent alive?
    python tools/ask_fusion.py -c "say(app.version)"

The job is ordinary Python, run inside Fusion on its main thread. It is handed
`adsk`, `app`, `ui`, `guard`, and `say(...)` for anything it wants in the
answer, because print() goes nowhere in Fusion. Anything it leaves in a
variable called `answer` comes back too, as JSON where that is possible.

Exits 0 when the job ran, 1 when it raised, 2 when the agent never answered.
A timeout here means Fusion is busy, blocked on a dialog, or gone.
"""

import argparse
import json
import os
import sys
import time
import uuid

QUEUE = os.path.join(os.path.expanduser("~"), "Documents", "UTP diagnostics",
                     "agent")
HEARTBEAT = os.path.join(QUEUE, "ready.json")


def ready(stale=10.0):
    """Whether the agent has said anything recently. (alive, what it said)"""
    try:
        beat = json.load(open(HEARTBEAT, encoding="utf-8"))
    except Exception:
        return False, None
    beat["seconds since"] = round(time.time() - beat.get("at", 0), 1)
    return beat["seconds since"] < stale and beat.get("state") == "ready", beat


def send(code, writes=False, timeout=180.0, quiet_for=20.0):
    """Drop a job and wait. Returns the result dict, or None if it never came.

    Two clocks on purpose. timeout is how long the job itself may take, since a
    pass over a real document is slow. quiet_for is how long the agent may go
    without a heartbeat before it is called dead, which is what tells a slow
    job apart from a Fusion that has stopped.
    """
    os.makedirs(QUEUE, exist_ok=True)
    name = time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:6]
    job = os.path.join(QUEUE, name + ".job.json")
    result = os.path.join(QUEUE, name + ".result.json")
    temporary = job + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"id": name, "writes": writes, "code": code}, handle)
    # Written aside and moved, so the watcher cannot pick up half a job.
    os.replace(temporary, job)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(result):
            for _attempt in range(10):
                try:
                    return json.load(open(result, encoding="utf-8"))
                except Exception:
                    time.sleep(0.05)
        alive, beat = ready(stale=quiet_for)
        if beat is None or beat.get("seconds since", 0) > quiet_for:
            if not os.path.exists(result):
                return None
        time.sleep(0.2)
    return None


def show(result):
    if result is None:
        alive, beat = ready()
        print("NO ANSWER. The agent did not reply.")
        print("   heartbeat: %s" % (json.dumps(beat) if beat else "none at all"))
        print("   Fusion is busy, waiting on a dialog, or not running.")
        return 2
    for line in result.get("said") or []:
        print("   " + line)
    if "answer" in result:
        print("   answer: " + json.dumps(result["answer"], indent=2)[:4000])
    if result.get("held back"):
        print("HELD BACK: %s" % result["held back"])
        return 1
    if not result.get("ok"):
        print("FAILED after %ss:" % result.get("seconds"))
        print((result.get("error") or "no reason given").rstrip())
        return 1
    print("ok, %ss%s" % (result.get("seconds"),
                         ", writing allowed" if result.get("writing") else ""))
    return 0


def main():
    parse = argparse.ArgumentParser()
    parse.add_argument("job", nargs="?", help="a .py file to run inside Fusion")
    parse.add_argument("-c", "--code", help="code to run instead of a file")
    parse.add_argument("--writes", action="store_true",
                       help="ask to write to the test document")
    parse.add_argument("--ready", action="store_true",
                       help="just say whether the agent is alive")
    parse.add_argument("--timeout", type=float, default=180.0)
    said = parse.parse_args()

    if said.ready:
        alive, beat = ready()
        print(json.dumps(beat, indent=2) if beat else "no heartbeat at all")
        return 0 if alive else 2
    code = said.code or (open(said.job, encoding="utf-8").read()
                         if said.job else None)
    if not code:
        parse.error("give a job file, or -c")
    return show(send(code, writes=said.writes, timeout=said.timeout))


if __name__ == "__main__":
    sys.exit(main())
