"""Crash reports (t0u.37): so a crash is never silent and always debuggable.

The background app turns on faulthandler at start, writing to crashes/live/fault-<pid>.log:
a native crash (an access violation in a Windows call, like 2026-10-06 14:03) then leaves the
Python stack of every thread there, which a normal log can't. Python errors on any thread go
to dictado.log through the except hooks. When the app dies, the supervisor (supervise.py)
turns that into a report folder crashes/<time>/ and restarts it:

    report.md     what happened, in one screen: time, version, exit code, the crashing line
    fault.log     faulthandler's native trace
    log-tail.txt  the last 300 lines of dictado.log
    status.json   what the app said it was doing
    config.toml   the settings (the calendar link removed: it's a secret)

Two markers: `seen-user` (dismissed on Home), `seen-claude` (Claude read it; a Claude Code
SessionStart hook can announce reports without it).
"""
from __future__ import annotations

import faulthandler
import logging
import re
import shutil
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
TAIL = 300
EXIT_NAMES = {0xC0000005: "access violation", 0xC0000409: "stack buffer overrun", 0xC00000FD: "stack overflow",
              0xC0000374: "heap corruption", 0xC0000135: "DLL not found", 0x40010004: "killed by Windows",
              0xC000013A: "Ctrl+C / console closed", 1: "exit code 1"}
_fault_file = None  # kept open for the life of the process: faulthandler writes to its fd


def crashes_dir(data: Path) -> Path:
    return Path(data) / "crashes"


def fault_path(data: Path, pid: int) -> Path:
    return crashes_dir(data) / "live" / f"fault-{pid}.log"


def enable(data: Path, pid: int) -> None:
    """Native crash trace to a file + Python errors on every thread to the log."""
    global _fault_file
    p = fault_path(data, pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    _fault_file = open(p, "w", encoding="utf-8")  # noqa: SIM115 (must stay open)
    faulthandler.enable(_fault_file, all_threads=True)
    if sys.platform == "darwin":
        import os
        import signal
        # `kill -USR1 <pid>` adds every thread's stack to the fault file (the supervisor does, on a hang)
        faulthandler.register(signal.SIGUSR1, file=_fault_file, all_threads=True, chain=False)
        try:  # a LaunchAgent/Finder start sends fd 2 nowhere: native libraries (MLX, PyObjC) print there
            err = open(Path(data) / "stderr.log", "a", encoding="utf-8")  # noqa: SIM115 (must stay open)
            os.dup2(err.fileno(), 2)
            sys.stderr = err
        except OSError:
            log.exception("stderr not redirected")

    def hook(exc_type, exc, tb):
        log.critical("unhandled error", exc_info=(exc_type, exc, tb))
    sys.excepthook = hook
    threading.excepthook = lambda a: log.critical("unhandled error in thread %s", a.thread and a.thread.name,
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def exit_name(code: int | None) -> str:
    if code is None:
        return "unknown"
    code &= 0xFFFFFFFF
    return f"0x{code:08X} ({EXIT_NAMES.get(code, 'crash')})" if code > 255 else f"{code} ({EXIT_NAMES.get(code, 'exit')})"


def is_crash(code: int | None, fault_text: str, log_tail: str) -> bool:
    """Native crash codes always; exit code 1 only with a trace (else it was killed: Task
    Manager, the installer's taskkill); 0 never (the supervisor checks clean state first).
    No exit code (macOS: the supervisor isn't the app's parent): a trace or an unhandled error."""
    if code is None:
        return bool(fault_text.strip()) or "unhandled error" in log_tail[-4000:]
    code &= 0xFFFFFFFF
    if code in (0, 0x40010004, 0xC000013A):
        return False
    if code >= 0xC0000000:
        return True
    return bool(fault_text.strip()) or "unhandled error" in log_tail[-4000:]


def _tail(path: Path, n: int = TAIL) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:]) + "\n"


def _where(fault_text: str) -> str:
    """The crashing thread's innermost frame from faulthandler's output, if there is one."""
    block = fault_text.split("Current thread", 1)
    if len(block) < 2:
        return ""
    m = re.search(r'File "([^"]+)", line (\d+) in (\S+)', block[1])
    return f"{Path(m.group(1)).name}:{m.group(2)} in {m.group(3)}" if m else ""


