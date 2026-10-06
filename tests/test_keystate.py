from dictado.keystate import KeyState

R = 0xA3


def ks():
    return KeyState(R, 1.0)


def test_lone_tap_toggles():
    k = ks()
    assert k.feed("down", R, 0) is None
    assert k.feed("up", R, 0.1) == "toggle"


def test_autorepeat_ignored():
    k = ks()
    k.feed("down", R, 0); k.feed("down", R, 0.3); k.feed("down", R, 0.5)
    assert k.feed("up", R, 0.6) == "toggle"


def test_combo_key_does_not_toggle():
    k = ks()
    k.feed("down", R, 0); k.feed("down", 0x43, 0.05); k.feed("up", 0x43, 0.1)
    assert k.feed("up", R, 0.15) is None


def test_combo_mouse_does_not_toggle():
    k = ks()
    k.feed("down", R, 0); k.feed("mouse", 0, 0.05)
    assert k.feed("up", R, 0.1) is None


def test_long_hold_does_not_toggle():
    k = ks()
    k.feed("down", R, 0)
    assert k.feed("up", R, 1.2) is None


def test_other_keys_alone_never_toggle():
    k = ks()
    for vk in (0xA2, 0x1B, 0x09, 0x12, 0x5B, 0x56):
        assert k.feed("down", vk, 0) is None and k.feed("up", vk, 0.05) is None


def test_esc_while_held_cancels_and_no_toggle():
    k = ks()
    k.feed("down", R, 0)
    assert k.feed("down", 0x1B, 0.1) == "cancel"
    assert k.feed("up", R, 0.2) is None


def test_left_ctrl_tap_is_not_toggle():
    k = ks()
    k.feed("down", 0xA2, 0)
    assert k.feed("up", 0xA2, 0.1) is None


def test_next_tap_after_combo_works():
    k = ks()
    k.feed("down", R, 0); k.feed("down", 0x43, 0.05); k.feed("up", R, 0.1)
    k.feed("down", R, 1)
    assert k.feed("up", R, 1.1) == "toggle"


def test_key_held_before_toggle_press_still_taps():
    # A key pressed before Right Ctrl (and released during) is not a combo with it.
    k = ks()
    k.feed("down", 0x41, 0); k.feed("down", R, 0.1); k.feed("up", 0x41, 0.15)
    assert k.feed("up", R, 0.2) == "toggle"


def test_held_reports():
    k = ks()
    assert not k.held
    k.feed("down", R, 0)
    assert k.held
