"""ipc on macOS: reload signal, window focus, launching another copy (see ecoscribe/ipc.py)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from . import signals

log = logging.getLogger(__name__)
RELOAD_EVENT = "Local\\EcoscribeReload"
UI_MUTEX = "Local\\EcoscribeUI"
UI_TITLE = "Ecoscribe"
UI_FOCUS = "Local\\EcoscribeUIFocus"  # the window process listens here (macOS has no FindWindow)


def signal_reload(name: str = RELOAD_EVENT) -> bool:
    """Ask the running background app to restart with the saved config."""
    return signals.signal(name)


class ReloadWatcher(threading.Thread):
    def __init__(self, on_reload, name: str = RELOAD_EVENT):
        super().__init__(name="ecoscribe-reload", daemon=True)
        self.on_reload = on_reload
        self._l = signals.Listener(name)

    def run(self) -> None:
        while True:
            data = self._l.wait(None)
            if data is None:
                return
            try:
                self.on_reload()
            except Exception:
                log.exception("reload handler failed")

    def stop(self) -> None:
        self._l.close()


def self_command(args: list[str]) -> list[str]:
    """How to start another copy of this program (the .app's binary or dev Python)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "ecoscribe", *args]


def _package_parent() -> str:
    return str(Path(__file__).resolve().parents[3])  # ecoscribe/platform/macos/ipc.py -> the folder holding ecoscribe/


def spawn(args: list[str]) -> subprocess.Popen:
    """A detached copy: own session, so it outlives us (a restart) and never shares our terminal."""
    devnull = subprocess.DEVNULL
    return subprocess.Popen(self_command(args), cwd=_package_parent(), start_new_session=True, close_fds=True,
                            stdin=devnull, stdout=devnull, stderr=devnull, env={**os.environ, "PYTHONUNBUFFERED": "1"})


def focus_ui() -> bool:
    """Bring an already open Ecoscribe window to the front. True if there was one."""
    return signals.signal(UI_FOCUS, b"focus")


def open_ui(page: str | None = None) -> None:
    """Open the window, or focus it if it's already open."""
    if page and signals.signal(UI_FOCUS, b"page:" + page.encode()):
        return
    if not page and focus_ui():
        return
    spawn(["--ui"] + (["--page", page] if page else []))
