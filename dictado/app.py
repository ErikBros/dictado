"""Orchestrator: idle <-> recording, plus a single transcription worker.

Recording and transcribing are decoupled: you can start the next dictation
while the previous one is still being transcribed; results land in order.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import replace
from pathlib import Path

from .deliver import set_clipboard_text

log = logging.getLogger(__name__)
LANG_NAMES = {"en": "English", "es": "Spanish", "sv": "Swedish", "el": "Greek"}
SR = 16000


class App:
    def __init__(self, cfg, recorder, engine, deliver_fn, ui, gate=None, history_path: Path | None = None,
                 press_enter=None, screen=None, spool=None):
        self.cfg = cfg
        self.recorder = recorder
        self.engine = engine
        self.deliver = deliver_fn
        self.ui = ui
        self.gate = gate
        self.history_path = history_path
        self.press_enter = press_enter or _press_enter
        self.spool = spool  # t0u.37: the recording on disk while it happens, for crash recovery
        self._screen_factory = screen  # None: dictado.context.ScreenNames (read lazily, Windows only)
        self._screen = None
        self._quiet = False  # hold mode: the mic is on since the key went down, not announced yet
        self._by_hold = False  # this recording stops when the key is let go
        self.state = "idle"
        self.next_lang: str | None = None  # dictation-languages: forced for the next dictation (key + L)
        self.last_lang: str | None = None  # what the last dictation was in: close calls stay with it
        self.ready = True
        self.last_text = ""
        self._lock = threading.RLock()
        self._jobs: queue.Queue = queue.Queue()
        self._pending = 0
        self._timer: threading.Timer | None = None
        self._t_start = 0.0
        self._warned_cpu = False
        self._worker = threading.Thread(target=self._work, name="dictado-worker", daemon=True)

    def start(self) -> None:
        self._worker.start()

    def shutdown(self) -> None:
        with self._lock:
            if self.state == "recording":
                self._cancel()
        self._jobs.put(None)

    # ---------- actions (any thread) ----------
    def on_action(self, action: str) -> None:
        with self._lock:
            if action in ("press", "tap", "hold", "release", "abort"):
                self._hold_action(action)
            elif action == "cancel" and self._quiet:
                self._drop_quiet()
            elif action == "toggle":
                if not self.ready:
                    self.ui.flash("Loading the model, one moment")
                elif self.state == "idle":
                    self._start()
                else:
                    self._stop()
            elif action == "cancel" and self.state == "recording":
                self._cancel()
            elif action == "lang":
                self.cycle_language()

    def set_next_language(self, code: str | None) -> None:
        """The tray's 'Next dictation in': same as the key, picked directly (None = auto)."""
        with self._lock:
            self.next_lang = code or None
            which = "This dictation" if self.state == "recording" else "Next dictation"
            self.ui.flash(f"{which}: {LANG_NAMES.get(self.next_lang, 'auto')}", 2.5)

    def cycle_language(self) -> str | None:
        """Dictation key + L (or the tray): the next dictation's language, Auto -> each of your
        languages -> Auto. While recording it applies to this one (it's read at the stop)."""
        langs = list(getattr(self.cfg.whisper, "languages", []) or [])
        if len(langs) < 2:
            self.ui.flash("One language set: add more in Settings", 2.5)
            return self.next_lang
        order = [None, *langs]
        self.next_lang = order[(order.index(self.next_lang) + 1) % len(order)] if self.next_lang in order else None
        which = "This dictation" if self.state == "recording" else "Next dictation"
        self.ui.flash(f"{which}: {LANG_NAMES.get(self.next_lang, 'auto')}" if self.next_lang else f"{which}: auto", 2.5)
        log.info("next dictation language -> %s", self.next_lang or "auto")
        return self.next_lang

    def _hold_action(self, action: str) -> None:
        """Hold-to-talk (t0u.28): see keystate.py for what each action means."""
        if action == "press":
            if self.state == "idle":
                if not self.ready:
                    self.ui.flash("Loading the model, one moment")
                    return
                self._start(quiet=True)
        elif action == "tap":
            if self._quiet:
                self._announce()  # a tap: hands-free from here, as today
            elif self.state == "recording":
                self._stop()
        elif action == "hold":
            if self._quiet:
                self._by_hold = True
                self._announce()
        elif action == "release":
            if self._quiet:
                self._by_hold = True
                self._announce()
            if self._by_hold and self.state == "recording":
                self._stop()
        elif action == "abort":
            if self._quiet:
                self._drop_quiet()
            elif self._by_hold and self.state == "recording":
                self._cancel()

    def _drop_quiet(self) -> None:
        """The press was a shortcut (Right Ctrl+C): close the mic without a sound."""
        self.recorder.abort()
        self._discard_spool()
        if self.gate:
            self.gate.restore()
        self._end_recording()
        self._refresh_ui()
        log.info("quiet start dropped (shortcut)")

    def _announce(self) -> None:
        self._quiet = False
        self.ui.sound("start")
        self.ui.recording(self._t_start)

    def _start(self, quiet: bool = False) -> None:
        try:
            self._start_inner(quiet)
        except Exception:
            log.exception("could not start recording")
            try:
                self.recorder.abort()
            except Exception:
                pass
            self._discard_spool()
            if self.gate:
                self.gate.restore()
            self._end_recording()
            self.ui.sound("error")
            self.ui.flash("Couldn't start recording, see the log")
            self._refresh_ui()

    def _start_inner(self, quiet: bool = False) -> None:
        warm = getattr(self.engine, "warm", None)
        if warm:  # on-demand engine: load the model while the user talks
            warm()
        self._screen = None
        if getattr(self.cfg.text, "screen_names", False):
            try:  # read the window now, while the user talks: the names are ready by the stop
                if self._screen_factory is None:
                    from .context import ScreenNames
                    self._screen_factory = ScreenNames
                self._screen = self._screen_factory().start()
            except Exception:
                log.exception("screen names unavailable")
        if self.gate:
            self.gate.open()
        self.recorder.begin()
        if self.spool is not None and hasattr(self.recorder, "chunks_since"):
            try:
                self.spool.begin(self.recorder.chunks_since)
            except Exception:
                log.exception("spool unavailable for this recording")
        self.state = "recording"
        self._t_start = time.monotonic()
        self._quiet, self._by_hold = quiet, False
        if not quiet:
            self.ui.sound("start")
            self.ui.recording(self._t_start)
        self._timer = threading.Timer(self.cfg.limits.max_record_s, self._autostop)
        self._timer.daemon = True
        self._timer.start()
        log.info("recording started%s", " (key down)" if quiet else "")

    def _autostop(self) -> None:
        with self._lock:
            if self.state == "recording" and time.monotonic() - self._t_start >= self.cfg.limits.max_record_s - 0.05:
                log.info("max length reached, stopping")
                self._stop()

    def _end_recording(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.state = "idle"
        self._quiet = self._by_hold = False

    def _stop(self) -> None:
        t_stop = time.monotonic()
        audio = self.recorder.end()
        if self.gate:
            self.gate.restore()
        self._end_recording()
        self.ui.sound("stop")
        audio_s = len(audio) / SR
        spooled = None
        if self.spool is not None:
            try:
                if audio_s < self.cfg.limits.min_audio_s:
                    self.spool.discard()
                else:
                    spooled = self.spool.finish(audio)
            except Exception:
                log.exception("spool finish failed")
        if audio_s < self.cfg.limits.min_audio_s:
            log.info("recording too short (%.2fs), discarded", audio_s)
            stream_ok = getattr(self.recorder, "last_stream_ok", True)  # sampled before end() closed it
            self.ui.flash("Too short" if audio_s > 0 or stream_ok else "No mic: see the log")
            self._refresh_ui()
            return
        self._pending += 1
        forced, self.next_lang = self.next_lang, None  # one dictation only
        self._jobs.put((audio, t_stop, self._screen, spooled, forced))
        self._screen = None
        self._refresh_ui()

    def _discard_spool(self) -> None:
        if self.spool is not None:
            try:
                self.spool.discard()
            except Exception:
                log.exception("spool discard failed")

    def _cancel(self) -> None:
        self.recorder.abort()
        self._discard_spool()
        if self.gate:
            self.gate.restore()
        self._end_recording()
        self.ui.sound("cancel")
        self._refresh_ui()
        self.ui.flash("Cancelled")
        log.info("recording cancelled")

    def _refresh_ui(self) -> None:
        if self.state == "recording":
            return
        if self._pending:
            self.ui.busy()
        else:
            self.ui.idle()

    def copy_last(self) -> None:
        if self.last_text:
            set_clipboard_text(self.last_text, private=False)

    # ---------- worker ----------
    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            audio, t_stop, screen, spooled, forced = job
            try:
                self._process(audio, t_stop, screen, forced)
            except Exception:
                log.exception("transcription/delivery failed")
                self.ui.flash("Error, see the log")
            finally:
                if self.spool is not None:
                    self.spool.done(spooled)
                with self._lock:
                    self._pending -= 1
                    self._refresh_ui()

    def _process(self, audio, t_stop: float, screen=None, forced: str | None = None) -> None:
        words = screen.get(wait_s=0.15) if screen is not None else None
        multi = len(getattr(self.cfg.whisper, "languages", []) or []) > 1
        kw = {"words": words} if words else {}
        if forced:
            kw["lang"] = forced
        elif multi and self.last_lang:
            kw["prefer"] = self.last_lang
        res = self.engine.transcribe(audio, **kw)
        if getattr(self.engine, "device", "cuda") == "cpu" and not self._warned_cpu:
            self._warned_cpu = True
            self.ui.flash("No GPU: slow mode")
        enter = False
        if res.text and getattr(self.cfg.text, "voice_commands", False):
            from .text import voice_commands
            text, enter = voice_commands(res.text)
            res = replace(res, text=text)
            if enter and not text:  # only "send it": submit what is already in the box
                self.press_enter()
                log.info("voice command: enter only")
                return
        if res.text and getattr(self.cfg.text, "snippets", None):
            from .text import snippets
            res = replace(res, text=snippets(res.text, self.cfg.text.snippets))
        if not res.text:
            log.info("no speech (audio_s=%.2f speech_s=%.2f)", len(audio) / SR, res.speech_s)
            self.ui.flash("Didn't hear you")
            return
        dr = self.deliver(res.text)
        if enter and dr.pasted:
            time.sleep(0.12)  # let the paste land before Enter submits it
            self.press_enter()
        stop_to_paste = int((time.monotonic() - t_stop) * 1000)
        self.last_text = res.text
        if res.lang:
            self.last_lang = res.lang
        if multi and dr.pasted:  # which language it heard, for a second
            self.ui.flash(f"✓ {str(res.lang).upper()}", 1.2)
        log.info("delivered chars=%d lang=%s audio_s=%.2f transcribe_ms=%d stop_to_paste_ms=%d target=%s pasted=%s reason=%s",
                 len(res.text), res.lang, len(audio) / SR, res.ms, stop_to_paste, dr.target_exe, dr.pasted, dr.reason)
        self._history(res, audio, dr)
        if not dr.pasted:
            self.ui.flash("Copied: paste with Ctrl+V" if dr.reason != "clipboard_busy" else "Couldn't paste")

    def recover(self) -> int:
        """At start: dictations a crash cut off (left in the spool) go to History as
        'recovered', never pasted. Returns how many."""
        if self.spool is None:
            return 0
        n = 0
        for p in self.spool.leftovers():
            try:
                audio = self.spool.read(p)
                if len(audio) / SR >= 0.5:
                    res = self.engine.transcribe(audio)
                    if res.text:
                        self._history(res, audio, None, recovered=True)
                        n += 1
                        log.warning("recovered a dictation cut off by a crash: chars=%d audio_s=%.1f",
                                    len(res.text), len(audio) / SR)
            except Exception:
                log.exception("recovering %s failed", p.name)
            finally:
                self.spool.done(p)
        if n:
            self.ui.flash("Recovered what you were saying: it's in History", 6.0)
        return n

    def _history(self, res, audio, dr, recovered: bool = False) -> None:
        if not self.history_path:
            return
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": res.text, "lang": res.lang,
               "audio_s": round(len(audio) / SR, 2), "ms": res.ms, "target": dr.target_exe if dr else None,
               "pasted": dr.pasted if dr else False}
        if recovered:
            rec["recovered"] = True
        try:
            with open(self.history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            log.exception("history write failed")


def _press_enter() -> None:
    import sys
    if sys.platform == "darwin":
        from .platform.macos.keys import press_enter
        return press_enter()
    from .sendkeys import send_keys
    send_keys([(0x0D, True), (0x0D, False)])  # VK_RETURN
