"""Transcription sessions: one folder per meeting or imported file.

<root>/<yyyy-mm-dd_hhmm>_<slug>[-N]/ holds audio/, meta.json, transcript.json,
transcript.{txt,md,srt} and progress.json. Plain files: the user and Claude read them.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)
META = "meta.json"


def root_dir(cfg_root: str = "") -> Path:
    return Path(cfg_root) if cfg_root else paths.data_dir() / "transcripts"


def slug(title: str) -> str:
    """Folder-safe ascii slug; Windows-illegal characters can't survive [a-z0-9-]."""
    s = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or "sesion"


def replace_retry(tmp: Path, path: Path, tries: int = 20, wait_s: float = 0.05) -> None:
    """os.replace, retried: on Windows it raises PermissionError while any reader (the
    window polling the file, antivirus) has the target open."""
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                try:
                    os.unlink(tmp)  # don't leave an orphan .tmp behind
                except OSError:
                    pass
                raise
            time.sleep(wait_s)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_retry(tmp, path)


def create(title: str, lang: str, source: str, root: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = f"{now:%Y-%m-%d_%H%M}_{slug(title)}"
    n = 1
    while True:
        d = root / (base if n == 1 else f"{base}-{n}")
        try:
            d.mkdir()  # atomic claim: two creators in the same minute can't share a folder
            break
        except FileExistsError:
            n += 1
    (d / "audio").mkdir()
    _write_json(d / META, {"title": title, "lang": lang, "source": source,
                           "created": now.isoformat(timespec="seconds"), "status": "new",
                           "duration_s": None, "model": None, "compute_type": None, "slow": False})
    return d


def import_file(src: Path, lang: str, root: Path, title: str | None = None) -> Path:
    src = Path(src)
    d = create(title or src.stem, lang, "import", root)
    shutil.copy2(src, d / "audio" / src.name)
    return d


def read_meta(d: Path) -> dict:
    return json.loads((Path(d) / META).read_text(encoding="utf-8"))


def write_meta(d: Path, **changes) -> dict:
    m = read_meta(d)
    m.update(changes)
    _write_json(Path(d) / META, m)
    return m


def list_sessions(root: Path) -> list[dict]:
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            m = read_meta(d)
        except Exception as e:
            log.warning("session %s skipped: unreadable meta (%s)", d.name, e)
            continue
        m["dir"] = str(d)
        out.append(m)
    out.sort(key=lambda m: (str(m.get("created", "")), Path(m["dir"]).name), reverse=True)
    return out


def rename(d: Path, title: str) -> dict:
    return write_meta(d, title=title)


def delete(d: Path) -> None:
    shutil.rmtree(d)
