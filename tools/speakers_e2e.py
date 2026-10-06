"""Speakers pass E2E against the RUNNING (installed) Dictado + add-on (t0u.22): import files over
the command channel, wait for transcript + speakers pass, report speaker counts. No sound, no input.

    python tools/speakers_e2e.py FILE[:expected_speakers] ... [--keep]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from dictado import commands, paths, sessions  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    data, root = paths.data_dir(), paths.data_dir() / "transcripts"
    before = {p.name for p in root.iterdir()}
    want = {}
    for f in a.files:
        path, _, n = f.rpartition(":") if f.count(":") > 1 else (f, "", "")
        want[Path(path).stem] = int(n) if n else None
    files = [f.rpartition(":")[0] if f.count(":") > 1 else f for f in a.files]
    out = commands.send(data, "import_files", {"paths": files, "lang": "auto"})
    print("import", out, flush=True)
    t0, ok = time.monotonic(), True
    while time.monotonic() - t0 < 1800:
        new = [p for p in root.iterdir() if p.name not in before]
        metas = [sessions.read_meta(p) for p in new]
        if len(new) == len(files) and all(m.get("status") in ("done", "failed") and m.get("speakers") in ("done", "failed", None)
                                          and not (m.get("status") == "done" and m.get("speakers") is None) for m in metas):
            break
        time.sleep(3)
    for p in sorted(p for p in root.iterdir() if p.name not in before):
        m = sessions.read_meta(p)
        segs = json.loads((p / "transcript.json").read_text(encoding="utf-8"))["segments"] if (p / "transcript.json").exists() else []
        labels = Counter(s.get("speaker") for s in segs)
        exp = next((v for k, v in want.items() if sessions.slug(k) in p.name), None)
        good = m.get("status") == "done" and m.get("speakers") == "done" and (exp is None or m.get("speakers_n") == exp)
        ok &= good
        print(("ok   " if good else "FAIL ") + f"{p.name}: status={m.get('status')} speakers={m.get('speakers')} "
              f"n={m.get('speakers_n')} expected={exp} labels={dict(labels)} {m.get('speakers_error') or ''}", flush=True)
        if not a.keep:
            shutil.rmtree(p, ignore_errors=True)
    print(f"total {time.monotonic() - t0:.0f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
