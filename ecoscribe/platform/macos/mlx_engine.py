"""Whisper on the Apple GPU (mlx-whisper) behind faster-whisper's WhisperModel interface (uat.3).

engine.py, transcribe.py and meeting.py call `model.transcribe(audio, language=..., vad_filter=...,
initial_prompt=...) -> (segments, info)` and `model.detect_language(audio) -> (lang, prob, probs)`.
This adapter gives them exactly that on top of mlx-whisper, so none of them changes:

- VAD is faster-whisper's own Silero (CPU, ONNX): speech is cut out, transcribed, and segment times
  are mapped back to the original audio, as faster-whisper does with vad_filter=True.
- Greedy decoding: mlx-whisper has no beam search. Measured on the Mac (spike/report-mac.md):
  same WER as the Windows beam-5 runs on every scored clip.
- Models map from the names in config/routes to mlx-community conversions. A route with no mlx
  conversion (KB-Whisper) or the CPU fallback step runs faster-whisper on the CPU instead.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

log = logging.getLogger(__name__)
SR = 16000

MLX_REPOS = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "deepdml/faster-whisper-large-v3-turbo-ct2": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "Systran/faster-whisper-large-v3": "mlx-community/whisper-large-v3-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
}
# MLX GPU streams belong to the thread that made them ("There is no Stream(gpu, 1) in current thread"):
# a model loaded on one thread can't run on another, and meetings transcribe from a worker thread.
# So every MLX call (load, encode, decode) runs on this one thread, whoever asks. That also serializes
# them, which mlx-whisper's one-model class attribute needs anyway.
_MLX = None
_MLX_LOCK = threading.Lock()


def on_mlx(fn, *args, **kw):
    global _MLX
    with _MLX_LOCK:
        if _MLX is None:
            from concurrent.futures import ThreadPoolExecutor
            _MLX = ThreadPoolExecutor(1, thread_name_prefix="ecoscribe-mlx")
    if threading.current_thread().name.startswith("ecoscribe-mlx"):
        return fn(*args, **kw)
    return _MLX.submit(fn, *args, **kw).result()


def mlx_repo(name: str) -> str | None:
    """The mlx conversion for a config/route model name; a repo id that is already mlx passes."""
    if name in MLX_REPOS:
        return MLX_REPOS[name]
    if name.startswith("mlx-community/"):
        return name
    return None


def ensure_mlx(repo: str, local_files_only: bool = False) -> str:
    """Local folder with the mlx weights: the HF cache, downloading once if allowed (and needed)."""
    from huggingface_hub import snapshot_download
    try:
        return snapshot_download(repo, local_files_only=True)
    except Exception:
        if local_files_only:
            log.info("mlx model %s not cached yet, downloading", repo)
        return snapshot_download(repo)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    words: list | None = None


@dataclass
class Word:
    """faster-whisper's Word shape: what Engine.word_confidence reads (dictado-9jc.6)."""
    start: float
    end: float
    word: str
    probability: float


@dataclass
class Info:
    language: str
    language_probability: float
    duration: float
    duration_after_vad: float
    all_language_probs: list = field(default_factory=list)


