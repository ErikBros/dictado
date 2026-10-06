"""The transcription worker: one session folder in, transcript files out.

Run as its own process (`dictado --transcribe <session-dir>`) so the big model's
VRAM is freed when the process ends, and a crash can't take dictation down. The
caller ends the process with winutil.hard_exit: CTranslate2 must never destroy a
model (runbook §10), so models loaded here are kept in _KEEP until the end.

Audio is decoded once (60 min at 16 kHz = 230 MB float32) and handed to
faster-whisper, whose transcribe() is a generator: segments stream out, never a
whole hour of results at once. Progress goes to progress.json, monotonic.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from . import export, models, segclean, sessions
from .choose import pick_language
from .config import TranscribeCfg
from .engine import _is_gpu_error
from .routing import mixed_langs, model_for

log = logging.getLogger(__name__)
SR = 16000
DETECT_S = 30
PIECE_MAX_S = 20.0  # mixed sessions: longest piece that gets one language
PIECE_GAP_S = 1.0   # a pause this long may switch language
PIECE_MIN_S = 3.0   # shorter than this, a piece takes the next region along: too little to detect
SHORT_S = 2.0       # a piece under this keeps the previous language unless detection is sure
SURE = 0.8          # share of the el+es probability the winner needs to count as sure
_KEEP: list = []  # never freed: see module docstring


def _default_factory(path, device, compute_type):
    from faster_whisper import WhisperModel
    return WhisperModel(path, device=device, compute_type=compute_type, local_files_only=True)


def _decode(path: Path) -> np.ndarray:
    from faster_whisper import decode_audio
    return decode_audio(str(path), sampling_rate=SR)


def _write_json(path: Path, data: dict) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    sessions.replace_retry(tmp, path)


def audio_file(d: Path) -> Path:
    """mix.flac for a recorded meeting, else the single imported file."""
    files = sorted(p for p in (Path(d) / "audio").iterdir() if p.is_file())
    mix = [p for p in files if p.name == "mix.flac"]
    if mix:
        return mix[0]
    if not files:
        raise FileNotFoundError(f"no audio in {Path(d) / 'audio'}")
    if len(files) > 1:  # a meeting without its mix: transcribing one source would silently lose the other
        raise FileNotFoundError(f"several sources and no mix.flac in {Path(d) / 'audio'}")
    return files[0]


def _speech(audio: np.ndarray) -> list[tuple[float, float]]:
    """Speech regions (seconds) from the VAD faster-whisper ships with (Silero)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500))
    return [(t["start"] / SR, t["end"] / SR) for t in ts]


def pieces(regions, max_s: float = PIECE_MAX_S, gap_s: float = PIECE_GAP_S,
           min_s: float = PIECE_MIN_S) -> list[tuple[float, float]]:
    """Speech regions -> the pieces a mixed session detects one language for (t0u.34).
    A pause of gap_s or more ends a piece (once it has min_s); a piece over max_s is cut
    between its regions, and a single region over max_s into equal parts."""
    groups: list[list[tuple[float, float]]] = []
    for a, b in regions:
        g = groups[-1] if groups else None
        if g and (a - g[-1][1] < gap_s or g[-1][1] - g[0][0] < min_s):
            g.append((a, b))
        else:
            groups.append([(a, b)])
    out: list[tuple[float, float]] = []
    for g in groups:
        cur: list[tuple[float, float]] = []
        for a, b in g:
            if cur and b - cur[0][0] > max_s:
                out.append((cur[0][0], cur[-1][1]))
                cur = []
            cur.append((a, b))
        if cur:
            out.append((cur[0][0], cur[-1][1]))
    final: list[tuple[float, float]] = []
    for a, b in out:
        n = math.ceil((b - a) / max_s - 1e-9) if b - a > max_s else 1
        step = (b - a) / n
        final += [(round(a + i * step, 2), round(a + (i + 1) * step, 2) if i + 1 < n else b) for i in range(n)]
    return final


