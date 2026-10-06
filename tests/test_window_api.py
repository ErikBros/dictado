import json
import os
import time

import pytest

from dictado import config, status
from dictado.window import Api


class FakeStartup:
    def __init__(self):
        self.value = None

    def app_command(self):
        return '"C:\\Apps\\Dictado\\Dictado.exe"'

    def is_enabled(self):
        return self.value is not None

    def enable(self, cmd):
        self.value = cmd

    def disable(self):
        self.value = None


@pytest.fixture
def api(tmp_path):
    signals = []
    a = Api(data_dir=tmp_path / "data", config_path=tmp_path / "cfg" / "config.toml",
            startup_mod=FakeStartup(), signal_reload=lambda: signals.append(1) or True,
            list_mic_names=lambda: ["Headset (Zone Vibe 100)", "Microphone (Anker PowerConf C20"],
            copy=lambda s: signals.append(("copy", s)))
    a._signals = signals
    (tmp_path / "data").mkdir()
    return a


def write_history(api, rows):
    with open(api._data_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_get_settings_defaults_and_options(api):
    s = api.get_settings()
    assert s["values"]["languages"] == "en"
    assert "ralt" not in [h["value"] for h in s["options"]["hotkeys"]]
    assert s["can_startup"] is True
    if config.MAC:  # Right Command, the system's default mic
        assert s["values"]["hotkey"] == "rcmd" and s["values"]["mic"] == ""
        assert {"value": "rcmd", "label": "Right Command (recommended)"} in s["options"]["hotkeys"]
        assert s["options"]["mics"][0] == {"value": "", "label": "System default"}
    else:
        assert s["values"]["hotkey"] == "rctrl"
        assert s["values"]["mic"] == ""  # a fresh install uses the Windows default mic
        assert {"value": "rctrl", "label": "Right Ctrl (recommended)"} in s["options"]["hotkeys"]
        assert s["options"]["mics"][0] == {"value": "", "label": "Windows default"}
        assert {"value": "Microphone (Anker PowerConf C20", "label": "Anker PowerConf C20"} in s["options"]["mics"]


def test_current_mic_kept_even_if_unplugged(api):
    assert api.save_settings({"mic": "Anker PowerConf"})["ok"]
    api._list_mic_names = lambda: ["Headset (Zone Vibe 100)"]
    s = api.get_settings()
    assert any(m["value"] == "Anker PowerConf" for m in s["options"]["mics"])


def test_save_settings_writes_config_toggles_startup_and_reloads(api):
    r = api.save_settings({"hotkey": "f13", "mic": "Headset (Zone Vibe 100)", "languages": "en,es",
                           "sounds": False, "overlay": True, "unmute": False, "startup": True})
    assert r["ok"] and r["restarting"]
    c = config.load(api._config_path)
    assert c.hotkey.key == "f13" and c.audio.device == "Headset (Zone Vibe 100)"
    assert c.whisper.languages == ["en", "es"] and c.ui.sounds is False and c.audio.unmute_while_recording is False
    assert api._startup.value == '"C:\\Apps\\Dictado\\Dictado.exe"'
    assert api._signals == [1]
    api.save_settings({"startup": False})
    assert api._startup.value is None
    assert config.load(api._config_path).hotkey.key == "f13"  # partial save keeps the rest


def test_save_settings_rejects_bad_values(api):
    r = api.save_settings({"hotkey": "ralt"})
    assert not r["ok"] and "not allowed" in r["error"]  # Right Alt is AltGr on the user's layout
    assert not api._config_path.exists()
    assert not api.save_settings({"languages": "fr"})["ok"]


def test_default_mic_is_empty_string_and_disables_gate(api):
    api.save_settings({"mic": ""})
    assert config.load(api._config_path).audio.device == ""


def test_history_newest_first_search_and_stats(api):
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_history(api, [
        {"ts": "2026-09-30T10:00:00", "text": "old one here ", "target": "slack.exe", "pasted": True},
        {"ts": now, "text": "Send the report today ", "target": "WindowsTerminal.exe", "pasted": True},
        {"ts": now, "text": "Climbing on Thursday ", "target": "chrome.exe", "pasted": False},
    ])
    h = api.get_history()
    assert [r["text"] for r in h["items"]][0] == "Climbing on Thursday "
    assert h["stats"]["today_words"] == 7 and h["stats"]["total_words"] == 10 and h["stats"]["total"] == 3
    assert [r["text"] for r in api.get_history(query="report")["items"]] == ["Send the report today "]


def test_history_survives_garbage_lines(api):
    (api._data_dir / "history.jsonl").write_text('{"text": "ok "}\nnot json\n\n', encoding="utf-8")
    assert [r["text"] for r in api.get_history()["items"]] == ["ok "]


def test_history_missing_file(api):
    assert api.get_history()["items"] == []


def test_clear_history_keeps_a_backup(api):
    write_history(api, [{"text": "a "}])
    api.clear_history()
    assert api.get_history()["items"] == []
    assert list(api._data_dir.glob("history-*.bak"))


def test_copy_text(api):
    api.copy_text("hola ")
    assert ("copy", "hola ") in api._signals


def test_status_alive_and_dead(api):
    assert api.get_status()["state"] == "stopped"
    status.write(api._data_dir / "status.json", state="ready", device="cuda")
    s = api.get_status()
    assert s["state"] == "ready" and s["alive"] is True  # our own pid wrote it
    p = api._data_dir / "status.json"
    d = json.loads(p.read_text())
    d["pid"] = 999999
    p.write_text(json.dumps(d))
    assert api.get_status()["state"] == "stopped"


def test_welcome_flag(api):
    assert api.get_welcome()["done"] is False
    api.finish_welcome()
    assert api.get_welcome()["done"] is True


from dictado.window import pretty_mic


def test_pretty_mic():
    assert pretty_mic("Microphone (Anker PowerConf C20") == "Anker PowerConf C20"
    assert pretty_mic("Headset (Zone Vibe 100)") == "Zone Vibe 100"
    assert pretty_mic("Line In") == "Line In"
    assert pretty_mic("") == ""


class FakeRec:
    instances = []

    def __init__(self, cfg, fail_begin=False):
        self.cfg, self.closed, self.aborted, self.device_name, self.fell_back = cfg, False, False, cfg.device, False
        self.fail_begin = fail_begin
        FakeRec.instances.append(self)

    def open(self): pass
    def begin(self):
        if self.fail_begin:
            raise OSError("no mic")
    def abort(self): self.aborted = True
    def close(self): self.closed = True
    def level(self): return 0.1


class FakeGate:
    instances = []

    def __init__(self, *a, **k):
        self.opened = self.restored = 0
        FakeGate.instances.append(self)

    def open(self): self.opened += 1
    def restore(self): self.restored += 1


def _fake_mic(api, monkeypatch, fail_begin=False):
    FakeRec.instances, FakeGate.instances = [], []
    import dictado.audio
    import dictado.micgate
    monkeypatch.setattr(dictado.audio, "Recorder", lambda cfg: FakeRec(cfg, fail_begin))
    monkeypatch.setattr(dictado.micgate, "MicGate", FakeGate)


def test_mic_test_start_stop_restores_gate(api, monkeypatch):
    _fake_mic(api, monkeypatch)
    api.mic_test_start("Anker PowerConf")
    assert api.mic_test_level() == 0.1
    api.mic_test_start("Headset")  # a second start replaces the first, never leaks it
    api.mic_test_stop()
    assert all(r.closed for r in FakeRec.instances) and all(g.restored == 1 for g in FakeGate.instances)
    assert api.mic_test_level() == 0.0


def test_mic_test_start_failure_restores_gate(api, monkeypatch):
    _fake_mic(api, monkeypatch, fail_begin=True)
    r = api.mic_test_start("Anker PowerConf")
    assert r.get("error")
    assert FakeGate.instances[0].restored == 1 and FakeRec.instances[0].closed


def test_concurrent_mic_test_calls_leak_nothing(api, monkeypatch):
    import threading
    _fake_mic(api, monkeypatch)
    ts = [threading.Thread(target=api.mic_test_start, args=("Anker",)) for _ in range(8)]
    ts += [threading.Thread(target=api.mic_test_stop) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    api.mic_test_stop()
    assert all(r.closed for r in FakeRec.instances)
    assert all(g.restored == 1 for g in FakeGate.instances)


def test_api_exposes_no_public_data_attributes(api):
    """pywebview turns every public attribute into JS API; only methods may be public."""
    leaks = [n for n in dir(api) if not n.startswith("_") and not callable(getattr(api, n))]
    assert leaks == []


def test_meeting_settings_and_on_demand_round_trip(api):
    v = api.get_settings()
    assert v["values"]["meet_mode"] == "prompt" and v["values"]["meet_lang"] == "sv" and v["values"]["on_demand"] is True
    assert [o["value"] for o in v["options"]["meet_modes"]] == ["prompt", "auto", "off"]
    assert api.save_settings({"meet_mode": "auto", "meet_lang": "el", "on_demand": False})["ok"]
    c = config.load(api._config_path)
    assert c.meetings.mode == "auto" and c.meetings.default_lang == "el" and c.whisper.on_demand is False
    assert not api.save_settings({"meet_mode": "siempre"})["ok"]
    assert not api.save_settings({"meet_lang": "fr"})["ok"]



def test_combo_shortcuts(api):
    if config.MAC:
        assert api.check_hotkey("Shift + Cmd + D") == {"ok": True, "value": "shift+cmd+d", "label": "Shift+Cmd+D"}
        assert not api.check_hotkey("cmd+c")["ok"] and not api.check_hotkey("alt+d")["ok"]
        assert api.save_settings({"hotkey": "shift+cmd+d"})["ok"] and config.load(api._config_path).hotkey.vk == 0
        return
    assert api.check_hotkey("Ctrl + L") == {"ok": True, "value": "ctrl+l", "label": "Ctrl+L"}
    assert not api.check_hotkey("ctrl+c")["ok"] and not api.check_hotkey("ctrl+alt+d")["ok"]
    assert api.save_settings({"hotkey": "ctrl+shift+d"})["ok"]
    c = config.load(api._config_path)
    assert c.hotkey.key == "ctrl+shift+d" and c.hotkey.vk == 0  # combos go through hotkeys.ComboMatcher
    assert api.get_settings()["values"]["hotkey_label"] == "Ctrl+Shift+D"


def test_swedish_is_a_dictation_language_on_its_own(tmp_path):
    """t0u.24: Swedish alone is allowed; Swedish mixed with others is not (one model per language set)."""
    from dictado.window import Api, LANGUAGES
    cfg = tmp_path / "config.toml"
    api = Api(data_dir=tmp_path, config_path=cfg, signal_reload=lambda: True)
    assert ("sv", "Swedish") in LANGUAGES
    assert api.save_settings({"languages": "sv"})["ok"]
    assert api.get_settings()["values"]["languages"] == "sv"
    assert not api.save_settings({"languages": "en,sv"})["ok"]
