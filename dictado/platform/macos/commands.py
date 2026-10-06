"""commands.py's signal and watcher on macOS (a Unix datagram socket instead of Local\\DictadoCommand)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import signals

log = logging.getLogger(__name__)
EVENT = "Local\\DictadoCommand"


def _signal(name: str = EVENT) -> bool:
    return signals.signal(name)


class Watcher(threading.Thread):
    """Background app side: waits on the socket (and every 5 s anyway) and runs requests."""

    def __init__(self, data_dir: Path, handler, name: str = EVENT):
        super().__init__(name="dictado-commands", daemon=True)
        self.data_dir, self.handler = Path(data_dir), handler
        self._l = signals.Listener(name)
        self._stopped = threading.Event()

    def run(self) -> None:
        from ...commands import run_pending
        while not self._stopped.is_set():
            self._l.wait(5.0)
            if self._stopped.is_set():
                return
            try:
                run_pending(self.data_dir, self.handler)
            except Exception:
                log.exception("command watcher failed")

    def stop(self) -> None:
        self._stopped.set()
        self._l.close()
