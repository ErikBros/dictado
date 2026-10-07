"""Window -> background app commands (start/stop a meeting, import files).

The window is its own process and never spawns workers: it writes
<data>/commands/<id>.json and sets Local\\EcoscribeCommand; the background app's
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
EVENT = "Local\\EcoscribeCommand"
NOT_RUNNING = "Ecoscribe isn't running"


def _dir(data_dir: Path) -> Path:
    d = Path(data_dir) / "commands"
    d.mkdir(parents=True, exist_ok=True)
    return d


if sys.platform == "darwin":  # a Unix socket instead of the named event (ecoscribe/platform/macos/commands.py)
    from .platform.macos.commands import Watcher, _signal  # noqa: F401
else:  # the named event Local\\EcoscribeCommand (ecoscribe/platform/windows/commands.py)
    from .platform.windows.commands import Watcher, _signal  # noqa: F401


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
            threading.Thread(target=run, name="ecoscribe-import", daemon=True).start()
            return {"ok": True, "queued": len(paths)}
        return {"ok": False, "error": f"unknown command: {cmd}"}
    return handle
