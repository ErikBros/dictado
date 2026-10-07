"""Checks on a finished dictation (2026-10-07: 50 s of Spanish came back as one sentence).

dropout_seconds: digital silence inside the recording (a Bluetooth mic dropping out sends zeros,
real room silence never is exactly zero). too_short: far less text than that much talking.
"""
from __future__ import annotations

import numpy as np

SR = 16000


def dropout_seconds(audio, floor: float = 1e-4, min_run_s: float = 0.2) -> float:
    """Total length of runs of |sample| < floor that last at least min_run_s."""
    a = np.abs(np.asarray(audio, np.float32)) < floor
    if not a.any():
        return 0.0
    edges = np.diff(np.concatenate(([0], a.view(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    runs = ends - starts
    return float(runs[runs >= min_run_s * SR].sum()) / SR


def too_short(text: str, audio_s: float, min_audio_s: float = 15.0, min_chars_per_s: float = 4.0) -> bool:
    """Normal dictation gives 8-12 characters per second of recording; the lost ones gave about 3."""
    return audio_s >= min_audio_s and len(text or "") < min_chars_per_s * audio_s
