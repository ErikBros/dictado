import numpy as np

from ecoscribe.speakers import label

SR = 16000


def seg(t0, t1):
    return {"t0": t0, "t1": t1, "text": "x", "speaker": None}


def tracks(mic_level, sys_level, seconds=4):
    n = seconds * SR
    rng = np.random.default_rng(0)
    return (rng.normal(0, mic_level, n).astype(np.float32) if mic_level else np.zeros(n, np.float32),
            rng.normal(0, sys_level, n).astype(np.float32) if sys_level else np.zeros(n, np.float32))


def test_mic_only_is_yo():
    mic, sysa = tracks(0.2, 0)
    assert label([seg(0, 2)], mic, sysa)[0]["speaker"] == "Me"


def test_system_only_is_otros():
    mic, sysa = tracks(0, 0.2)
    assert label([seg(0, 2)], mic, sysa)[0]["speaker"] == "Others"


def test_echo_in_mic_goes_to_otros():
    mic, sysa = tracks(0.05, 0.2)  # their voice leaking into my mic, weaker than the system track
    assert label([seg(0, 2)], mic, sysa)[0]["speaker"] == "Others"


def test_both_mic_louder_is_yo():
    mic, sysa = tracks(0.3, 0.02)
    assert label([seg(0, 2)], mic, sysa)[0]["speaker"] == "Me"


def test_segment_past_audio_end_stays_none():
    mic, sysa = tracks(0.2, 0)
    assert label([seg(10, 12)], mic, sysa)[0]["speaker"] is None


def test_per_segment():
    n = 4 * SR
    mic = np.zeros(n, np.float32); sysa = np.zeros(n, np.float32)
    mic[:2 * SR] = 0.2
    sysa[2 * SR:] = 0.2
    out = label([seg(0, 2), seg(2, 4)], mic, sysa)
    assert [s["speaker"] for s in out] == ["Me", "Others"]
