"""The watchdog (t0u.37) with a fake process table."""
import json

from ecoscribe import crash
from ecoscribe.supervise import Supervisor


class Procs:
    def __init__(self):
        self.live, self.codes = set(), {}

    def open(self, pid):
        return pid if pid in self.live or pid in self.codes else None

    def alive(self, h):
        return h in self.live

    def exit_code(self, h):
        return self.codes.get(h, 0)

    def end(self, pid, code):
        self.live.discard(pid)
        self.codes[pid] = code


def setup(tmp_path, pid=100, state="ready"):
    data = tmp_path / "data"
    data.mkdir()
    (data / "status.json").write_text(json.dumps({"pid": pid, "state": state}))
    log = data / "ecoscribe.log"
    log.write_text("INFO ecoscribe.app: recording started\n")
    procs, spawned, t = Procs(), [], [1000.0]
    procs.live.add(pid)
    sup = Supervisor(data, spawn=spawned.append, proc=procs, log_path=log, version="1.4.1", clock=lambda: t[0])
    assert sup.step() == "ok" and sup.pid == pid
    return sup, procs, spawned, data, t


def status(data, **kw):
    st = json.loads((data / "status.json").read_text())
    st.update(kw)
    (data / "status.json").write_text(json.dumps(st))


def test_crash_makes_a_report_and_restarts(tmp_path):
    sup, procs, spawned, data, _ = setup(tmp_path)
    procs.end(100, 0xC0000005)
    assert sup.step() == "ok"
    [rep] = crash.reports(data)
    assert spawned == [["--restarted", "--after-crash", str(rep)]]
    assert "access violation" in (rep / "report.md").read_text(encoding="utf-8")
    status(data, pid=200)  # the new copy is up
    procs.live.add(200)
    assert sup.step() == "ok" and sup.pid == 200


def test_quit_ends_the_watchdog(tmp_path):
    sup, procs, spawned, data, _ = setup(tmp_path)
    status(data, state="stopped")
    procs.end(100, 0)
    assert sup.step() == "quit" and spawned == [] and crash.reports(data) == []


def test_settings_restart_is_followed_not_reported(tmp_path):
    sup, procs, spawned, data, _ = setup(tmp_path)
    status(data, state="restarting")
    procs.end(100, 0)
    assert sup.step() == "ok" and spawned == []
    status(data, pid=300, state="loading")
    procs.live.add(300)
    assert sup.step() == "ok" and sup.pid == 300 and crash.reports(data) == []


def test_restart_that_never_comes_back_is_started(tmp_path):
    sup, procs, spawned, data, t = setup(tmp_path)
    status(data, state="restarting")
    procs.end(100, 0)
    sup.step()
    t[0] += 31
    sup.step()
    assert spawned == [["--restarted"]]


def test_killed_is_not_a_crash(tmp_path):
    sup, procs, spawned, data, _ = setup(tmp_path)
    procs.end(100, 1)  # taskkill /F
    assert sup.step() == "killed" and spawned == [] and crash.reports(data) == []


def test_third_crash_in_ten_minutes_stops_restarting(tmp_path):
    sup, procs, spawned, data, t = setup(tmp_path)
    for i, pid in enumerate((100, 201, 202)):
        if i:
            status(data, pid=pid, state="ready")
            procs.live.add(pid)
            sup.step()
        procs.end(pid, 0xC0000005)
        r = sup.step()
        t[0] += 60
    assert r == "gave_up" and len(spawned) == 2
    st = json.loads((data / "status.json").read_text())
    assert st["state"] == "crashed" and "3 times" in st["error"]
    assert "stopped restarting" in (crash.reports(data)[0] / "report.md").read_text(encoding="utf-8")


class MacProcs(Procs):
    """macOS: the watchdog isn't the app's parent, so there is never an exit code."""

    def __init__(self):
        super().__init__()
        self.killed = []

    def exit_code(self, h):
        return None

    def kill(self, h):
        self.killed.append(h)
        self.live.discard(h)


def mac_setup(tmp_path, hang_s=None):
    sup, _, spawned, data, t = setup(tmp_path)
    procs = MacProcs()
    procs.live.add(100)
    sup.proc, sup.hang_s = procs, hang_s
    return sup, procs, spawned, data, t


def test_mac_crash_with_a_native_trace_is_a_crash(tmp_path):
    sup, procs, spawned, data, _ = mac_setup(tmp_path)
    fp = crash.fault_path(data, 100)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text('Fatal Python error: Segmentation fault\n\nCurrent thread 0x1 (most recent call first):\n'
                  '  File "/x/ecoscribe/engine.py", line 42 in run\n')
    procs.live.discard(100)
    assert sup.step() == "ok"
    [rep] = crash.reports(data)
    assert spawned == [["--restarted", "--after-crash", str(rep)]]
    text = (rep / "report.md").read_text(encoding="utf-8")
    assert "Exit: unknown" in text and "engine.py:42 in run" in text


