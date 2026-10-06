"""The watchdog (t0u.37) with a fake process table."""
import json

from dictado import crash
from dictado.supervise import Supervisor


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
    log = data / "dictado.log"
    log.write_text("INFO dictado.app: recording started\n")
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
