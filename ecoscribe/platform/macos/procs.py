"""Process bits for macOS: adopt a worker by pid after a restart, the exe name of a pid, liveness."""
from __future__ import annotations

import os
import signal as _sig
import subprocess
import time
from pathlib import Path


def alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, someone else's
    try:  # a zombie child counts as gone
        return subprocess.run(["ps", "-o", "stat=", "-p", str(int(pid))], capture_output=True, text=True,
                              timeout=2).stdout.strip()[:1] not in ("Z", "")
    except Exception:
        return True


def exe_of_pid(pid: int) -> str:
    """'ecoscribe' / 'python3.12' -> normalised like detect.app_from_nonpackaged: lowercase, no extension."""
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=2).stdout.strip()
    except Exception:
        return ""
    name = Path(out).name.lower()
    if name.startswith("python"):
        return "python"
    return name


class PidProc:
    """Popen-like handle on a process we did not start (adopted after a restart)."""

    def __init__(self, pid: int):
        self.pid = int(pid)

    def poll(self):
        return None if alive(self.pid) else 0  # the real exit code of a non-child is unknowable here

    def kill(self):
        try:
            os.kill(self.pid, _sig.SIGKILL)
        except ProcessLookupError:
            pass

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while alive(self.pid) and (end is None or time.monotonic() < end):
            time.sleep(0.05)
        return self.poll()


def attach_pid(pid: int):
    """A PidProc if `pid` is still a Ecoscribe (or dev Python) process, else None."""
    if not pid or exe_of_pid(pid) not in ("ecoscribe", "python"):
        return None
    return PidProc(pid) if alive(pid) else None
