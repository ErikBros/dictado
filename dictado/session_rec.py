"""Record a meeting: the mic and the system audio, to three FLACs, in step.

A pump (every 100 ms) reads both sources, writes mic.flac and system.flac as
they come, and writes mix.flac for the span both tracks have reached; that
same mixed span feeds the live chunker. If one source falls more than a second
behind (stream died, device missing) it is padded with silence, so the mix and
the live transcript never stall. The mic gate stays open for the whole session
(the user's mics are muted at volume 0) and is restored once at stop.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .chunker import Chunker
from .flacw import FlacWriter, mix

log = logging.getLogger(__name__)
SR = 16000
PUMP_S = 0.1
MAX_LAG_S = 1.0
FLUSH_EVERY = 10  # pumps (~1 s): what a crash can lose


class MicSource:
    """The Dictado mic (by name, MME, 16 kHz mono), opened for the whole session."""

    def __init__(self, audio_cfg, sd_module=None):
        if sd_module is None:
            import sounddevice as sd_module
        self.cfg, self.sd = audio_cfg, sd_module
        self.device_name = ""
        self._stream = None
        self._lock = threading.Lock()
        self._buf: list[np.ndarray] = []
        self._level = 0.0

    def start(self) -> None:
        from .choose import pick_device
        idx = pick_device(list(self.sd.query_devices()), list(self.sd.query_hostapis()), self.cfg.device, self.cfg.host)
        if idx is not None:
            self.device_name = self.sd.query_devices(idx)["name"]
        else:  # no name asked for (the Mac default) or not found: the system's default input
            try:
                self.device_name = self.sd.query_devices(kind="input")["name"]
            except Exception:
                self.device_name = "Windows default mic"

        def cb(indata, frames, t, status):
            block = np.array(indata[:, 0], np.float32, copy=True)
            self._level = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
            with self._lock:
                self._buf.append(block)
        self._stream = self.sd.InputStream(device=idx, samplerate=SR, channels=1, dtype="float32",
                                           blocksize=1600, callback=cb)
        self._stream.start()
        log.info("meeting mic=%s", self.device_name)

    def stop(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                log.debug("mic close failed", exc_info=True)

    def read(self) -> np.ndarray:
        with self._lock:
            buf, self._buf = self._buf, []
        return np.concatenate(buf) if buf else np.zeros(0, np.float32)

    def level(self) -> float:
        return min(1.0, self._level)


class _Silent:
    device_name = "ninguno"

    def start(self): pass
    def stop(self): pass
    def read(self): return np.zeros(0, np.float32)
    def level(self): return 0.0


class SessionRecorder:
    def __init__(self, session_dir: Path, mic_factory: Callable, loop_factory: Callable, gate=None,
                 on_chunk: Callable[[float, np.ndarray], None] | None = None, threaded: bool = True,
                 chunker: Chunker | None = None):
        self.dir = Path(session_dir)
        self.mic_factory, self.loop_factory = mic_factory, loop_factory
        self.gate, self.on_chunk, self.threaded = gate, on_chunk, threaded
        self.chunker = chunker or Chunker()
        self.warnings: list[str] = []
        self.mic = self.loop = None
        self._pend = {"mic": np.zeros(0, np.float32), "system": np.zeros(0, np.float32)}
        self._w: dict[str, FlacWriter] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._stopped = False
        self._gate_open = False
        self._pumps = 0

    def _source(self, factory, kind: str, warning: str):
        try:
            src = factory()
            src.start()
            return src
        except Exception as e:
            log.warning("%s source failed: %s", kind, e)
            self.warnings.append(warning)
            return _Silent()

    def start(self) -> None:
        audio = self.dir / "audio"
        audio.mkdir(parents=True, exist_ok=True)
        self._w = {k: FlacWriter(audio / f"{k}.flac") for k in ("mic", "system", "mix")}
        if self.gate:
            self._gate_open = True
            self.gate.open()
        self.mic = self._source(self.mic_factory, "mic", "No mic: recording only the computer's audio")
        self.loop = self._source(self.loop_factory, "system", "No computer audio: recording only the mic")
        if self.threaded:
            self._thread = threading.Thread(target=self._run, name="dictado-session-rec", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        nxt = time.monotonic()
        while not self._stop.is_set():
            nxt += PUMP_S
            try:
                self.pump()
            except Exception:
                log.exception("session pump failed")
            self._stop.wait(max(0.0, nxt - time.monotonic()))

    def pump(self, final: bool = False) -> None:
        with self._lock:
            for k, src in (("mic", self.mic), ("system", self.loop)):
                block = src.read()
                if len(block):
                    self._w[k].write(block)
                    self._pend[k] = np.concatenate([self._pend[k], block])
            m, y = self._pend["mic"], self._pend["system"]
            lag = abs(len(m) - len(y))
            if final or lag > MAX_LAG_S * SR:  # pad the lagging track so the mix keeps moving
                short = "mic" if len(m) < len(y) else "system"
                pad = np.zeros(lag, np.float32)
                self._w[short].write(pad)
                self._pend[short] = np.concatenate([self._pend[short], pad])
                m, y = self._pend["mic"], self._pend["system"]
            n = min(len(m), len(y))
            if not n:
                return
            mixed = mix(m[:n], y[:n])
            self._pend["mic"], self._pend["system"] = m[n:], y[n:]
            self._w["mix"].write(mixed)
            self._pumps += 1
            if self._pumps % FLUSH_EVERY == 0:
                for w in self._w.values():
                    w.flush()
            ready = self.chunker.push(mixed)  # under the lock: the final pump in stop() may race the thread
        for t0, audio in ready:
            self._emit(t0, audio)

    def _emit(self, t0, audio) -> None:
        if self.on_chunk:
            try:
                self.on_chunk(t0, audio)
            except Exception:
                log.exception("on_chunk failed")

    def levels(self) -> tuple[float, float]:
        return (self.mic.level() if self.mic else 0.0, self.loop.level() if self.loop else 0.0)

    def stop(self) -> dict:
        if self._stopped:
            return self._durations()
        self._stopped = True
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self.pump(final=True)
        except Exception:
            log.exception("final pump failed")
        with self._lock:
            rest = self.chunker.flush()
        if rest:
            self._emit(*rest)
        for src in (self.mic, self.loop):
            try:
                src and src.stop()
            except Exception:
                log.exception("source stop failed")
        for w in self._w.values():
            w.close()
        if self.gate and self._gate_open:
            self._gate_open = False
            self.gate.restore()
        return self._durations()

    def _durations(self) -> dict:
        return {k: round(w.samples / SR, 2) for k, w in self._w.items()}
