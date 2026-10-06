"""The dictation in progress on disk, recovered after a crash (t0u.37)."""
import json
import time

import numpy as np

from dictado import spool as spool_mod
from dictado.app import App
from dictado.config import Config
from dictado.deliver import DeliveryResult
from dictado.spool import Spool
from tests.test_app import FakeEngine, FakeGate, FakeUi, wait

SR = 16000


class ChunkRecorder:
    """Records 0.1 s chunks while 'recording'; exposes them like audio.Recorder."""

    def __init__(self):
        self.chunks, self.recording = [], False

    def begin(self):
        self.recording, self.chunks = True, []

    def add(self, seconds):
        self.chunks.append(np.full(int(seconds * SR), 0.25, np.float32))

    def chunks_since(self, i):
        return list(self.chunks[i:]), len(self.chunks)

    def end(self):
        self.recording = False
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)

    def abort(self):
        self.recording = False

    def level(self):
        return 0.0


def make(tmp_path, rec, eng=None):
    app = App(Config(), rec, eng or FakeEngine(), lambda t: DeliveryResult(True, "x.exe", "ok"), FakeUi(),
              gate=FakeGate(), history_path=tmp_path / "h.jsonl", spool=Spool(tmp_path / "spool"))
    app.start()
    return app


def test_recording_reaches_disk_while_you_talk(tmp_path, monkeypatch):
    monkeypatch.setattr(spool_mod, "FLUSH_S", 0.05)
    rec = ChunkRecorder()
    app = make(tmp_path, rec)
    app.on_action("toggle")
    rec.add(1.0)
    rec.add(1.0)
    [f] = list((tmp_path / "spool").glob("rec-*.f32"))
    assert wait(lambda: f.stat().st_size == 2 * SR * 4)  # 2 s of float32, before any stop
    app.on_action("toggle")
    assert wait(lambda: not f.exists())  # delivered: gone


def test_cancel_and_too_short_leave_nothing(tmp_path):
    rec = ChunkRecorder()
    app = make(tmp_path, rec)
    app.on_action("toggle")
    rec.add(1.0)
    app.on_action("cancel")
    app.on_action("toggle")
    rec.add(0.05)
    app.on_action("toggle")
    time.sleep(0.2)
    assert list((tmp_path / "spool").glob("*")) == []


def test_crash_leftover_goes_to_history_as_recovered(tmp_path):
    sp = tmp_path / "spool"
    sp.mkdir()
    (sp / "rec-1.f32").write_bytes(np.full(2 * SR, 0.2, np.float32).tobytes())
    (sp / "rec-2.f32").write_bytes(np.full(SR // 10, 0.2, np.float32).tobytes())  # 0.1 s: not worth it
    app = make(tmp_path, ChunkRecorder())
    assert app.recover() == 1
    [row] = [json.loads(l) for l in (tmp_path / "h.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["recovered"] is True and row["pasted"] is False and row["text"]
    assert list(sp.glob("*")) == []
    assert ("flash", "Recovered what you were saying: it's in History", 6.0) in app.ui.events


def test_half_written_file_still_reads():
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / "rec-9.f32"
    p.write_bytes(np.ones(10, np.float32).tobytes() + b"\x00\x01")  # a crash mid-write
    assert len(Spool.read(p)) == 10
