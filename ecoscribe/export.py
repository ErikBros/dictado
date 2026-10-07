"""Transcript exports: .txt, .md (timestamps + Yo/Otros), .srt, and the 'Copy for Claude' text.

Whisper cuts speech at every short pause, so .txt, .md and Copy for Claude read in turns
(consecutive lines of one speaker joined); .srt keeps every line with its own timing."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .routing import LANG_NAMES


_SPEAKER = {"Yo": "Me", "Otros": "Others"}  # transcripts before 1.2.1 were labelled in Spanish

def _hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def _duration(s) -> str:
    if s is None:
        return "?"
    s = int(round(s))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _date(meta: dict) -> str:
    try:
        return datetime.fromisoformat(meta["created"]).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(meta.get("created", "?"))


def _lang(meta: dict) -> str:
    code = meta.get("detected_lang") or meta.get("lang") or "?"
    return LANG_NAMES.get(code, code)


def _app(meta: dict) -> str:
    return meta.get("app") or {"import": "Imported file", "meeting": "Meeting"}.get(meta.get("source"), "?")


TURN_GAP_S = 2.0  # a longer pause, or the other speaker, starts a new turn
TURN_MAX_S = 90.0  # a monologue still gets a timestamp every minute and a half


def turns(segments: list[dict]) -> list[dict]:
    """Consecutive segments of the same speaker, less than TURN_GAP_S apart, joined into one
    (t0 of the first, t1 of the last). New dicts: transcript.json keeps every segment."""
    out: list[dict] = []
    for s in segments:
        text = s["text"].strip()
        if not text:
            continue
        last = out[-1] if out else None
        if (last is not None and last.get("speaker") == s.get("speaker") and s["t0"] - last["t1"] < TURN_GAP_S
                and s["t1"] - last["t0"] <= TURN_MAX_S):
            last["text"] += " " + text
            last["t1"] = s["t1"]
        else:
            out.append({**s, "text": text})
    return out


def to_txt(segments: list[dict]) -> str:
    return "".join(s["text"] + "\n" for s in turns(segments))


def _body(segments: list[dict], names: dict | None = None) -> str:
    names = names or {}  # meta speaker_names: "Speaker 2" -> "Mamá" (t0u.22)
    lines = []
    for s in turns(segments):
        text = s["text"]
        spk = s.get("speaker")
        who = f" {names.get(spk) or _SPEAKER.get(spk, spk)}:" if spk else ""
        lines.append(f"**[{_hms(s['t0'])}]{who}** {text}")
    return "\n\n".join(lines) + "\n"


NOTES = "notes.md"  # t0u.30: what the user typed during the call


def read_notes(d: Path) -> str:
    try:
        return (Path(d) / NOTES).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def to_md(meta: dict, segments: list[dict], notes: str = "") -> str:
    head = f"# {meta.get('title', 'Transcript')}\n\n{_date(meta)} · {_lang(meta)} · {_duration(meta.get('duration_s'))}\n\n"
    if notes:
        head += f"## My notes\n\n{notes}\n\n## Transcript\n\n"
    return head + _body(segments, meta.get("speaker_names"))


def to_srt(segments: list[dict]) -> str:
    out = []
    for s in (s for s in segments if s["text"].strip()):
        out.append(f"{len(out) + 1}\n{_srt_time(s['t0'])} --> {_srt_time(s['t1'])}\n{s['text'].strip()}\n\n")
    return "".join(out)


def for_claude(meta: dict, segments: list[dict], notes: str = "") -> str:
    head = [f"Transcript: {meta.get('title', '')}", f"Date: {_date(meta)}", f"App: {_app(meta)}",
            f"Duration: {_duration(meta.get('duration_s'))}", f"Language: {_lang(meta)}"]
    people = (meta.get("calendar") or {}).get("attendees")
    if people:  # from the calendar event (t0u.35)
        head.append("Attendees: " + ", ".join(people))
    head.append("")
    if notes:
        head += ["My notes:", notes, ""]
    return "\n".join(head) + "\n" + _body(segments, meta.get("speaker_names"))


SUMMARY_ASK = ("Summarize this meeting for me. Give: the decisions made, the action items (who, what, by when), "
               "and the open questions. Quote the transcript with its timestamp where it matters. "
               "Answer in the language the meeting was held in, plainly, without filler.")


NOTES_ASK = (" I took notes during the call (My notes, below the header): use them as the outline, "
             "fill each point from the transcript, and say where the transcript disagrees with a note.")


def summary_prompt(meta: dict, segments: list[dict], notes: str = "") -> str:
    """Copy summary prompt: the request on top, then the same text as Copy for Claude."""
    return SUMMARY_ASK + (NOTES_ASK if notes else "") + "\n\n" + for_claude(meta, segments, notes)


def write_all(d: Path) -> list[Path]:
    d = Path(d)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
    out = []
    for name, text in (("transcript.txt", to_txt(segs)), ("transcript.md", to_md(meta, segs, read_notes(d))),
                       ("transcript.srt", to_srt(segs))):
        (d / name).write_text(text, encoding="utf-8")
        out.append(d / name)
    return out
