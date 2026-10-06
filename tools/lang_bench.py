"""Dictation language check (dictado-bvf), real GPU model. Windows Python.

    python lang_bench.py

Runs the dictation engine with all four languages ticked (en, es, sv, el -> large-v3) on one
clip per language from tests/fixtures, with and without a "prefer" of another language, and
prints the detected language and the time. Every clip must come back in its own language.
"""
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from faster_whisper import decode_audio  # noqa: E402

from dictado import winutil  # noqa: E402
from dictado.config import Config  # noqa: E402
from dictado.engine import Engine, dictation_model  # noqa: E402

winutil.add_cuda_dll_dirs()
sys.stdout.reconfigure(encoding="utf-8")
SR = 16000
FIX = APP / "tests" / "fixtures"
cfg = Config()
cfg.whisper.languages = ["en", "es", "sv", "el"]
clips = {
    "en": decode_audio(str(FIX / "en_long.wav"), sampling_rate=SR),
    "es": decode_audio(str(FIX / "es_climb.wav"), sampling_rate=SR),
    "sv": decode_audio(str(FIX / "sv_meeting.flac"), sampling_rate=SR)[: 7 * SR],
    "el": decode_audio(str(FIX / "el_podcast.flac"), sampling_rate=SR)[: 7 * SR],
}
eng = Engine(cfg.whisper, cfg.text)
t = time.perf_counter()
eng.load()
print(f"model {dictation_model(cfg.whisper)[0]} on {eng.device}, load {time.perf_counter() - t:.1f} s")
bad = 0
for want, audio in clips.items():
    for prefer in (None, "en" if want != "en" else "es"):
        r = eng.transcribe(audio, prefer=prefer) if prefer else eng.transcribe(audio)
        ok = r.lang == want
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {want} prefer={prefer or '-':2} -> {r.lang} {r.ms:4d} ms  {r.text[:60]!r}")
print("all right" if not bad else f"{bad} wrong")
