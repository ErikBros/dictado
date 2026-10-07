"""Build a long test recording (default 60 min) for the worker's long-file test.

Loops the three meeting fixtures with 2-8 s random silences until N minutes and
writes 16 kHz mono wav. Not committed: lands in %LOCALAPPDATA%\\ecoscribe\\bench\\.

    python tools/make_long.py --minutes 60 [--out PATH]
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
FIX = APP / "tests" / "fixtures"
CLIPS = ["sv_meeting", "el_podcast", "en_meeting"]
SR = 16000


def default_out() -> Path:
    from ecoscribe import paths
    return paths.data_dir() / "bench" / "long_60min.wav"


def build(minutes: float, out: Path, seed: int = 0) -> Path:
    from faster_whisper import decode_audio
    clips = [(decode_audio(str(FIX / f"{c}.flac"), sampling_rate=SR) * 32767).astype("<i2") for c in CLIPS]
    rng = np.random.default_rng(seed)
    target = int(minutes * 60 * SR)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with wave.open(str(out), "wb") as w:  # streamed: never holds the whole hour in memory
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        i = 0
        while written < target:
            for chunk in (clips[i % len(clips)], np.zeros(int(rng.uniform(2, 8) * SR), "<i2")):
                chunk = chunk[: target - written]
                w.writeframes(chunk.tobytes())
                written += len(chunk)
            i += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    out = build(a.minutes, a.out or default_out())
    print(out, f"{out.stat().st_size / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
