"""The meeting worker: `dictado --meeting DIR`.

Records mic + system audio (session_rec), transcribes pause-cut chunks as they
come into live.jsonl (what the pill and the Reuniones page show), and when the
meeting stops (a `stop` file in DIR or the named event) finishes the FLACs, runs
the full-quality pass on mix.flac with the same, already loaded model, labels
each segment Yo / Otros and writes the transcript. One process per meeting:
its VRAM is freed when it exits (hard exit, models are never destroyed).
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path

import numpy as np

from . import export, models, segclean, sessions, speakers, transcribe
from .config import TranscribeCfg
from .routing import mixed_langs, model_for

log = logging.getLogger(__name__)
SR = 16000
STOP_EVENT = "Local\\DictadoMeetingStop"
MAX_S = 4 * 3600  # a forgotten recording stops itself after 4 h


def stop_checker(d: Path, event_name: str | None = STOP_EVENT):
    """True once DIR/stop exists or the named event is set."""
    handle = None
    if event_name:
        try:
            import win32event
            handle = win32event.CreateEvent(None, True, False, event_name)
        except Exception:
            log.warning("no stop event, the stop file still works", exc_info=True)

    def check() -> bool:
        if (Path(d) / "stop").exists():
            return True
        if handle is not None:
            import win32event
            return win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_OBJECT_0
        return False
    return check


def _default_recorder(d: Path, on_chunk):
    from . import config, paths
    from .loopback import Loopback
    from .micgate import MicGate
    from .session_rec import MicSource, SessionRecorder
    audio_cfg = config.load(paths.config_path()).audio
    gate = MicGate(audio_cfg.device, audio_cfg.unmute_volume, enabled=audio_cfg.unmute_while_recording)
    return SessionRecorder(d, mic_factory=lambda: MicSource(audio_cfg), loop_factory=Loopback, gate=gate,
                           on_chunk=on_chunk)


def _current_lang(d: Path, fallback):
    """The meeting's language now: meta lang (changed from the live view) or the start one.
    The loaded model stays (large-v3 and turbo speak every language); the final pass routes
    on meta lang, so a switch also picks the right model for the whole recording."""
    try:
        lang = sessions.read_meta(d).get("lang")
    except Exception:
        return fallback
    return None if lang == "auto" else (lang or fallback)


def _append_live(d: Path, line: dict) -> None:
    with open(Path(d) / "live.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def _write_levels(d: Path, rec) -> None:
    try:
        mic, system = rec.levels()
        transcribe._write_json(Path(d) / "levels.json", {"mic": round(float(mic), 5), "system": round(float(system), 5),
                                                          "t": round(time.time(), 1)})
    except Exception as e:  # best effort: never stop a recording over a level file
        log.debug("levels not written (%s)", e)


def _label(d: Path) -> None:
    from faster_whisper import decode_audio
    audio = Path(d) / "audio"
    mic = decode_audio(str(audio / "mic.flac"), sampling_rate=SR)
    system = decode_audio(str(audio / "system.flac"), sampling_rate=SR)
    path = Path(d) / "transcript.json"
    tr = json.loads(path.read_text(encoding="utf-8"))
    tr["segments"] = segclean.drop_silent(tr["segments"], mic, system)
    speakers.label(tr["segments"], mic, system)
    transcribe._write_json(path, tr)
    export.write_all(d)


def run(session_dir: Path, cfg: TranscribeCfg, recorder_factory=_default_recorder, stop_check=None,
        poll_s: float = 0.25, factory=transcribe._default_factory, resolve=models.for_transcribe,
        clock=time.monotonic, prompt: str | None = None, speech=transcribe._speech) -> int:
    d = Path(session_dir)
    stop_check = stop_check or stop_checker(d)
    cache: dict = {}
    try:
        meta = sessions.write_meta(d, source="meeting", status="recording", error=None)
        lang = meta["lang"]
        live_lang = None if lang == "auto" else lang  # auto: each chunk detects; the final pass routes
        name = cfg.detector_model if lang == "auto" else model_for(lang, cfg)
        model, _ = transcribe._load(name, cfg, 0, factory, resolve, d, cache)
        sessions.write_meta(d, status="recording")
        chunks: queue.Queue = queue.Queue()
        dropping = threading.Event()
        last_lang = [None]  # a mixed meeting's last live language: short unsure chunks keep it
        t_start = clock()

        def on_chunk(t0, audio):
            chunks.put((t0, audio))

        def live():
            while True:
                item = chunks.get()
                if item is None:
                    return
                if dropping.is_set():
                    continue
                t0, audio = item
                try:
                    lang_now = _current_lang(d, live_lang)  # the user can switch it mid-meeting (meta lang)
                    if mixed_langs(lang_now):  # Greek + Spanish: each chunk is one or the other (t0u.34)
                        lang_now = transcribe.pick_mixed(model, audio, mixed_langs(lang_now), last_lang[0])
                        last_lang[0] = lang_now
                    gen, _ = model.transcribe(audio, language=lang_now, beam_size=cfg.beam_size, vad_filter=True,
                                              condition_on_previous_text=False, initial_prompt=prompt)
                    text = " ".join(s["text"] for s in segclean.clean_segments(
                        [{"text": s.text} for s in gen]))
                except Exception:
                    log.exception("live chunk at %.1f s failed", t0)
                    continue
                t1 = round(t0 + len(audio) / SR, 2)
                lag = round(clock() - t_start - t1, 2)
                if text:
                    _append_live(d, {"t0": round(t0, 2), "t1": t1, "text": text, "lag_s": lag})
                log.info("live chunk t0=%.1f t1=%.1f live_lag_s=%.2f chars=%d", t0, t1, lag, len(text))

        worker = threading.Thread(target=live, name="dictado-live", daemon=True)
        worker.start()
        rec = recorder_factory(d, on_chunk)
        try:
            rec.start()
            log.info("meeting recording lang=%s model=%s", lang, name)
            last_lv = None
            while not stop_check() and clock() - t_start < MAX_S:
                if last_lv is None or clock() - last_lv >= 1.0:  # the background app's silence backup reads it
                    last_lv = clock()
                    _write_levels(d, rec)
                time.sleep(poll_s)
            log.info("meeting stop after %.0f s", clock() - t_start)
        finally:  # whatever happened: finish the FLACs and give the mic back
            durations = rec.stop()
            dropping.set()  # chunks still queued are covered by the final pass
            chunks.put(None)
        worker.join(timeout=120)  # at most one chunk (<= 20 s of audio) still in flight
        if worker.is_alive():
            log.warning("live chunk still running after 120 s; final pass waits for it")
            worker.join()
        sessions.write_meta(d, status="finalizing", recorded_s=durations.get("mix"))
        rc = transcribe.run(d, cfg, factory=factory, resolve=resolve, cache=cache, prompt=prompt, speech=speech)
        if rc == 0:
            _label(d)
        return rc
    except Exception as e:
        log.exception("meeting failed")
        try:
            sessions.write_meta(d, status="failed", error=f"{type(e).__name__}: {e}")
        except Exception:
            log.exception("could not mark %s failed", d)
        return 1


def main(session_dir: str) -> int:
    """`dictado --meeting DIR`: called from __main__, which hard-exits with the result."""
    from . import config, paths, winutil
    d = Path(session_dir)
    winutil.setup_logging(d / "worker.log", logging.INFO)
    for noisy in ("faster_whisper", "httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    winutil.add_cuda_dll_dirs()
    full = config.load(paths.config_path())
    from .calendar_ics import session_words
    from .text import vocab_prompt
    return run(d, full.transcribe, prompt=vocab_prompt(session_words(d, full.text.vocabulary)))
