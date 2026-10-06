"""Restart-on-save that can never lose the engine.

Order matters: start the replacement FIRST (it waits for our mutex), then tear
down, each step guarded, then release the mutex and exit. If the replacement
can't even be started, nothing is torn down and the current engine keeps running.
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable

log = logging.getLogger(__name__)


def do_restart(spawn: Callable[[], object], cleanup_steps: Iterable[tuple[str, Callable[[], None]]],
               release: Callable[[], None], exit_fn: Callable[[int], None],
               on_spawn_fail: Callable[[], None]) -> bool:
    try:
        spawn()
    except Exception:
        log.exception("could not start the replacement; keeping this engine running")
        on_spawn_fail()
        return False
    for name, step in cleanup_steps:
        try:
            step()
        except Exception:
            log.exception("restart cleanup step %s failed (continuing)", name)
    try:
        release()
    except Exception:
        log.exception("releasing the single-instance mutex failed")
    exit_fn(0)
    return True