def test_mac_unhandled_error_in_the_log_is_a_crash(tmp_path):
    sup, procs, spawned, data, _ = mac_setup(tmp_path)
    (data / "ecoscribe.log").write_text("CRITICAL ecoscribe.crash: unhandled error\nTraceback ...\n")
    procs.live.discard(100)
    assert sup.step() == "ok" and len(crash.reports(data)) == 1


def test_mac_kill_without_a_trace_is_not_a_crash(tmp_path):
    sup, procs, spawned, data, _ = mac_setup(tmp_path)
    procs.live.discard(100)  # kill -9, Activity Monitor > Force Quit
    assert sup.step() == "killed" and spawned == [] and crash.reports(data) == []


def test_frozen_past_hang_s_is_killed_reported_and_restarted(tmp_path):
    sup, procs, spawned, data, t = mac_setup(tmp_path, hang_s=60)
    fw = crash.FreezeWatch(data, 100, limit_s=3.0, clock=lambda: t[0])
    t[0] += 5
    dump = fw.check()  # the app's own thread notices the freeze and dumps every stack
    assert dump and fw.marker().exists()
    (fw.marker()).write_text(str(t[0] - 5))  # the marker holds wall time; the test clock stands in for it
    assert sup.step() == "ok" and procs.killed == []  # first sighting: the 60 s count starts now
    t[0] += 30
    assert sup.step() == "ok" and procs.killed == [] and spawned == []  # watched 30 s: not yet
    t[0] += 31
    assert sup.step() == "ok" and procs.killed == [100]
    [rep] = crash.reports(data)
    assert spawned == [["--restarted", "--after-crash", str(rep)]]
    assert "Frozen" in (rep / "report.md").read_text(encoding="utf-8")
    assert (rep / dump.name).exists() and not fw.marker().exists()


def test_hang_check_is_off_without_hang_s(tmp_path):
    sup, procs, spawned, data, t = mac_setup(tmp_path)
    fw = crash.FreezeWatch(data, 100, limit_s=3.0, clock=lambda: t[0])
    t[0] += 5
    fw.check()
    t[0] += 600
    assert sup.step() == "ok" and procs.killed == [] and spawned == []


def test_freeze_marker_goes_when_the_main_thread_answers(tmp_path):
    data = tmp_path
    t = [0.0]
    fw = crash.FreezeWatch(data, 7, limit_s=3.0, clock=lambda: t[0])
    t[0] = 5
    fw.check()
    assert fw.marker().exists()
    fw.beat()
    assert not fw.marker().exists()


def test_restarted_copy_quit_before_it_was_picked_up_is_a_quit(tmp_path):
    sup, procs, spawned, data, t = setup(tmp_path)
    procs.end(100, 0xC0000005)
    assert sup.step() == "ok" and len(spawned) == 1  # crash -> restarted
    status(data, pid=200, state="stopped")  # the new copy started and was quit before the next look
    procs.end(200, 0)
    assert sup.step() == "quit"
    t[0] += 60
    assert len(spawned) == 1  # never started again



def test_waking_from_sleep_does_not_kill_a_healthy_app(tmp_path):
    """The marker's last beat is hours old after the PC slept; the app answers again at once."""
    sup, procs, spawned, data, t = mac_setup(tmp_path, hang_s=60)
    fw = crash.FreezeWatch(data, 100, limit_s=3.0, clock=lambda: t[0])
    t[0] += 8 * 3600  # a night's sleep
    fw.check()  # the freeze thread wakes first and writes the marker
    assert sup.step() == "ok" and procs.killed == []
    fw.beat()  # the main thread answers: marker gone
    t[0] += 120
    assert sup.step() == "ok" and procs.killed == [] and spawned == []


def test_windows_frozen_app_is_killed_too(tmp_path):
    """dictado-yjr: the same hang check on Windows (WinProc gained kill)."""
    sup, procs, spawned, data, t = setup(tmp_path)
    killed = []
    procs.kill = lambda h: (killed.append(h), procs.end(h, 0xDEAD))
    sup.hang_s = 60
    m = crash.crashes_dir(data) / "live" / "frozen-100"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text("0")
    sup.step()
    t[0] += 61
    sup.step()
    assert killed == [100] and spawned and spawned[0][:2] == ["--restarted", "--after-crash"]


def test_winproc_kill_ends_a_real_process():
    import subprocess
    import sys
    import time

    import pytest
    if sys.platform != "win32":
        pytest.skip("Windows process handles")
    from ecoscribe.supervise import WinProc
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    wp = WinProc()
    h = wp.open(p.pid)
    assert wp.alive(h)
    wp.kill(h)
    end = time.monotonic() + 5
    while wp.alive(h) and time.monotonic() < end:
        time.sleep(0.05)
    assert not wp.alive(h) and wp.exit_code(h) == 0xDEAD
