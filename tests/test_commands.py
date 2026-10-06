"""Window -> background command channel (no real event: signal and watcher are faked)."""
import threading
import time
from pathlib import Path

from dictado import commands


def test_round_trip(tmp_path):
    seen = []

    def signal():  # the background app answers as soon as it's signalled
        threading.Thread(target=lambda: commands.run_pending(
            tmp_path, lambda c, a: seen.append((c, a)) or {"ok": True, "dir": "D"})).start()
        return True
    out = commands.send(tmp_path, "start_meeting", {"lang": "sv"}, signal=signal)
    assert out == {"ok": True, "dir": "D"} and seen == [("start_meeting", {"lang": "sv"})]
    assert list((tmp_path / "commands").iterdir()) == []  # nothing left behind


def test_not_running_is_reported_and_cleaned(tmp_path):
    out = commands.send(tmp_path, "stop_meeting", signal=lambda: False)
    assert out == {"ok": False, "error": commands.NOT_RUNNING}
    assert list((tmp_path / "commands").iterdir()) == []


def test_signalled_but_nobody_answers(tmp_path):
    t0 = time.monotonic()
    out = commands.send(tmp_path, "stop_meeting", signal=lambda: True, wait_s=0.3)
    assert out["error"] == commands.NOT_RUNNING and time.monotonic() - t0 < 2
    assert list((tmp_path / "commands").iterdir()) == []  # a later start won't run a stale stop


def test_handler_errors_become_answers(tmp_path):
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "a.json").write_text('{"cmd": "x", "args": {}}', encoding="utf-8")
    assert commands.run_pending(tmp_path, lambda c, a: 1 / 0) == 1
    assert "ZeroDivisionError" in (tmp_path / "commands" / "a.done.json").read_text(encoding="utf-8")


class Ctl:
    def __init__(self):
        self.calls = []

    def start_meeting(self, lang, title="Reunión", app=None):
        self.calls.append(("start", lang, title))
        return Path("T/2026-10-05_1400_reunion")

    def stop_meeting(self):
        self.calls.append(("stop",))

    def enqueue_file(self, path, lang, title=None):
        self.calls.append(("file", Path(path).name, lang))
        return Path("T/x")


class Watch:
    def __init__(self):
        self.langs = {"_manual": "en"}

    def lang_for(self, app):
        return self.langs.get(app, "sv")

    def remember(self, app, lang):
        self.langs[app] = lang


def test_handler_table(tmp_path):
    ctl, w = Ctl(), Watch()
    h = commands.handler_for(ctl, w)
    assert h("start_meeting", {})["ok"] and ctl.calls[-1] == ("start", "en", "Meeting")  # last manual language
    h("start_meeting", {"lang": "el"})
    assert w.langs["_manual"] == "el"
    assert h("stop_meeting", {}) == {"ok": True}
    f = tmp_path / "pod.mp3"
    f.write_bytes(b"x")
    assert h("import_files", {"paths": [str(f)], "lang": "el"}) == {"ok": True, "queued": 1}
    for _ in range(100):
        if ("file", "pod.mp3", "el") in ctl.calls:
            break
        time.sleep(0.01)
    assert ("file", "pod.mp3", "el") in ctl.calls
    assert not h("import_files", {"paths": [str(tmp_path / "nope.mp3")]})["ok"]
    assert not h("borrar_todo", {})["ok"]


def test_stale_answers_are_cleaned(tmp_path):
    import os
    d = tmp_path / "commands"
    d.mkdir()
    old, new = d / "a.done.json", d / "b.done.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    commands.run_pending(tmp_path, lambda c, a: {})
    assert not old.exists() and new.exists()  # a fresh answer may still be read by its sender


def test_set_meeting_lang_command():
    class C:
        def __init__(self):
            self.langs = []

        def set_lang(self, lang):
            self.langs.append(lang)
            return lang != "el"
    c = C()
    h = commands.handler_for(c, None)
    assert h("set_meeting_lang", {"lang": "en"}) == {"ok": True} and c.langs == ["en"]
    assert not h("set_meeting_lang", {"lang": "fr"})["ok"]
    assert h("set_meeting_lang", {"lang": "el"})["error"] == "No meeting is recording"
