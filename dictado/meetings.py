"""Meetings and file jobs, owned by the background app: at most ONE worker process.

A meeting is `dictado --meeting DIR`, a file job `dictado --transcribe DIR`. Two at
once is never allowed (three models at once stalled dictation in t0u.2): imports
queue FIFO, and a call can't wait, so a meeting started while a job runs kills the
job (its session goes back to the FRONT of the queue and restarts from scratch
after the meeting). The state lives in <data>/meetings.json for the window and
the pill; workers are detached, so a restarted background app adopts them by pid.

A session that ends done gets a speakers pass (`dictado --speakers DIR`, t0u.22) when
the speaker add-on is installed: a queued job like a file, run by meta `speakers:
pending`, never touching the session's status (the transcript is usable meanwhile).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import sessions

log = logging.getLogger(__name__)
STATE = "meetings.json"
STOP_EVENT = "Local\\DictadoMeetingStop"
ACTIVE = {"new", "queued", "recording", "finalizing", "running", "downloading"}


def read_state(data_dir: Path) -> dict:
    try:
        return json.loads((Path(data_dir) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"meeting": None, "job": None, "queue": []}


class _StopEvent:
    """Local\\DictadoMeetingStop, manual reset (the worker opens the same one)."""

    def __init__(self, name: str = STOP_EVENT):
        import win32event
        self._ev = win32event
        self._h = win32event.CreateEvent(None, True, False, name)

    def set(self):
        self._ev.SetEvent(self._h)

    def reset(self):
        self._ev.ResetEvent(self._h)


class PidProc:
    """Popen-like handle on a process we did not start (adopted after a restart)."""

    def __init__(self, pid: int, handle):
        self.pid, self._h = pid, handle

    def poll(self):
        import ctypes
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(self._h, ctypes.byref(code))
        return None if code.value == 259 else int(code.value)  # STILL_ACTIVE

    def kill(self):
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(self._h, 1)

    def wait(self, timeout=None):
        import ctypes
        ctypes.windll.kernel32.WaitForSingleObject(self._h, 0xFFFFFFFF if timeout is None else int(timeout * 1000))
        return self.poll()


def attach_pid(pid: int):
    """A PidProc if `pid` is still a Ecoscribe (or dev Python) process, else None: after a
    reboot the pid in meetings.json may belong to anything."""
    import ctypes
    from . import detect
    if not pid or detect._exe_of_pid(pid) not in ("dictado", "python", "pythonw"):
        return None
    h = ctypes.windll.kernel32.OpenProcess(0x100000 | 0x1000 | 0x1, False, pid)  # SYNCHRONIZE|QUERY|TERMINATE
    return PidProc(pid, h) if h else None


if sys.platform == "darwin":  # dictado/platform/macos/procs.py; the worker stops on DIR/stop, no named event
    from .platform.macos.procs import PidProc, attach_pid  # noqa: F811

    class _StopEvent:  # noqa: F811
        def __init__(self, name: str = STOP_EVENT):
            pass

        def set(self):
            pass

        def reset(self):
            pass


def _default_spawn(args):
    from . import ipc
    return ipc.spawn(args)


class Controller:
    def __init__(self, data_dir: Path, cfg, spawn=_default_spawn, clock=time.time, on_change=None,
                 stop_event=None, attach=attach_pid, speakers_ok=None):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.root = sessions.root_dir(cfg.transcribe.root)
        self.spawn, self.clock, self.on_change = spawn, clock, on_change
        if speakers_ok is None:
            from . import diarize
            speakers_ok = lambda: diarize.available(cfg)  # noqa: E731  (checked each time: the add-on may be installed later)
        self.speakers_ok = speakers_ok
        self.calendar = None  # calendar_ics.CalendarFeed: names a meeting from the event happening now (t0u.35)
        self._stop_ev = stop_event if stop_event is not None else _StopEvent()
        self._lock = threading.RLock()
        self.meeting: dict | None = None  # dir, app, lang, started, proc, stopping
        self.job: dict | None = None  # dir, proc, kind (transcribe | speakers)
        # a call that starts while the last meeting is still saving: its session waits here and
        # records as soon as the old worker exits (never two meeting workers at once)
        self.next_meeting: dict | None = None  # dir, app, lang
        self.queue: list[Path] = []
        self._last: dict | None = None
        self._restore(read_state(self.data), attach)
        with self._lock:
            self._next()
            self._publish()

    # -- restore after a restart ------------------------------------------------------------
    def _restore(self, st: dict, attach) -> None:
        self.queue = [Path(d) for d in st.get("queue") or [] if Path(d).is_dir()]
        m = st.get("meeting")
        if m and Path(m["dir"]).is_dir():
            proc = attach(m.get("pid"))
            if proc is not None and proc.poll() is None:
                self.meeting = {"dir": Path(m["dir"]), "app": m.get("app"), "lang": m.get("lang"),
                                "started": m.get("started"), "proc": proc, "stopping": m.get("status") == "stopping"}
                log.info("adopted meeting worker pid=%s %s", proc.pid, m["dir"])
            else:  # killed mid-call (an install, a crash): transcribe what was recorded
                self._recover_or_fail(Path(m["dir"]), "Ecoscribe closed during the call")
        nm = st.get("next_meeting")
        if nm and Path(nm["dir"]).is_dir():
            if self.meeting is not None and self.meeting["stopping"]:  # still waiting its turn
                self.next_meeting = {"dir": Path(nm["dir"]), "app": nm.get("app"), "lang": nm.get("lang")}
            else:  # the old worker is gone and the call may be over: don't record a stale call
                self._mark_failed(Path(nm["dir"]), "Ecoscribe restarted before recording started")
        j = st.get("job")
        if j and Path(j["dir"]).is_dir():
            proc = attach(j.get("pid"))
            if proc is not None and proc.poll() is None:
                self.job = {"dir": Path(j["dir"]), "proc": proc, "kind": self._kind(Path(j["dir"]))}
                log.info("adopted job worker pid=%s %s", proc.pid, j["dir"])
            elif sessions.read_meta(j["dir"]).get("status") != "done" or self._kind(Path(j["dir"])) == "speakers":
                self._requeue_front(Path(j["dir"]))

    # -- public API (any thread) ------------------------------------------------------------
    def _event_now(self, app: str | None):
        """The calendar event this call belongs to, or None. Never fails a meeting."""
        if self.calendar is None:
            return None
        try:
            from datetime import timezone
            return self.calendar.lookup(datetime.fromtimestamp(self.clock(), timezone.utc), app)
        except Exception:
            log.exception("calendar lookup failed; default title")
            return None

    def _create(self, title: str, lang: str, ev) -> Path:
        d = sessions.create(ev.title if ev is not None else title, lang, "meeting", self.root)
        if ev is not None:
            from .calendar_ics import meta_info
            sessions.write_meta(d, calendar=meta_info(ev))
            log.info("meeting named from the calendar (%d attendees)", len(ev.attendees))
        return d

    def start_meeting(self, lang: str, title: str = "Meeting", app: str | None = None) -> Path:
        ev = self._event_now(app) if title == "Meeting" else None  # outside the lock: reads a file
        with self._lock:
            if self.meeting is not None and not self.meeting["stopping"]:
                log.info("meeting already running: %s", self.meeting["dir"])
                return self.meeting["dir"]
            if self.meeting is not None:  # the last one is still saving: this call waits its turn
                if self.next_meeting is None:
                    d = self._create(title, lang, ev)
                    sessions.write_meta(d, status="queued")
                    self.next_meeting = {"dir": d, "app": app, "lang": lang}
                    log.info("meeting %s waits for %s to finish saving", d, self.meeting["dir"])
                    self._publish()
                return self.next_meeting["dir"]
            return self._spawn_meeting(self._create(title, lang, ev), lang, app)

    def _spawn_meeting(self, d: Path, lang: str, app: str | None) -> Path:
        """Lock held. Kill a running job (a call can't wait), then start recording into d."""
        if self.job is not None:  # the job restarts after the meeting
            jd = self.job["dir"]
            log.info("meeting starts: killing %s job %s, back to the queue front", self.job.get("kind"), jd)
            self._kill(self.job["proc"])
            self.job = None
            self._requeue_front(jd)
        if app:
            try:
                sessions.write_meta(d, app=app)  # "App: Signal" in Copy for Claude, and findable later
            except Exception:
                log.exception("app not written for %s", d)
        self._stop_ev.reset()  # a set event left by the last meeting would stop this one at once
        try:
            proc = self.spawn(["--meeting", str(d)])
        except Exception as e:
            log.exception("meeting worker did not start")
            self._mark_failed(d, f"couldn't start: {e}")
            self._next()
            self._publish()
            return d
        self.meeting = {"dir": d, "app": app, "lang": lang,
                        "started": datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds"),
                        "proc": proc, "stopping": False}
        log.info("meeting started lang=%s app=%s %s pid=%s", lang, app, d, getattr(proc, "pid", None))
        self._publish()
        return d

    def set_lang(self, lang: str) -> bool:
        """Switch the recording meeting's language: live chunks from now on, and the final pass."""
        with self._lock:
            if self.meeting is None or self.meeting["stopping"]:
                return False
            sessions.write_meta(self.meeting["dir"], lang=lang)
            self.meeting["lang"] = lang
            log.info("meeting language -> %s %s", lang, self.meeting["dir"])
            self._publish()
            return True

    def stop_meeting(self) -> None:
        with self._lock:
            if self.next_meeting is not None and (self.meeting is None or self.meeting["stopping"]):
                d = self.next_meeting.pop("dir")
                self.next_meeting = None
                log.info("waiting meeting %s cancelled before it recorded", d)
                try:
                    sessions.delete(d)
                except OSError:
                    log.exception("could not remove %s", d)
                self._publish()
                return
            if self.meeting is None or self.meeting["stopping"]:
                return
            d = self.meeting["dir"]
            try:
                (d / "stop").write_text("", encoding="utf-8")
            except OSError:
                log.exception("stop file not written; the event still stops it")
            self._stop_ev.set()
            self.meeting["stopping"] = True
            log.info("meeting stop requested %s", d)
            self._publish()

    def enqueue_file(self, path: Path, lang: str, title: str | None = None) -> Path:
        d = sessions.import_file(Path(path), lang, self.root, title=title)  # copy outside the lock
        with self._lock:
            sessions.write_meta(d, status="queued")
            self.queue.append(d)
            log.info("queued %s lang=%s", d, lang)
            self._next()
            self._publish()
        return d

    def poll(self) -> None:
        """Call every second: reap finished or dead workers, start the next job."""
        with self._lock:
            if self.meeting is not None:
                rc = self.meeting["proc"].poll()
                if rc is not None:
                    d = self.meeting["dir"]
                    log.info("worker for %s exited rc=%s status=%s", d, rc, self._meta_status(d))
                    self._recover_or_fail(d, f"the recording stopped unexpectedly (code {rc})")
                    self._after_done(d)
                    self.meeting = None
                    self._stop_ev.reset()
                    if self.next_meeting is not None:
                        nm, self.next_meeting = self.next_meeting, None
                        self._spawn_meeting(nm["dir"], nm["lang"], nm["app"])
            if self.job is not None:
                rc = self.job["proc"].poll()
                if rc is not None:
                    jd, kind = self.job["dir"], self.job.get("kind")
                    self.job = None
                    if kind == "speakers":
                        self._speakers_reaped(jd, rc)
                    else:
                        self._reaped(jd, rc, "the transcription")
                        self._after_done(jd)
            self._next()
            self._publish()

    def levels(self) -> tuple[float, float] | None:
        """(mic, system) of the recording meeting from the worker's levels.json, or None
        when unknown (no meeting, no file yet, or stale: a stuck worker is not silence)."""
        with self._lock:
            d = self.meeting["dir"] if self.meeting else None
        if d is None:
            return None
        try:
            lv = json.loads((d / "levels.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if self.clock() - float(lv.get("t", 0)) > 10:
            return None
        return float(lv["mic"]), float(lv["system"])

    def state(self) -> dict:
        with self._lock:
            m = j = None
            if self.meeting is not None:
                d = self.meeting["dir"]
                meta_status = self._meta_status(d)
                status = ("finalizing" if meta_status == "finalizing" else
                          "stopping" if self.meeting["stopping"] else "recording")
                m = {"dir": str(d), "app": self.meeting["app"], "lang": self.meeting["lang"],
                     "started": self.meeting["started"], "status": status,
                     "pid": getattr(self.meeting["proc"], "pid", None)}
            nxt = None
            if self.next_meeting is not None:
                nxt = {"dir": str(self.next_meeting["dir"]), "app": self.next_meeting["app"],
                       "lang": self.next_meeting["lang"], "status": "waiting"}
            if self.job is not None:
                j = {"dir": str(self.job["dir"]), "pct": self._pct(self.job["dir"]),
                     "pid": getattr(self.job["proc"], "pid", None), "kind": self.job.get("kind", "transcribe")}
            return {"meeting": m, "job": j, "queue": [str(d) for d in self.queue], "next_meeting": nxt}

    # -- internals (lock held) --------------------------------------------------------------
    def _next(self) -> None:
        while self.meeting is None and self.job is None and self.queue:
            d = self.queue.pop(0)
            kind = self._kind(d)
            try:
                proc = self.spawn([f"--{kind}", str(d)])
            except Exception as e:
                log.exception("job worker did not start for %s", d)
                if kind == "speakers":
                    self._speakers_reaped(d, None, f"couldn't start: {e}")
                else:
                    self._mark_failed(d, f"couldn't start: {e}")
                continue
            self.job = {"dir": d, "proc": proc, "kind": kind}
            log.info("%s job started %s pid=%s", kind, d, getattr(proc, "pid", None))

    def _reaped(self, d: Path, rc: int, what: str) -> None:
        status = self._meta_status(d)
        log.info("worker for %s exited rc=%s status=%s", d, rc, status)
        if status != "done":
            self._mark_failed(d, f"{what} ended before finishing (code {rc})")

    def _kind(self, d: Path) -> str:
        """speakers when the session is done and only its speakers pass is left, else transcribe."""
        try:
            m = sessions.read_meta(d)
        except Exception:
            return "transcribe"
        return "speakers" if m.get("status") == "done" and m.get("speakers") in ("pending", "running") else "transcribe"

    def _after_done(self, d: Path) -> None:
        """A transcript just finished: queue its speakers pass (front: it's short) if the add-on is there."""
        try:
            m = sessions.read_meta(d)
            if m.get("status") != "done" or m.get("speakers") is not None or not self.speakers_ok():
                return
            sessions.write_meta(d, speakers="pending")
        except Exception:
            log.exception("speakers pass not queued for %s", d)
            return
        if d not in self.queue:
            self.queue.insert(0, d)
        log.info("speakers pass queued %s", d)

    def _speakers_reaped(self, d: Path, rc, error: str | None = None) -> None:
        try:
            if sessions.read_meta(d).get("speakers") in ("pending", "running"):
                sessions.write_meta(d, speakers="failed", speakers_error=error or f"the speakers pass ended early (code {rc})")
        except Exception:
            log.exception("could not mark the speakers pass of %s", d)

    def _recover_or_fail(self, d: Path, why: str) -> None:
        """A meeting whose worker died before finishing: if it left audio, its final pass
        (transcript + Me / Others) runs as the next job; otherwise it is failed. A finished
        or already failed session is left alone, so a recovery that fails is not retried."""
        if self._meta_status(d) not in ACTIVE:
            return
        mix = d / "audio" / "mix.flac"
        try:
            has_audio = mix.stat().st_size > 0
        except OSError:
            has_audio = False
        if not has_audio:
            self._mark_failed(d, f"{why}, nothing was recorded")
            return
        try:
            sessions.write_meta(d, recovered=why)
        except Exception:
            log.exception("could not mark %s recovered", d)
        log.info("recovering %s (%s): final pass on what was recorded", d, why)
        self._requeue_front(d)

    def _requeue_front(self, d: Path) -> None:
        try:
            if self._kind(d) == "speakers":  # the transcript is done: only the pass goes back
                sessions.write_meta(d, speakers="pending")
            else:
                (d / "progress.json").unlink(missing_ok=True)
                sessions.write_meta(d, status="queued")
        except Exception:
            log.exception("could not mark %s queued", d)
        if d in self.queue:
            self.queue.remove(d)
        self.queue.insert(0, d)

    @staticmethod
    def _kill(proc) -> None:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            log.exception("kill failed")

    @staticmethod
    def _mark_failed(d: Path, error: str) -> None:
        try:
            if Controller._meta_status(d) in ACTIVE:
                sessions.write_meta(d, status="failed", error=error)
        except Exception:
            log.exception("could not mark %s failed", d)

    @staticmethod
    def _meta_status(d: Path) -> str | None:
        try:
            return sessions.read_meta(d).get("status")
        except Exception:
            return None

    @staticmethod
    def _pct(d: Path) -> int:
        try:
            return int(json.loads((Path(d) / "progress.json").read_text(encoding="utf-8")).get("pct", 0))
        except (OSError, ValueError, TypeError):
            return 0

    def _publish(self) -> None:
        st = self.state()
        if st == self._last:
            return
        self._last = st
        try:
            path = self.data / STATE
            sessions._write_json(path, st)
        except OSError:
            log.exception("meetings.json not written")
        if self.on_change:
            try:
                self.on_change(st)
            except Exception:
                log.exception("on_change failed")
