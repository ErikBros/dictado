"""Yo / Otros labels from which source carries the energy of each segment.

Not diarization: in a call on this PC, the user's voice is loud on the mic track
and the others are on the system (loopback) track. Their voice can leak into
the mic from the speakers, but it is weaker there than on the system track,
so comparing the two is enough for "me vs them".
"""
from __future__ import annotations

import numpy as np

SR = 16000


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def label(segments: list[dict], mic: np.ndarray, system: np.ndarray, sr: int = SR) -> list[dict]:
    n = max(len(mic), len(system))
    for s in segments:
        a, b = int(s["t0"] * sr), int(s["t1"] * sr)
        if a >= n or b <= a:
            continue
        m, y = _rms(mic[a:b]), _rms(system[a:b])
        if m <= 1e-6 and y <= 1e-6:
            continue
        s["speaker"] = "Me" if m > y else "Others"
    return segments
