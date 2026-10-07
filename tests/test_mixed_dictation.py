"""Dictation in more than one of your languages (dictado-1tw): each run in its own language."""
from types import SimpleNamespace

import numpy as np

from ecoscribe.config import TextCfg, WhisperCfg
from ecoscribe.engine import SR, Engine

# a fake recording: es 0-10 s, el 10-16 s, es 16-24 s, as constant levels the fake model can read
LEVEL = {"es": 0.1, "el": 0.2, "en": 0.3, "sv": 0.4}
PIECES = [(0.0, 5.0), (5.2, 10.0), (10.2, 16.0), (16.2, 24.0)]


def recording(parts=(("es", 10), ("el", 6), ("es", 8))):
    return np.concatenate([np.full(int(s * SR), LEVEL[lang], np.float32) for lang, s in parts])


class FakeModel:
    def __init__(self, *a, **k):
        self.calls = []

    def detect_language(self, audio, **kw):
        lv = float(np.median(audio)) if len(audio) else 0.0
        lang = min(LEVEL, key=lambda k: abs(LEVEL[k] - lv))
        return lang, 0.9, [(lang, 0.9), ("en", 0.05)]

    def transcribe(self, audio, language=None, **kw):
        self.calls.append((language, round(len(audio) / SR, 1), kw.get("beam_size")))
        seg = SimpleNamespace(text=f" [{language} {len(audio) // SR}s]", no_speech_prob=0.01)
        return iter([seg]), SimpleNamespace(duration=len(audio) / SR, duration_after_vad=len(audio) / SR)


def engine(langs=("en", "es", "sv", "el")):
    e = Engine(WhisperCfg(device="cuda", languages=list(langs)), TextCfg(), model_factory=FakeModel,
               resolve=lambda n: n)
    e.model = FakeModel()
    e._pieces = lambda audio: [p for p in PIECES if p[1] * SR <= len(audio) + SR]
    return e


def test_each_run_in_its_own_language_in_order():
    e = engine()
    r = e.transcribe(recording())
    assert [c[0] for c in e.model.calls] == ["es", "el", "es"]  # pieces of one language joined into runs
    assert r.lang == "es+el" and r.text.startswith("[es") and "[el" in r.text


def test_one_language_is_one_pass_as_before():
    e = engine()
    r = e.transcribe(recording((("es", 24),)))
    assert len(e.model.calls) == 1 and r.lang == "es"


def test_a_disagreeing_piece_is_checked_again_the_full_way():
    e = engine()
    seen = []

    def detect(chunk, langs, full=False):
        seen.append(full)
        if not full and abs(float(np.median(chunk)) - LEVEL["el"]) < 0.01:
            return "en"  # the quick way gets the Greek piece wrong...
        return min(LEVEL, key=lambda k: abs(LEVEL[k] - float(np.median(chunk))))  # ...the full way doesn't
    e._detect = detect
    assert e.language_runs(recording(), ["en", "es", "sv", "el"]) == [(0.0, 10.0, "es"), (10.2, 16.0, "el"),
                                                                        (16.2, 24.0, "es")]
    assert seen.count(True) == 1  # only the piece that disagreed paid for the full check


def test_no_mixing_when_forced_single_language_short_or_preview():
    e = engine()
    e.transcribe(recording(), lang="es")  # dictation key + L: the user said which
    assert [c[0] for c in e.model.calls] == ["es"]
    e = engine(langs=("es",))
    e.transcribe(recording())
    assert len(e.model.calls) == 1
    e = engine()
    e.transcribe(recording((("es", 1), ("el", 1.5))))  # under 3 s: one language
    assert len(e.model.calls) == 1
    e = engine()
    e.preview(recording())  # the live text stays one quick pass
    assert len(e.model.calls) == 1 and e.model.calls[0][2] == 1
