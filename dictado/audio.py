"""Microphone capture.

By default the stream is opened at the tap and closed after (keep_open=False),
so Windows doesn't show "app is using your microphone" all day. With
keep_open=True it stays open and a short pre-roll is buffered. The mic is
chosen by NAME (indexes drift when devices come and go) and the stream is
reopened automatically if it dies while needed.
"""
from __future__ import annotations

import collections
import logging
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .choose import pick_device
from .config import AudioCfg

log = logging.getLogger(__name__)
SR = 16000


class Recorder:
    def __init__(self, cfg: AudioCfg, sd_module=None, on_warning: Callable[[str], None] = lambda m: None,
                 monitor_s: float = 2.0, retry_s: float = 3.0):
        if sd_module is None:
            import sounddevice as sd_module
        self.cfg = cfg
        self.sd = sd_module
        self.on_warning = on_warning
        self.monitor_s = monitor_s
        self.retry_s = retry_s
        self.device_name = ""
        self.fell_back = False
        self.recording = False
        self.last_stream_ok = True  # was a stream open when the last recording ended?
        self._stream = None
        self._gen = 0  # bumps whenever a stream is retired; stale callbacks are dropped
        self._slock = threading.RLock()  # owns stream open/close/replace
        self._lock = threading.Lock()  # owns the audio buffers
        self._ring: collections.deque = collections.deque()
        self._ring_n = 0
        self._chunks: list[np.ndarray] = []
        self._level = 0.0
        self._preroll_n = int(cfg.preroll_s * cfg.samplerate)
        self._stop = threading.Event()
        self._warned_open = False
        self._monitor = None

    # ---------- stream lifecycle ----------
    def _resolve(self):
        devices = list(self.sd.query_devices())
        hostapis = list(self.sd.query_hostapis())
        idx = pick_device(devices, hostapis, self.cfg.device, self.cfg.host)
        if idx is None and not (self.cfg.device or "").strip():  # no mic chosen: the default, by design (no warning)
            self.fell_back = False
            if sys.platform != "darwin":
                return None, "Windows default mic"
            try:
                return None, self.sd.query_devices(kind="input")["name"]
            except Exception:
                return None, "System default"
        if idx is None:
            if not self.fell_back:
                self.on_warning(f"Mic '{self.cfg.device}' not found, using the default")
            self.fell_back = True
            return None, "predeterminado"
        self.fell_back = False
        return idx, devices[idx]["name"]

    def _open_stream(self) -> bool:
        """Open a stream unless a live one exists. Caller holds _slock."""
        if self._stream is not None and getattr(self._stream, "active", True):
            return True
        self._retire_stream(background=True)  # a dead stream's stop() can hang; don't do it under _slock
        gen = self._gen
        try:
            idx, name = self._resolve()
            stream = self.sd.InputStream(device=idx, samplerate=self.cfg.samplerate, channels=1,
                                         dtype="float32", blocksize=480,
                                         callback=lambda *a: self._callback(gen, *a))
            stream.start()
        except Exception as e:
            if not self._warned_open:
                self.on_warning("Can't open the mic, retrying")
                self._warned_open = True
            log.warning("mic open failed: %s", e)
            return False
        self._stream = stream
        self.device_name = name
        self._warned_open = False
        log.info("audio device=%s fell_back=%s", name, self.fell_back)
        return True

    def _retire_stream(self, background: bool = False) -> None:
        """Detach the current stream; its late callbacks are ignored. Caller holds _slock."""
        s, self._stream = self._stream, None
        self._gen += 1
        if s is None:
            return

        def shut():
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        if background:
            threading.Thread(target=shut, daemon=True).start()
        else:
            shut()

    def _needed(self) -> bool:
        return self.cfg.keep_open or self.recording

    def open(self) -> None:
        with self._slock:
            if self.cfg.keep_open:
                self._open_stream()
            else:  # look the mic up now so a missing one is reported at startup, not at the first tap
                try:
                    _, self.device_name = self._resolve()
                except Exception:
                    log.exception("mic lookup failed")
        self._monitor = threading.Thread(target=self._watch, name="dictado-mic", daemon=True)
        self._monitor.start()

    def close(self) -> None:
        self._stop.set()
        with self._slock:
            self._retire_stream()

    def _watch(self) -> None:
        while not self._stop.wait(self.retry_s if (self._needed() and self._stream is None) else self.monitor_s):
            with self._slock:  # re-check under the lock: begin()/end() may have just run
                if not self._needed():
                    continue
                s = self._stream
                if s is not None and not getattr(s, "active", True):
                    log.warning("mic stream died, reopening")
                self._open_stream()

    def stream_open(self) -> bool:
        return self._stream is not None

    # ---------- audio thread ----------
    def _callback(self, gen, indata, frames, time_info, status) -> None:
        if gen != self._gen:
            return  # a retired stream still draining
        block = np.array(indata[:, 0], dtype=np.float32, copy=True)
        self._level = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
        with self._lock:
            if self.recording:
                self._chunks.append(block)
            self._ring.append(block)
            self._ring_n += len(block)
            while self._ring and self._ring_n - len(self._ring[0]) >= self._preroll_n:
                self._ring_n -= len(self._ring.popleft())

    # ---------- public API ----------
    def begin(self) -> None:
        with self._slock:
            if not self.cfg.keep_open:
                with self._lock:
                    self._ring.clear()
                    self._ring_n = 0
                self.recording = True  # so the monitor retries if the open fails
                self._open_stream()
            with self._lock:
                pre = np.concatenate(self._ring) if self._ring else np.zeros(0, np.float32)
                self._chunks = [pre[-self._preroll_n:]] if self._preroll_n else []
                self.recording = True

    def _finish(self) -> list:
        with self._slock:
            with self._lock:
                self.recording = False
                chunks, self._chunks = self._chunks, []
            self.last_stream_ok = self._stream is not None
            if not self.cfg.keep_open:
                self._retire_stream(background=True)
        return chunks

    def chunks_since(self, i: int):
        """(chunks recorded after the first i, new count): the spool's flush (t0u.37)."""
        with self._lock:
            return list(self._chunks[i:]), len(self._chunks)

    def end(self) -> np.ndarray:
        chunks = self._finish()
        return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)

    def abort(self) -> None:
        self._finish()

    def level(self) -> float:
        return min(1.0, self._level)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        assert f.getframerate() == SR and f.getnchannels() == 1 and f.getsampwidth() == 2, path
        data = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
    return (data.astype(np.float32) / 32768.0)


class FileSource:
    """Stands in for the mic in tests: 'hears' a wav file in real time from begin()."""

    def __init__(self, path):
        self.path = Path(path)
        self.device_name = f"file:{self.path.name}"
        self.fell_back = False
        self.recording = False
        self._clip = np.zeros(0, np.float32)
        self._t0 = 0.0

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def _current(self) -> Path:
        if self.path.is_dir():
            return self.path / (self.path / "next_clip.txt").read_text(encoding="utf-8").strip()
        return self.path

    def begin(self) -> None:
        self._clip = read_wav(self._current())
        self._t0 = time.monotonic()
        self.recording = True

    def end(self) -> np.ndarray:
        self.recording = False
        n = int((time.monotonic() - self._t0) * SR)
        return self._clip[:n].copy()

    def abort(self) -> None:
        self.recording = False

    def level(self) -> float:
        return 0.3 if self.recording else 0.0
