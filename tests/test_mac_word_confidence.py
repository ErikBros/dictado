"""dictado-9jc.6: the mlx model gives words with probabilities (faster-whisper's shape), no real model needed."""
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="mlx")


def test_word_timestamps_give_faster_whisper_shaped_words(monkeypatch):
    from ecoscribe.platform.macos import mlx_engine as me
    m = me.MlxWhisperModel.__new__(me.MlxWhisperModel)
    raw = {"segments": [{"start": 0.0, "end": 2.0, "text": " Hola amigos.", "words": [
        {"word": " Hola", "start": 0.1, "end": 0.5, "probability": 0.98},
        {"word": " amigos.", "start": 0.6, "end": 1.2, "probability": 0.71}]}]}
    seen = {}
    monkeypatch.setattr(m, "_run", lambda *a, **k: seen.setdefault("args", a) and raw, raising=False)
    segs, _ = m.transcribe(np.zeros(32000, np.float32), language="es", without_timestamps=False, word_timestamps=True)
    words = [(w.word.strip(), w.probability) for s in segs for w in s.words]
    assert words == [("Hola", 0.98), ("amigos.", 0.71)]
    assert seen["args"][-1] is True  # word_timestamps reached mlx_whisper


def test_without_word_timestamps_no_words(monkeypatch):
    from ecoscribe.platform.macos import mlx_engine as me
    m = me.MlxWhisperModel.__new__(me.MlxWhisperModel)
    raw = {"segments": [{"start": 0.0, "end": 2.0, "text": " Hola."}]}
    monkeypatch.setattr(m, "_run", lambda *a, **k: raw, raising=False)
    segs, _ = m.transcribe(np.zeros(16000 * 31, np.float32), language="es")  # over 30 s: the full path
    assert [s.words for s in segs] == [None]


def test_the_word_pass_reuses_the_dictations_tokens_only_for_the_same_clip():
    from ecoscribe.platform.macos import mlx_engine as me
    m = me.MlxWhisperModel.__new__(me.MlxWhisperModel)
    a = np.ones(16000, np.float32)
    m._last_tokens = (m._clip_key(a, "en", None), [1, 2, 3])
    assert m._aligned(a * 0.5, "en", None) is None  # another clip: the caller transcribes with word timestamps
    assert m._aligned(a, "es", None) is None  # another language
