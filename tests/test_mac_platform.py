"""macOS pieces of the platform seam (uat.2): signals, commands over them, the login agent, pid adoption."""
import os
import subprocess
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS implementations")


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "d"  # short: Unix socket paths max out at 104 bytes
    monkeypatch.setenv("ECOSCRIBE_DATA_DIR", str(d))
    return d


def test_signal_reaches_a_listener_and_says_when_nobody_listens():
    from ecoscribe.platform.macos import signals
    assert signals.signal("Local\\EcoscribeT1") is False  # nobody created it, like OpenEvent failing
    lst = signals.Listener("Local\\EcoscribeT1")
    try:
        assert signals.signal("Local\\EcoscribeT1", b"hi") is True
        assert lst.wait(1) == b"hi"
        assert lst.wait(0.05) is None  # auto-reset: one signal, one wake
    finally:
        lst.close()
    assert signals.signal("Local\\EcoscribeT1") is False


def test_close_wakes_a_blocked_wait():
    from ecoscribe.platform.macos import signals
    lst = signals.Listener("Local\\EcoscribeT2")
    got = []
    t = threading.Thread(target=lambda: got.append(lst.wait(None)))
    t.start()
    time.sleep(0.1)
    lst.close()
    t.join(2)
    assert not t.is_alive() and got == [None]


def test_stale_socket_from_a_crash_is_replaced():
    from ecoscribe.platform.macos import signals
    path = signals.sock_path("Local\\EcoscribeT3")
    open(path, "w").close()  # a leftover file, nobody bound
    assert signals.signal("Local\\EcoscribeT3") is False
    lst = signals.Listener("Local\\EcoscribeT3")
    try:
        assert signals.signal("Local\\EcoscribeT3") is True
    finally:
        lst.close()


def test_reload_watcher_runs_the_handler(data_dir):
    from ecoscribe import ipc
    hits = []
    w = ipc.ReloadWatcher(lambda: hits.append(1), "Local\\EcoscribeReload-t")
    w.start()
    try:
        assert ipc.signal_reload("Local\\EcoscribeReload-t")
        end = time.monotonic() + 2
        while not hits and time.monotonic() < end:
            time.sleep(0.02)
        assert hits == [1]
    finally:
        w.stop()


def test_window_command_round_trip_through_the_watcher(data_dir):
    from ecoscribe import commands
    w = commands.Watcher(data_dir, lambda cmd, args: {"ok": True, "cmd": cmd, "args": args})
    w.start()
    try:
        out = commands.send(data_dir, "stop_meeting", {"x": 1})
        assert out == {"ok": True, "cmd": "stop_meeting", "args": {"x": 1}}
    finally:
        w.stop()
    assert commands.send(data_dir, "stop_meeting", wait_s=0.2) == {"ok": False, "error": commands.NOT_RUNNING}


def test_login_agent_round_trip(tmp_path, monkeypatch):
    from ecoscribe.platform.macos import startup
    monkeypatch.setattr(startup.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(startup.subprocess, "run", lambda *a, **k: None)  # never touch the real launchd
    assert not startup.is_enabled()
    startup.enable("/Applications/Dictado.app/Contents/MacOS/Dictado")
    assert startup.get() == "/Applications/Dictado.app/Contents/MacOS/Dictado"
    startup.disable()
    assert not startup.is_enabled()


def test_attach_pid_adopts_only_live_ecoscribe_processes():
    from ecoscribe.platform.macos import procs
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        p = procs.attach_pid(child.pid)  # dev runs are python: adopted
        assert p is not None and p.poll() is None
        p.kill()
        child.wait(5)
        assert procs.attach_pid(child.pid) is None
    finally:
        child.kill()
    assert procs.attach_pid(os.getppid() if False else 1) is None  # launchd: not ours


def test_default_mic_on_mac_is_the_system_default():
    from ecoscribe.choose import pick_device
    devs = [{"name": "MacBook Pro Microphone", "hostapi": 0, "max_input_channels": 1}]
    assert pick_device(devs, [{"name": "Core Audio"}], "", "Core Audio") is None
    assert pick_device(devs, [{"name": "Core Audio"}], "macbook", "Core Audio") == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS")
def test_spawned_copies_start_where_python_finds_the_package():
    from pathlib import Path
    from ecoscribe.platform.macos import ipc
    assert (Path(ipc._package_parent()) / "ecoscribe" / "__main__.py").exists()
