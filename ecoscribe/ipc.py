"""Tiny IPC between the background app and the window: one named event + process launch."""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path

if sys.platform != "darwin":
    import win32con
    import win32event

log = logging.getLogger(__name__)
RELOAD_EVENT = "Local\\EcoscribeReload"
UI_MUTEX = "Local\\EcoscribeUI"
UI_TITLE = "Ecoscribe"


def signal_reload(name: str = RELOAD_EVENT) -> bool:
    """Ask the running background app to restart with the saved config."""
    try:
        h = win32event.OpenEvent(win32con.EVENT_MODIFY_STATE, False, name)
    except Exception:
        return False
    win32event.SetEvent(h)
    return True


class ReloadWatcher(threading.Thread):
    def __init__(self, on_reload, name: str = RELOAD_EVENT):
        super().__init__(name="ecoscribe-reload", daemon=True)
        self.on_reload = on_reload
        self._event = win32event.CreateEvent(None, False, False, name)  # auto-reset
        self._stop = win32event.CreateEvent(None, True, False, None)

    def run(self) -> None:
        while True:
            r = win32event.WaitForMultipleObjects([self._event, self._stop], False, win32event.INFINITE)
            if r == win32event.WAIT_OBJECT_0 + 1:
                return
            try:
                self.on_reload()
            except Exception:
                log.exception("reload handler failed")

    def stop(self) -> None:
        win32event.SetEvent(self._stop)


def self_command(args: list[str]) -> list[str]:
    """How to start another copy of this program (installed exe or dev Python)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "ecoscribe", *args]


def _package_parent() -> str:
    return str(Path(__file__).resolve().parent.parent)


def spawn(args: list[str]) -> subprocess.Popen:
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    exe = self_command(args)
    if not getattr(sys, "frozen", False) and exe[0].lower().endswith("python.exe"):
        exe[0] = exe[0][:-len("python.exe")] + "pythonw.exe"  # no console window in dev
    return subprocess.Popen(exe, cwd=_package_parent(), creationflags=flags, close_fds=True)


def focus_ui() -> bool:
    """Bring an already open Ecoscribe window to the front. True if there was one."""
    import win32gui
    hwnd = win32gui.FindWindow(None, UI_TITLE)
    if not hwnd:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return True


def open_ui(page: str | None = None) -> None:
    """Open the window, or focus it if it's already open."""
    if focus_ui():
        return
    spawn(["--ui"] + (["--page", page] if page else []))


if sys.platform == "darwin":  # macOS: same names over Unix sockets (ecoscribe/platform/macos/ipc.py)
    from .platform.macos.ipc import (RELOAD_EVENT, UI_FOCUS, UI_MUTEX, UI_TITLE, ReloadWatcher, _package_parent,  # noqa: F811,F401
                          focus_ui, open_ui, self_command, signal_reload, spawn)
