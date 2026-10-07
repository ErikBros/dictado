import json
import threading
import time

import numpy as np
import pytest

from ecoscribe.app import App
from ecoscribe.config import Config
from ecoscribe.deliver import DeliveryResult
from ecoscribe.engine import Result

SR = 16000


class FakeRecorder:
    def __init__(self, seconds=1.0):
        self.seconds = seconds
        self.recording = False
        self.aborted = 0

    def begin(self): self.recording = True
    def end(self):
        self.recording = False
        return np.zeros(int(self.seconds * SR), np.float32)
    def abort(self):
        self.recording = False
        self.aborted += 1
    def level(self): return 0.0


class FakeEngine:
    def __init__(self, delay=0.0, fail_first=False):
        self.delay, self.fail_first, self.n = delay, fail_first, 0

    def transcribe(self, audio):
        self.n += 1
        time.sleep(self.delay)
        if self.fail_first and self.n == 1:
            raise RuntimeError("cuda boom")
        return Result(text=f"text {self.n} ", lang="en", speech_s=1.0, ms=5)


class FakeGate:
    def __init__(self): self.opened = self.restored = 0
    def open(self): self.opened += 1; return True
    def restore(self): self.restored += 1


class FakeUi:
    def __init__(self): self.events = []
    def __getattr__(self, name):
        return lambda *a: self.events.append((name, *a))


def make(tmp_path, rec=None, eng=None, **limits):
    cfg = Config()
    for k, v in limits.items():
        setattr(cfg.limits, k, v)
    delivered = []

    def deliver(text):
        delivered.append(text)
        return DeliveryResult(True, "x.exe", "ok")

    app = App(cfg, rec or FakeRecorder(), eng or FakeEngine(), deliver, FakeUi(), gate=FakeGate(),
              history_path=tmp_path / "h.jsonl")
    app.start()
    return app, delivered


def wait(pred, t=3.0):
    end = time.monotonic() + t
    while time.monotonic() < end and not pred():
        time.sleep(0.01)
    return pred()


def test_toggle_cycle_delivers(tmp_path):
    app, out = make(tmp_path)
    app.on_action("toggle"); assert app.state == "recording"
    app.on_action("toggle"); assert app.state == "idle"
    assert wait(lambda: out == ["text 1 "])
    h = [json.loads(l) for l in (tmp_path / "h.jsonl").read_text(encoding="utf-8").splitlines()]
    assert h[0]["text"] == "text 1 " and h[0]["pasted"] is True
    assert app.gate.opened == 1 and app.gate.restored == 1
    app.shutdown()


def test_cancel_discards(tmp_path):
    rec = FakeRecorder()
    app, out = make(tmp_path, rec=rec)
    app.on_action("toggle"); app.on_action("cancel")
    assert app.state == "idle" and rec.aborted == 1 and app.gate.restored == 1
    time.sleep(0.2)
    assert out == []
    app.shutdown()


def test_cancel_when_idle_is_noop(tmp_path):
    app, out = make(tmp_path)
    app.on_action("cancel")
    assert app.state == "idle"
    app.shutdown()


def test_short_recording_discarded(tmp_path):
    app, out = make(tmp_path, rec=FakeRecorder(seconds=0.1))
    app.on_action("toggle"); app.on_action("toggle")
    time.sleep(0.2)
    assert out == [] and app.engine.n == 0
    app.shutdown()


def test_jobs_deliver_in_order(tmp_path):
    app, out = make(tmp_path, eng=FakeEngine(delay=0.3))
    app.on_action("toggle"); app.on_action("toggle")
    time.sleep(0.05)
    app.on_action("toggle"); assert app.state == "recording"  # can dictate again while busy
    app.on_action("toggle")
    assert wait(lambda: out == ["text 1 ", "text 2 "])
    app.shutdown()


def test_engine_exception_keeps_worker_alive(tmp_path):
    app, out = make(tmp_path, eng=FakeEngine(fail_first=True))
    app.on_action("toggle"); app.on_action("toggle")
    time.sleep(0.2)
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: out == ["text 2 "])
    assert any(e[0] == "flash" for e in app.ui.events)
    app.shutdown()


def test_max_length_autostops(tmp_path):
    app, out = make(tmp_path, max_record_s=0.2)
    app.on_action("toggle")
    assert wait(lambda: out == ["text 1 "])
    assert app.state == "idle"
    app.shutdown()


def test_toggle_ignored_while_loading(tmp_path):
    app, out = make(tmp_path)
    app.ready = False
    app.on_action("toggle")
    assert app.state == "idle"
    app.shutdown()


def test_copy_last(tmp_path, monkeypatch):
    copied = []
    monkeypatch.setattr("ecoscribe.app.set_clipboard_text", lambda s, private=True: copied.append(s))
    app, out = make(tmp_path)
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: out)
    app.copy_last()
    assert copied == ["text 1 "]
    app.shutdown()


