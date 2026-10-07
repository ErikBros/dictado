"""Home crash card + Settings > Troubleshooting with what the macOS watchdog writes (dictado-4ey)."""
import json
import sys

import pytest

from ecoscribe import crash
from ecoscribe.supervise import Supervisor
from ecoscribe.window import Api


class MacProcs:
    """No exit code for a process the watchdog didn't start (macOS)."""

    def __init__(self, live):
        self.live = set(live)

    def open(self, pid):
        return pid if pid in self.live else None

    def alive(self, h):
        return h in self.live

    def exit_code(self, h):
        return None

    def kill(self, h):
        self.live.discard(h)


@pytest.fixture
def mac_crash(tmp_path):
    """A native crash on the Mac, through the real Supervisor: a report folder like the app makes."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "status.json").write_text(json.dumps({"pid": 100, "state": "ready"}))
    (data / "ecoscribe.log").write_text("INFO ecoscribe: ready\n")
    (data / "stderr.log").write_text("libc++abi: terminating due to uncaught exception of type std::runtime_error\n")
    fp = crash.fault_path(data, 100)
    fp.parent.mkdir(parents=True)
    fp.write_text('Fatal Python error: Segmentation fault\n\nCurrent thread 0x1 (most recent call first):\n'
                  '  File "/x/ecoscribe/platform/macos/mlx_engine.py", line 77 in on_mlx\n')
    procs, spawned = MacProcs({100}), []
    sup = Supervisor(data, spawn=spawned.append, proc=procs, log_path=data / "ecoscribe.log", version="1.4.3")
    assert sup.step() == "ok"
    procs.live.discard(100)
    assert sup.step() == "ok" and spawned  # reported and restarted
    copied = []
    api = Api(data_dir=data, config_path=tmp_path / "config.toml", copy=copied.append)
    return api, data, copied


def test_the_card_shows_a_mac_crash_and_copies_it_for_claude(mac_crash):
    api, data, copied = mac_crash
    c = api.crashes()
    [item] = c["items"]
    assert item["exit"] == "unknown" and not c["gave_up"]
    assert api.copy_crash_report(item["name"])["ok"]
    assert "mlx_engine.py:77 in on_mlx" in copied[0] and "Please find the cause" in copied[0]
    assert api.crashes()["items"] == []  # copied = seen


def test_debug_info_names_the_platform_and_has_the_crash(mac_crash):
    api, data, _ = mac_crash
    info = api.debug_info()
    assert "Platform: " in info and "Recent crashes: " + crash.reports(data)[0].name in info
    if sys.platform == "darwin":
        assert "macOS" in info and "## stderr.log" in info and "libc++abi" in info


def test_open_logs_folder_uses_the_platform_opener(mac_crash, monkeypatch):
    from ecoscribe import window
    api, data, _ = mac_crash
    opened = []
    monkeypatch.setattr(window, "_startfile", opened.append)
    assert api.open_logs_folder()["ok"] and opened == [str(data)]
