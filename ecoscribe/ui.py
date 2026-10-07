"""Sounds and the Ui hub that drives the pill, tray and prompt box (per platform: Windows in
ecoscribe/platform/windows/shell.py, macOS in ecoscribe/platform/macos/shell.py).

Other threads never touch tk directly; they post to a queue the tk main loop drains.
"""
from __future__ import annotations

import logging
import math
import queue
import struct
import time
import tkinter as tk
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from . import meetui

if TYPE_CHECKING:
    from .platform.windows.shell import Overlay, PromptWindow, Tray

log = logging.getLogger(__name__)


def _tone(path: Path, f0: float, f1: float, ms: int, amp: float = 0.15) -> None:
    n = int(16000 * ms / 1000)
    fade = int(16000 * 0.01)
    frames = bytearray()
    phase = 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * i / n
        phase += 2 * math.pi * f / 16000
        env = min(1.0, i / fade, (n - i) / fade)
        frames += struct.pack("<h", int(32767 * amp * env * math.sin(phase)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes(bytes(frames))


class Sounds:
    def __init__(self, folder: Path, enabled: bool = True):
        self.enabled = enabled
        self.files = {}
        folder.mkdir(parents=True, exist_ok=True)
        for name, (f0, f1, ms) in {"start": (660, 880, 70), "stop": (880, 660, 70),
                                   "cancel": (440, 440, 120), "error": (330, 220, 160)}.items():
            p = folder / f"{name}.wav"
            if not p.exists():
                _tone(p, f0, f1, ms)
            self.files[name] = p

    def play(self, name: str) -> None:
        if not self.enabled or name not in self.files:
            return
        import winsound
        winsound.PlaySound(str(self.files[name]), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


class Ui:
    """Thread-safe facade the App talks to. Everything runs on the tk thread."""

    def __init__(self, root: tk.Tk, overlay: Overlay | None, sounds: Sounds, tray: Tray | None = None):
        self.root, self.overlay, self.sounds, self.tray = root, overlay, sounds, tray
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self.prompts: PromptWindow | None = None  # set by __main__ when meetings are on
        self._dict_state = "idle"
        self._meet: dict = {"meeting": None, "job": None, "queue": []}
        self.root.after(50, self._drain)

    def _post(self, fn, *args) -> None:
        self._q.put((fn, args))

    def _drain(self) -> None:
        try:
            while True:
                fn, args = self._q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log.exception("ui call failed")
        except queue.Empty:
            pass
        if self.overlay:
            try:
                self.overlay.tick()
            except Exception:
                log.exception("overlay tick failed")
        if self.prompts:
            try:
                self.prompts.tick()
            except Exception:
                log.exception("prompt tick failed")
        self.root.after(50, self._drain)

    def _tray(self, state):
        self._dict_state = state
        if self.tray:
            self.tray.set_state(meetui.tray_state(state, self._meet))

    def _set_meeting(self, state: dict, view: dict | None) -> None:
        changed = meetui.tray_meeting_label(state) != meetui.tray_meeting_label(self._meet)
        self._meet = state
        if self.tray:
            self.tray.set_state(meetui.tray_state(self._dict_state, state))
            if changed:
                self.tray.refresh()
        if self.overlay:
            self.overlay.set_meeting(view)

    def set_meeting(self, state: dict, view: dict | None) -> None:
        """Controller state + the pill's meeting layer (meetui.meeting_view)."""
        self._post(self._set_meeting, state, view)

    def prompt(self, kind: str, app=None, lang=None) -> None:
        """start / end? / done / failed: show the box above the pill; dismiss: close a start box."""
        if not self.prompts:
            return
        if kind in ("dismiss", "dismiss_end"):
            self._post(self.prompts.dismiss, "start" if kind == "dismiss" else "end?")
        else:
            self._post(self.prompts.show, meetui.Prompt(kind, app, lang, time.monotonic()))

    def sound(self, name):
        self.sounds.play(name)  # winsound async is thread-safe

    def recording(self, t0):
        self._post(self._tray, "recording")
        if self.overlay:
            self._post(self.overlay.recording, t0)

    def busy(self):
        self._post(self._tray, "busy")
        if self.overlay:
            self._post(self.overlay.busy)

    def idle(self):
        self._post(self._tray, "idle")
        if self.overlay:
            self._post(self.overlay.idle)

    def flash(self, msg, seconds: float = 2.0):
        if self.overlay:
            self._post(self.overlay.flash, msg, seconds)
