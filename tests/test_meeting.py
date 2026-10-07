"""--meeting worker with a fake recorder and a fake model."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ecoscribe import meeting, sessions
from ecoscribe.config import TranscribeCfg
from ecoscribe.flacw import FlacWriter

SR = 16000


class FakeModel:
    def __init__(self, delay=0.0):
        self.delay, self.calls = delay, []

    def detect_language(self, audio, **kw):
        return "sv", 0.9, []

    def transcribe(self, audio, language=None, **kw):
        self.calls.append(len(audio))
        if self.delay:
            time.sleep(self.delay)
        dur = len(audio) / SR

        def gen():
            yield SimpleNamespace(start=0.0, end=dur / 2, text=" hej")
            yield SimpleNamespace(start=dur / 2, end=dur, text=" då")
        return gen(), SimpleNamespace(duration=dur)


class FakeRecorder:
    """Writes 4 s of tracks at stop: mic loud in the first half, system in the second."""

    def __init__(self, d, on_chunk):
        self.d, self.on_chunk, self.started, self.stopped = Path(d), on_chunk, False, 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped += 1
        mic, sysa = np.zeros(4 * SR, np.float32), np.zeros(4 * SR, np.float32)
        mic[: 2 * SR], sysa[2 * SR:] = 0.3, 0.3
        for name, a in (("mic", mic), ("system", sysa), ("mix", mic + sysa)):
            w = FlacWriter(self.d / "audio" / f"{name}.flac")
            w.write(a)
            w.close()
        return {"mix": 4.0}

    def levels(self):
        return (0.1, 0.2)


def start(tmp_path, model, stop_after_chunks=2, chunk_s=3.0):
    d = sessions.create("Reunión", "sv", "meeting", tmp_path / "t")
    holder = {}

    def rec_factory(sd, on_chunk):
        holder["rec"] = FakeRecorder(sd, on_chunk)
        return holder["rec"]
    stop = threading.Event()

    def drive():  # the "meeting": chunks arrive, then the user leaves the call
        while "rec" not in holder or not holder["rec"].started:
            time.sleep(0.01)
        for i in range(stop_after_chunks):
            holder["rec"].on_chunk(i * chunk_s, np.full(int(chunk_s * SR), 0.2, np.float32))
        time.sleep(0.2)
        stop.set()
    threading.Thread(target=drive, daemon=True).start()
    factory = lambda path, device, ct: model  # noqa: E731
    rc = meeting.run(d, TranscribeCfg(), recorder_factory=rec_factory, stop_check=stop.is_set, poll_s=0.02,
                     factory=factory, resolve=lambda name, cfg: Path("M:/") / name.replace("/", "--"))
    return d, rc, holder["rec"]


def test_live_lines_in_order_with_session_times(tmp_path):
    d, rc, _ = start(tmp_path, FakeModel())
    assert rc == 0
    lines = [json.loads(l) for l in (d / "live.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(l["t0"], l["t1"]) for l in lines] == [(0.0, 3.0), (3.0, 6.0)]
    assert lines[0]["text"] == "hej då"
    assert all("lag_s" in l for l in lines)


def test_final_pass_labels_speakers_and_finishes(tmp_path):
    d, rc, rec = start(tmp_path, FakeModel())
    assert rc == 0 and rec.stopped == 1
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert [s["speaker"] for s in tr["segments"]] == ["Me", "Others"]
    meta = sessions.read_meta(d)
    assert meta["status"] == "done" and meta["source"] == "meeting"
    assert (d / "transcript.md").exists()


def test_stop_during_chunk(tmp_path):
    model = FakeModel(delay=0.5)
    t0 = time.monotonic()
    d, rc, rec = start(tmp_path, model, stop_after_chunks=3)
    assert rc == 0
    assert time.monotonic() - t0 < 5
    assert sessions.read_meta(d)["status"] == "done"
    assert model.calls.count(4 * SR) == 1  # the final pass ran exactly once


def test_stop_file(tmp_path):
    d = sessions.create("x", "sv", "meeting", tmp_path / "t")
    check = meeting.stop_checker(d, event_name=None)
    assert not check()
    (d / "stop").write_text("", encoding="utf-8")
    assert check()


def test_crash_while_recording_still_stops_the_recorder(tmp_path):
    d = sessions.create("x", "sv", "meeting", tmp_path / "t")
    holder = {}

    def rec_factory(sd, on_chunk):
        holder["rec"] = FakeRecorder(sd, on_chunk)
        return holder["rec"]

    def boom():
        raise RuntimeError("stop check blew up")
    rc = meeting.run(d, TranscribeCfg(), recorder_factory=rec_factory, stop_check=boom, poll_s=0.01,
                     factory=lambda p, dev, ct: FakeModel(), resolve=lambda n, c: Path("M:/x"))
    assert rc == 1 and holder["rec"].stopped == 1
    assert sessions.read_meta(d)["status"] == "failed"


def test_worker_writes_levels_for_the_silence_backup(tmp_path):
    d, rc, _ = start(tmp_path, FakeModel())
    lv = json.loads((d / "levels.json").read_text(encoding="utf-8"))
    assert (lv["mic"], lv["system"]) == (0.1, 0.2) and lv["t"] > 0



def test_live_language_follows_a_switch(tmp_path):
    """Switching the language mid-meeting (meta lang) applies to the next live chunk."""
    d = sessions.create("Reunión", "sv", "meeting", tmp_path / "t")
    from ecoscribe import meeting as mt
    assert mt._current_lang(d, "sv") == "sv"
    sessions.write_meta(d, lang="en")
    assert mt._current_lang(d, "sv") == "en"
    sessions.write_meta(d, lang="auto")
    assert mt._current_lang(d, "sv") is None  # auto: each chunk detects


def test_a_recovered_meeting_gets_the_final_pass_and_labels(tmp_path):
    """ecoscribe --transcribe on a killed meeting: transcribe what was saved, then Me / Others."""
    from ecoscribe import transcribe
    d = sessions.create("Meeting", "sv", "meeting", tmp_path / "t")
    FakeRecorder(d, None).stop()  # the FLACs a killed worker left behind
    sessions.write_meta(d, status="queued", recovered=True)
    rc = transcribe.run_session(d, TranscribeCfg(), factory=lambda path, device, ct: FakeModel(),
                                resolve=lambda name, cfg: Path("M:/") / name.replace("/", "--"))
    assert rc == 0
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert [s["speaker"] for s in tr["segments"]] == ["Me", "Others"]
    assert sessions.read_meta(d)["status"] == "done" and (d / "transcript.md").exists()


def test_an_imported_file_is_not_labelled(tmp_path):
    from ecoscribe import transcribe
    d = sessions.create("x", "sv", "import", tmp_path / "t")
    w = FlacWriter(d / "audio" / "x.flac")
    w.write(np.full(2 * SR, 0.2, np.float32))
    w.close()
    rc = transcribe.run_session(d, TranscribeCfg(), factory=lambda path, device, ct: FakeModel(),
                                resolve=lambda name, cfg: Path("M:/") / name.replace("/", "--"))
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert rc == 0 and all(s["speaker"] is None for s in tr["segments"])
