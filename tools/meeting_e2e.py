"""Meeting E2E against the RUNNING (installed) Dictado: the window's command channel starts a
meeting, a real clip plays through the default output, the command channel stops it, and the
finished session is checked. Plays sound: only with the user's OK.

    python tools/meeting_e2e.py [--clip FLAC] [--seconds 45] [--lang sv] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from dictado import commands, meetings, paths, sessions  # noqa: E402

CLIP = APP.parent.parent / "dictado-transcription" / "spike" / "sv_real" / "ssp324" / "ssp324_first300s.flac"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=str(CLIP))
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--lang", default="sv")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    import sounddevice as sd
    from faster_whisper import decode_audio
    data = paths.data_dir()
    rep, ok = {"checks": []}, True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        rep["checks"].append({"name": name, "pass": bool(cond), "detail": str(detail)})
        print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)

    clip = decode_audio(a.clip, sampling_rate=48000)[: int(a.seconds * 48000)]
    out = commands.send(data, "start_meeting", {"lang": a.lang, "title": "Prueba E2E reunión"})
    check("start_meeting answered by the running app", out.get("ok"), out)
    if not out.get("ok"):
        return 1
    d = Path(out["dir"])
    t0 = time.monotonic()
    while not (d / "audio" / "system.flac").exists() and time.monotonic() - t0 < 120:
        time.sleep(0.5)
    st = meetings.read_state(data)
    check("meetings.json shows the meeting", st.get("meeting") and Path(st["meeting"]["dir"]) == d, st.get("meeting"))
    time.sleep(2)
    sd.play(clip, 48000)
    t_play, first_live = time.monotonic(), None
    while sd.get_stream().active:
        if first_live is None and (d / "live.jsonl").exists() and (d / "live.jsonl").stat().st_size:
            first_live = time.monotonic() - t_play
        time.sleep(0.25)
    time.sleep(2)
    check("live text appeared while playing", first_live is not None and first_live < 30, f"{first_live} s")
    out = commands.send(data, "stop_meeting")
    check("stop_meeting answered", out.get("ok"), out)
    t0 = time.monotonic()
    while sessions.read_meta(d).get("status") not in ("done", "failed") and time.monotonic() - t0 < 300:
        time.sleep(1)
    meta = sessions.read_meta(d)
    check("finalized", meta.get("status") == "done", meta.get("status"))
    check("routed to large-v3", "large-v3" in str(meta.get("model")), meta.get("model"))
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8")) if (d / "transcript.json").exists() else {}
    segs = tr.get("segments", [])
    otros = sum(1 for s in segs if s.get("speaker") == "Others")
    check("segments labelled Others", segs and otros >= 0.8 * len(segs), f"{otros}/{len(segs)}")
    text = " ".join(s["text"] for s in segs)
    check("no tags or credits", "<i>" not in text and "Text:" not in text)
    check("Swedish words recognised", "Simple Swedish Podcast" in text or "samtal" in text, text[:120])
    for ext in ("txt", "md", "srt"):
        check(f"transcript.{ext}", (d / f"transcript.{ext}").exists())
    t0 = time.monotonic()  # the worker labels and exports after "done", then exits; the controller reaps it each second
    while meetings.read_state(data).get("meeting") and time.monotonic() - t0 < 10:
        time.sleep(0.5)
    st = meetings.read_state(data)
    check("controller idle again", not st.get("meeting"), st.get("meeting"))
    rep.update(session=str(d), first_live_s=first_live, segments=len(segs), meta=meta, ok=ok)
    if a.out:
        a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
