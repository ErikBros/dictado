"""Cut a live audio stream into chunks for the live transcript.

A chunk ends at a pause (pause_s of quiet after at least min_s of audio) or is
forced at max_s, so words are rarely split and the transcript stays a few
seconds behind. Chunks with no sound at all are dropped (time still advances).
"Quiet" is relative: below thresh, or below a third of the recent speech level,
because the gaps in a podcast or a call carry room tone and music above a fixed
floor (2026-10-05: no pause ever counted, chunks waited the full 20 s). max_s is
8 s for the same reason: the final pass redoes the whole recording anyway.
"""
from __future__ import annotations

import numpy as np

SR = 16000


class Chunker:
    def __init__(self, sr: int = SR, min_s: float = 3.0, max_s: float = 8.0, pause_s: float = 0.5,
                 thresh: float = 0.01):
        self.sr, self.min_n, self.max_n = sr, int(min_s * sr), int(max_s * sr)
        self.pause_n, self.thresh = int(pause_s * sr), thresh
        self.t = 0.0  # session time of the start of the buffer
        self._buf: list[np.ndarray] = []
        self._n = 0
        self._quiet_tail = 0
        self._loud = False
        self._speech = 0.0  # running speech level (RMS of loud blocks)

    def _emit(self, n: int):
        audio = np.concatenate(self._buf) if self._buf else np.zeros(0, np.float32)
        head, rest = audio[:n], audio[n:]
        t0, loud = self.t, self._loud or bool(len(head) and np.max(np.abs(head)) >= self.thresh)
        self.t += len(head) / self.sr
        self._buf, self._n = ([rest] if len(rest) else []), len(rest)
        self._loud = bool(len(rest) and np.max(np.abs(rest)) >= self.thresh)
        self._quiet_tail = 0
        return (t0, head) if loud and len(head) else None

    def push(self, block: np.ndarray) -> list:
        out = []
        if not len(block):
            return out
        self._buf.append(np.asarray(block, np.float32))
        self._n += len(block)
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
        if rms < max(self.thresh, self._speech / 3):
            self._quiet_tail += len(block)
        else:
            self._quiet_tail, self._loud = 0, True
            self._speech = rms if not self._speech else 0.9 * self._speech + 0.1 * rms
        while self._n >= self.max_n:
            c = self._emit(self.max_n)
            if c:
                out.append(c)
        if self._n >= self.min_n and self._quiet_tail >= self.pause_n:
            c = self._emit(self._n)
            if c:
                out.append(c)
        return out

    def flush(self):
        return self._emit(self._n) if self._n else None
