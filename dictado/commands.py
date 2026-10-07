"""Window -> background app commands (start/stop a meeting, import files).

The window is its own process and never spawns workers: it writes
<data>/commands/<id>.json and sets Local\\DictadoCommand; the background app's
CommandWatcher runs it on the meetings Controller and writes <id>.done.json.
Nobody answering within `wait_s` means the background app isn't running: the
request is removed and the page is told, nothing waits in a folder for days.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)
EVENT = "Local\\DictadoCommand"
NOT_RUNNING = "Dictado isn't running"


def _dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "commands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _signal(name: str = EVENT) -> bool:
    import win32con
    import win32event
    try:
        h = win32event.OpenEvent(win32con.EVENT_MODIFY_STATE, False, name)
    except Exception:
        return False
    win32event.SetEvent(h)
    return True


if sys.platform == "darwin":  # a Unix socket instead of the named event (dictado/platform/macos/commands.py)
    from .platform.macos.commands import _signal  # noqa: F811


def send(data_dir: Path, cmd: str, args: dict | None = None, wait_s: float = 3.0, signal=_signal,
         sleep=time.sleep) -> dict:
    d = _dir(data_dir)
    cid = uuid.uuid4().hex
    req, done = d / f"{cid}.json", d / f"{cid}.done.json"
    tmp = d / f"{cid}.tmp"
    tmp.write_text(json.dumps({"cmd": cmd, "args": args or {}}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, req)
    if signal():
        t_end = time.monotonic() + wait_s
        while time.monotonic() < t_end:
            if done.exists():
                try:
                    out = json.loads(done.read_text(encoding="utf-8"))
                    done.unlink()
                    return out
                except (OSError, ValueError):
                    pass  # still being written
            sleep(0.05)
    try:
        req.unlink()
    except OSError:  # taken at the last moment: its answer is lost, the action still happened
        pass
    return {"ok": False, "error": NOT_RUNNING}


def run_pending(data_dir: Path, handler) -> int:
    """Run every waiting request through handler(cmd, args) -> dict. Returns how many ran."""
    n = 0
    old = time.time() - 60
    for stale in _dir(data_dir).glob("*.done.json"):  # answers nobody waited for (sender timed out)
        try:
            if stale.stat().st_mtime < old:
                stale.unlink()
        except OSError:
            pass
    for req in sorted(_dir(data_dir).glob("*.json")):
        if req.name.endswith(".done.json"):
            continue
        try:
            msg = json.loads(req.read_text(encoding="utf-8"))
            req.unlink()
        except (OSError, ValueError):
            continue  # half-written, or the sender gave up and removed it
        try:
            out = handler(msg.get("cmd"), msg.get("args") or {})
        except Exception as e:
            log.exception("command %s failed", msg.get("cmd"))
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        done = req.with_name(req.stem + ".done.json")
        tmp = req.with_name(req.stem + ".done.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, done)
        n += 1
    return n


class Watcher(threading.Thread):
    """Background app side: waits on the event (and every 5 s anyway) and runs requests."""

    def __init__(self, data_dir: Path, handler, name: str = EVENT):
        import win32event
        super().__init__(name="dictado-commands", daemon=True)
        self.data_dir, self.handler, self._we = Path(data_dir), handler, win32event
        self._event = win32event.CreateEvent(None, False, False, name)
        self._stop = win32event.CreateEvent(None, True, False, None)

    def run(self) -> None:
        while True:
            r = self._we.WaitForMultipleObjects([self._event, self._stop], False, 5000)
            if r == self._we.WAIT_OBJECT_0 + 1:
                return
            try:
                run_pending(self.data_dir, self.handler)
            except Exception:
                log.exception("command watcher failed")

    def stop(self) -> None:
        self._we.SetEvent(self._stop)


if sys.platform == "darwin":
    from .platform.macos.commands import Watcher  # noqa: F811


def handler_for(ctl, watch=None, manual_key: str = "_manual"):
    """The background app's command table over a meetings Controller."""
    def handle(cmd: str, args: dict) -> dict:
        if cmd == "start_meeting":
            lang = args.get("lang") or (watch.lang_for(manual_key) if watch else "sv")
            if watch:
                watch.remember(manual_key, lang)
            app = getattr(watch, "call_app_now", lambda: None)() if watch else None
            return {"ok": True, "dir": str(ctl.start_meeting(lang, title=args.get("title") or "Meeting", app=app))}
        if cmd == "set_meeting_lang":
            lang = args.get("lang") or ""
            from .languages import valid_meeting_lang
            if not valid_meeting_lang(lang):
                return {"ok": False, "error": f"unknown language: {lang}"}
            return {"ok": True} if ctl.set_lang(lang) else {"ok": False, "error": "No meeting is recording"}
        if cmd == "stop_meeting":
            ctl.stop_meeting()
            return {"ok": True}
        if cmd == "import_files":  # copying a big video takes longer than the sender waits: answer first
            paths, lang = [Path(p) for p in args.get("paths", [])], args.get("lang") or "auto"
            missing = [str(p) for p in paths if not p.is_file()]
            if missing:
                return {"ok": False, "error": "Not found: " + ", ".join(missing)}

            def run():
                for p in paths:
                    try:
                        ctl.enqueue_file(p, lang)
                    except Exception:
                        log.exception("import of %s failed", p)
            threading.Thread(target=run, name="dictado-import", daemon=True).start()
            return {"ok": True, "queued": len(paths)}
        return {"ok": False, "error": f"unknown command: {cmd}"}
    return handle