def make_report(data: Path, pid: int, code: int | None, log_path: Path, config_path: Path | None = None,
                version: str = "", now: float | None = None, gave_up: bool = False) -> Path:
    data = Path(data)
    now = time.time() if now is None else now
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now))
    d = crashes_dir(data) / stamp
    n = 2
    while d.exists():
        d = crashes_dir(data) / f"{stamp}-{n}"
        n += 1
    d.mkdir(parents=True)
    fp = fault_path(data, pid)
    fault = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
    if fp.exists():
        shutil.move(str(fp), d / "fault.log")
    for fz in sorted(fp.parent.glob(f"freeze-{pid}-*.log")) if fp.parent.exists() else []:  # FreezeWatch dumps
        shutil.move(str(fz), d / fz.name)
    tail = _tail(log_path)
    (d / "log-tail.txt").write_text(tail, encoding="utf-8")
    for name in ("status.json",):
        if (data / name).exists():
            shutil.copy2(data / name, d / name)
    if config_path and Path(config_path).exists():  # the calendar link is a secret: never in a report
        cfg = Path(config_path).read_text(encoding="utf-8", errors="replace")
        (d / "config.toml").write_text(re.sub(r'(?m)^(calendar_url\s*=\s*).*$', r'\1"<removed>"', cfg), encoding="utf-8")
    last = [l for l in tail.splitlines() if l.strip()][-1:] or ["(empty log)"]
    where = _where(fault)
    lines = [f"# Dictado crash {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}", "",
             f"- Version: {version or '?'}", f"- Process: {pid}", f"- Exit: {exit_name(code)}",
             f"- Crashed in: {where or 'no Python frame (see fault.log)'}",
             f"- Last log line: `{last[0][:300]}`",
             f"- Restarted: {'no, 3 crashes in 10 minutes: Dictado stopped restarting itself' if gave_up else 'yes'}",
             "", "Files here: fault.log (native trace, every thread), log-tail.txt (last 300 log lines), "
             "status.json, config.toml (calendar link removed).", ""]
    if fault.strip():
        lines += ["## fault.log", "", "```", fault.strip()[:6000], "```", ""]
    (d / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return d


def reports(data: Path) -> list[Path]:
    root = crashes_dir(data)
    if not root.exists():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and p.name != "live" and (p / "report.md").exists()),
                  key=lambda p: p.name, reverse=True)


_LEGACY = {"user": "seen-erik"}  # 1.4.1 wrote seen-erik before the marker became seen-user


def unseen(data: Path, by: str) -> list[Path]:
    old = _LEGACY.get(by)
    return [p for p in reports(data) if not (p / f"seen-{by}").exists() and not (old and (p / old).exists())]


def mark_seen(d: Path, by: str) -> None:
    (Path(d) / f"seen-{by}").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def for_claude(d: Path) -> str:
    """Copy crash report for Claude: the summary plus the log tail."""
    d = Path(d)
    text = (d / "report.md").read_text(encoding="utf-8", errors="replace")
    tail = (d / "log-tail.txt").read_text(encoding="utf-8", errors="replace") if (d / "log-tail.txt").exists() else ""
    return (f"Dictado crashed. Please find the cause. Report folder: {d}\n\n{text}\n"
            f"## Last log lines\n\n```\n{tail[-8000:]}\n```\n")


def clean_live(data: Path, alive_pids: set[int]) -> None:
    """Remove empty fault files of processes that ended cleanly."""
    live = crashes_dir(data) / "live"
    if not live.exists():
        return
    for p in live.glob("fault-*.log"):
        try:
            pid = int(p.stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        if pid not in alive_pids and p.stat().st_size == 0:
            p.unlink(missing_ok=True)


class FreezeWatch:
    """Notices the app's main (tk) thread not answering: today's crashes froze first and
    Windows offered to force-close Dictado, while every key on the PC lagged behind the hook.
    The main loop calls beat() every 0.5 s; if no beat comes for `limit_s`, every thread's
    stack goes to crashes/live/freeze-<pid>-<n>.log and the log says so. Once per freeze."""

    def __init__(self, data: Path, pid: int, limit_s: float = 3.0, clock=time.monotonic):
        self.dir, self.pid, self.limit, self.clock = crashes_dir(data) / "live", pid, limit_s, clock
        self.last = clock()
        self.frozen = False
        self.count = 0
        self._stop = threading.Event()

    def marker(self) -> Path:
        """Exists while frozen; holds when the main thread last answered (the supervisor's hang check)."""
        return self.dir / f"frozen-{self.pid}"

    def beat(self) -> None:
        if self.frozen:
            log.warning("main thread answering again after %.1f s", self.clock() - self.last)
            self.frozen = False
            self.marker().unlink(missing_ok=True)
        self.last = self.clock()

    def check(self) -> Path | None:
        """One look; returns the dump file when it just wrote one."""
        stale = self.clock() - self.last
        if stale < self.limit or self.frozen:
            return None
        self.frozen = True
        self.count += 1
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self.dir / f"freeze-{self.pid}-{self.count}.log"
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"Main thread not answering for {stale:.1f} s at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.flush()
            faulthandler.dump_traceback(f, all_threads=True)
        log.error("FREEZE: main thread not answering for %.1f s; every thread's stack in %s", stale, p)
        self.marker().write_text(str(time.time() - stale), encoding="utf-8")
        return p

    def start(self) -> "FreezeWatch":
        def loop():
            while not self._stop.wait(1.0):
                try:
                    self.check()
                except Exception:
                    log.exception("freeze check failed")
        threading.Thread(target=loop, name="dictado-freezewatch", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
