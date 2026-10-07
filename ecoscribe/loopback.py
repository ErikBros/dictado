"""System audio: WASAPI loopback of the default output device, as 16 kHz mono.

WASAPI loopback sends no packets while nothing plays, so the stream is placed
on the wall clock: silence comes out as zeros and the system track stays
aligned with the mic. The default output can change mid-meeting (headphones on
or off); check_device() reopens on the new one. PortAudio only sees device
changes after a re-init, so each check uses a fresh PyAudio instance.
Spike pick (stage 1): PyAudioWPatch.
"""
from __future__ import annotations

import collections
import logging
import threading
import time

import numpy as np

log = logging.getLogger(__name__)
SR = 16000
GAP_S = 0.05  # data starting this much after the cursor = a real gap, filled with zeros
FILL_LAG_S = 0.1  # during silence, zeros are emitted up to now - this
IDLE_S = 0.2  # no data for this long = silence


class GapFiller:
    """Puts timestamped blocks on a continuous sample timeline (session time in seconds)."""

    def __init__(self, sr: int = SR):
        self.sr = sr
        self.t0 = 0.0
        self.cursor = 0  # samples placed so far (emitted + buffered)
        self.buf: list[np.ndarray] = []
        self.filled = 0  # zeros emitted ahead of real data, may be overlapped by late data

    def start(self, t0: float) -> None:
        self.t0, self.cursor, self.buf, self.filled = t0, 0, [], 0

    def push(self, block: np.ndarray, t_end: float) -> None:
        if not len(block):
            return
        start = int(round((t_end - self.t0) * self.sr)) - len(block)
        if start - self.cursor >= GAP_S * self.sr:
            self._zeros(start - self.cursor)
        elif start < self.cursor and self.filled:
            cut = min(self.cursor - start, self.filled, len(block))  # late data over our own zeros
            block = block[cut:]
        self.filled = 0
        self.buf.append(block)
        self.cursor += len(block)

    def _zeros(self, n: int) -> None:
        if n > 0:
            self.buf.append(np.zeros(n, np.float32))
            self.cursor += n

    def pull(self, now: float) -> np.ndarray:
        wall = int((now - self.t0) * self.sr)
        if wall - self.cursor > IDLE_S * self.sr:
            n = int((now - self.t0 - FILL_LAG_S) * self.sr) - self.cursor
            self._zeros(n)
            self.filled += max(0, n)
        out = np.concatenate(self.buf).astype(np.float32) if self.buf else np.zeros(0, np.float32)
        self.buf = []
        return out


class Loopback:
    def __init__(self, pa_module=None, clock=time.monotonic, check_s: float | None = 2.0):
        if pa_module is None:
            import pyaudiowpatch as pa_module
        self.pa_mod, self.clock, self.check_s = pa_module, clock, check_s
        self.device_name = ""
        self._pa = self._stream = None
        self._rate = self._ch = 0
        self._q: collections.deque = collections.deque()
        self._gen = 0
        self._lock = threading.Lock()
        self._fill = GapFiller(SR)
        self._resampler = None
        self._level = 0.0
        self._stop = threading.Event()

    # ---------- stream ----------
    def _open(self) -> None:
        pa = self.pa_mod.PyAudio()
        dev = pa.get_default_wasapi_loopback()
        self._rate, self._ch = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])
        gen = self._gen

        def cb(data, frames, info, status):
            if gen == self._gen:
                self._q.append((data, self.clock()))
            return (None, self.pa_mod.paContinue)
        stream = pa.open(format=self.pa_mod.paFloat32, channels=self._ch, rate=self._rate, input=True,
                         input_device_index=dev["index"], frames_per_buffer=1024, stream_callback=cb)
        stream.start_stream()
        self._pa, self._stream, self.device_name = pa, stream, dev["name"]
        self._resampler = None
        log.info("loopback device=%s rate=%d ch=%d", dev["name"], self._rate, self._ch)

    def _close(self) -> None:
        s, pa, self._stream, self._pa = self._stream, self._pa, None, None
        self._gen += 1
        for fn in (getattr(s, "stop_stream", None), getattr(s, "close", None), getattr(pa, "terminate", None)):
            try:
                fn and fn()
            except Exception:
                log.debug("loopback close step failed", exc_info=True)

    def start(self) -> None:
        with self._lock:
            self._fill.start(self.clock())
            self._open()
        if self.check_s:
            threading.Thread(target=self._watch, name="ecoscribe-loopback", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._close()

    def _watch(self) -> None:
        while not self._stop.wait(self.check_s):
            try:
                self.check_device()
            except Exception:
                log.exception("loopback device check failed")

    def check_device(self) -> None:
        pa = self.pa_mod.PyAudio()
        try:
            name = pa.get_default_wasapi_loopback()["name"]
        finally:
            try:
                pa.terminate()
            except Exception:
                pass
        if name == self.device_name:
            return
        log.info("output device changed %s -> %s: reopening loopback", self.device_name, name)
        with self._lock:
            self._close()  # first: no more old-device callbacks can be queued after this
            self._drain()  # still decoded with the old device's rate and channels
            self._open()

    # ---------- data ----------
    def _to_mono16k(self, data: bytes) -> np.ndarray:
        import av
        x = np.frombuffer(data, dtype=np.float32)
        if self._resampler is None:
            self._resampler = av.AudioResampler(format="flt", layout="mono", rate=SR)
        # Fold to mono ourselves (plain average): swresample's stereo downmix is -3 dB per
        # channel, so a full-scale stereo signal would come out 1.41x too loud and clip.
        mono = x.reshape(-1, self._ch).mean(axis=1) if self._ch > 1 else x
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(mono, np.float32).reshape(1, -1),
                                           format="flt", layout="mono")
        frame.sample_rate = self._rate
        out = [f.to_ndarray().reshape(-1) for f in self._resampler.resample(frame)]
        return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)

    def _drain(self) -> None:
        while self._q:
            data, t = self._q.popleft()
            block = self._to_mono16k(data)
            if len(block):
                self._level = float(np.sqrt(np.mean(block * block)))
            self._fill.push(block, t)

    def read(self) -> np.ndarray:
        with self._lock:
            self._drain()
            out = self._fill.pull(self.clock())
        if not len(out) or not out.any():
            self._level *= 0.5
        return out

    def level(self) -> float:
        return min(1.0, self._level)
