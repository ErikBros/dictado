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


def test_the_mac_quick_piece_check_is_used_and_full_still_pads():
    """dictado-1tw on the Mac: mlx has no faster-whisper internals; its detect_language_piece is the quick way."""
    seen = []

    class MlxLike(FakeModel):
        def detect_language_piece(self, audio):
            seen.append(("quick", round(len(audio) / SR, 1)))
            return self.detect_language(audio)

        def detect_language(self, audio, **kw):
            seen.append(("full", round(len(audio) / SR, 1)))
            return FakeModel.detect_language(self, audio, **kw)

    e = engine(("es", "el"))
    e.model = MlxLike()
    a = recording((("es", 5),))
    assert e._detect(a, ["es", "el"]) == "es" and seen[0] == ("quick", 5.0)
    seen.clear()
    assert e._detect(a, ["es", "el"], full=True) == "es" and seen == [("full", 5.0)]


def test_a_short_pause_between_languages_still_splits():
    """Silero's default 400 ms pad each side swallowed pauses under ~0.8 s, so a switch after a breath
    was never cut (measured on the Mac 2026-10-07: 1 of 8 Greek -> Spanish joins split; 8 of 8 at 100 ms)."""
    import wave
    from pathlib import Path
    fx = Path(__file__).parent / "fixtures"

    def wav(name):
        with wave.open(str(fx / name)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    def trim(a):  # the clips' own silence at the ends would widen the gap
        loud = np.flatnonzero(np.abs(a) > 0.02)
        return a[loud[0]:loud[-1] + 1]
    es, en = trim(wav("es_climb.wav")), trim(wav("en_fox.wav"))
    for gap_s in (0.3, 0.5):
        audio = np.concatenate([es, np.zeros(int(gap_s * SR), np.float32), en])
        ps = Engine._pieces(audio)
        assert len(ps) >= 2, (gap_s, ps)


def test_an_unsure_quick_check_is_checked_the_full_way():
    """dictado-l2x: turbo's quick check heard a clean 3 s Spanish piece as English (0.87) and both pieces
    agreed, so nothing was re-checked and the English half vanished. Every wrong quick answer measured
    (967 pieces, turbo and large-v3) was under QUICK_SURE; a sure one is still used as is."""
    from ecoscribe.engine import QUICK_SURE
    seen = []

    class Unsure(FakeModel):
        def __init__(self, p):
            super().__init__()
            self.p = p

        def detect_language_piece(self, audio):
            seen.append("quick")
            return "en", self.p, [("en", self.p), ("es", 1 - self.p)]

        def detect_language(self, audio, **kw):
            seen.append("full")
            return FakeModel.detect_language(self, audio, **kw)

    e = engine(("en", "es"))
    a = recording((("es", 3),))
    e.model = Unsure(0.87)
    assert e._detect(a, ["en", "es"]) == "es" and seen == ["quick", "full"]
    seen.clear()
    e.model = Unsure(QUICK_SURE)
    assert e._detect(a, ["en", "es"]) == "en" and seen == ["quick"]

def test_word_confidence_is_a_second_pass_with_word_timestamps():
    """dictado-9jc.1: how sure Whisper was of each word, asked for after the paste."""
    class Worded(FakeModel):
        def transcribe(self, audio, language=None, **kw):
            self.calls.append((language, kw.get("word_timestamps"), kw.get("without_timestamps")))
            w = [SimpleNamespace(word=" Hola", probability=0.9), SimpleNamespace(word=" amigos.", probability=0.4)]
            seg = SimpleNamespace(text=" Hola amigos.", no_speech_prob=0.01, words=w if kw.get("word_timestamps") else None)
            return iter([seg]), SimpleNamespace(duration=len(audio) / SR, duration_after_vad=len(audio) / SR)

    e = engine(("es", "el"))
    e.model = Worded()
    e._pieces = lambda audio: [(0.0, len(audio) / SR)]
    a = recording((("es", 4),))
    assert e.word_confidence(a, "es") == [("Hola", 0.9), ("amigos.", 0.4)]
    assert e.model.calls == [("es", True, False)]
    assert e.transcribe(a, lang="es").text.strip() == "Hola amigos."
    assert e.model.calls[-1] == ("es", None, True)  # the dictation itself stays without word timestamps

    class NoWords(FakeModel):  # the Mac's mlx model until dictado-9jc.6
        pass
    e.model = NoWords()
    assert e.word_confidence(a, "es") is None
