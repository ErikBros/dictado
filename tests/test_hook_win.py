import threading
import time

import pytest

from ecoscribe.hook import HookThread
from ecoscribe.sendkeys import send_keys

pytestmark = pytest.mark.win
R = 0xA3


def tap(vk=R):
    send_keys([(vk, True), (vk, False)])


def wait_for(pred, timeout=1.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def hook():
    got = []
    h = HookThread(got.append, R, 1.0, accept_injected=True, reinstall_s=0.5)
    h.start()
    assert wait_for(lambda: h.installs >= 1)
    yield h, got
    h.stop()


def test_tap_toggles(hook):
    h, got = hook
    tap()
    assert wait_for(lambda: got == ["toggle"])


def test_combo_does_not_toggle(hook):
    h, got = hook
    send_keys([(R, True), (0x43, True), (0x43, False), (R, False)])
    time.sleep(0.4)
    assert got == []


def test_survives_reinstall(hook):
    h, got = hook
    time.sleep(1.3)
    assert h.installs >= 3
    tap()
    assert wait_for(lambda: got == ["toggle"])


def test_injected_ignored_when_not_accepted():
    got = []
    h = HookThread(got.append, R, 1.0, accept_injected=False, reinstall_s=30)
    h.start()
    try:
        assert wait_for(lambda: h.installs >= 1)
        tap()
        time.sleep(0.4)
        assert got == []
    finally:
        h.stop()


def test_stop_joins():
    h = HookThread(lambda a: None, R, 1.0, accept_injected=True, reinstall_s=30)
    h.start()
    assert wait_for(lambda: h.installs >= 1)
    h.stop()
    h.join(2)
    assert not h.is_alive()


def _close_start_if_open():
    import win32gui
    if win32gui.GetClassName(win32gui.GetForegroundWindow()) == "Windows.UI.Core.CoreWindow":
        send_keys([(0x1B, True), (0x1B, False)])
        time.sleep(0.3)


def test_cancel_combo_swallows_esc_so_start_menu_stays_closed():
    import win32gui
    from tests.winhelp import Target
    t = Target("EcoscribeTargetHook")
    got = []
    h = HookThread(got.append, R, 1.0, accept_injected=True, reinstall_s=30, swallow_cancel=lambda: True)
    h.start()
    try:
        assert wait_for(lambda: h.installs >= 1)
        assert t.focus()
        send_keys([(R, True)]); time.sleep(0.05)
        send_keys([(0x1B, True), (0x1B, False)]); time.sleep(0.05)
        send_keys([(R, False)])
        time.sleep(0.6)
        cls = win32gui.GetClassName(win32gui.GetForegroundWindow())
        _close_start_if_open()
        assert got == ["cancel"]
        assert cls != "Windows.UI.Core.CoreWindow", "Ctrl+Esc reached Windows and opened Start"
        assert win32gui.GetForegroundWindow() == t.hwnd
    finally:
        h.stop()
        t.close()


def test_esc_not_swallowed_when_not_recording():
    seen = []
    h = HookThread(lambda a: None, R, 1.0, accept_injected=True, reinstall_s=30, swallow_cancel=lambda: False)
    h.start()
    try:
        assert wait_for(lambda: h.installs >= 1)
        assert h.would_swallow(0x1B, True) is False
    finally:
        h.stop()


def test_lost_key_up_recovers_on_timer():
    got = []
    h = HookThread(got.append, R, 1.0, accept_injected=True, reinstall_s=0.3)
    h.start()
    try:
        assert wait_for(lambda: h.installs >= 1)
        # simulate a key-up the hook never saw: state says held, the key is physically up
        h.keys.held = True
        h._toggle_down = True
        n = h.installs
        assert wait_for(lambda: not h.keys.held and not h._toggle_down, 2)
        assert wait_for(lambda: h.installs > n, 2)
        tap()
        assert wait_for(lambda: got == ["toggle"])
    finally:
        h.stop()


def test_combo_shortcut_fires_once_and_is_swallowed():
    """Ctrl+L as the shortcut: one toggle per press, plain L doesn't toggle. (That the keys are
    swallowed is ComboMatcher's (fire, swallow) -> return 1, unit-tested in test_hotkeys.)"""
    from ecoscribe.hotkeys import ComboMatcher
    got = []
    h = HookThread(got.append, 0, 1.0, accept_injected=True, reinstall_s=30, combo=ComboMatcher("ctrl+l"))
    h.start()
    assert wait_for(lambda: h.installs >= 1)
    try:
        send_keys([(0xA2, True), (0x4C, True), (0x4C, False), (0xA2, False)])
        assert wait_for(lambda: got == ["toggle"])
        send_keys([(0x4C, True), (0x4C, False)])  # plain L still types
        time.sleep(0.4)
        assert got == ["toggle"]
    finally:
        h.stop()


@pytest.fixture
def hold_hook():
    got = []
    h = HookThread(got.append, R, 1.0, accept_injected=True, reinstall_s=30, hold=True, hold_s=0.5)
    h.start()
    assert wait_for(lambda: h.installs >= 1)
    yield h, got
    h.stop()


def test_hold_mode_on_the_real_hook(hold_hook):
    """t0u.28 through the real LL hook: the hold fires by the clock, not by auto-repeat."""
    h, got = hold_hook
    send_keys([(R, True)]); time.sleep(0.8); send_keys([(R, False)])
    assert wait_for(lambda: got == ["press", "hold", "release"])
    got.clear()
    tap()
    assert wait_for(lambda: got == ["press", "tap"])
    got.clear()
    send_keys([(R, True), (0x43, True), (0x43, False), (R, False)])
    assert wait_for(lambda: got == ["press", "abort"])
