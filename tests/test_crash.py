"""Crash reports (t0u.37)."""
import subprocess
import sys
from pathlib import Path

from ecoscribe import crash

APP = Path(__file__).resolve().parent.parent


def test_native_crash_leaves_every_thread_stack(tmp_path):
    """A real access violation in a child process: faulthandler writes the stack to the file."""
    code = ("import sys; sys.path.insert(0, r'%s'); from ecoscribe import crash; import os, faulthandler;"
            "crash.enable(r'%s', os.getpid());\n"
            "def dictating(): faulthandler._sigsegv()\n"
            "dictating()") % (APP, tmp_path)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60)
    assert p.returncode != 0  # (_sigsegv exits 3 via the C runtime; a real fault exits 0xC0000005)
    [f] = list((tmp_path / "crashes" / "live").glob("fault-*.log"))
    text = f.read_text(encoding="utf-8")
    assert "most recent call first" in text and "line 2 in dictating" in text


def test_report_folder_has_summary_trace_tail_and_no_secret(tmp_path):
    data = tmp_path / "data"
    fp = crash.fault_path(data, 4242)
    fp.parent.mkdir(parents=True)
    fp.write_text('Windows fatal exception: access violation\n\nCurrent thread 0x1 (most recent call first):\n'
                  '  File "C:\\x\\ecoscribe\\context.py", line 117 in window_texts\n', encoding="utf-8")
    log = tmp_path / "ecoscribe.log"
    log.write_text("\n".join(f"line {i}" for i in range(500)) + "\n2026 INFO ecoscribe.app: recording started\n")
    cfg = tmp_path / "config.toml"
    cfg.write_text('[meetings]\ncalendar_url = "https://calendar.google.com/x/private-SECRET/basic.ics"\n')
    d = crash.make_report(data, 4242, 0xC0000005, log, cfg, version="1.4.1", now=1791288000)
    rep = (d / "report.md").read_text(encoding="utf-8")
    assert "0xC0000005 (access violation)" in rep and "context.py:117 in window_texts" in rep
    assert "recording started" in rep and "Restarted: yes" in rep
    assert len((d / "log-tail.txt").read_text().splitlines()) == crash.TAIL
    assert "SECRET" not in (d / "config.toml").read_text() and "<removed>" in (d / "config.toml").read_text()
    assert not fp.exists() and (d / "fault.log").exists()
    assert crash.unseen(data, "claude") == [d] and crash.unseen(data, "user") == [d]
    crash.mark_seen(d, "user")
    assert crash.unseen(data, "user") == [] and crash.unseen(data, "claude") == [d]
    assert "Please find the cause" in crash.for_claude(d)


def test_what_counts_as_a_crash():
    assert crash.is_crash(0xC0000005, "", "")
    assert crash.is_crash(-1073741819, "", "")  # the same code, signed
    assert not crash.is_crash(1, "", "INFO all fine")  # killed: Task Manager, installer
    assert crash.is_crash(1, "", "CRITICAL unhandled error")
    assert not crash.is_crash(0, "", "") and not crash.is_crash(0x40010004, "", "")


def test_clean_exits_leave_no_fault_files(tmp_path):
    for pid, text in ((1, ""), (2, "trace"), (3, "")):
        p = crash.fault_path(tmp_path, pid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    crash.clean_live(tmp_path, alive_pids={3})
    left = sorted(p.name for p in (tmp_path / "crashes" / "live").iterdir())
    assert left == ["fault-2.log", "fault-3.log"]


def test_freeze_watch_dumps_once_per_freeze(tmp_path):
    t = [0.0]
    fw = crash.FreezeWatch(tmp_path, 7, limit_s=3.0, clock=lambda: t[0])
    t[0] = 2.0
    assert fw.check() is None
    t[0] = 3.5
    p = fw.check()
    assert p is not None and "not answering for 3.5 s" in p.read_text(encoding="utf-8")
    assert "most recent call first" in p.read_text(encoding="utf-8")  # every thread's stack
    t[0] = 9.0
    assert fw.check() is None  # same freeze: one dump
    fw.beat()
    t[0] = 13.0
    assert fw.check().name == "freeze-7-2.log"  # a new freeze after it answered again


def _api(tmp_path, copied):
    from ecoscribe.window import Api
    return Api(data_dir=tmp_path / "data", config_path=tmp_path / "config.toml", signal_reload=lambda: True,
               copy=copied.append)


def test_home_lists_crashes_until_dismissed_and_copies_the_report(tmp_path):
    copied = []
    api = _api(tmp_path, copied)
    (tmp_path / "data").mkdir()
    log = tmp_path / "data" / "ecoscribe.log"
    log.write_text("INFO ecoscribe.app: recording started\n")
    d = crash.make_report(tmp_path / "data", 9, 0xC0000005, log, version="1.4.1", now=1791288000)
    got = api.crashes()
    assert [c["name"] for c in got["items"]] == [d.name] and "access violation" in got["items"][0]["exit"]
    assert api.copy_crash_report(d.name)["ok"] and "Please find the cause" in copied[-1]
    assert api.crashes()["items"] == []  # copying it counts as seen
    assert crash.unseen(tmp_path / "data", "claude") == [d]  # Claude's marker is separate
    assert not api.copy_crash_report("../../etc")["ok"]


def test_debug_info_has_logs_status_and_no_secret(tmp_path):
    copied = []
    api = _api(tmp_path, copied)
    data = tmp_path / "data"
    data.mkdir()
    (data / "ecoscribe.log").write_text("\n".join(f"log line {i}" for i in range(400)))
    (tmp_path / "config.toml").write_text('[meetings]\ncalendar_url = "https://x/private-SECRET/basic.ics"\n')
    api.copy_debug_info()
    text = copied[-1]
    assert "log line 399" in text and "log line 150" not in text  # last 200 lines
    assert "SECRET" not in text and "Version:" in text and "Recent crashes: none" in text


def test_detailed_logging_setting(tmp_path):
    from ecoscribe import config
    api = _api(tmp_path, [])
    assert api.get_settings()["values"]["debug_log"] is False
    assert api.save_settings({"debug_log": True})["ok"]
    assert config.load(tmp_path / "config.toml").ui.debug_log is True


def test_reports_dismissed_by_1_4_1_stay_dismissed(tmp_path):
    log = tmp_path / "ecoscribe.log"
    log.write_text("x\n")
    d = crash.make_report(tmp_path, 5, 0xC0000005, log, now=1791288000)
    (d / "seen-erik").write_text("1")  # the 1.4.1 marker name
    assert crash.unseen(tmp_path, "user") == [] and crash.unseen(tmp_path, "claude") == [d]