def pick_mixed(model, audio: np.ndarray, langs: list[str], prev: str | None = None) -> str:
    """Which of `langs` this piece is in. A short piece the detector isn't sure about keeps
    `prev`: a lone "sí" or "ναι" is too little to switch on."""
    try:
        _, _, probs = model.detect_language(audio)
    except Exception as e:
        if _is_gpu_error(e):
            raise
        return prev or langs[0]
    lang = pick_language(probs or [], langs)
    p = dict(probs or [])
    total = sum(p.get(x, 0.0) for x in langs)
    sure = total > 0 and p.get(lang, 0.0) / total >= SURE
    if prev and not sure and len(audio) / SR < SHORT_S:
        return prev
    return lang


def mixed_segments(model, audio: np.ndarray, langs: list[str], cfg: TranscribeCfg, prompt: str | None = None,
                   speech=_speech):
    """Segments of a mixed session: each piece detected (among `langs` only) and
    transcribed in its own language. Times are relative to `audio`; each has .lang."""
    prev = None
    for a, b in pieces(speech(audio)):
        chunk = audio[int(a * SR):int(b * SR)]
        lang = prev = pick_mixed(model, chunk, langs, prev)
        gen, _ = model.transcribe(chunk, language=lang, beam_size=cfg.beam_size, vad_filter=True,
                                  condition_on_previous_text=False, initial_prompt=prompt)
        for s in gen:
            yield SimpleNamespace(start=s.start + a, end=s.end + a, text=s.text, lang=lang)


def steps(cfg: TranscribeCfg) -> list[tuple[str, str]]:
    """Load attempts in order: configured precision, then int8_float16 on CUDA, then CPU."""
    out = [("cuda", cfg.compute_type)]
    if cfg.compute_type != "int8_float16":
        out.append(("cuda", "int8_float16"))
    out.append(("cpu", "int8"))
    return out


class _Progress:
    def __init__(self, d: Path, total_s: float, clock):
        self.path, self.total, self.clock = Path(d) / "progress.json", total_s, clock
        self.done, self.last = 0.0, None

    def update(self, t: float, force: bool = False) -> None:
        self.done = max(self.done, min(float(t), self.total))
        now = self.clock()
        if force or self.last is None or now - self.last >= 1.0:
            self.last = now
            pct = 100 if force else min(99, int(100 * self.done / self.total)) if self.total else 0
            try:  # best effort: a locked progress file must never fail the job
                _write_json(self.path, {"done_s": round(self.done, 2), "total_s": round(self.total, 2), "pct": pct})
            except OSError as e:
                log.warning("progress not written (%s); continuing", e)
                self.last = None  # try again on the next segment

    def finish(self) -> None:
        self.done = self.total
        self.update(self.total, force=True)


def _load(name, cfg, start, factory, resolve, d, cache=None):
    """Load `name` from fallback step `start` on. `cache` (name -> (model, step, device, ct))
    lets one process reuse a model it already holds: the detector when the route is the
    same model, a meeting's live model for its final pass."""
    if cache is not None and start == 0 and name in cache:
        m, i, device, ct = cache[name]
        sessions.write_meta(d, model=name, compute_type=ct, device=device, slow=device == "cpu")
        log.info("route model=%s compute=%s device=%s (already loaded)", name, ct, device)
        return m, i
    plan = steps(cfg)
    path = str(resolve(name, cfg))
    for i in range(start, len(plan)):
        device, ct = plan[i]
        try:
            m = factory(path, device, ct)
        except Exception as e:
            if device == "cuda" and _is_gpu_error(e) and i + 1 < len(plan):
                log.warning("load %s on %s/%s failed (%s); next fallback", name, device, ct, e)
                continue
            raise
        _KEEP.append(m)
        if cache is not None:
            cache[name] = (m, i, device, ct)
        sessions.write_meta(d, model=name, compute_type=ct, device=device, slow=device == "cpu")
        log.info("route model=%s compute=%s device=%s", name, ct, device)
        return m, i
    raise RuntimeError(f"no way to load {name}")


