"""The Mac pill's live text (dictado-ayq): drawn offscreen, nothing shown on screen."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")


@pytest.fixture
def overlay():
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ecoscribe.platform.macos import shell
    o = shell.Overlay(level_fn=lambda: 0.0)
    o._place_and_show = lambda: None  # never on screen
    o._hide = lambda: None
    return o


def test_live_text_widens_the_pill_and_shows_under_the_timer(overlay):
    from ecoscribe.platform.macos import shell
    overlay.recording(time.monotonic())
    assert overlay.h == shell.MH and "para" not in overlay.view.spec  # nothing heard yet: the plain pill
    overlay.live("I would like to schedule the climbing")
    overlay.tick()
    assert (overlay.w, overlay.h) == (max(shell.LW, overlay.w), shell.LH) and overlay.w >= shell.LW
    assert overlay.view.spec["para"][0] == "I would like to schedule the climbing"
    assert overlay.view.spec["texts"][0][0].startswith("Dictating 0:0")


def test_live_text_only_while_recording_and_cleared_after(overlay):
    from ecoscribe.platform.macos import shell
    overlay.live("too early")
    assert overlay.live_text == ""
    overlay.recording(time.monotonic())
    overlay.live("hola")
    overlay.busy()
    assert overlay.live_text == "" and overlay.h == shell.H  # Transcribing…: the small pill again
    overlay.recording(time.monotonic())
    overlay.tick()
    assert "para" not in overlay.view.spec  # a new dictation starts without the old text


def test_the_hint_does_not_move_as_the_timer_ticks(overlay):
    overlay.recording(time.monotonic() - 7)
    overlay.live("x")
    overlay.tick()
    x7 = overlay.view.spec["texts"][1][1]
    overlay._t0 = time.monotonic() - 74
    overlay.tick()
    assert overlay.view.spec["texts"][1][1] == x7


def test_ui_forwards_live_text_to_the_mac_pill():
    from ecoscribe.platform.macos import shell
    assert hasattr(shell.Overlay, "live")  # ui.Ui.live only forwards to an overlay that has one
