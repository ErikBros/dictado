"""The Mac key tap's logic (uat.4), fed synthetic events: no real tap, no keys sent, no permissions needed."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS key tap")

RCMD, LCMD, ESC, C, MINUS, D, LSHIFT = 54, 55, 53, 8, 27, 2, 56
CMD_BITS = 0x00100000 | 0x10  # device-independent Command + right-Command device bit
LCMD_BITS = 0x00100000 | 0x08


def hook(**kw):
    from dictado.platform.macos.keyhook import HookThread
    acts = []
    h = HookThread(acts.append, RCMD, 1.0, **kw)
    h._consumer.start()
    return h, acts


def settle(acts, n, t=1.0):
    end = time.monotonic() + t
    while len(acts) < n and time.monotonic() < end:
        time.sleep(0.01)
    time.sleep(0.05)
    return acts


def test_lone_tap_of_right_command_toggles():
    h, acts = hook()
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    h.handle("flags", RCMD, 0, False, t=0.15)
    assert settle(acts, 1) == ["toggle"]


def test_right_command_shortcut_does_not_toggle():
    h, acts = hook()
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    h.handle("down", C, CMD_BITS, False, t=0.05)  # Right Cmd+C: a copy, not a dictation
    h.handle("up", C, CMD_BITS, False, t=0.08)
    h.handle("flags", RCMD, 0, False, t=0.12)
    assert settle(acts, 1, 0.3) == []


def test_left_command_is_not_the_toggle():
    h, acts = hook()
    h.handle("flags", LCMD, LCMD_BITS, False, t=0.0)
    h.handle("flags", LCMD, 0, False, t=0.1)
    assert settle(acts, 1, 0.3) == []


def test_minus_is_not_escape():
    """Mac keycode 27 is '-', Windows VK 0x1B is Esc: the shift in keymap keeps them apart."""
    h, acts = hook()
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    h.handle("down", MINUS, CMD_BITS, False, t=0.05)
    assert settle(acts, 1, 0.3) == []


def test_escape_while_holding_cancels_and_is_swallowed_only_while_recording():
    recording = [True]
    h, acts = hook(swallow_cancel=lambda: recording[0])
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    assert h.handle("down", ESC, CMD_BITS, False, t=0.05) is True  # swallowed
    assert h.handle("up", ESC, CMD_BITS, False, t=0.07) is True
    assert settle(acts, 1) == ["cancel"]
    h.handle("flags", RCMD, 0, False, t=0.1)
    recording[0] = False
    h.handle("flags", RCMD, CMD_BITS, False, t=1.0)
    assert h.handle("down", ESC, CMD_BITS, False, t=1.05) is False  # not recording: Esc goes through


def test_our_own_synthetic_keys_are_ignored():
    h, acts = hook()
    h.handle("flags", RCMD, CMD_BITS, True, t=0.0)
    h.handle("flags", RCMD, 0, True, t=0.1)
    assert settle(acts, 1, 0.3) == []


def test_mouse_click_while_held_makes_it_a_shortcut():
    h, acts = hook()
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    h.handle("mouse", 0, 0, False, t=0.05)  # Cmd+click
    h.handle("flags", RCMD, 0, False, t=0.1)
    assert settle(acts, 1, 0.3) == []


def test_hold_to_talk_presses_holds_and_releases():
    h, acts = hook(hold=True, hold_s=0.2)
    h.handle("flags", RCMD, CMD_BITS, False)
    time.sleep(0.35)
    h.handle("flags", RCMD, 0, False)
    assert settle(acts, 3) == ["press", "hold", "release"]


def test_combo_fires_once_and_is_swallowed():
    from dictado.hotkeys import ComboMatcher
    h, acts = hook(combo=ComboMatcher("cmd+shift+d"))
    h.handle("flags", LCMD, LCMD_BITS, False)
    h.handle("flags", LSHIFT, LCMD_BITS | 0x00020000 | 0x02, False)
    assert h.handle("down", D, LCMD_BITS | 0x00020000 | 0x02, False) is True
    assert h.handle("down", D, LCMD_BITS | 0x00020000 | 0x02, False) is True  # auto-repeat
    assert h.handle("up", D, LCMD_BITS | 0x00020000 | 0x02, False) is True
    assert settle(acts, 1) == ["toggle"]


def test_mac_shortcut_rules():
    from dictado import hotkeys
    assert hotkeys.normalize("rcmd") == "rcmd" and hotkeys.label("rcmd") == "Right Command"
    assert hotkeys.normalize("Shift + Cmd + D") == "shift+cmd+d"
    for bad in ("cmd+c", "cmd+q", "alt+2", "ralt", "cmd+tab"):
        with pytest.raises(ValueError):
            hotkeys.normalize(bad)
    assert hotkeys.normalize("ctrl+alt+d") == "ctrl+alt+d"  # no AltGr on the Mac


L = 37


def test_right_command_plus_l_picks_the_next_language_and_swallows_the_l():
    h, acts = hook()
    assert not h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    assert h.handle("down", L, CMD_BITS, False, t=0.05)  # swallowed: no app sees Cmd+L
    assert h.handle("down", L, CMD_BITS, False, t=0.10)  # auto-repeat: swallowed, no second "lang"
    assert h.handle("up", L, CMD_BITS, False, t=0.15)
    h.handle("flags", RCMD, 0, False, t=0.2)
    assert settle(acts, 1, 0.3) == ["lang"]  # and no dictation toggle from that Right Command press


def test_l_with_command_released_first_is_still_swallowed_on_the_way_up():
    h, acts = hook()
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    assert h.handle("down", L, CMD_BITS, False, t=0.05)
    h.handle("flags", RCMD, 0, False, t=0.1)  # Command up before L
    assert h.handle("up", L, 0, False, t=0.15)
    assert settle(acts, 1, 0.3) == ["lang"]


def test_plain_l_and_left_command_l_pass_through():
    h, acts = hook()
    assert not h.handle("down", L, 0, False, t=0.0)  # typing an l
    assert not h.handle("up", L, 0, False, t=0.05)
    h.handle("flags", LCMD, LCMD_BITS, False, t=0.1)  # Left Cmd+L: the browser's address bar
    assert not h.handle("down", L, LCMD_BITS, False, t=0.15)
    assert not h.handle("up", L, LCMD_BITS, False, t=0.2)
    h.handle("flags", LCMD, 0, False, t=0.25)
    assert settle(acts, 1, 0.3) == []


def test_no_language_key_with_a_combo_shortcut():
    from dictado.hotkeys import ComboMatcher
    h, acts = hook(combo=ComboMatcher("cmd+shift+d"))
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    assert not h.handle("down", L, CMD_BITS, False, t=0.05)
    assert "lang" not in settle(acts, 1, 0.3)
