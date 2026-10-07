"""Live transcript while dictating (dictado-live): what the pill shows, and that it never gets in the way."""
import numpy as np

from ecoscribe.live import SR, LivePreview, tail


def test_tail_keeps_the_end_at_a_word():
    assert tail("hola  que\ntal") == "hola que tal"
    long = " ".join(f"palabra{i}" for i in range(40))
    t = tail(long, 60)
    assert t.startswith("…") and long.endswith(t[1:]) and len(t) <= 60
    assert not t[1:].startswith("alabra")  # never half a word


def _source(seconds):
    chunks = [np.full(SR // 2, 0.1, np.float32) for _ in range(int(seconds * 2))]
    state = {"n": 0}

    def chunks_since(i):
        state["n"] = min(len(chunks), state["n"] + 2)  # one more second each call
        return chunks[i:state["n"]], state["n"]
    return chunks_since


def test_each_pass_sees_the_recording_so_far_and_shows_the_tail():
    seen, shown = [], []
    lp = LivePreview(_source(40), lambda a: seen.append(len(a)) or f"texto {len(a) // SR}", shown.append,
                     window_s=28.0, min_s=1.5)
    assert lp.step() is False  # 1 s: too short to bother
    for _ in range(31):
        lp.step()
    assert seen[0] == 2 * SR and max(seen) == 28 * SR  # only the last 28 s once it's longer
    assert shown[-1] == "texto 28" and lp.passes == len(seen)


def test_skipped_or_unchanged_passes_leave_the_pill_alone():
    shown = []
    answers = iter([None, "hola", "hola", "hola mundo"])
    lp = LivePreview(_source(10), lambda a: next(answers), shown.append, min_s=0)
    for _ in range(4):
        lp.step()
    assert shown == ["hola", "hola mundo"]  # None = model busy or loading: skipped, not blanked


def test_stopped_preview_never_shows_late_text():
    shown = []
    lp = LivePreview(_source(10), lambda a: (lp.stop(), "tarde")[1], shown.append, min_s=0)
    assert lp.step() is False and shown == []  # the stop landed while the pass ran


def test_dropouts_are_digital_silence_only():
    from ecoscribe.quality import dropout_seconds
    rng = np.random.default_rng(0)
    talk = (0.05 * rng.standard_normal(SR * 4)).astype(np.float32)
    room = (0.002 * rng.standard_normal(SR * 2)).astype(np.float32)  # quiet room: not a dropout
    gap = np.zeros(SR * 3, np.float32)  # the headset sent zeros for 3 s
    blip = np.zeros(SR // 20, np.float32)  # 50 ms: too short to count
    a = np.concatenate([talk, room, gap, talk, blip, talk])
    assert abs(dropout_seconds(a) - 3.0) < 0.01
    assert dropout_seconds(talk) == 0.0


def test_too_short_flags_the_lost_dictations():
    from ecoscribe.quality import too_short
    assert too_short("x" * 138, 50.1)  # 2026-10-07 11:06: 50 s of Spanish, one sentence
    assert too_short("x" * 116, 36.9)
    assert not too_short("x" * 468, 45.0)  # the same speaker, complete
    assert not too_short("ok", 3.0)  # short ones are never judged


def test_a_slow_pass_stretches_the_gap_so_the_model_is_free_at_the_stop():
    t = [0.0]
    lp = LivePreview(_source(10), lambda a: (t.__setitem__(0, t[0] + 1.9), "hola")[1], lambda s: None,
                     min_s=0, clock=lambda: t[0])
    assert lp.gap() == 2.0
    lp.step()
    assert abs(lp.gap() - 4.75) < 1e-9  # a 1.9 s pass (large-v3 on the Mac): next one 4.75 s later
