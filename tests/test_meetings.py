"""Meeting/job controller: one worker at a time, with a fake spawn."""
import json
from pathlib import Path
from types import SimpleNamespace

from dictado import meetings, sessions
from dictado.config import Config


class FakeProc:
    _pid = 1000

    def __init__(self, args):
        FakeProc._pid += 1
        self.pid, self.args, self.rc, self.killed = FakeProc._pid, list(args), None, False

    def poll(self):
        return self.rc

    def kill(self):
        self.killed, self.rc = True, -9

    def wait(self, timeout=None):
        return self.rc


class Spawner:
    def __init__(self):
        self.procs = []

    def __call__(self, args):
        p = FakeProc(args)
        self.procs.append(p)
        return p

    def alive(self):
        return [p for p in self.procs if p.rc is None]


class Event:
    def __init__(self):
        self.set_n, self.reset_n = 0, 0

    def set(self):
        self.set_n += 1

    def reset(self):
        self.reset_n += 1


def make(tmp_path, attach=None, speakers=False):
    cfg = Config()
    cfg.transcribe.root = str(tmp_path / "tr")
    sp, ev = Spawner(), Event()
    changes = []
    c = meetings.Controller(tmp_path / "data", cfg, spawn=sp, on_change=changes.append, stop_event=ev,
                            attach=attach or (lambda pid: None), speakers_ok=lambda: speakers)
    return c, sp, ev, changes


