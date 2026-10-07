import sys

import pytest

from ecoscribe import hotkeys

# Windows key rules (VK codes, Win key, AltGr). The Mac rules are in test_mac_keys.py.
win_rules = pytest.mark.skipif(sys.platform == "darwin", reason="Windows shortcut rules")


@win_rules
def test_lone_keys_and_combos_parse():
    assert hotkeys.parse("rctrl") == (frozenset(), "rctrl")
    assert hotkeys.normalize("Shift + Ctrl + D") == "ctrl+shift+d"
    assert hotkeys.normalize("ctrl+l") == "ctrl+l"
    assert hotkeys.normalize("win+f9") == "win+f9"
    assert hotkeys.label("ctrl+shift+d") == "Ctrl+Shift+D" and hotkeys.label("rctrl") == "Right Ctrl"
    assert hotkeys.label("alt+f9") == "Alt+F9"


@win_rules
@pytest.mark.parametrize("bad", ["", "l", "f5", "ctrl+c", "ctrl+v", "alt+tab", "alt+f4", "win+l",
                                 "ctrl+alt+d", "hyper+d", "ctrl+ctrl+d", "ctrl+esc", "ctrl+enter"])
def test_refused(bad):
    with pytest.raises(ValueError):
        hotkeys.parse(bad)


def feed(m, *events):
    return [m.key(vk, down) for vk, down in events]


LCTRL, RCTRL, SHIFT, L = 0xA2, 0xA3, 0xA0, 0x4C


@win_rules
def test_combo_fires_once_and_is_swallowed():
    m = hotkeys.ComboMatcher("ctrl+l")
    out = feed(m, (LCTRL, True), (L, True), (L, True), (L, False), (LCTRL, False))
    assert out == [(False, False), (True, True), (False, True), (False, True), (False, False)]


@win_rules
def test_either_ctrl_counts_and_extra_modifiers_dont_match():
    m = hotkeys.ComboMatcher("ctrl+l")
    assert feed(m, (RCTRL, True), (L, True), (L, False), (RCTRL, False))[1] == (True, True)
    assert feed(m, (LCTRL, True), (SHIFT, True), (L, True), (L, False))[2] == (False, False)  # Ctrl+Shift+L passes through


def test_plain_key_passes_through():
    m = hotkeys.ComboMatcher("ctrl+l")
    assert feed(m, (L, True), (L, False)) == [(False, False), (False, False)]


def test_cancel_hint_on_the_pill():
    """t0u.36: the Dictating pill says how to cancel. A combo has no Esc cancel (tray only)."""
    from ecoscribe.hotkeys import cancel_hint
    assert cancel_hint("rctrl") == "Right Ctrl + Esc to cancel"
    assert cancel_hint("f13") == "F13 + Esc to cancel"
    assert cancel_hint("ctrl+l") == "Cancel from the tray icon"
