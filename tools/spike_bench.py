"""Stage 1 spike bench: WER, real-time factor, VRAM per model and precision.

Each (model, compute_type) runs in its own child process (`--one`), so VRAM is
measured cleanly and no model is ever destroyed in-process (runbook §10). Dictado
1.1's resident turbo is part of the baseline: "total" VRAM is what the card would
hold during a meeting with dictation running.

    python tools/spike_bench.py --out <dir>        # writes bench.json; report.md is written by hand from it
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
FIX = APP / "tests" / "fixtures"
SR = 16000
CLIPS = {"sv": "sv_meeting", "el": "el_podcast", "en": "en_meeting"}
MODELS = ["large-v3-turbo", "KBLab/kb-whisper-large", "Systran/faster-whisper-large-v3"]
COMPUTES = ["float16", "int8_float16"]
_KEEP: list = []  # never destroy a model: CTranslate2 aborts the process (runbook §10)


def vram_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout
    return int(out.strip().splitlines()[0])


class Peak:
    def __init__(self):
        self.peak, self.stop = vram_mb(), threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop.wait(0.5):
            try:
                self.peak = max(self.peak, vram_mb())
            except Exception:
                pass


def one(model: str, compute: str) -> dict:
    import numpy as np
    from dictado import config, models, paths, winutil
    from dictado.wer import wer
    winutil.add_cuda_dll_dirs()
    from faster_whisper import WhisperModel, decode_audio
    cfg = config.load(paths.config_path()).transcribe
    res = {"model": model, "compute": compute, "vram_before": vram_mb()}
    path = str(models.for_transcribe(model, cfg))
    t0 = time.monotonic()
    m = WhisperModel(path, device="cuda", compute_type=compute, local_files_only=True)
    _KEEP.append(m)
    res["load_s"] = round(time.monotonic() - t0, 2)
    res["vram_loaded"] = vram_mb()
    noise = np.random.default_rng(0).normal(0, 0.05, SR * 3).astype(np.float32)
    list(m.transcribe(noise, language="en", vad_filter=False)[0])  # warm-up
    peak = Peak()
    res["clips"] = {}
    for lang, name in CLIPS.items():
        audio = decode_audio(str(FIX / f"{name}.flac"), sampling_rate=SR)
        ref = (FIX / f"{name}.txt").read_text(encoding="utf-8")
        t0 = time.monotonic()
        segs, _ = m.transcribe(audio, language=lang, beam_size=5, vad_filter=True, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segs)
        dt = time.monotonic() - t0
        res["clips"][lang] = {"audio_s": round(len(audio) / SR, 1), "s": round(dt, 2),
                              "rtf": round(dt / (len(audio) / SR), 3), "wer": round(wer(ref, text), 3),
                              "text": text}
    chunk = decode_audio(str(FIX / "sv_meeting.flac"), sampling_rate=SR)[: 10 * SR]
    t0 = time.monotonic()
    list(m.transcribe(chunk, language="sv", beam_size=5, vad_filter=True, condition_on_previous_text=False)[0])
    res["chunk10_sv_s"] = round(time.monotonic() - t0, 2)
    peak.stop.set()
    res["vram_peak"] = peak.peak
    res["vram_model"] = res["vram_loaded"] - res["vram_before"]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", nargs=2, metavar=("MODEL", "COMPUTE"))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.one:
        from dictado import winutil
        try:
            print("RESULT " + json.dumps(one(*a.one), ensure_ascii=False), flush=True)
            winutil.hard_exit(0)
        except Exception as e:
            print("RESULT " + json.dumps({"model": a.one[0], "compute": a.one[1], "error": f"{type(e).__name__}: {e}"}),
                  flush=True)
            winutil.hard_exit(1)
    results = []
    for model in MODELS:
        for compute in COMPUTES:
            p = subprocess.run([sys.executable, __file__, "--one", model, compute], capture_output=True,
                               text=True, encoding="utf-8", timeout=1800, cwd=str(APP),
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})  # Greek text on stdout
            line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
            r = json.loads(line[7:]) if line else {"model": model, "compute": compute, "error": p.stderr[-800:]}
            print(json.dumps({k: v for k, v in r.items() if k != "clips"}), flush=True)
            results.append(r)
            time.sleep(3)  # let VRAM settle before the next child
    out = a.out or APP
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
