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
SR = 16000
# dictado-1tw: a dictation in more than one of your languages. Cut at short pauses, detect each piece
# (the quick way, then the full way for a piece that disagrees), transcribe each run in its language.
MIX_PAUSE_MS = 200  # a breath can switch language
MIX_PAD_MS = 30  # Silero pads 400 ms each side by default: a pause under ~1 s vanished, so a switch after a breath never split (Mac, 2026-10-07: 0/6 at 400 ms, 6/6 at 30 ms for 0.3 s pauses; runs keep a 0.1 s margin)
QUICK_SURE = 0.95  # a quick answer less sure than this is checked the full way: turbo heard a clean 3 s Spanish piece as English at 0.87 (Windows GPU, 2026-10-07; every wrong quick answer in 967 fixture pieces was under 0.95)
MIX_MIN_S = 1.5  # a shorter piece joins the next one: too little to tell the language
MIX_FROM_S = 3.0  # shorter dictations are one language
_GPU_ERRORS = ("cuda", "cublas", "cudnn", "out of memory", "metal")  # metal: the Mac GPU


@dataclass
class Result:
    text: str
    lang: str
    speech_s: float
    ms: int


def _timestamps(words_out) -> dict:
    """A dictation goes without timestamps (fastest); the clarity pass asks for word timestamps, which
    come with each word's probability (dictado-9jc.1)."""
    return {"without_timestamps": True} if words_out is None else {"without_timestamps": False, "word_timestamps": True}


def _collect(segments, words_out) -> None:
    if words_out is not None:
        words_out.extend((w.word.strip(), round(float(w.probability), 3))
                         for s in segments for w in (getattr(s, "words", None) or []))


def _is_gpu_error(e: BaseException) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in _GPU_ERRORS)


def _default_factory(name, device, compute_type, local_files_only=False):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device=device, compute_type=compute_type, local_files_only=local_files_only)