def run(session_dir: Path, cfg: TranscribeCfg, factory=_default_factory, resolve=models.for_transcribe,
        decode=_decode, clock=time.monotonic, cache: dict | None = None, prompt: str | None = None,
        speech=_speech) -> int:
    d = Path(session_dir)
    cache = {} if cache is None else cache
    try:
        meta = sessions.write_meta(d, status="running", error=None)
        audio = np.asarray(decode(audio_file(d)), dtype=np.float32)
        total = len(audio) / SR
        prog = _Progress(d, total, clock)
        prog.update(0, force=False)
        lang = meta["lang"]
        if lang == "auto":
            det, _ = _load(cfg.detector_model, cfg, 0, factory, resolve, d, cache)
            lang = det.detect_language(audio[: DETECT_S * SR])[0]
            sessions.write_meta(d, detected_lang=lang)
            log.info("detected lang=%s", lang)
        mixed = mixed_langs(lang)
        name = model_for(lang, cfg)
        log.info("route lang=%s model=%s", lang, name)
        model, step = _load(name, cfg, 0, factory, resolve, d, cache)
        segs: list[dict] = []
        offset = 0.0
        while True:
            try:
                rest = audio[int(offset * SR):]
                if mixed:  # Greek + Spanish: each piece in its own language (t0u.34)
                    gen = mixed_segments(model, rest, mixed, cfg, prompt, speech=speech)
                else:
                    gen, _info = model.transcribe(rest, language=lang, beam_size=cfg.beam_size, vad_filter=True,
                                                  condition_on_previous_text=False, initial_prompt=prompt)
                for s in gen:
                    text = s.text.strip()
                    if text:
                        seg = {"t0": round(s.start + offset, 2), "t1": round(s.end + offset, 2),
                               "text": text, "speaker": None}
                        if mixed:
                            seg["lang"] = s.lang
                        segs.append(seg)
                    prog.update(s.end + offset)
                break
            except Exception as e:
                if not _is_gpu_error(e) or step + 1 >= len(steps(cfg)):
                    raise
                offset = segs[-1]["t1"] if segs else 0.0
                log.error("GPU error at %.1f s (%s); reloading with the next fallback", offset, e)
                model, step = _load(name, cfg, step + 1, factory, resolve, d, cache)
        segs = segclean.clean_segments(segs)
        _write_json(d / "transcript.json", {"segments": segs, "lang": lang, "model": name})
        sessions.write_meta(d, status="done", duration_s=round(total, 2), lang_used=lang)
        export.write_all(d)
        prog.finish()
        log.info("done segments=%d audio_s=%.1f", len(segs), total)
        return 0
    except Exception as e:
        log.exception("transcription failed")
        try:
            sessions.write_meta(d, status="failed", error=f"{type(e).__name__}: {e}")
        except Exception:
            log.exception("could not mark %s failed", d)
        return 1


def run_session(session_dir: Path, cfg: TranscribeCfg, **kw) -> int:
    """The --transcribe job: run(), and for a meeting (recovered after its worker was
    killed mid-call) also the Me / Others labels the meeting worker would have added."""
    d = Path(session_dir)
    rc = run(d, cfg, **kw)
    if rc == 0 and sessions.read_meta(d).get("source") == "meeting":
        from .meeting import _label
        try:
            _label(d)
        except Exception:  # the transcript is there, only without speakers
            log.exception("labels failed for %s", d)
    return rc


def main(session_dir: str) -> int:
    """`dictado --transcribe DIR`: called from __main__, which hard-exits with the result."""
    from . import config, paths, winutil
    d = Path(session_dir)
    winutil.setup_logging(d / "worker.log", logging.INFO)
    for noisy in ("faster_whisper", "httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    winutil.add_cuda_dll_dirs()
    full = config.load(paths.config_path())
    from .calendar_ics import session_words
    from .text import vocab_prompt
    return run_session(d, full.transcribe, prompt=vocab_prompt(session_words(d, full.text.vocabulary)))
