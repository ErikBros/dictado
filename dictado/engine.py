"""faster-whisper wrapper: load once, keep warm, transcribe with a language allow-list.

If the GPU dies after startup (sleep/resume, driver reset, OOM from another
app) the model is reloaded, falling back to CPU if CUDA stays gone, and the
same audio is retried: the utterance is not lost.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

from .choose import pick_language
from .config import TextCfg, WhisperCfg
from .text import clean, is_hallucination, vocab_prompt

log = logging.getLogger(__name__)
_GPU_ERRORS = ("cuda", "cublas", "cudnn", "out of memory", "metal")  # metal: the Mac GPU


@dataclass
class Result:
    text: str
    lang: str
    speech_s: float
    ms: int


def _is_gpu_error(e: BaseException) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in _GPU_ERRORS)


def _default_factory(name, device, compute_type, local_files_only=False):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device=device, compute_type=compute_type, local_files_only=local_files_only)


if sys.platform == "darwin":  # mlx on the Apple GPU behind the same interface (dictado/platform/macos/mlx_engine.py)
    from .platform.macos.mlx_engine import factory as _default_factory  # noqa: F811


from .languages import needs_big_model


def dictation_model(cfg: WhisperCfg) -> tuple[str, str]:
    """(model, compute_type) for the dictation languages: any language turbo handles poorly
    (Swedish, Greek, most added ones) runs everything on large-v3 (well under a second, about
    twice turbo's time)."""
    if needs_big_model(cfg.languages):
        return cfg.sv_model, cfg.sv_compute_type
    return cfg.model, cfg.compute_type


class Engine:
    def __init__(self, cfg: WhisperCfg, text_cfg: TextCfg, model_factory=_default_factory, resolve=None):
        self.cfg = cfg
        self.text_cfg = text_cfg
        self.factory = model_factory
        if resolve is None:
            from .models import ensure_local
            # the default factory loads real WhisperModels: give it a plain-file copy
            # (on the Mac the factory finds its own mlx weights: no CT2 mirror)
            resolve = ensure_local if model_factory is _default_factory and sys.platform != "darwin" else (lambda name: name)
        self.resolve = resolve
        self.model = None
        self.device = cfg.device
        self.fallback_reason: str | None = None
        self._load_lock = threading.Lock()
        # Never free a model: destroying one after a long (>30 s) transcription throws
        # an uncaught C++ exception in CTranslate2 and aborts the process (2026-10-02).
        self._retired: list = []

    def load(self) -> None:
        with self._load_lock:
            if self.model is not None:
                self._retired.append(self.model)
                self.model = None
            try:
                name, compute_type = dictation_model(self.cfg)
                self.model = self._make(name, self.cfg.device, compute_type)
                self.device = self.cfg.device
                self.fallback_reason = None
                self._warmup()
            except Exception as e:  # CUDA missing/OOM: degrade instead of dying
                self.fallback_reason = f"{type(e).__name__}: {e}"
                log.error("whisper on %s failed (%s); falling back to small/cpu", self.cfg.device, self.fallback_reason)
                self.model = self._make("small", "cpu", "int8")
                self.device = "cpu"
                self._warmup()

    def _make(self, name, device, compute_type):
        path = str(self.resolve(name))  # local plain-file copy; downloads only if never fetched
        return self.factory(path, device, compute_type, local_files_only=True)

    def _warmup(self) -> None:
        # Exercise the real decode path (beam search) with and without VAD so the
        # first dictation is as fast as the rest (VAD's Silero model loads lazily).
        noise = (np.random.default_rng(0).normal(0, 0.05, 16000 * 3)).astype(np.float32)
        for vad in (False, True):
            self.model.detect_language(noise, vad_filter=vad)
            list(self.model.transcribe(noise, language=self.cfg.languages[0], beam_size=self.cfg.beam_size,
                                       vad_filter=vad, without_timestamps=True,
                                       condition_on_previous_text=False)[0])

    def transcribe(self, audio: np.ndarray, words=None, lang: str | None = None, prefer: str | None = None) -> Result:
        """`words`: extra names for this dictation only (from the screen), after Your words."""
        t0 = time.perf_counter()
        audio = np.asarray(audio, dtype=np.float32)
        try:
            text, lang, speech_s = self._run(audio, words, lang, prefer)
        except Exception as e:
            if not _is_gpu_error(e):
                raise
            log.error("whisper failed at runtime (%s: %s); reloading and retrying", type(e).__name__, e)
            self.load()
            text, lang, speech_s = self._run(audio, words, lang, prefer)
        return Result(text=text, lang=lang, speech_s=speech_s, ms=int((time.perf_counter() - t0) * 1000))

    def _run(self, audio: np.ndarray, words=None, forced: str | None = None, prefer: str | None = None):
        if forced:
            lang = forced  # the user chose this dictation's language (dictation key + L)
        elif len(self.cfg.languages) == 1:
            lang = self.cfg.languages[0]  # nothing to choose: skip the extra encoder pass
        else:
            try:
                _, _, probs = self.model.detect_language(audio, vad_filter=True)
                lang = pick_language(probs, self.cfg.languages, prefer)
            except Exception as e:
                if _is_gpu_error(e):
                    raise
                lang = self.cfg.languages[0]  # no speech for detection to look at
        segments, info = self.model.transcribe(
            audio, language=lang, beam_size=self.cfg.beam_size, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
            without_timestamps=True, initial_prompt=vocab_prompt([*self.text_cfg.vocabulary, *(words or [])]))
        segments = list(segments)
        raw = "".join(s.text for s in segments).strip()
        speech_s = float(getattr(info, "duration_after_vad", info.duration))
        no_speech = max((getattr(s, "no_speech_prob", 0.0) for s in segments), default=1.0)
        if is_hallucination(raw, speech_s, no_speech):
            return "", lang, speech_s
        return clean(raw, self.text_cfg.strip_fillers, self.text_cfg.append_space), lang, speech_s
