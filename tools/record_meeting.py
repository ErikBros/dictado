"""Record and live-transcribe a real meeting from a terminal (stage 2 hand-off for the user's call).

    python tools/record_meeting.py --lang sv [--minutes 10] [--title "Reunión"]

Starts `ecoscribe --meeting` on a new session folder, prints the live transcript as
it arrives, and stops after --minutes or on Ctrl+C (writes the stop file, so the
worker finishes the FLACs and runs the final pass). Prints where everything is.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from ecoscribe import config, paths, sessions  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="sv", help="sv, en, es, el or auto")
    ap.add_argument("--minutes", type=float, default=0, help="stop by itself after N minutes (0 = Ctrl+C)")
    ap.add_argument("--title", default="Reunión")
    a = ap.parse_args(argv)
    cfg = config.load(paths.config_path()).transcribe
    d = sessions.create(a.title, a.lang, "meeting", sessions.root_dir(cfg.root))
    print(f"Sesión: {d}")
    p = subprocess.Popen([sys.executable, "-m", "ecoscribe", "--meeting", str(d)], cwd=str(APP))
    live, seen, t0 = d / "live.jsonl", 0, time.monotonic()
    try:
        while p.poll() is None:
            if a.minutes and time.monotonic() - t0 > a.minutes * 60:
                break
            if live.exists():
                lines = live.read_text(encoding="utf-8").splitlines()
                for line in lines[seen:]:
                    x = json.loads(line)
                    print(f"[{x['t0']:7.1f}s, {x['lag_s']:+.1f}s] {x['text']}", flush=True)
                seen = len(lines)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    print("Parando: guardando y haciendo la pasada final...")
    (d / "stop").write_text("", encoding="utf-8")
    p.wait()
    meta = sessions.read_meta(d)
    print(f"Estado: {meta['status']}  grabado: {meta.get('recorded_s')} s  modelo: {meta.get('model')}")
    print(f"Transcripción: {d / 'transcript.md'}")
    return 0 if meta["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