def audio(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


def finish(proc, d, status="done"):
    sessions.write_meta(d, status=status)
    proc.rc = 0


def test_jobs_run_one_at_a_time_fifo(tmp_path):
    c, sp, _, _ = make(tmp_path)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    b = c.enqueue_file(audio(tmp_path, "b.m4a"), "en", title="Bee")
    assert sessions.read_meta(b)["title"] == "Bee"
    assert [p.args for p in sp.procs] == [["--transcribe", str(a)]]
    assert sessions.read_meta(b)["status"] == "queued"
    assert c.state()["queue"] == [str(b)]
    c.poll()
    assert len(sp.procs) == 1  # a still runs
    finish(sp.procs[0], a)
    c.poll()
    assert [p.args for p in sp.procs][-1] == ["--transcribe", str(b)]
    assert len(sp.alive()) == 1
    finish(sp.procs[1], b)
    c.poll()
    assert c.state()["job"] is None and c.state()["queue"] == []


def test_meeting_while_job_runs_kills_and_requeues_job_at_front(tmp_path):
    c, sp, _, _ = make(tmp_path)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    b = c.enqueue_file(audio(tmp_path, "b.m4a"), "sv")
    (a / "progress.json").write_text('{"pct": 40}', encoding="utf-8")
    m = c.start_meeting("sv", app="msteams")
    job = sp.procs[0]
    assert job.killed
    assert sp.procs[-1].args == ["--meeting", str(m)]
    assert len(sp.alive()) == 1
    assert c.state()["queue"] == [str(a), str(b)]
    assert sessions.read_meta(a)["status"] == "queued"
    assert not (a / "progress.json").exists()  # restarts from scratch
    st = c.state()["meeting"]
    assert st["dir"] == str(m) and st["app"] == "msteams" and st["lang"] == "sv"
    assert sessions.read_meta(m)["source"] == "meeting"
    c.poll()
    assert len(sp.procs) == 2  # no job while the meeting records
    finish(sp.procs[-1], m)
    c.poll()
    assert sp.procs[-1].args == ["--transcribe", str(a)]
    assert len(sp.alive()) == 1


def test_second_meeting_returns_running_dir(tmp_path):
    c, sp, _, _ = make(tmp_path)
    m = c.start_meeting("sv")
    assert c.start_meeting("en") == m
    assert len(sp.procs) == 1


def test_dead_worker_marks_failed_and_next_job_starts(tmp_path):
    c, sp, _, _ = make(tmp_path)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    b = c.enqueue_file(audio(tmp_path, "b.m4a"), "sv")
    sp.procs[0].rc = 3  # crashed, meta still says running
    sessions.write_meta(a, status="running")
    c.poll()
    m = sessions.read_meta(a)
    assert m["status"] == "failed" and "3" in m["error"]
    assert sp.procs[-1].args == ["--transcribe", str(b)]


def test_dead_meeting_worker_marked_failed(tmp_path):
    c, sp, ev, _ = make(tmp_path)
    m = c.start_meeting("sv")
    sessions.write_meta(m, status="recording")
    sp.procs[0].rc = 1
    c.poll()
    assert sessions.read_meta(m)["status"] == "failed"
    assert c.state()["meeting"] is None


def test_stop_meeting_writes_stop_file_and_sets_event(tmp_path):
    c, sp, ev, _ = make(tmp_path)
    m = c.start_meeting("sv")
    assert ev.reset_n == 1  # a stale set event from the last meeting must not stop this one
    c.stop_meeting()
    assert (m / "stop").exists() and ev.set_n == 1
    assert c.state()["meeting"]["status"] == "stopping"
    c.stop_meeting()  # idempotent
    assert ev.set_n == 1
    finish(sp.procs[0], m)
    c.poll()
    assert c.state()["meeting"] is None


def test_stop_without_meeting_is_noop(tmp_path):
    c, _, ev, _ = make(tmp_path)
    c.stop_meeting()
    assert ev.set_n == 0


def test_state_file_round_trips_and_on_change(tmp_path):
    c, sp, _, changes = make(tmp_path)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    (a / "progress.json").write_text('{"pct": 42}', encoding="utf-8")
    c.poll()
    st = json.loads((tmp_path / "data" / "meetings.json").read_text(encoding="utf-8"))
    assert st["job"] == {"dir": str(a), "pct": 42, "pid": sp.procs[0].pid, "kind": "transcribe"}
    assert st == c.state()
    assert changes and changes[-1] == st
    assert meetings.read_state(tmp_path / "data") == st


def test_restart_adopts_running_worker_and_queue(tmp_path):
    """Saving Ajustes restarts the background app; the detached worker keeps going."""
    c, sp, _, _ = make(tmp_path)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    b = c.enqueue_file(audio(tmp_path, "b.m4a"), "sv")
    m = c.start_meeting("sv", app="slack")
    meeting_proc = sp.procs[-1]
    c2, sp2, _, _ = make(tmp_path, attach=lambda pid: meeting_proc if pid == meeting_proc.pid else None)
    st = c2.state()
    assert st["meeting"]["dir"] == str(m) and st["meeting"]["app"] == "slack"
    assert st["queue"] == [str(a), str(b)]
    assert sp2.procs == []
    finish(meeting_proc, m)
    c2.poll()
    assert sp2.procs[-1].args == ["--transcribe", str(a)]


def test_restart_with_dead_pid_requeues_job(tmp_path):
    c, sp, _, _ = make(tmp_path)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    c2, sp2, _, _ = make(tmp_path)  # attach finds nothing: the job's process is gone
    assert [p.args for p in sp2.procs] == [["--transcribe", str(a)]]


def test_spawn_failure_marks_failed_and_moves_on(tmp_path):
    cfg = Config()
    cfg.transcribe.root = str(tmp_path / "tr")
    calls = []

    def spawn(args):
        calls.append(args)
        if len(calls) == 1:
            raise OSError("no exe")
        return FakeProc(args)
    c = meetings.Controller(tmp_path / "data", cfg, spawn=spawn, stop_event=Event(), attach=lambda pid: None)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    b = c.enqueue_file(audio(tmp_path, "b.m4a"), "sv")
    assert sessions.read_meta(a)["status"] == "failed"
    assert c.state()["job"]["dir"] == str(b)


def test_a_call_while_the_last_meeting_saves_waits_then_records(tmp_path):
    c, sp, ev, _ = make(tmp_path)
    d1 = c.start_meeting("sv", app="msteams")
    c.stop_meeting()  # saving: the worker runs its final pass
    d2 = c.start_meeting("en", app="slack")
    assert d2 != d1 and len(sp.alive()) == 1  # never two meeting workers
    st = c.state()
    assert st["next_meeting"]["dir"] == str(d2) and st["next_meeting"]["status"] == "waiting"
    assert c.start_meeting("en", app="slack") == d2  # asking again doesn't stack a third
    finish(sp.procs[0], d1)
    c.poll()
    assert c.state()["meeting"]["dir"] == str(d2) and c.state()["meeting"]["status"] == "recording"
    assert sp.procs[-1].args == ["--meeting", str(d2)] and c.state()["next_meeting"] is None


def test_stopping_a_waiting_meeting_cancels_it(tmp_path):
    c, sp, ev, _ = make(tmp_path)
    d1 = c.start_meeting("sv")
    c.stop_meeting()
    d2 = c.start_meeting("sv")
    c.stop_meeting()  # the second call ended before the first finished saving
    assert not d2.exists() and c.state()["next_meeting"] is None
    finish(sp.procs[0], d1)
    c.poll()
    assert c.state()["meeting"] is None and len(sp.procs) == 1


def test_restart_keeps_or_fails_a_waiting_meeting(tmp_path):
    c, sp, _, _ = make(tmp_path)
    m1 = c.start_meeting("sv")
    c.stop_meeting()
    m2 = c.start_meeting("en", app="slack")
    proc = sp.procs[-1]
    c2, sp2, _, _ = make(tmp_path, attach=lambda pid: proc if pid == proc.pid else None)
    assert c2.state()["next_meeting"]["dir"] == str(m2)  # old worker still saving: m2 keeps waiting
    finish(proc, m1)
    c2.poll()
    assert sp2.procs[-1].args == ["--meeting", str(m2)]


def test_restart_after_the_old_worker_died_fails_the_waiting_meeting(tmp_path):
    c, sp, _, _ = make(tmp_path)
    c.start_meeting("sv")
    c.stop_meeting()
    m2 = c.start_meeting("en")
    c2, sp2, _, _ = make(tmp_path)  # nothing to adopt
    assert c2.state()["next_meeting"] is None and sessions.read_meta(m2)["status"] == "failed"
    assert not any(p.args == ["--meeting", str(m2)] for p in sp2.procs)


def test_switch_language_while_recording(tmp_path):
    c, sp, _, _ = make(tmp_path)
    assert not c.set_lang("en")  # nothing records
    d = c.start_meeting("sv")
    assert c.set_lang("en") and sessions.read_meta(d)["lang"] == "en" and c.state()["meeting"]["lang"] == "en"
    c.stop_meeting()
    assert not c.set_lang("el")  # saving: too late, the final pass already has its language


def killed_meeting(tmp_path, with_audio=True):
    """A meeting whose worker was killed mid-call (installer taskkill, crash): meta still
    says recording, the FLACs hold what was flushed."""
    c, sp, _, _ = make(tmp_path)
    d = c.start_meeting("es", app="signal")
    sessions.write_meta(d, status="recording")
    if with_audio:
        (d / "audio" / "mix.flac").write_bytes(b"fLaC" + b"\0" * 64)
    return c, sp, d


def test_restart_recovers_a_killed_meeting_with_audio(tmp_path):
    _, _, d = killed_meeting(tmp_path)
    c2, sp2, _, _ = make(tmp_path)  # the worker is gone
    assert sp2.procs[-1].args == ["--transcribe", str(d)]  # final pass on what was recorded
    meta = sessions.read_meta(d)
    assert meta["recovered"] and meta["status"] == "queued"
    assert c2.state()["meeting"] is None and c2.state()["job"]["dir"] == str(d)


def test_restart_fails_a_killed_meeting_without_audio(tmp_path):
    _, _, d = killed_meeting(tmp_path, with_audio=False)
    c2, sp2, _, _ = make(tmp_path)
    assert sessions.read_meta(d)["status"] == "failed" and sp2.procs == []


def test_a_meeting_worker_that_dies_mid_call_is_recovered(tmp_path):
    c, sp, d = killed_meeting(tmp_path)
    sp.procs[0].rc = 1
    c.poll()
    assert sp.procs[-1].args == ["--transcribe", str(d)] and sessions.read_meta(d)["recovered"]
    assert c.state()["meeting"] is None


def test_a_failed_recovery_is_not_retried(tmp_path):
    c, sp, d = killed_meeting(tmp_path)
    sp.procs[0].rc = 1
    c.poll()
    finish(sp.procs[-1], d, status="failed")
    c.poll()
    assert len(sp.procs) == 2 and sessions.read_meta(d)["status"] == "failed"



# -- speakers pass (t0u.22) -------------------------------------------------------------------
def test_a_finished_meeting_gets_a_speakers_pass(tmp_path):
    c, sp, _, _ = make(tmp_path, speakers=True)
    d = c.start_meeting("es", app="signal")
    c.stop_meeting()
    finish(sp.procs[0], d)
    c.poll()
    assert sp.procs[-1].args == ["--speakers", str(d)]
    meta = sessions.read_meta(d)
    assert meta["speakers"] == "pending" and meta["status"] == "done"  # the transcript is usable meanwhile
    assert c.state()["job"]["kind"] == "speakers"
    sessions.write_meta(d, speakers="done")
    sp.procs[-1].rc = 0
    c.poll()
    assert len(sp.procs) == 2 and c.state()["job"] is None  # once


def test_no_addon_no_speakers_pass(tmp_path):
    c, sp, _, _ = make(tmp_path, speakers=False)
    d = c.start_meeting("es")
    finish(sp.procs[0], d)
    c.poll()
    assert len(sp.procs) == 1 and "speakers" not in sessions.read_meta(d)


def test_an_import_gets_one_too_after_its_transcript(tmp_path):
    c, sp, _, _ = make(tmp_path, speakers=True)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    finish(sp.procs[0], a)
    c.poll()
    assert sp.procs[-1].args == ["--speakers", str(a)]


def test_a_call_kills_the_speakers_pass_which_reruns_after_without_touching_status(tmp_path):
    c, sp, _, _ = make(tmp_path, speakers=True)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    finish(sp.procs[0], a)
    c.poll()
    pass_proc = sp.procs[-1]
    m = c.start_meeting("en")
    assert pass_proc.killed and sessions.read_meta(a)["status"] == "done"
    assert sessions.read_meta(a)["speakers"] == "pending" and c.state()["queue"][0] == str(a)
    finish(sp.procs[-1], m)
    c.poll()
    assert sp.procs[-1].args == ["--speakers", str(m)]  # the call that just ended first, then the interrupted one
    sessions.write_meta(m, speakers="done")
    sp.procs[-1].rc = 0
    c.poll()
    assert sp.procs[-1].args == ["--speakers", str(a)]


def test_a_speakers_worker_that_dies_marks_only_the_pass_failed(tmp_path):
    c, sp, _, _ = make(tmp_path, speakers=True)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    finish(sp.procs[0], a)
    c.poll()
    sp.procs[-1].rc = 1  # died with the pass still running
    c.poll()
    meta = sessions.read_meta(a)
    assert meta["status"] == "done" and meta["speakers"] == "failed" and len(sp.procs) == 2


def test_restart_requeues_a_pending_speakers_pass(tmp_path):
    c, sp, _, _ = make(tmp_path, speakers=True)
    a = c.enqueue_file(audio(tmp_path, "a.m4a"), "sv")
    finish(sp.procs[0], a)
    c.poll()
    c2, sp2, _, _ = make(tmp_path, speakers=True)  # the pass's process is gone
    assert sp2.procs[-1].args == ["--speakers", str(a)] and sessions.read_meta(a)["status"] == "done"


def test_the_call_app_is_written_into_the_session(tmp_path):
    """Copy for Claude said "App: Meeting" for a Signal call: meta never had the app (deep dive 2026-10-05)."""
    c, sp, _, _ = make(tmp_path)
    d = c.start_meeting("es", app="signal")
    assert sessions.read_meta(d)["app"] == "signal"
