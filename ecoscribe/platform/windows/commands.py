"""commands.py's signal and watcher on Windows: the named event Local\\EcoscribeCommand
(macOS: a Unix datagram socket, ecoscribe/platform/macos/commands.py)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)
EVENT = "Local\\EcoscribeCommand"


def _signal(name: str = EVENT) -> bool:
    import win32con
    import win32event
    try:
        h = win32event.OpenEvent(win32con.EVENT_MODIFY_STATE, False, name)
    except Exception:
        return False
    win32event.SetEvent(h)
    return True


class Watcher(threading.Thread):
    """Background app side: waits on the event (and every 5 s anyway) and runs requests."""

    def __init__(self, data_dir: Path, handler, name: str = EVENT):
        import win32event
        super().__init__(name="ecoscribe-commands", daemon=True)
        self.data_dir, self.handler, self._we = Path(data_dir), handler, win32event
        self._event = win32event.CreateEvent(None, False, False, name)
        self._stop = win32event.CreateEvent(None, True, False, None)

    def run(self) -> None:
        from ...commands import run_pending
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
