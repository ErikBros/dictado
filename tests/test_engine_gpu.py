import re
from pathlib import Path

import numpy as np
import pytest

from ecoscribe.audio import read_wav
from ecoscribe.config import TextCfg, WhisperCfg
from ecoscribe.engine import SR

pytestmark = pytest.mark.gpu
FIX = Path(__file__).parent / "fixtures"
EXPECTED = {
    "en_fox": ("en", "The quick brown fox jumps over the lazy dog, then runs back to the barn."),
    "en_long": ("en", "I would like to schedule the climbing session for Thursday evening, "
                      "and please remind me to bring the new shoes and the chalk bag."),
    "es_climb": ("es", "Mañana por la mañana voy a escalar con mis amigos en Gotemburgo."),
}


def words(s):
    return re.findall(r"\w+", s.lower())


def recall(got, want):
    g = set(words(got))
    w = words(want)
    return sum(x in g for x in w) / len(w)


@pytest.fixture(scope="module")
def engine():
    """Multilingual engine (en + es) so the Spanish cases still prove detection works."""
    from ecoscribe.engine import Engine
    e = Engine(WhisperCfg(languages=["en", "es"]), TextCfg())
    e.load()
    return e


@pytest.fixture(scope="module")
def engine_en(engine):
    """The shipped default: English only (shares the loaded model)."""
    from ecoscribe.engine import Engine
    e = Engine(WhisperCfg(), TextCfg())
    e.model, e.device = engine.model, engine.device
    return e


def test_default_is_english_only_and_skips_detection(engine_en):
    assert engine_en.cfg.languages == ["en"]
    r = engine_en.transcribe(read_wav(FIX / "en_long.wav"))
    assert r.lang == "en" and recall(r.text, EXPECTED["en_long"][1]) >= 0.85
    best = min(engine_en.transcribe(read_wav(FIX / "en_long.wav")).ms for _ in range(3))
    print("english-only en_long best ms", best)
    assert best < 800


def test_first_call_is_warm(engine):
    r = engine.transcribe(read_wav(FIX / "en_fox.wav"))
    print("first call ms", r.ms)
    assert r.ms < 800


def test_loaded_on_gpu(engine):
    import sys
    assert engine.fallback_reason is None
    assert engine.device == ("mlx" if sys.platform == "darwin" else "cuda")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_accuracy_language_first_word(engine, name):
    lang, want = EXPECTED[name]
    r = engine.transcribe(read_wav(FIX / f"{name}.wav"))
    print(name, r)
    assert r.lang == lang
    assert recall(r.text, want) >= 0.85, r.text
    assert words(r.text)[0] == words(want)[0], r.text
    assert r.text.endswith(" ")


@pytest.mark.parametrize("name,want", [("en_thanks", "thank you"), ("es_gracias", "gracias")])
def test_short_real_phrases_not_dropped(engine, name, want):
    r = engine.transcribe(read_wav(FIX / f"{name}.wav"))
    print(name, r)
    assert want in r.text.lower()


def test_silence_empty(engine):
    assert engine.transcribe(read_wav(FIX / "silence_3s.wav")).text == ""


def test_zeros_empty(engine):
    assert engine.transcribe(np.zeros(16000, np.float32)).text == ""


def test_latency_10s_under_1s(engine):
    a = read_wav(FIX / "en_long.wav")
    best = min(engine.transcribe(a).ms for _ in range(3))
    print("en_long best ms", best)
    assert best < 1000


def _trimmed(name):
    a = read_wav(FIX / f"{name}.wav")
    loud = np.flatnonzero(np.abs(a) > 0.02)
    return a[loud[0]:loud[-1] + 1]


@pytest.mark.parametrize("gap_s", [0.3, 0.5])
def test_mixed_dictation_after_a_breath(engine, gap_s):
    """dictado-l2x: a language switch after a short breath splits on the real model (MIX_PAD_MS = 30),
    each run in its own language, in order."""
    es, en = _trimmed("es_climb"), _trimmed("en_fox")
    r = engine.transcribe(np.concatenate([es, np.zeros(int(gap_s * SR), np.float32), en]))
    print(gap_s, r)
    assert r.lang == "es+en", r
    half = len(words(r.text)) // 2
    assert recall(" ".join(words(r.text)[:half + 3]), EXPECTED["es_climb"][1]) >= 0.8, r.text
    assert recall(r.text, EXPECTED["en_fox"][1]) >= 0.85, r.text
    assert r.ms < 2500
