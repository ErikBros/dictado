"""segclean wired into the workers: no tags, credits or silence inventions in transcripts (t0u.7, t0u.8)."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from dictado import meeting, sessions, transcribe
from dictado.config import TranscribeCfg
from dictado.flacw import FlacWriter

SR = 16000
SEGS = [(0.0, 2.0, " Hej <i>alla</i>"), (2.0, 4.0, " då"), (4.0, 6.0, " Text: VSI OrdKedjan 2021 www.vsi-stockholm.se")]


class Model:
    def detect_language(self, audio, **kw):
        return "sv", 0.9, []

    def transcribe(self, audio, **kw):
        segs = SEGS if len(audio) >= 6 * SR else [(0.0, len(audio) / SR, " ja <i>visst</i>"), (0.0, 0.1, " Undertexter av Amara.org")]
        return iter(SimpleNamespace(start=a, end=b, text=t) for a, b, t in segs), SimpleNamespace()


def test_imported_file_transcript_has_no_tags_or_credits(tmp_path):
    d = sessions.create("x", "sv", "import", tmp_path / "t")
    (d / "audio" / "a.wav").write_bytes(b"")
    rc = transcribe.run(d, TranscribeCfg(), factory=lambda p, dev, ct: Model(),
                        resolve=lambda n, c: Path("M:/x"), decode=lambda p: np.zeros(6 * SR, np.float32))
    assert rc == 0
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert [s["text"] for s in tr["segments"]] == ["Hej alla", "då"]
    assert "<i>" not in (d / "transcript.md").read_text(encoding="utf-8")


class Recorder:
    """6 s: the user 0-2 s, the others 2-4 s, then digital silence on both tracks."""

    def __init__(self, d, on_chunk):
        self.d, self.on_chunk, self.started = Path(d), on_chunk, False

    def start(self):
        self.started = True

    def stop(self):
        mic, sysa = np.zeros(6 * SR, np.float32), np.zeros(6 * SR, np.float32)
        mic[: 2 * SR], sysa[2 * SR: 4 * SR] = 0.3, 0.3
        for name, a in (("mic", mic), ("system", sysa), ("mix", mic + sysa)):
            w = FlacWriter(self.d / "audio" / f"{name}.flac")
            w.write(a)
            w.close()
        return {"mix": 6.0}


def test_meeting_drops_silence_inventions_and_cleans_live_lines(tmp_path):
    d = sessions.create("x", "sv", "meeting", tmp_path / "t")
    holder, stop = {}, threading.Event()

    def rec_factory(sd, on_chunk):
        holder["rec"] = Recorder(sd, on_chunk)
        return holder["rec"]

    def drive():
        while "rec" not in holder or not holder["rec"].started:
            time.sleep(0.01)
        holder["rec"].on_chunk(0.0, np.full(3 * SR, 0.2, np.float32))
        time.sleep(0.3)
        stop.set()
    threading.Thread(target=drive, daemon=True).start()
    rc = meeting.run(d, TranscribeCfg(), recorder_factory=rec_factory, stop_check=stop.is_set, poll_s=0.02,
                     factory=lambda p, dev, ct: Model(), resolve=lambda n, c: Path("M:/x"))
    assert rc == 0
    live = [json.loads(l)["text"] for l in (d / "live.jsonl").read_text(encoding="utf-8").splitlines()]
    assert live == ["ja visst"]
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert [(s["text"], s["speaker"]) for s in tr["segments"]] == [("Hej alla", "Me"), ("då", "Others")]
