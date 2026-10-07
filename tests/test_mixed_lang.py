"""Mixed-language sessions (t0u.34): "el,es" = Greek + Spanish, detected piece by piece."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ecoscribe import meeting, sessions, transcribe
from ecoscribe.config import TranscribeCfg
from ecoscribe.flacw import FlacWriter
from ecoscribe.routing import LANG_NAMES, mixed_langs, model_for

SR = 16000
GREEK, SPANISH = 0.1, 0.2  # the fake model "hears" the language in the sample value


def test_mixed_code_names_and_routes_by_first_language():
    assert mixed_langs("el,es") == ["el", "es"]
    assert mixed_langs("el") is None and mixed_langs("auto") is None
    assert LANG_NAMES["el,es"] == "Greek + Spanish"
    assert model_for("el,es", TranscribeCfg()) == "Systran/faster-whisper-large-v3"


def test_pieces_cut_at_pauses_and_cap_length():
    regions = [(0.0, 2.0), (2.3, 4.0), (6.0, 9.0), (9.2, 30.0), (31.0, 31.5)]
    out = transcribe.pieces(regions, max_s=15.0, gap_s=1.0, min_s=3.0)
    # a short pause doesn't cut, a 2 s pause does; a group over 15 s is cut between its
    # regions first, and a single 20.8 s region into equal halves (no 0.8 s scrap)
    assert out == [(0.0, 4.0), (6.0, 9.0), (9.2, 19.6), (19.6, 30.0), (31.0, 31.5)]


def test_pieces_keep_a_short_start_together():
    # under min_s the next region joins even after a long pause: 1 s alone is too little to detect
    assert transcribe.pieces([(0.0, 1.0), (3.0, 6.0)], max_s=15.0, gap_s=1.0, min_s=3.0) == [(0.0, 6.0)]


class MixedModel:
    """detect_language reads the samples: 0.1 = Greek, 0.2 = Spanish. English always scores
    highest, so a choice outside el/es would show up."""

    def __init__(self, path=None, device="cuda", compute_type="int8_float16"):
        self.calls = []

    def detect_language(self, audio, **kw):
        greek = abs(float(np.mean(audio)) - GREEK) < 0.05
        probs = [("en", 0.6), ("el", 0.3 if greek else 0.1), ("es", 0.1 if greek else 0.3)]
        return "en", 0.6, probs

    def transcribe(self, audio, language=None, **kw):
        self.calls.append(language)
        dur = len(audio) / SR

        def gen():
            yield SimpleNamespace(start=0.0, end=dur, text=f" {language}")
        return gen(), SimpleNamespace(duration=dur)


def mixed_audio():
    a = np.zeros(20 * SR, np.float32)
    a[0: 5 * SR] = GREEK       # 0-5 s Greek
    a[7 * SR: 12 * SR] = SPANISH  # 7-12 s Spanish
    a[14 * SR: 19 * SR] = GREEK   # 14-19 s Greek
    return a


def speech_of(audio):
    return [(0.0, 5.0), (7.0, 12.0), (14.0, 19.0)]


def test_final_pass_detects_each_piece_and_offsets_segments(tmp_path):
    d = sessions.create("Clase", "el,es", "import", tmp_path / "t")
    (d / "audio" / "a.wav").write_bytes(b"")
    models = []

    def factory(path, device, ct):
        models.append(MixedModel())
        return models[-1]
    rc = transcribe.run(d, TranscribeCfg(), factory=factory, resolve=lambda n, c: Path("M:/") / n.replace("/", "--"),
                        decode=lambda p: mixed_audio(), clock=iter(range(0, 10_000)).__next__, speech=speech_of)
    assert rc == 0
    assert len(models) == 1  # one model (large-v3) for the whole session, no detector
    assert models[0].calls == ["el", "es", "el"]
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert [(s["t0"], s["t1"], s["lang"], s["text"]) for s in tr["segments"]] == [
        (0.0, 5.0, "el", "el"), (7.0, 12.0, "es", "es"), (14.0, 19.0, "el", "el")]
    assert tr["lang"] == "el,es"
    meta = sessions.read_meta(d)
    assert meta["status"] == "done" and meta["lang_used"] == "el,es"
    assert meta["model"] == "Systran/faster-whisper-large-v3"


def test_short_unsure_piece_keeps_the_previous_language(tmp_path):
    m = MixedModel()
    a = np.zeros(10 * SR, np.float32)
    a[0: 5 * SR] = GREEK
    a[7 * SR: int(7.8 * SR)] = SPANISH  # 0.8 s "sí": too short to trust
    segs = list(transcribe.mixed_segments(m, a, ["el", "es"], TranscribeCfg(),
                                          speech=lambda x: [(0.0, 5.0), (7.0, 7.8)]))
    assert [s.lang for s in segs] == ["el", "el"]


def test_nothing_said_gives_no_segments():
    assert list(transcribe.mixed_segments(MixedModel(), np.zeros(SR, np.float32), ["el", "es"],
                                          TranscribeCfg(), speech=lambda x: [])) == []


class Rec:
    def __init__(self, d, on_chunk):
        self.d, self.on_chunk, self.started = Path(d), on_chunk, False

    def start(self):
        self.started = True

    def stop(self):
        a = mixed_audio()
        for name, x in (("mic", a), ("system", np.zeros_like(a)), ("mix", a)):
            w = FlacWriter(self.d / "audio" / f"{name}.flac")
            w.write(x)
            w.close()
        return {"mix": 20.0}

    def levels(self):
        return (0.1, 0.0)


def test_meeting_live_chunks_detect_greek_or_spanish(tmp_path):
    d = sessions.create("Clase", "el,es", "meeting", tmp_path / "t")
    model, holder, stop = MixedModel(), {}, threading.Event()

    def rec_factory(sd, on_chunk):
        holder["rec"] = Rec(sd, on_chunk)
        return holder["rec"]

    def drive():
        while "rec" not in holder or not holder["rec"].started:
            time.sleep(0.01)
        holder["rec"].on_chunk(0.0, np.full(3 * SR, SPANISH, np.float32))
        holder["rec"].on_chunk(3.0, np.full(3 * SR, GREEK, np.float32))
        time.sleep(0.3)
        stop.set()
    threading.Thread(target=drive, daemon=True).start()
    rc = meeting.run(d, TranscribeCfg(), recorder_factory=rec_factory, stop_check=stop.is_set, poll_s=0.02,
                     factory=lambda p, dev, ct: model, resolve=lambda n, c: Path("M:/") / n.replace("/", "--"),
                     speech=speech_of)
    assert rc == 0
    live = [json.loads(l) for l in (d / "live.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["text"] for l in live] == ["es", "el"]
    assert model.calls[:2] == ["es", "el"]
    assert model.calls[2:] == ["el", "es", "el"]  # the final pass, same model
