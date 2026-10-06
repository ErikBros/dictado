"""Meetings started by hand also record the app (t0u.33): the call app that holds the mic
right now (the foreground one if several), else nothing ("App: Meeting" as before)."""
from pathlib import Path

from dictado import commands
from dictado.detect import MicUse, call_app_now


def use(app, in_use=True, start=1, nonpackaged=True):
    return MicUse(app=app, in_use=in_use, start=start, stop=0 if in_use else 2, nonpackaged=nonpackaged)


def test_the_call_app_on_the_mic():
    assert call_app_now([use("signal"), use("chrome")], {"signal", "chrome"}) == "signal"
    assert call_app_now([use("signal", in_use=False)], {"signal"}) is None
    assert call_app_now([use("spotify")], {"spotify"}) is None  # not a call app


def test_foreground_wins_then_the_newest():
    uses = [use("slack", start=5), use("zoom", start=9)]
    assert call_app_now(uses, {"slack", "zoom"}, foreground="slack") == "slack"
    assert call_app_now(uses, {"slack", "zoom"}) == "zoom"


def test_a_crash_leftover_is_ignored():
    assert call_app_now([use("zoom")], set()) is None  # "in use" but zoom isn't running
    assert call_app_now([use("msteams", nonpackaged=False)], set()) == "msteams"  # packaged: no exe to check


class Ctl:
    def __init__(self):
        self.calls = []

    def start_meeting(self, lang, title="Meeting", app=None):
        self.calls.append((lang, app))
        return Path("T/x")


class Watch:
    def __init__(self, app):
        self.app = app

    def lang_for(self, key):
        return "sv"

    def remember(self, key, lang):
        pass

    def call_app_now(self):
        return self.app


def test_manual_start_passes_the_app():
    ctl = Ctl()
    commands.handler_for(ctl, Watch("signal"))("start_meeting", {})
    commands.handler_for(ctl, Watch(None))("start_meeting", {})
    assert ctl.calls == [("sv", "signal"), ("sv", None)]


def test_watch_prefers_the_call_it_already_sees(tmp_path):
    from dictado.config import Config
    from dictado.meetwatch import MeetWatch
    w = MeetWatch(Ctl(), Config(), lambda *a: None, read=lambda: ([use("zoom")], [], {"zoom"}), data_dir=tmp_path)
    assert w.call_app_now() == "zoom"
    w.call = "msteams"
    assert w.call_app_now() == "msteams"
    broken = MeetWatch(Ctl(), Config(), lambda *a: None, read=lambda: 1 / 0, data_dir=tmp_path)
    assert broken.call_app_now() is None
