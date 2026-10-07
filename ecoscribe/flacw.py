"""Streaming 16 kHz mono FLAC writer (PyAV) and the mic + system mixer.

Meetings are written as they happen. libav buffers its output, so the file is
written through our own file object with a small buffer, and flush() pushes it to
disk: a hard-killed worker keeps everything up to the last flush (measured: 4.97
of 5 s). FLAC is lossless and about 1 MB per minute here.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 16000


class FlacWriter:
    def __init__(self, path: Path, sr: int = SR):
        import av
        self.path, self.sr, self.samples = Path(path), sr, 0
        self._av = av
        self._f = open(self.path, "wb")
        self._c = av.open(self._f, "w", format="flac", buffer_size=4096)
        self._s = self._c.add_stream("flac", rate=sr, layout="mono")
        self._s.format = "s16"
        self._closed = False

    def write(self, audio: np.ndarray) -> None:
        if self._closed or not len(audio):
            return
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").reshape(1, -1)
        frame = self._av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = self.sr
        frame.pts = self.samples
        for p in self._s.encode(frame):
            self._c.mux(p)
        self.samples += pcm.shape[1]

    def flush(self) -> None:
        if not self._closed:
            self._f.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for p in self._s.encode(None):
            self._c.mux(p)
        self._c.close()
        self._f.close()


def mix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Sum two tracks sample by sample (shorter one padded with silence), clipped to [-1, 1]."""
    n = max(len(a), len(b))
    out = np.zeros(n, np.float32)
    out[: len(a)] += a
    out[: len(b)] += b
    return np.clip(out, -1.0, 1.0)