class MlxWhisperModel:
    device = "mlx"

    def __init__(self, path: str, dtype: str = "float16"):
        import mlx.core as mx
        from mlx_whisper.load_models import load_model
        self.path = path
        self.fp16 = dtype != "float32"
        self.dtype = mx.float16 if self.fp16 else mx.float32
        t = time.monotonic()
        self.model = on_mlx(load_model, path, dtype=self.dtype)
        log.info("mlx model %s loaded in %.1f s", path, time.monotonic() - t)

    # ---------- faster-whisper's interface ----------
    def detect_language(self, audio, vad_filter: bool = False, vad_parameters=None, language_detection_segments=1,
                        language_detection_threshold=0.5):
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
        audio = np.asarray(audio, np.float32)
        if vad_filter:  # the dictation's own VAD settings, so detection and transcription cut the same samples
            speech, _ = _speech_only(audio, vad_parameters or {"min_silence_duration_ms": 500})
            audio = speech if len(speech) else audio  # no speech: look at all of it, like faster-whisper
        _, probs = on_mlx(lambda: self.model.detect_language(self._features(audio)))
        probs = probs[0] if isinstance(probs, list) else probs  # one clip in a batch of one
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[0][0], float(ranked[0][1]), [(k, float(v)) for k, v in ranked]

    def detect_language_piece(self, audio):
        """detect_language on a short piece without padding it to 30 s (dictado-1tw on the Mac): the
        encoder runs on the piece's own frames (its first n positions), the same trick faster-whisper's
        quick path uses on Windows. Returns what detect_language returns."""
        return on_mlx(self._detect_piece, np.asarray(audio, np.float32))

    def _detect_piece(self, audio):
        import mlx.core as mx
        import mlx.nn as nn
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram
        from mlx_whisper.tokenizer import get_tokenizer
        m = self.model
        mel = log_mel_spectrogram(audio[:N_SAMPLES], n_mels=m.dims.n_mels)  # (frames, n_mels), no padding
        n = min(N_FRAMES, max(200, mel.shape[0] + mel.shape[0] % 2))  # even, like faster-whisper's 200-frame floor
        mel = mx.pad(mel[:n], [(0, n - min(n, mel.shape[0])), (0, 0)]).astype(self.dtype)
        enc = m.encoder
        x = nn.gelu(enc.conv1(mel[None]))
        x = nn.gelu(enc.conv2(x))
        x = x + enc._positional_embedding[: x.shape[1]]
        for block in enc.blocks:
            x, _, _ = block(x)
        x = enc.ln_post(x)
        tok = get_tokenizer(m.is_multilingual, num_languages=m.num_languages)
        logits = m.logits(mx.array([[tok.sot]]), x)[:, 0]
        mask = mx.full(logits.shape[-1], -mx.inf, dtype=mx.float32)
        mask[list(tok.all_language_tokens)] = 0.0
        p = np.array(mx.softmax(logits.astype(mx.float32) + mask, axis=-1))[0]
        ranked = sorted(((c, float(p[j])) for j, c in zip(tok.all_language_tokens, tok.all_language_codes)),
                        key=lambda kv: kv[1], reverse=True)
        return ranked[0][0], ranked[0][1], ranked

    def transcribe(self, audio, language: str | None = None, beam_size: int = 5, vad_filter: bool = False,
                   vad_parameters=None, condition_on_previous_text: bool = True, without_timestamps: bool = False,
                   initial_prompt: str | None = None, word_timestamps: bool = False, **_ignored):
        audio = np.asarray(audio, np.float32)
        duration = len(audio) / SR
        chunks = None
        if vad_filter:
            audio, chunks = _speech_only(audio, vad_parameters)
        after = len(audio) / SR
        if not len(audio):
            return iter(()), Info(language or "en", 1.0, duration, 0.0)
        lang, prob = language, 1.0
        if lang is None:
            lang, prob, _ = self.detect_language(audio)
        if word_timestamps and len(audio) <= 30 * SR:  # dictado-9jc.6: the dictation's own tokens, aligned
            seg = self._aligned(audio, lang, initial_prompt)
            if seg is not None:
                return iter([seg]), Info(lang, prob, duration, after)
        if without_timestamps and len(audio) <= 30 * SR:  # a dictation: one encoder pass, shared with detection
            seg = self._short(audio, lang, initial_prompt)
            self._fkey = None  # shared by this dictation's detection only, never by the next clip
            if seg is not None:
                return iter([seg]), Info(lang, prob, duration, after)
        raw = self._run(audio, lang, condition_on_previous_text, initial_prompt, without_timestamps, word_timestamps)
        segs = [Segment(start=float(s["start"]), end=float(s["end"]), text=s["text"],
                        no_speech_prob=float(s.get("no_speech_prob", 0.0)), avg_logprob=float(s.get("avg_logprob", 0.0)),
                        words=[Word(float(w["start"]), float(w["end"]), w["word"], float(w.get("probability", 0.0)))
                               for w in s.get("words") or []] if word_timestamps else None)
                for s in raw["segments"]]
        if chunks:
            from faster_whisper.vad import SpeechTimestampsMap
            ts = SpeechTimestampsMap(chunks, SR)
            for s in segs:
                s.start = ts.get_original_time(s.start)
                s.end = ts.get_original_time(s.end, is_end=True)
                for w in s.words or ():
                    w.start = ts.get_original_time(w.start)
                    w.end = ts.get_original_time(w.end, is_end=True)
        return iter(segs), Info(lang, prob, duration, after)

    def _features(self, audio: np.ndarray):
        """Encoder output for the first 30 s of `audio`, cached for the last clip: a dictation with two
        allowed languages detects and transcribes the same samples, and pays for one encoder pass."""
        import hashlib

        import mlx.core as mx
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
        audio = audio[:N_SAMPLES]
        key = (len(audio), hashlib.blake2b(audio.tobytes(), digest_size=16).digest())
        if getattr(self, "_fkey", None) != key:
            mel = log_mel_spectrogram(audio, n_mels=self.model.dims.n_mels, padding=N_SAMPLES)
            mel = pad_or_trim(mel, N_FRAMES, axis=-2).astype(self.dtype)
            feats = self.model.encoder(mel[None])
            mx.eval(feats)
            self._fkey, self._feats = key, feats
        return self._feats

    def _short(self, audio: np.ndarray, lang: str, prompt: str | None):
        """One greedy decode over the cached features; None when it looks off (repetitive or unsure), and the
        full path with its temperature fallback takes over, as faster-whisper would."""
        from mlx_whisper.decoding import DecodingOptions, decode
        res = on_mlx(lambda: decode(self.model, self._features(audio)[0],
                                    DecodingOptions(language=lang, without_timestamps=True, fp16=self.fp16,
                                                    temperature=0.0, prompt=prompt or None)))
        if res.compression_ratio > 2.4 or res.avg_logprob < -1.0:
            return None
        self._last_tokens = (self._clip_key(audio, lang, prompt), list(res.tokens))  # for the word pass after the paste
        return Segment(start=0.0, end=round(len(audio) / SR, 2), text=res.text, no_speech_prob=float(res.no_speech_prob),
                       avg_logprob=float(res.avg_logprob))

    @staticmethod
    def _clip_key(audio: np.ndarray, lang, prompt):
        import hashlib
        return (len(audio), lang, prompt or None, hashlib.blake2b(audio.tobytes(), digest_size=16).digest())

    def _aligned(self, audio: np.ndarray, lang: str, prompt: str | None):
        """Word timings + probabilities for the clip the last dictation decoded (dictado-9jc.6): its tokens
        are aligned to the audio in one forward pass instead of a second full transcription (~1.2-1.8 s).
        None when the clip isn't the one decoded last (the caller then transcribes with word timestamps)."""
        last = getattr(self, "_last_tokens", None)
        if not last or last[0] != self._clip_key(audio, lang, prompt):
            return None
        tokens = last[1]

        def run():
            from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
            from mlx_whisper.timing import find_alignment
            from mlx_whisper.tokenizer import get_tokenizer
            m = self.model
            tok = get_tokenizer(m.is_multilingual, num_languages=m.num_languages, language=lang, task="transcribe")
            mel = log_mel_spectrogram(audio, n_mels=m.dims.n_mels, padding=N_SAMPLES)
            mel = pad_or_trim(mel, N_FRAMES, axis=-2).astype(self.dtype)
            return find_alignment(m, tok, [t for t in tokens if t < tok.eot], mel, len(audio) // 160)
        timings = on_mlx(run)
        if not timings:
            return None
        from mlx_whisper.timing import merge_punctuations
        merge_punctuations(timings, "\"'“¿([{-", "\"'.。,，!！?？:：”)]}、")  # like the full path: "dog," is one word
        words = [Word(float(w.start), float(w.end), w.word, float(w.probability)) for w in timings if w.word]
        return Segment(start=0.0, end=round(len(audio) / SR, 2), text="".join(w.word for w in words), words=words)

    def _run(self, audio, lang, condition, prompt, without_timestamps, word_timestamps=False):
        import mlx_whisper
        from mlx_whisper.transcribe import ModelHolder
        def run():
            ModelHolder.model, ModelHolder.model_path = self.model, self.path  # use OUR loaded model
            return mlx_whisper.transcribe(audio, path_or_hf_repo=self.path, language=lang, verbose=None,
                                          condition_on_previous_text=condition, initial_prompt=prompt or None,
                                          without_timestamps=without_timestamps, word_timestamps=word_timestamps,
                                          fp16=self.fp16)
        return on_mlx(run)


def _speech_only(audio: np.ndarray, vad_parameters=None):
    """(speech samples glued together, the chunks to map times back), like faster-whisper's vad_filter."""
    from faster_whisper.vad import VadOptions, collect_chunks, get_speech_timestamps
    opts = VadOptions(**vad_parameters) if isinstance(vad_parameters, dict) else (vad_parameters or VadOptions())
    chunks = get_speech_timestamps(audio, opts)
    if not chunks:
        return np.zeros(0, np.float32), []
    parts, _ = collect_chunks(audio, chunks)
    return np.concatenate(parts).astype(np.float32), chunks


def factory(name: str, device: str, compute_type: str, local_files_only: bool = False):
    """WhisperModel(name, device, compute_type) for the Mac: mlx on the GPU when the model has an mlx
    conversion, else faster-whisper on the CPU (KB-Whisper, and the "cpu" fallback step)."""
    import os
    if device != "cpu":
        repo = mlx_repo(name) if not os.path.isdir(name) else name
        if repo is not None:
            return MlxWhisperModel(repo if os.path.isdir(repo) else ensure_mlx(repo, local_files_only),
                                   "float32" if compute_type == "float32" else "float16")
        log.info("no mlx conversion of %s: faster-whisper on the CPU", name)
    from faster_whisper import WhisperModel
    from ... import models
    path = name if os.path.isdir(name) else str(models.ensure_local(name))
    return WhisperModel(path, device="cpu", compute_type="int8")


def steps(cfg) -> list[tuple[str, str]]:
    """Load attempts in order (transcribe.steps on the Mac): the GPU, then the CPU."""
    return [("mlx", "float16"), ("cpu", "int8")]


def info() -> SimpleNamespace:
    import mlx.core as mx
    return SimpleNamespace(device=str(mx.default_device()), mlx=mx.__version__)
