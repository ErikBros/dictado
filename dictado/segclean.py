"""Transcript segment cleanup: what Whisper learned from subtitles and must not reach a transcript.

Whisper (KB-Whisper most of all: it is trained on subtitles) writes italic tags and, on
silence, invents subtitle credits ("Text: VSI OrdKedjan 2021 www.vsi-stockholm.se").
Credits are caught by their shape; for a recorded meeting, a segment where both the
mic and the system track are digitally silent is dropped too, whatever it says.
"""
from __future__ import annotations

import html
import re

import numpy as np

SR = 16000
SILENT_RMS = 1e-3  # about -60 dBFS: a typical mic noise floor is ~2e-4, speech on either track is 1e-2 or more

_TAG = re.compile(r"</?(?:i|b|u|em|strong|font)(?:\s[^<>]*)?>", re.IGNORECASE)
_CREDIT = re.compile(
    r"^\s*(?:text(?:ning)?|undertext(?:er|ning)?|svensktextning|översättning|subtitles|subtítulos)"
    r"(?:\s*:|\s+(?:av|från|by|por|realizados)\b|\.nu\b)",
    re.IGNORECASE)


def strip_tags(text: str) -> str:
    text = _TAG.sub("", html.unescape(text)) if "&" in text else _TAG.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def is_credit(text: str) -> bool:
    return bool(_CREDIT.search(text))


def clean_segments(segments: list[dict]) -> list[dict]:
    """Strip tags from every segment; drop credits and segments left empty."""
    out = []
    for s in segments:
        text = strip_tags(s["text"])
        if text and re.search(r"\w", text) and not is_credit(text):
            out.append({**s, "text": text})
    return out


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def drop_silent(segments: list[dict], mic: np.ndarray, system: np.ndarray, sr: int = SR) -> list[dict]:
    """Drop segments with no sound on either track (Whisper filling silence). A segment
    outside the recorded audio is kept: never lose text on a judgement we can't make."""
    n = max(len(mic), len(system))
    out = []
    for s in segments:
        a, b = int(s["t0"] * sr), int(s["t1"] * sr)
        if a >= n or b <= a or max(_rms(mic[a:b]), _rms(system[a:b])) >= SILENT_RMS:
            out.append(s)
    return out
