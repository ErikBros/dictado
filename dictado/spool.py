"""What you are saying, on disk while you say it (t0u.37).

A crash used to lose the dictation in progress: the audio only lived in memory. Now the
recording is appended to spool/rec-<n>.f32 (raw float32, 16 kHz mono: no header to
break if the process dies mid-write) every half second, rewritten whole at the stop, and
deleted once the text is delivered. Whatever is left at the next start was cut off by a
crash: it is transcribed into History as "recovered" (never pasted: the cursor is
somewhere else by now).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
SR = 16000
FLUSH_S = 0.5
MIN_S = 0.5  # less than this isn't worth recovering


class Spool:
    def __init__(self, folder: Path):
        self.dir = Path(folder)
        self.cur: Path | None = None
        self._n = 0  # chunks already written
        self._stop: threading.Event | None = None

    def begin(self, chunks_since) -> None:
        """New recording. chunks_since(i) -> (new chunks, new i), read every FLUSH_S."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cur = self.dir / f"rec-{time.time_ns()}.f32"
        self.cur.write_bytes(b"")
        self._n = 0
        stop = self._stop = threading.Event()
        path = self.cur

        def flush():
            while not stop.wait(FLUSH_S):
                try:
                    new, self._n = chunks_since(self._n)
                    if new:
                        with open(path, "ab") as f:
                            for c in new:
                                f.write(np.asarray(c, np.float32).tobytes())
                except Exception:
                    log.debug("spool flush failed", exc_info=True)
        threading.Thread(target=flush, name="dictado-spool", daemon=True).start()

    def _halt(self) -> Path | None:
        if self._stop:
            self._stop.set()
            self._stop = None
        p, self.cur = self.cur, None
        return p

    def finish(self, audio: np.ndarray) -> Path | None:
        """The stop: the whole recording, kept until done(path)."""
        p = self._halt()
        if p is None:
            return None
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(np.asarray(audio, np.float32).tobytes())
        os.replace(tmp, p)
        return p

    def discard(self) -> None:
        p = self._halt()
        if p is not None:
            p.unlink(missing_ok=True)

    @staticmethod
    def done(p: Path | None) -> None:
        if p is not None:
            Path(p).unlink(missing_ok=True)

    def leftovers(self) -> list[Path]:
        if not self.dir.exists():
            return []
        return sorted(p for p in self.dir.glob("rec-*.f32") if p != self.cur)

    @staticmethod
    def read(p: Path) -> np.ndarray:
        data = Path(p).read_bytes()
        return np.frombuffer(data[: len(data) // 4 * 4], dtype=np.float32).copy()
