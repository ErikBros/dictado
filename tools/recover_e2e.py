"""Killed-meeting recovery E2E against the RUNNING (installed) Dictado (t0u.18): start a
meeting over the command channel, hard-kill its worker the way the 1.2.2 installer did
(taskkill /F), and check the background app turns what was recorded into a finished,
labelled transcript on its own. Plays no sound; the test session is deleted afterwards.

    python tools/recover_e2e.py [--seconds 15] [--keep]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from dictado import commands, meetings, paths, sessions  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--keep", action="store_true", help="leave the test session in Meetings")
    a = ap.parse_args(argv)
    data = paths.data_dir()
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)

    st = meetings.read_state(data)
    if st.get("meeting") or st.get("job"):
        print("something is recording or transcribing: not touching it", st)
        return 2
    out = commands.send(data, "start_meeting", {"lang": "en", "title": "Prueba recuperar"})
    check("start_meeting answered by the running app", out.get("ok"), out)
    if not out.get("ok"):
        return 1
    d = Path(out["dir"])
    t0 = time.monotonic()
    while not (d / "audio" / "mix.flac").exists() and time.monotonic() - t0 < 120:
        time.sleep(0.5)
    time.sleep(a.seconds)
    pid = (meetings.read_state(data).get("meeting") or {}).get("pid")
    check("meeting worker pid known", pid, pid)
    r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
    check("worker killed", r.returncode == 0, r.stdout.strip() or r.stderr.strip())
    t0 = time.monotonic()
    while sessions.read_meta(d).get("status") not in ("done", "failed") and time.monotonic() - t0 < 300:
        time.sleep(1)
    meta = sessions.read_meta(d)
    check("recovered, not failed", meta.get("status") == "done", f"{meta.get('status')} {meta.get('error')}")
    check("marked recovered", meta.get("recovered"), meta.get("recovered"))
    check("duration covers what was recorded", (meta.get("duration_s") or 0) >= a.seconds * 0.8, meta.get("duration_s"))
    t0 = time.monotonic()  # labels and exports come after "done", then the job worker exits
    while meetings.read_state(data).get("job") and time.monotonic() - t0 < 60:
        time.sleep(0.5)
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8")) if (d / "transcript.json").exists() else {}
    segs = tr.get("segments", [])
    check("segments labelled (or none: a quiet room)", all(s.get("speaker") in ("Me", "Others") for s in segs), len(segs))
    for ext in ("txt", "md", "srt"):
        check(f"transcript.{ext}", (d / f"transcript.{ext}").exists())
    st = meetings.read_state(data)
    check("controller idle again", not st.get("meeting") and not st.get("job"), st)
    if not a.keep:
        shutil.rmtree(d, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
