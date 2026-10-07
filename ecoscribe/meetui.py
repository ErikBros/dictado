"""What the pill, the tray and the meeting prompt show, as plain logic (ui.py draws it).

Dictation always wins the pill: dictating over a meeting shows Dictando, then the
pill goes back to "Taking notes 12:04" with the latest live line. The tray is red
while a meeting records. The prompt near the pill asks at a call start, at a long
silence ("Did the meeting end?") and says when a transcript is ready.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from . import sessions

PROMPT_S = 60.0
START_PROMPT_S = 10.0  # "Are you in a meeting?" counts down on its Not now button (t0u.21)
QUESTIONS = ("start", "end?")  # prompts that need an answer; done/failed are just notes
DONE_S = 15.0
APP_NAMES = {"msteams": "Teams", "ms-teams": "Teams", "teams": "Teams", "slack": "Slack", "zoom": "Zoom",
             "discord": "Discord", "signal": "Signal", "telegram": "Telegram", "webex": "Webex",
             "whatsapp": "WhatsApp", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox",
             "brave": "Brave", "opera": "Opera"}
# Meeting / file language choices: English + Swedish built in, plus the user's added languages
# (dictado-ehs). The background app refills it from the config at start (set_langs).
LANGS: list[tuple[str, str]] = []


def set_langs(extra) -> list[tuple[str, str]]:
    from .languages import available, meeting_options
    LANGS[:] = meeting_options(available(extra))
    return LANGS


set_langs([])


def app_name(app: str | None) -> str:
    if not app:
        return "a call"
    for k, v in APP_NAMES.items():
        if app == k or app.startswith(k):
            return v
    return app.capitalize()


def _elapsed(started: str | None, now: float) -> str:
    try:
        secs = max(0, int(now - datetime.fromisoformat(started).timestamp()))
    except (TypeError, ValueError):
        secs = 0
    h, rest = divmod(secs, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


def meeting_view(state: dict, now: float, line: str | None, width: int = 44) -> dict | None:
    """The meeting layer of the pill, or None when no meeting runs."""
    m = (state or {}).get("meeting")
    if not m:
        return None
    if m.get("status") in ("stopping", "finalizing"):
        return {"label": "Saving…", "line": "", "busy": True}
    line = (line or "").strip()
    if len(line) > width:
        line = "…" + line[-(width - 1):].lstrip()
    return {"label": f"Taking notes {_elapsed(m.get('started'), now)}", "line": line, "busy": False}


def pill_layer(dictation_mode: str, view: dict | None) -> str:
    """dictation | meeting | hidden. Dictation modes are Overlay.mode values."""
    if dictation_mode in ("recording", "busy"):
        return "dictation"
    return "meeting" if view else "hidden"


def tray_meeting_label(state: dict) -> str:
    m = (state or {}).get("meeting")
    if not m:
        return "Transcribe meeting now"
    return "Saving meeting…" if m.get("status") in ("stopping", "finalizing") else "Stop meeting"


def tray_recording(state: dict) -> bool:
    """True while a meeting records or saves: the tray shows Stop instead of the language submenu."""
    return bool((state or {}).get("meeting"))


def tray_lang_items(last_lang: str) -> list[tuple[str, str, bool]]:
    """(code, name, checked) for "Transcribe meeting now >": the last language used is ticked."""
    return [(c, n, c == last_lang) for c, n in LANGS]


def tray_state(dictation_state: str, state: dict) -> str:
    if dictation_state != "idle":
        return dictation_state
    m = (state or {}).get("meeting")
    if not m:
        return "idle"
    return "busy" if m.get("status") in ("stopping", "finalizing") else "recording"


def last_live_line(d, tail_bytes: int = 4096) -> str | None:
    """Text of the last complete line of live.jsonl, reading only the file's tail."""
    p = Path(d) / "live.jsonl"
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            chunk = f.read().decode("utf-8", "ignore")
    except OSError:
        return None
    for raw in reversed(chunk.splitlines()):
        try:
            return json.loads(raw).get("text")
        except ValueError:
            continue  # half-written or cut by the seek
    return None


class Tracker:
    """Notices sessions that leave the controller (meeting or job ended): done / failed."""

    def __init__(self):
        self._seen: set[str] = set()

    def update(self, state: dict) -> list[tuple[str, str]]:
        now = set()
        if state.get("meeting"):
            now.add(state["meeting"]["dir"])
        if state.get("job"):
            now.add(state["job"]["dir"])
        out = []
        for d in sorted(self._seen - now):
            try:
                status = sessions.read_meta(d).get("status")
            except Exception:
                continue
            if status in ("done", "failed"):
                out.append((status, d))
        self._seen = now
        return out


def placement(current, new) -> str:
    """How `new` meets the open prompt: show (nothing open, or a note), queue (a note behind a
    question: it must not hide a call prompt), displace (a question over a question)."""
    if current is None or current.kind not in QUESTIONS:
        return "show"
    return "displace" if new.kind in QUESTIONS else "queue"


class Prompt:
    """kind: start (a call began) | end? (long silence) | done | failed (a transcript ended)."""

    def __init__(self, kind: str, app: str | None, lang: str | None, opened_at: float):
        self.kind, self.app, self.lang, self.opened_at = kind, app, lang, opened_at
        if kind == "start":
            self.title, self.question = "Are you in a meeting? Take notes?", f"{app_name(app)} is using the mic. Language:"
            self.buttons = [("Take notes", "transcribir"), ("Not now", "ahora_no")]
        elif kind == "end?":
            self.title, self.question = "Did the meeting end?", "Nothing has been heard for a while."
            self.buttons = [("Stop", "parar"), ("Keep going", "seguir")]
        elif kind == "done":
            self.title, self.question = "Transcript ready", ""
            self.buttons = [("Open", "abrir"), ("Close", "hide")]
        else:
            self.title, self.question = "Transcription failed", ""
            self.buttons = [("Open", "abrir"), ("Close", "hide")]

    @property
    def timeout_s(self) -> float:
        return START_PROMPT_S if self.kind == "start" else PROMPT_S if self.kind == "end?" else DONE_S

    def countdown(self, now: float) -> int | None:
        """Whole seconds left on a start prompt (10 .. 1), None for the others."""
        if self.kind != "start":
            return None
        return max(1, math.ceil(self.timeout_s - (now - self.opened_at)))

    def button_text(self, choice: str, now: float) -> str:
        label = dict((c, l) for l, c in self.buttons)[choice]
        n = self.countdown(now) if choice == "ahora_no" else None
        return f"{label} ({n})" if n is not None else label

    def expired(self, now: float) -> str | None:
        """None while open; else what the timeout means (start: Not now; others: just hide)."""
        if now - self.opened_at < self.timeout_s:
            return None
        return "ahora_no" if self.kind == "start" else "hide"
