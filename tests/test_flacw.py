import numpy as np

from ecoscribe.flacw import FlacWriter, mix

SR = 16000


def test_round_trip(tmp_path):
    from faster_whisper import decode_audio
    p = tmp_path / "a.flac"
    w = FlacWriter(p)
    rng = np.random.default_rng(0)
    blocks = [rng.uniform(-0.5, 0.5, n).astype(np.float32) for n in (1600, 4000, 333)]
    for b in blocks:
        w.write(b)
    w.close()
    assert w.samples == sum(len(b) for b in blocks)
    back = decode_audio(str(p), sampling_rate=SR)
    ref = np.concatenate(blocks)
    assert abs(len(back) - len(ref)) <= 1
    n = min(len(back), len(ref))
    assert np.max(np.abs(back[:n] - ref[:n])) < 1e-3  # 16-bit quantization only


def test_empty_file_is_valid(tmp_path):
    from faster_whisper import decode_audio
    p = tmp_path / "e.flac"
    w = FlacWriter(p)
    w.close()
    assert p.exists() and len(decode_audio(str(p), sampling_rate=SR)) == 0


def test_close_twice_is_harmless(tmp_path):
    w = FlacWriter(tmp_path / "x.flac")
    w.write(np.zeros(160, np.float32))
    w.close()
    w.close()


def test_mix_pads_and_clips():
    a = np.array([0.6, 0.6, 0.6], np.float32)
    b = np.array([0.6], np.float32)
    assert np.allclose(mix(a, b), [1.0, 0.6, 0.6])
    assert np.allclose(mix(b, np.zeros(0, np.float32)), [0.6])


def test_hard_killed_writer_leaves_a_readable_file(tmp_path):
    """The meeting worker can die mid-call: everything up to the last flush must decode."""
    import subprocess
    import sys
    from pathlib import Path

    from faster_whisper import decode_audio
    app = Path(__file__).resolve().parent.parent
    p = tmp_path / "crash.flac"
    code = ("import sys, os, numpy as np; sys.path.insert(0, sys.argv[1]);"
            "from ecoscribe.flacw import FlacWriter; w = FlacWriter(sys.argv[2]);"
            "[w.write(np.full(1600, 0.2, np.float32)) for _ in range(50)]; w.flush(); os._exit(0)")
    subprocess.run([sys.executable, "-c", code, str(app), str(p)], check=True)
    back = decode_audio(str(p), sampling_rate=SR)
    assert len(back) / SR >= 4.5  # 5 s written, at most the encoder's last frame lost