if sys.platform == "darwin":  # mlx on the Apple GPU behind the same interface (ecoscribe/platform/macos/mlx_engine.py)
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
        self._busy = threading.Lock()  # a dictation waits for a preview pass; a preview never waits
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

    def _detect(self, chunk: np.ndarray, langs: list[str], full: bool = False) -> str:
        """The language of one piece among `langs`. The quick way feeds the encoder only the piece
        (faster-whisper: ~25 ms instead of ~160 ms for the 30 s window), used only when sure; full=True pads to 30 s."""
        m = self.model
        if not full and hasattr(m, "feature_extractor") and hasattr(m, "model"):
            from faster_whisper.transcribe import get_ctranslate2_storage
            n_max = m.feature_extractor.nb_max_frames
            f = m.feature_extractor(chunk)[..., :n_max]
            n = min(n_max, max(200, f.shape[-1] + f.shape[-1] % 2))
            f = np.pad(f, ((0, 0), (0, n - f.shape[-1])))
            res = m.model.detect_language(get_ctranslate2_storage(f[None].astype(np.float32)))[0]
            probs = [(tok[2:-2], pr) for tok, pr in res]
        elif not full and hasattr(m, "detect_language_piece"):  # mlx (macOS): the same quick way
            _, _, probs = m.detect_language_piece(chunk)
        else:
            full = True
            _, _, probs = m.detect_language(chunk)
        p = {k: v for k, v in probs if k in langs}
        if not p:
            return langs[0]
        best = max(p, key=p.get)
        if not full and p[best] < QUICK_SURE:
            return self._detect(chunk, langs, full=True)
        return best

    @staticmethod
    def _pieces(audio: np.ndarray) -> list[tuple[float, float]]:
        """Speech cut at pauses of MIX_PAUSE_MS, pieces of at least MIX_MIN_S (Silero VAD)."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        from .transcribe import pieces
        ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=MIX_PAUSE_MS, speech_pad_ms=MIX_PAD_MS))
        return pieces([(t["start"] / SR, t["end"] / SR) for t in ts], gap_s=MIX_PAUSE_MS / 1000, min_s=MIX_MIN_S)

    def language_runs(self, audio: np.ndarray, langs: list[str]) -> list[tuple[float, float, str]] | None:
        """[(start_s, end_s, lang)] runs of one language each, or None when there is one piece.
        A piece that disagrees with the main language is checked again the full way first: the quick
        way once heard a Swedish piece as English (2026-10-07)."""
        ps = self._pieces(audio)
        if len(ps) < 2:
            return None
        got = [(a, b, self._detect(audio[int(a * SR):int(b * SR)], langs)) for a, b in ps]
        dur: dict[str, float] = {}
        for a, b, lang in got:
            dur[lang] = dur.get(lang, 0.0) + b - a
        main = max(dur, key=dur.get)
        runs: list[tuple[float, float, str]] = []
        for a, b, lang in got:
            if lang != main:
                lang = self._detect(audio[int(a * SR):int(b * SR)], langs, full=True)
            if runs and runs[-1][2] == lang:
                runs[-1] = (runs[-1][0], b, lang)
            else:
                runs.append((a, b, lang))
        return runs

    def _run_mixed(self, audio: np.ndarray, runs, words=None, beam_size: int | None = None, words_out=None):
        """Each run in its own language; the text in order. Result lang "es+el" (first seen first)."""
        prompt = vocab_prompt([*self.text_cfg.vocabulary, *(words or [])])
        texts, speech_s, order = [], 0.0, []
        for a, b, lang in runs:
            chunk = audio[max(0, int((a - 0.1) * SR)):int((b + 0.1) * SR)]
            segments, info = self.model.transcribe(
                chunk, language=lang, beam_size=beam_size or self.cfg.beam_size, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
                initial_prompt=prompt, **_timestamps(words_out))
            segments = list(segments)
            _collect(segments, words_out)
            raw = "".join(s.text for s in segments).strip()
            run_s = float(getattr(info, "duration_after_vad", info.duration))
            no_speech = max((getattr(s, "no_speech_prob", 0.0) for s in segments), default=1.0)
            speech_s += run_s
            if raw and not is_hallucination(raw, run_s, no_speech):
                texts.append(raw)
                if lang not in order:
                    order.append(lang)
        log.info("mixed dictation: %s", ", ".join(f"{lang} {b - a:.1f}s" for a, b, lang in runs))
        if not texts:
            return "", runs[0][2], speech_s
        return clean(" ".join(texts), self.text_cfg.strip_fillers, self.text_cfg.append_space), "+".join(order), speech_s

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
        with self._busy:
            try:
                text, lang, speech_s = self._run(audio, words, lang, prefer)
            except Exception as e:
                if not _is_gpu_error(e):
                    raise
                log.error("whisper failed at runtime (%s: %s); reloading and retrying", type(e).__name__, e)
                self.load()
                text, lang, speech_s = self._run(audio, words, lang, prefer)
        return Result(text=text, lang=lang, speech_s=speech_s, ms=int((time.perf_counter() - t0) * 1000))

    def preview(self, audio: np.ndarray, lang: str | None = None, prefer: str | None = None) -> Result | None:
        """The live transcript's quick pass (dictado-live): greedy, no screen names. None when the
        model is loading or a dictation is being transcribed: the preview never makes it wait."""
        if self.model is None or not self._busy.acquire(blocking=False):
            return None
        t0 = time.perf_counter()
        try:
            text, lang, speech_s = self._run(np.asarray(audio, dtype=np.float32), None, lang, prefer, beam_size=1,
                                             mix=False)
        except Exception:
            log.debug("preview pass failed", exc_info=True)
            return None
        finally:
            self._busy.release()
        return Result(text=text, lang=lang, speech_s=speech_s, ms=int((time.perf_counter() - t0) * 1000))

    def word_confidence(self, audio: np.ndarray, lang: str | None = None, words=None) -> list[tuple[str, float]] | None:
        """dictado-9jc.1: [(word, probability)], how sure Whisper was of each word. A second pass with word
        timestamps, asked for after the paste: inline it would add ~80 ms to every dictation. `lang` is
        what the dictation came out in (a mix like "es+en" is split again). None when the model can't
        say."""
        out: list[tuple[str, float]] = []
        with self._busy:
            if self.model is None:
                return None
            self._run(np.asarray(audio, dtype=np.float32), words, None if not lang or "+" in lang else lang,
                      words_out=out)
        return out or None

    def _run(self, audio: np.ndarray, words=None, forced: str | None = None, prefer: str | None = None,
             beam_size: int | None = None, mix: bool = True, words_out=None):
        langs = list(self.cfg.languages)
        if mix and not forced and len(langs) > 1 and len(audio) >= MIX_FROM_S * SR:
            try:
                runs = self.language_runs(audio, langs)
            except Exception as e:
                if _is_gpu_error(e):
                    raise
                log.warning("per-piece language check failed (%s): one language for all", e)
                runs = None
            if runs and len(runs) > 1:
                return self._run_mixed(audio, runs, words, beam_size, words_out)
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
            audio, language=lang, beam_size=beam_size or self.cfg.beam_size, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
            initial_prompt=vocab_prompt([*self.text_cfg.vocabulary, *(words or [])]), **_timestamps(words_out))
        segments = list(segments)
        _collect(segments, words_out)
        raw = "".join(s.text for s in segments).strip()
        speech_s = float(getattr(info, "duration_after_vad", info.duration))
        no_speech = max((getattr(s, "no_speech_prob", 0.0) for s in segments), default=1.0)
        if is_hallucination(raw, speech_s, no_speech):
            return "", lang, speech_s
        return clean(raw, self.text_cfg.strip_fillers, self.text_cfg.append_space), lang, speech_s
