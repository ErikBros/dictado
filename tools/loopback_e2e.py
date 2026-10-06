"""Swedish from the computer, end to end: play a clip through the default output while
the real meeting worker records mic + system audio, then score its transcript.

    python tools/loopback_e2e.py --audio CLIP.flac --ref REF.txt --root RUNS_DIR [--lang sv]

Plays sound on the speakers/headphones and opens the mic: only with the user's OK.
Prints WER of the whole transcript and of the Otros (system) segments alone, and
how many segments were labelled Yo (mic). system.flac stays in the session folder
for tools/sv_real_bench.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from dictado import sessions  # noqa: E402
from dictado.wer import wer  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--lang", default="sv")
    a = ap.parse_args(argv)
    import sounddevice as sd
    from faster_whisper import decode_audio
    clip = decode_audio(a.audio, sampling_rate=48000)
    a.root.mkdir(parents=True, exist_ok=True)
    d = sessions.create(f"Prueba loopback {Path(a.audio).stem}", a.lang, "meeting", a.root)
    print(f"Sesión: {d}", flush=True)
    p = subprocess.Popen([sys.executable, "-m", "dictado", "--meeting", str(d)], cwd=str(APP))
    sysf = d / "audio" / "system.flac"
    t0 = time.monotonic()
    while not sysf.exists():
        if p.poll() is not None or time.monotonic() - t0 > 180:
            print("the meeting worker never started recording", flush=True)
            return 1
        time.sleep(0.5)
    time.sleep(3)
    print(f"Reproduciendo {len(clip) / 48000:.0f} s en {sd.query_devices(kind='output')['name']}", flush=True)
    sd.play(clip, 48000)
    sd.wait()
    time.sleep(3)
    (d / "stop").write_text("", encoding="utf-8")
    p.wait()
    meta = sessions.read_meta(d)
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    segs = tr["segments"]
    ref = Path(a.ref).read_text(encoding="utf-8")
    full = " ".join(s["text"].strip() for s in segs)
    otros = " ".join(s["text"].strip() for s in segs if s.get("speaker") == "Otros")
    live = [json.loads(l)["text"] for l in (d / "live.jsonl").read_text(encoding="utf-8").splitlines()] \
        if (d / "live.jsonl").exists() else []
    out = {"session": str(d), "status": meta["status"], "model": meta.get("model"),
           "recorded_s": meta.get("recorded_s"), "segments": len(segs),
           "yo": [s["text"] for s in segs if s.get("speaker") == "Yo"],
           "wer_final": round(wer(ref, full), 4), "wer_otros": round(wer(ref, otros), 4),
           "wer_live": round(wer(ref, " ".join(live)), 4) if live else None}
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    (d / "e2e_score.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if meta["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
