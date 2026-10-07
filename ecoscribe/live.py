"""Live transcript while you dictate (dictado-live): the pill shows what it has heard so far.

Every `every_s` a quick pass (beam 1, no screen names) runs on the last `window_s` of the recording
and the pill shows the tail of it. On a slow GPU the gap grows to `slow_x` times the last pass, so the
model is mostly free when the stop comes (the Mac session measured 1.9 s passes with large-v3). Only a preview: the full, careful transcription still runs at the
stop and is what gets pasted. A pass never waits: if the model is loading or busy it is skipped, so
the preview can never delay the paste.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)
SR = 16000


def tail(text: str, max_chars: int = 100) -> str:
    """The end of `text`, cut at a word boundary with a leading "…" when it doesn't fit."""
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    cut = text[-(max_chars - 1):]
    sp = cut.find(" ")
    if 0 <= sp < 20:
        cut = cut[sp + 1:]
    return "…" + cut


class LivePreview:
    """One per recording. chunks_since(i) -> (new chunks, new i), like the spool's;
    preview(audio) -> text, or None when it was skipped; show(text) updates the pill."""

    def __init__(self, chunks_since: Callable, preview: Callable[[np.ndarray], str | None],
                 show: Callable[[str], None], every_s: float = 2.0, window_s: float = 15.0,
                 min_s: float = 1.5, clock=time.monotonic, slow_x: float = 2.5):
        self.chunks_since, self.preview, self.show = chunks_since, preview, show
        self.every_s, self.window_s, self.min_s, self.clock = every_s, window_s, min_s, clock
        self.slow_x = slow_x
        self.last_pass_s = 0.0
        self._chunks: list[np.ndarray] = []
        self._i = 0
        self._stop = threading.Event()
        self._t: threading.Thread | None = None
        self.passes = 0
        self.last = ""

    def start(self) -> "LivePreview":
        self._t = threading.Thread(target=self._loop, name="ecoscribe-live", daemon=True)
        self._t.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def audio(self) -> np.ndarray:
        new, self._i = self.chunks_since(self._i)
        self._chunks.extend(new)
        if not self._chunks:
            return np.zeros(0, np.float32)
        a = np.concatenate(self._chunks).astype(np.float32)
        return a[-int(self.window_s * SR):]

    def step(self) -> bool:
        """One pass; True if the pill got new text."""
        a = self.audio()
        if len(a) < self.min_s * SR or self._stop.is_set():
            return False
        t0 = self.clock()
        text = self.preview(a)
        self.last_pass_s = self.clock() - t0
        if text is None or self._stop.is_set():
            return False
        self.passes += 1
        t = tail(text)
        if not t or t == self.last:
            return False
        self.last = t
        self.show(t)
        return True

    def gap(self) -> float:
        """Seconds until the next pass: every_s, or longer after a slow pass."""
        return max(self.every_s, self.slow_x * self.last_pass_s)

    def _loop(self) -> None:
        while not self._stop.wait(self.gap()):
            try:
                self.step()
            except Exception:
                log.exception("live preview pass failed")
                return
