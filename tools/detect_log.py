"""Passive meeting-detector logger (log-only mode, pre-mortem #1).

Polls the ConsentStore + window titles every 2 s, forever, and appends to
%LOCALAPPDATA%\\ecoscribe\\detector.log:
  <iso time> startup pid=<pid>
  <iso time> mic_on|mic_off <app>
  <iso time> start|end <app> titles=[<matching meeting titles>]
Never prompts, never records audio, never touches the desktop. One copy at a time.

    pythonw tools/detect_log.py [--once] [--log PATH]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecoscribe import detect, paths  # noqa: E402


def line(log: Path, *parts) -> None:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join([datetime.now().isoformat(timespec="seconds"), *map(str, parts)]) + "\n")


def poll(det: detect.Detector, prev: set[str], log: Path) -> set[str]:
    uses = detect.read_consent()
    titles = detect.window_titles()
    running = detect.running_apps()
    now_in_use = {u.app for u in uses if u.in_use}
    for app in sorted(now_in_use - prev):
        line(log, "mic_on", app)
    for app in sorted(prev - now_in_use):
        line(log, "mic_off", app)
    ev = det.update(uses, titles, time.monotonic(), running=running)
    if ev:
        matched = [f"{t} ({exe})" for t, exe in titles if detect.MEETING_TITLE.search(t)]
        line(log, ev.kind, ev.app, f"titles={matched}")
    return now_in_use


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--once", action="store_true", help="one poll, then exit (smoke test)")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args(argv)
    log = a.log or paths.data_dir() / "detector.log"
    if not a.once:
        from ecoscribe import winutil
        if not winutil.single_instance("Local\\EcoscribeDetectLog"):
            return 0
    line(log, "startup", f"pid={os.getpid()}", "once" if a.once else "")
    det, prev = detect.Detector(), set()
    while True:
        try:
            prev = poll(det, prev, log)
        except Exception as e:  # keep logging through transient registry/window errors
            line(log, "error", f"{type(e).__name__}: {e}")
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
