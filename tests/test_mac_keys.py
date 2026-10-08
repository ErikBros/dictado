"""The Mac key tap's logic (uat.4), fed synthetic events: no real tap, no keys sent, no permissions needed."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS key tap")

RCMD, LCMD, ESC, C, MINUS, D, LSHIFT = 54, 55, 53, 8, 27, 2, 56
CMD_BITS = 0x00100000 | 0x10  # device-independent Command + right-Command device bit
LCMD_BITS = 0x00100000 | 0x08


def hook(**kw):
    from ecoscribe.platform.macos.keyhook import HookThread
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
    # dictado-2jy: wait for the consumer to fire the hold; a fixed sleep raced it on the shared CI runner
    assert settle(acts, 2, 2.0) == ["press", "hold"]
    h.handle("flags", RCMD, 0, False)
    assert settle(acts, 3) == ["press", "hold", "release"]


def test_combo_fires_once_and_is_swallowed():
    from ecoscribe.hotkeys import ComboMatcher
    h, acts = hook(combo=ComboMatcher("cmd+shift+d"))
    h.handle("flags", LCMD, LCMD_BITS, False)
    h.handle("flags", LSHIFT, LCMD_BITS | 0x00020000 | 0x02, False)
    assert h.handle("down", D, LCMD_BITS | 0x00020000 | 0x02, False) is True
    assert h.handle("down", D, LCMD_BITS | 0x00020000 | 0x02, False) is True  # auto-repeat
    assert h.handle("up", D, LCMD_BITS | 0x00020000 | 0x02, False) is True
    assert settle(acts, 1) == ["toggle"]


def test_mac_shortcut_rules():
    from ecoscribe import hotkeys
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
    from ecoscribe.hotkeys import ComboMatcher
    h, acts = hook(combo=ComboMatcher("cmd+shift+d"))
    h.handle("flags", RCMD, CMD_BITS, False, t=0.0)
    assert not h.handle("down", L, CMD_BITS, False, t=0.05)
    assert "lang" not in settle(acts, 1, 0.3)


KP_ENTER, RETURN = 76, 36


def test_numpad_enter_taps_like_the_dictation_key_and_is_swallowed():
    """dictado-1k7: [hotkey] numpad_enter, like Windows' numpad_alias."""
    h, acts = hook(numpad_enter=True)
    assert h.handle("down", KP_ENTER, 0, False, t=0.0) is True
    assert h.handle("down", KP_ENTER, 0, False, t=0.05) is True  # auto-repeat: still swallowed
    assert h.handle("up", KP_ENTER, 0, False, t=0.15) is True
    assert settle(acts, 1) == ["toggle"]


def test_return_and_numpad_enter_when_off_pass_through():
    h, acts = hook(numpad_enter=True)
    assert h.handle("down", RETURN, 0, False, t=0.0) is False  # the main Return still types
    assert h.handle("up", RETURN, 0, False, t=0.1) is False
    h2, acts2 = hook()
    assert h2.handle("down", KP_ENTER, 0, False, t=0.0) is False  # off by default
    assert h2.handle("up", KP_ENTER, 0, False, t=0.1) is False
    assert settle(acts, 1, 0.2) == [] and settle(acts2, 1, 0.2) == []


def test_numpad_enter_hold_and_escape_cancel_like_the_key():
    h, acts = hook(numpad_enter=True, swallow_cancel=lambda: True)
    h.handle("down", KP_ENTER, 0, False, t=0.0)
    h.handle("up", KP_ENTER, 0, False, t=0.1)
    assert settle(acts, 1) == ["toggle"]
    h.handle("down", KP_ENTER, 0, False, t=1.0)
    assert h.handle("down", ESC, 0, False, t=1.1) is True  # numpad Enter + Esc cancels, the Esc swallowed
    h.handle("up", ESC, 0, False, t=1.15)
    h.handle("up", KP_ENTER, 0, False, t=1.2)
    assert "cancel" in settle(acts, 2)


def test_numpad_enter_fires_a_combo_shortcut_too():
    from ecoscribe.hotkeys import ComboMatcher
    h, acts = hook(combo=ComboMatcher("cmd+shift+d"), numpad_enter=True)
    assert h.handle("down", KP_ENTER, 0, False) is True
    assert h.handle("up", KP_ENTER, 0, False) is True
    assert settle(acts, 1) == ["toggle"]
