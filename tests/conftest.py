import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


import os

import pytest


@pytest.fixture(autouse=True)
def _desktop_tests_only_when_idle(request):
    """Tests marked `win` inject keys / use the clipboard / open windows: never while the user works.
    Before the first one: wait for 45 s of idle. Then a hook watches for REAL input (ours is
    flagged as injected); if the user touches anything, the next desktop test waits again."""
    global _GUARD
    if request.node.get_closest_marker("win") is None or os.environ.get("DICTADO_FORCE_DESKTOP"):
        yield
        return
    from tests.idle import RealInputGuard, wait_idle
    max_wait = float(os.environ.get("DICTADO_IDLE_WAIT", "600"))
    if _GUARD is None or _GUARD.tripped.is_set():
        if not wait_idle(45, max_wait):
            pytest.skip("someone is using the PC: desktop test skipped")
        if _GUARD is None:
            _GUARD = RealInputGuard()
        _GUARD.tripped.clear()
    yield
    if _GUARD.tripped.is_set():
        pytest.fail(f"real {_GUARD.what} input during a desktop test: result not trustworthy, rerun when idle")


_GUARD = None


@pytest.fixture(autouse=True)
def _no_real_screen_read(request, monkeypatch):
    """Unit tests never read the real foreground window (t0u.27 screen names). Tests marked
    `real_window_texts` keep the real function but must fake `_read` themselves (t0u.37)."""
    if request.node.get_closest_marker("real_window_texts"):
        return
    from dictado import context
    monkeypatch.setattr(context, "window_texts", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _never_restart_eriks_dictado(monkeypatch):
    """Tests must never signal the REAL background app: a save_settings() without a fake
    signal_reload restarted the developer's running Dictado on every test run (found 2026-10-06,
    t0u.37). Named test events (anything but the real one) still go through."""
    from dictado import ipc
    real = ipc.signal_reload

    def guarded(name=ipc.RELOAD_EVENT):
        if name == ipc.RELOAD_EVENT:
            return True  # pretend it was delivered; nothing reaches the running app
        return real(name)
    monkeypatch.setattr(ipc, "signal_reload", guarded)
