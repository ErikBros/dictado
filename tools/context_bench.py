"""t0u.27 test first: does putting on-screen names in the dictation prompt help or hurt?

Real read speech with names (FLEURS en test, one clip per sentence, C:\\Temp\\dictado-ctx\\en).
Each clip is dictated three ways with the dictation model and settings:
  base     no prompt (today)
  window   names from a simulated window holding this sentence plus 4 other sentences
           (you reply to a message that mentions the names you then say)
  distract names from a window with 5 other sentences only (names on screen you never say)
Reports WER, the share of the clip's names spelled exactly, and transcription time.

    python tools/context_bench.py [--dir C:\\Temp\\dictado-ctx\\en] [--n 220] [--out OUT.json]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
SR = 16000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path(r"C:\Temp\dictado-ctx\en"))
    ap.add_argument("--n", type=int, default=220)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    from dictado import winutil
    from dictado.context import names_from_text
    from dictado.models import ensure_local
    from dictado.text import vocab_prompt
    from dictado.wer import wer
    winutil.add_cuda_dll_dirs()
    from faster_whisper import WhisperModel, decode_audio
    m = WhisperModel(str(ensure_local(a.model)), device="cuda", compute_type="float16", local_files_only=True)
    man = json.loads((a.dir / "manifest.json").read_text(encoding="utf-8"))[: a.n]
    rng = random.Random(27)

    def run(audio, prompt):
        t0 = time.perf_counter()
        segs, _ = m.transcribe(audio, language=a.lang, beam_size=5, vad_filter=True,
                               vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False,
                               without_timestamps=True, initial_prompt=prompt)
        text = "".join(s.text for s in segs).strip()
        return text, (time.perf_counter() - t0) * 1000

    run(decode_audio(str(a.dir / man[0]["file"]), sampling_rate=SR), None)  # warm-up
    rows = []
    for i, c in enumerate(man):
        audio = decode_audio(str(a.dir / c["file"]), sampling_rate=SR)
        others = rng.sample([x["ref"] for x in man if x is not c], 5)
        prompts = {"base": None,
                   "window": vocab_prompt(names_from_text([c["ref"], *others[:4]])),
                   "distract": vocab_prompt(names_from_text(others))}
        row = {"file": c["file"], "ref": c["ref"], "names": c["names"]}
        for k, p in prompts.items():
            text, ms = run(audio, p)
            hits = sum(1 for nm in c["names"] if re.search(rf"(?<!\w){re.escape(nm)}(?!\w)", text))
            row[k] = {"text": text, "ms": round(ms), "wer": wer(c["ref"], text), "hits": hits, "prompt": p}
        rows.append(row)
        if i % 20 == 0:
            print(i, flush=True)
    names = sum(len(r["names"]) for r in rows)
    summary = {}
    for k in ("base", "window", "distract"):
        summary[k] = {"wer": round(statistics.mean(r[k]["wer"] for r in rows), 4),
                      "names_right": round(sum(r[k]["hits"] for r in rows) / names, 4),
                      "ms_median": statistics.median(r[k]["ms"] for r in rows),
                      "ms_p90": sorted(r[k]["ms"] for r in rows)[int(0.9 * len(rows))],
                      "worse_than_base": sum(1 for r in rows if r[k]["wer"] > r["base"]["wer"] + 1e-9),
                      "better_than_base": sum(1 for r in rows if r[k]["wer"] < r["base"]["wer"] - 1e-9)}
        print(k, summary[k], flush=True)
    if a.out:
        a.out.write_text(json.dumps({"clips": len(rows), "names": names, "summary": summary, "rows": rows},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    winutil.hard_exit(0)


if __name__ == "__main__":
    sys.exit(main())
