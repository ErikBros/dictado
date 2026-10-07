"""Permissions granted while Ecoscribe runs show up without a restart (dictado-6qp). No real TCC calls."""
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS")


def _seq(*states):
    it = iter(states)
    last = {}

    def check():
        nonlocal last
        last = next(it, last)
        return dict(last)
    return check


def test_mic_granted_later_is_reported_and_watch_ends():
    from ecoscribe.platform.macos import permissions
    off = {"accessibility": True, "input": True, "microphone": False, "audio": True}
    on = {**off, "microphone": True}
    seen = []
    permissions.watch(lambda st, old: seen.append((st, old)), interval=0, check=_seq(off, off, on))
    assert seen == [(off, None), (on, off)]  # first look, then only the change
    assert permissions.missing(st=off) == ["Microphone"] and permissions.missing(st=on) == []


def test_all_on_at_start_checks_once():
    from ecoscribe.platform.macos import permissions
    calls = []
    on = {"accessibility": True, "input": True, "microphone": True, "audio": True}
    permissions.watch(lambda st, old: calls.append(st), interval=0, check=_seq(on))
    assert calls == [on]


def test_stop_ends_the_watch():
    from ecoscribe.platform.macos import permissions
    stop = threading.Event()
    stop.set()
    off = {"accessibility": False, "input": False, "microphone": False, "audio": False}
    calls = []
    permissions.watch(lambda st, old: calls.append(st), interval=60, stop=stop, check=_seq(off))
    assert calls == [off]  # returned at once, no 60 s wait
