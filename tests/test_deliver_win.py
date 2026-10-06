import threading
import time

import pytest

from dictado import deliver as dl
from dictado.sendkeys import send_keys
from tests.winhelp import Target

pytestmark = pytest.mark.win


@pytest.fixture
def target():
    t = Target("DictadoTargetDeliver")
    assert t.focus()
    yield t
    t.close()


def test_pastes_and_restores_clipboard(target):
    dl.set_clipboard_text("SENTINEL", private=False)
    r = dl.deliver("Hola mundo ", restore_delay_s=0.4)
    assert r.pasted and r.reason == "ok"
    assert r.target_exe.lower() == "python.exe"
    assert target.wait_text(lambda t: t == "Hola mundo ") == "Hola mundo "
    time.sleep(0.8)
    assert dl.get_clipboard_text() == "SENTINEL"


def test_unicode_roundtrip(target):
    s = "Mañana, Ελλάδα, naïve, 😀 "
    dl.deliver(s, restore_delay_s=0.2)
    assert target.wait_text(lambda t: t == s) == s


def test_shift_held_waits_then_pastes(target):
    send_keys([(0x10, True)])
    holder = threading.Timer(0.5, lambda: send_keys([(0x10, False)]))
    holder.start()
    r = dl.deliver("Plain paste ", restore_delay_s=0.2)
    holder.join()
    assert r.waited_ms >= 400
    assert target.wait_text(lambda t: t == "Plain paste ") == "Plain paste "


def _hold_clipboard(seconds):
    """Another process holds the clipboard WITH an owner window, like real apps do.
    (OpenClipboard(NULL) does not block other processes, measured 2026-10-01.)"""
    import subprocess
    import sys
    code = ("import win32clipboard,win32gui,time;"
            "h=win32gui.CreateWindowEx(0,'STATIC','holder',0,0,0,0,0,0,0,0,None);"
            "win32clipboard.OpenClipboard(h);print('held',flush=True);"
            f"time.sleep({seconds});win32clipboard.CloseClipboard()")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def test_clipboard_busy_retries(target):
    p = _hold_clipboard(0.1)
    r = dl.deliver("busy ok ", restore_delay_s=0.2)
    p.wait(5)
    assert r.pasted and target.wait_text(lambda x: x == "busy ok ") == "busy ok "

    p = _hold_clipboard(2.0)
    r = dl.deliver("never ", restore_delay_s=0.2)
    p.wait(5)
    assert not r.pasted and r.reason == "clipboard_busy"


def test_user_copied_meanwhile_not_clobbered(target):
    dl.set_clipboard_text("OLD", private=False)
    dl.deliver("x ", restore_delay_s=0.5)
    time.sleep(0.2)
    dl.set_clipboard_text("NEW", private=False)
    time.sleep(0.8)
    assert dl.get_clipboard_text() == "NEW"


def test_empty_is_noop(target):
    r = dl.deliver("")
    assert not r.pasted and r.reason == "empty"


def test_wait_clipboard_quiet_waits_for_readers():
    t = [0.0]
    owners = iter([1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

    def clock():
        return t[0]

    def sleep(s):
        t[0] += s

    waited = dl._wait_clipboard_quiet(quiet_s=0.04, max_s=0.4, owner=lambda: next(owners, 0), clock=clock, sleep=sleep)
    assert 0.04 <= waited <= 0.08


def test_wait_clipboard_quiet_gives_up():
    t = [0.0]
    waited = dl._wait_clipboard_quiet(quiet_s=0.04, max_s=0.4, owner=lambda: 1,
                                      clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert 0.4 <= waited <= 0.42


def test_consecutive_deliveries_all_land(target):
    """Realistic spacing: dictations are seconds apart (talk + transcribe), so each
    write's clipboard watchers (incl. the clipboard service's read ~200 ms later and
    our own restore at 0.8 s) are done before the next paste. Firing them 100 ms apart
    collides with that late read; measured 2026-10-01, see runbook section 9."""
    import win32gui
    for i in range(10):
        time.sleep(1.2)
        before = target.text()
        r = dl.deliver(f"w{i} ", restore_delay_s=0.8)
        got = target.wait_text(lambda t, i=i: t.endswith(f"w{i} "), 2)
        fg = win32gui.GetForegroundWindow()
        assert got.endswith(f"w{i} "), (
            f"step {i}: reason={r.reason} delta={got[len(before):]!r} fg_is_target={fg == target.hwnd} "
            f"fg={win32gui.GetClassName(fg)}|{win32gui.GetWindowText(fg)[:40]} clip={dl.get_clipboard_text()!r} "
            f"pastes={target.pastes()[-3:]}")


def test_modifier_held_too_long_copies_instead_of_pasting(target):
    send_keys([(0x12, True)])  # Alt held past the 1.5 s wait
    try:
        r = dl.deliver("held alt ", restore_delay_s=0.2)
    finally:
        send_keys([(0x12, False)])
    assert not r.pasted and r.reason == "modifier_held"
    time.sleep(0.4)
    assert target.text() == ""
    assert dl.get_clipboard_text() == "held alt "  # left for a manual Ctrl+V, not restored away
