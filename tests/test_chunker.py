import numpy as np

from dictado.chunker import Chunker

SR = 16000


def speech(s):
    return np.full(int(s * SR), 0.2, np.float32)


def quiet(s):
    return np.zeros(int(s * SR), np.float32)


def feed(c, *parts, block=1600):
    out = []
    for p in parts:
        for i in range(0, len(p), block):
            out += c.push(p[i:i + block])
    return out


def test_cuts_at_pause_after_min():
    c = Chunker()
    out = feed(c, speech(4), quiet(0.6), speech(1))
    assert len(out) == 1
    t0, audio = out[0]
    assert t0 == 0 and 4.4 <= len(audio) / SR <= 4.7


def test_short_speech_waits_for_min():
    c = Chunker()
    assert feed(c, speech(1), quiet(0.6), speech(1)) == []


def test_forces_cut_at_max():
    c = Chunker(max_s=20)
    out = feed(c, speech(45))
    assert [round(len(a) / SR) for _, a in out] == [20, 20]


def test_t0_contiguous_and_flush_returns_rest():
    c = Chunker()
    out = feed(c, speech(4), quiet(0.6), speech(4), quiet(0.6), speech(2))
    rest = c.flush()
    chunks = out + ([rest] if rest else [])
    t = 0.0
    for t0, a in chunks:
        assert abs(t0 - t) < 1e-6
        t += len(a) / SR
    assert abs(t - 11.2) < 0.01


def test_silence_only_chunks_are_marked_silent():
    c = Chunker(max_s=5)
    out = feed(c, quiet(11))
    assert out == []  # nothing to transcribe in pure silence
    rest = c.flush()
    assert rest is None


def noisy(s, level):
    return np.full(int(s * SR), level, np.float32)


def test_pause_counts_over_background_noise():
    """A podcast's gaps aren't silent (room tone, music bed): relative to the speech they still are."""
    c = Chunker()
    out = feed(c, speech(4), noisy(0.6, 0.03), speech(1))
    assert len(out) == 1 and 4.4 <= len(out[0][1]) / SR <= 4.7


def test_live_default_never_waits_more_than_8_s():
    out = feed(Chunker(), speech(17))  # continuous speech, no pause at all
    assert [round(len(a) / SR) for _, a in out] == [8, 8]


def test_noise_alone_is_still_dropped():
    assert feed(Chunker(), noisy(25, 0.005)) == []
