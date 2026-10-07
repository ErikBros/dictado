"""Where Ecoscribe keeps its files: %LOCALAPPDATA%/%APPDATA% on Windows, Application Support on macOS."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

MAC_DIR = Path.home() / "Library" / "Application Support" / "Ecoscribe"
OLD_MAC_DIR = Path.home() / "Library" / "Application Support" / "Dictado"  # before the rename (dictado-c9u)
OLD_INSTANCE = "Local\\DictadoSingleInstance"  # the old app's single-instance mutex / lock file


def data_dir() -> Path:
    if sys.platform == "darwin":
        d = Path(os.environ.get("ECOSCRIBE_DATA_DIR") or MAC_DIR)
    else:
        d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ecoscribe"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    if sys.platform == "darwin":
        return Path(os.environ.get("ECOSCRIBE_DATA_DIR") or MAC_DIR) / "config.toml"
    return Path(os.environ.get("APPDATA", Path.home())) / "ecoscribe" / "config.toml"


def downloads_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"


def renamed_dirs() -> list[tuple[Path, Path]]:
    """(old, new) folder pairs from the Dictado days. None when a test points the data dir elsewhere."""
    if sys.platform == "darwin":
        return [] if os.environ.get("ECOSCRIBE_DATA_DIR") else [(OLD_MAC_DIR, MAC_DIR)]
    pairs = []
    for var in ("LOCALAPPDATA", "APPDATA"):  # data + config
        if os.environ.get(var):
            base = Path(os.environ[var])
            pairs.append((base / "dictado", base / "ecoscribe"))
    return pairs


def old_app_running() -> bool:
    """Does a Dictado (before the rename) still hold its single-instance mutex / lock?"""
    if sys.platform == "darwin":
        import fcntl
        lock = OLD_MAC_DIR / "run" / "DictadoSingleInstance.lock"
        if not lock.exists():
            return False
        fd = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)
    try:
        import win32api
        import win32event
        h = win32event.OpenMutex(0x00100000, False, OLD_INSTANCE)  # SYNCHRONIZE; fails when nobody holds it
    except Exception:
        return False
    win32api.CloseHandle(h)
    return True


def migrate(old: Path, new: Path, old_running=old_app_running, tries: int = 10) -> str:
    """Move the Dictado folder to the Ecoscribe one (dictado-c9u). Returns what it did:
    "none" no old folder, "moved", "kept" both exist (the new one wins, the old one is left alone),
    "busy" an old Dictado still runs (try again next start), "failed" the move itself failed."""
    old, new = Path(old), Path(new)
    if not old.is_dir():
        return "none"
    if old_running():
        return "busy"
    if new.is_dir() and all(p.is_file() and p.suffix == ".log" for p in new.iterdir()):
        shutil.rmtree(new, ignore_errors=True)  # empty, or only the log of an early start (an --mcp run
    if new.exists():                            # while the old app held the lock): not data worth keeping
        return "kept"
    new.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            old.rename(new)  # same volume: instant, and all or nothing
            break
        except OSError:  # a just-killed old window's WebView2 can hold files for a moment
            if i == tries - 1:
                return "failed"
            time.sleep(0.5)
    _repoint_meetings(new / "meetings.json", old, new)
    return "moved"


def _repoint_meetings(state: Path, old: Path, new: Path) -> None:
    """meetings.json keeps absolute folders of queued jobs: point them at the moved folder."""
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    o = str(old)

    def fix(v):
        if isinstance(v, str) and (v == o or v.startswith(o + os.sep)):
            return str(new) + v[len(o):]
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v
    state.write_text(json.dumps(fix(data), indent=2, ensure_ascii=False), encoding="utf-8")


def migrate_all(old_running=old_app_running) -> list[tuple[Path, Path, str]]:
    """Every folder pair, what happened to each (logged once logging is up)."""
    return [(o, n, migrate(o, n, old_running)) for o, n in renamed_dirs()]
