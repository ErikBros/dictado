"""Hold Right Ctrl to talk, let go to stop (t0u.28). Opt-in: [hotkey] hold_to_talk.

With it on, the key's press starts the mic quietly (no sound, no pill) so the first word is
never lost; then:
  - released before hold_s, nothing else pressed = a tap: the recording goes on hands-free (as today)
  - still held at hold_s = hold-to-talk: sound + pill now, and letting go stops it
  - another key or a click while held = it was a shortcut (Right Ctrl+C): the quiet start is
    dropped without a sound; a hold already announced is cancelled
A recording started by a tap is never touched by shortcuts, as today.
"""
import time

from ecoscribe.keystate import KeyState
from tests.test_app import make, wait

R = 0xA3


def hk():
    return KeyState(R, 1.0, hold=True, hold_s=0.5)


def test_quick_press_is_press_then_tap():
    k = hk()
    assert k.feed("down", R, 0) == "press"
    assert k.feed("down", R, 0.1) is None  # auto-repeat
    assert k.tick(0.3) is None
    assert k.feed("up", R, 0.3) == "tap"


def test_long_press_is_hold_then_release():
    k = hk()
    k.feed("down", R, 0)
    assert k.tick(0.4) is None
    assert k.tick(0.6) == "hold"
    assert k.tick(0.9) is None  # once
    assert k.feed("up", R, 3.0) == "release"


def test_release_after_hold_s_without_a_tick_is_still_a_release():
    k = hk()
    k.feed("down", R, 0)
    assert k.feed("up", R, 0.7) == "release"


def test_other_key_or_click_while_held_aborts_once():
    k = hk()
    k.feed("down", R, 0)
    assert k.feed("down", 0x43, 0.1) == "abort"
    assert k.feed("down", 0x56, 0.2) is None
    assert k.tick(0.8) is None  # no hold after a shortcut
    assert k.feed("up", R, 0.9) is None
    k.feed("down", R, 2)
    assert k.feed("mouse", 0, 2.1) == "abort"


def test_esc_while_held_still_cancels():
    k = hk()
    k.feed("down", R, 0)
    assert k.feed("down", 0x1B, 0.1) == "cancel"
    assert k.feed("up", R, 0.2) is None


def test_off_is_exactly_the_old_tap_rule():
    k = KeyState(R, 1.0)
    assert k.feed("down", R, 0) is None and k.tick(0.8) is None
    assert k.feed("up", R, 0.9) == "toggle"
    k.feed("down", R, 2)
    assert k.feed("up", R, 3.5) is None


def hold_app(tmp_path):
    app, out = make(tmp_path)
    app.cfg.hotkey.hold_to_talk = True
    return app, out


def test_app_hold_to_talk_cycle(tmp_path):
    app, out = hold_app(tmp_path)
    app.on_action("press")
    assert app.state == "recording" and ("sound", "start") not in app.ui.events  # quiet until it counts
    app.on_action("hold")
    assert ("sound", "start") in app.ui.events
    app.on_action("release")
    assert app.state == "idle" and wait(lambda: out == ["text 1 "])
    app.shutdown()


def test_app_tap_goes_hands_free_and_tap_stops(tmp_path):
    app, out = hold_app(tmp_path)
    app.on_action("press"); app.on_action("tap")
    assert app.state == "recording" and ("sound", "start") in app.ui.events
    app.on_action("abort")  # Right Ctrl+C while dictating hands-free: ignored, as today
    assert app.state == "recording"
    app.on_action("press"); app.on_action("tap")
    assert app.state == "idle" and wait(lambda: out == ["text 1 "])
    app.shutdown()


def test_app_shortcut_drops_the_quiet_start_silently(tmp_path):
    app, out = hold_app(tmp_path)
    app.on_action("press"); app.on_action("abort")
    assert app.state == "idle" and app.recorder.aborted == 1 and app.gate.restored == 1
    assert not [e for e in app.ui.events if e[0] in ("sound", "flash")]
    time.sleep(0.2)
    assert out == []
    app.shutdown()


def test_app_shortcut_during_an_announced_hold_cancels(tmp_path):
    app, out = hold_app(tmp_path)
    app.on_action("press"); app.on_action("hold"); app.on_action("abort")
    assert app.state == "idle" and ("flash", "Cancelled") in app.ui.events
    app.shutdown()


def test_app_esc_on_a_quiet_start_is_silent(tmp_path):
    app, out = hold_app(tmp_path)
    app.on_action("press"); app.on_action("cancel")
    assert app.state == "idle" and not [e for e in app.ui.events if e[0] in ("sound", "flash")]
    app.shutdown()


def test_setting_round_trips(tmp_path):
    from ecoscribe.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.get_settings()["values"]["hold_to_talk"] is False
    assert api.save_settings({"hold_to_talk": True})["ok"]
    assert api.get_settings()["values"]["hold_to_talk"] is True
