"""status.json: what the background app is doing, for the window to show."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def read(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(path: Path, **fields) -> dict:
    """Merge fields into the current status and write it atomically."""
    path = Path(path)
    cur = read(path) or {}
    cur.update(fields, ts=time.time(), pid=os.getpid())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    for _ in range(20):  # the window may be reading it this instant
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            time.sleep(0.02)
    return cur
