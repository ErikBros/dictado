"""Real voices (Swedish by default, --lang el for Greek): WER of each model on one or more recordings of the same text.

The FLEURS clip (spike/sv_real/) read straight from the file, after a trip through
the speakers and WASAPI loopback, and after a Teams-like Opus squeeze: same
reference, so the WER difference is what the path costs. One child process per
model (models are never destroyed in-process, runbook §10).

    python tools/sv_real_bench.py [--lang sv] --ref REF.txt --out OUT.json AUDIO [AUDIO ...]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
SR = 16000
MODELS = ["KBLab/kb-whisper-large", "Systran/faster-whisper-large-v3", "large-v3-turbo"]
COMPUTE = "int8_float16"
_KEEP: list = []


def one(model: str, ref_path: str, audios: list[str], lang: str = "sv") -> dict:
    from ecoscribe import config, models, paths, winutil
    from ecoscribe.wer import wer
    winutil.add_cuda_dll_dirs()
    from faster_whisper import WhisperModel, decode_audio
    cfg = config.load(paths.config_path()).transcribe
    m = WhisperModel(str(models.for_transcribe(model, cfg)), device="cuda", compute_type=COMPUTE,
                     local_files_only=True)
    _KEEP.append(m)
    ref = Path(ref_path).read_text(encoding="utf-8")
    res = {"model": model, "compute": COMPUTE, "files": {}}
    for a in audios:
        audio = decode_audio(a, sampling_rate=SR)
        t0 = time.monotonic()
        segs, _ = m.transcribe(audio, language=lang, beam_size=5, vad_filter=True, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segs)
        res["files"][Path(a).name] = {"audio_s": round(len(audio) / SR, 1), "s": round(time.monotonic() - t0, 2),
                                      "wer": round(wer(ref, text), 4), "text": text}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--one")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--lang", default="sv")
    ap.add_argument("--out", type=Path)
    ap.add_argument("audio", nargs="+")
    a = ap.parse_args(argv)
    if a.one:
        from ecoscribe import winutil
        try:
            print("RESULT " + json.dumps(one(a.one, a.ref, a.audio, a.lang), ensure_ascii=False), flush=True)
            winutil.hard_exit(0)
        except Exception as e:
            print("RESULT " + json.dumps({"model": a.one, "error": f"{type(e).__name__}: {e}"}), flush=True)
            winutil.hard_exit(1)
    results = []
    for model in MODELS:
        p = subprocess.run([sys.executable, __file__, "--one", model, "--lang", a.lang, "--ref", a.ref, *a.audio], capture_output=True,
                           text=True, encoding="utf-8", timeout=1800, cwd=str(APP),
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
        r = json.loads(line[7:]) if line else {"model": model, "error": p.stderr[-800:]}
        for name, f in r.get("files", {}).items():
            print(f"{model:34} {name:28} WER {f['wer']:.3f}  ({f['s']} s)", flush=True)
        if "error" in r:
            print(f"{model}: {r['error']}", flush=True)
        results.append(r)
        time.sleep(3)
    if a.out:
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