def test_concurrent_toggles_are_serialized(tmp_path):
    app, out = make(tmp_path)
    ts = [threading.Thread(target=app.on_action, args=("toggle",)) for _ in range(10)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert app.state == "idle"
    assert wait(lambda: len(out) == 5)
    app.shutdown()


def test_start_failure_rolls_back_and_remutes(tmp_path):
    class BadRecorder(FakeRecorder):
        def begin(self):
            raise OSError("no mic")
    app, out = make(tmp_path, rec=BadRecorder())
    app.on_action("toggle")
    assert app.state == "idle"
    assert app.gate.opened == 1 and app.gate.restored == 1
    assert any(e[0] == "flash" for e in app.ui.events)
    app.on_action("toggle")  # still usable (and still failing cleanly)
    assert app.state == "idle"
    app.shutdown()


def flashes(app):
    return [e[1] for e in app.ui.events if e[0] == "flash"]


def test_no_speech_flashes(tmp_path):
    class Silent(FakeEngine):
        def transcribe(self, audio):
            return Result(text="", lang="en", speech_s=0.0, ms=5)
    app, out = make(tmp_path, eng=Silent())
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: "Didn't hear you" in flashes(app))
    assert out == []
    app.shutdown()


def test_short_flashes(tmp_path):
    app, out = make(tmp_path, rec=FakeRecorder(seconds=0.1))
    app.on_action("toggle"); app.on_action("toggle")
    assert "Too short" in flashes(app)
    app.shutdown()


def test_mic_not_open_at_stop_flashes(tmp_path):
    class NoStream(FakeRecorder):
        last_stream_ok = False
        def end(self):
            self.recording = False
            return np.zeros(0, np.float32)
    app, out = make(tmp_path, rec=NoStream())
    app.on_action("toggle"); app.on_action("toggle")
    assert any("mic" in f.lower() for f in flashes(app))
    app.shutdown()


def test_instant_tap_with_working_mic_says_short_not_no_mic(tmp_path):
    class Instant(FakeRecorder):
        last_stream_ok = True
        def end(self):
            self.recording = False
            return np.zeros(0, np.float32)
    app, out = make(tmp_path, rec=Instant())
    app.on_action("toggle"); app.on_action("toggle")
    assert "Too short" in flashes(app)
    app.shutdown()


def test_cpu_fallback_flashes_once(tmp_path):
    eng = FakeEngine()
    eng.device = "cpu"
    app, out = make(tmp_path, eng=eng)
    for _ in range(2):
        app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: len(out) == 2)
    assert sum("GPU" in f for f in flashes(app)) == 1
    app.shutdown()


class StreamingRecorder(FakeRecorder):
    """Hands out 0.1 s chunks while recording, like the real one (for the live text)."""

    def __init__(self, seconds=1.0):
        super().__init__(seconds)
        self.chunks = []

    def begin(self):
        super().begin()
        self.chunks = []

        def feed():
            while self.recording:
                self.chunks.append(np.full(SR // 10, 0.1, np.float32))
                time.sleep(0.02)
        threading.Thread(target=feed, daemon=True).start()

    def chunks_since(self, i):
        return list(self.chunks[i:]), len(self.chunks)


class PreviewEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.previews = []

    def preview(self, audio, lang=None, prefer=None):
        self.previews.append(len(audio))
        return Result(text=f"oigo {len(self.previews)}", lang="es", speech_s=1.0, ms=1)


def test_live_text_while_recording_then_the_real_paste(tmp_path, monkeypatch):
    monkeypatch.setattr(App, "LIVE_EVERY_S", 0.05)
    eng = PreviewEngine()
    app, out = make(tmp_path, rec=StreamingRecorder(), eng=eng)
    app.on_action("toggle")
    assert wait(lambda: any(e[0] == "live" for e in app.ui.events))
    app.on_action("toggle")
    assert wait(lambda: out)
    n = len(eng.previews)
    time.sleep(0.2)
    assert len(eng.previews) == n  # stopped with the recording
    assert out == ["text 1 "]  # the careful pass is what gets pasted, never the preview
    assert [e for e in app.ui.events if e[0] == "live"][0][1] == "oigo 1"


def test_live_text_off_in_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(App, "LIVE_EVERY_S", 0.05)
    eng = PreviewEngine()
    app, out = make(tmp_path, rec=StreamingRecorder(), eng=eng)
    app.cfg.ui.live_text = False
    app.on_action("toggle")
    time.sleep(0.3)
    app.on_action("toggle")
    assert wait(lambda: out) and eng.previews == []


def test_a_much_too_short_result_keeps_its_audio(tmp_path):
    class Terse(FakeEngine):
        def transcribe(self, audio):
            return Result(text="Una frase. ", lang="es", speech_s=30.0, ms=5)
    app, out = make(tmp_path, rec=FakeRecorder(seconds=30.0), eng=Terse())
    app.on_action("toggle")
    app.on_action("toggle")
    assert wait(lambda: out)
    kept = list((tmp_path / "suspect").glob("*-es.f32"))
    assert len(kept) == 1 and kept[0].stat().st_size == 30 * SR * 4
