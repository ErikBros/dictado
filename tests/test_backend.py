import sys
import threading
import time
import uuid

import pytest

from dictado import config, ipc, startup, status, tomlw


def test_toml_roundtrip(tmp_path):
    c = config.Config()
    c.hotkey.key = "f13"
    c.audio.device = 'Mic "quoted" \\ name'
    c.whisper.languages = ["en", "es"]
    c.ui.sounds = False
    c.limits.max_record_s = 120.0
    p = tmp_path / "config.toml"
    tomlw.save(c, p)
    back = config.load(p)
    assert back == c


def test_toml_save_is_atomic_and_creates_dir(tmp_path):
    p = tmp_path / "sub" / "config.toml"
    tomlw.save(config.Config(), p)
    assert p.exists() and not list(p.parent.glob("*.tmp"))


def test_startup_toggle_uses_given_value_name():
    name = f"DictadoTest-{uuid.uuid4().hex[:6]}"
    try:
        assert not startup.is_enabled(name)
        startup.enable('"C:\\x\\Dictado.exe"', name)
        assert startup.is_enabled(name) and startup.get(name) == '"C:\\x\\Dictado.exe"'
        startup.disable(name)
        assert not startup.is_enabled(name)
        startup.disable(name)  # idempotent
    finally:
        startup.disable(name)


def test_status_roundtrip(tmp_path):
    p = tmp_path / "status.json"
    assert status.read(p) is None
    status.write(p, state="ready", device="cuda", mic="Anker")
    s = status.read(p)
    assert s["state"] == "ready" and s["device"] == "cuda" and "ts" in s and "pid" in s
    status.write(p, state="loading")
    assert status.read(p)["state"] == "loading" and status.read(p)["device"] == "cuda"  # merged


def test_status_corrupt_file_reads_none(tmp_path):
    p = tmp_path / "status.json"
    p.write_text("{nope", encoding="utf-8")
    assert status.read(p) is None


def test_reload_event_roundtrip():
    name = f"Local\\DictadoTestReload-{uuid.uuid4().hex[:6]}"
    assert ipc.signal_reload(name) is False  # nobody listening
    got = threading.Event()
    w = ipc.ReloadWatcher(got.set, name)
    w.start()
    time.sleep(0.1)
    assert ipc.signal_reload(name) is True
    assert got.wait(2)
    w.stop()


def test_self_command_dev_vs_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = ipc.self_command(["--ui", "--page", "historial"])
    assert cmd[0] == sys.executable and cmd[1:3] == ["-m", "dictado"] and cmd[-2:] == ["--page", "historial"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Dictado\Dictado.exe")
    assert ipc.self_command(["--ui"]) == [r"C:\Apps\Dictado\Dictado.exe", "--ui"]


def test_startup_command_only_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert startup.app_command() is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Dictado\Dictado.exe")
    want = r"C:\Apps\Dictado\Dictado.exe" if sys.platform == "darwin" else '"C:\\Apps\\Dictado\\Dictado.exe"'
    assert startup.app_command() == want  # a LaunchAgent takes the bare path, the Run key a quoted one


from dictado.__main__ import decide_launch


@pytest.mark.parametrize("have,restarted,test,want", [
    (True, False, False, "run"),
    (True, True, False, "run"),
    (False, False, False, "open_ui"),   # Start-menu click while running: never a 2nd engine
    (False, True, False, "wait"),       # the old copy is still shutting down
    (False, False, True, "exit"),       # test instances never open windows
])
def test_decide_launch(have, restarted, test, want):
    assert decide_launch(have, restarted, test) == want


def test_toml_escapes_control_characters(tmp_path):
    c = config.Config()
    c.audio.device = "Mic\tone\nline é \"q\" \\ end"
    p = tmp_path / "c.toml"
    tomlw.save(c, p)
    assert config.load(p).audio.device == c.audio.device
