"""Turns raw key/mouse events into actions.

Tap mode (default): a toggle is a LONE tap of the toggle key: pressed and released with
no other key or mouse button in between, held for less than max_tap_s. Anything else
(combos like RCtrl+C, long holds, every other key) is ignored, which is what lets you
navigate freely while recording. Actions: "toggle", "cancel" (Esc while held).

Hold mode ([hotkey] hold_to_talk, t0u.28) adds hold-to-talk next to the tap. Actions:
"press" (key down: the app starts the mic quietly so no word is lost), "tap" (let go
before hold_s), "hold" (still held at hold_s, from tick()), "release" (let go after
that), "abort" (another key or a click while held: it was a shortcut), "cancel" (Esc).
"""
from __future__ import annotations

VK_ESCAPE = 0x1B


class KeyState:
    def __init__(self, toggle_vk: int, max_tap_s: float, hold: bool = False, hold_s: float = 0.5):
        self.toggle_vk = toggle_vk
        self.max_tap_s = max_tap_s
        self.hold = hold
        self.hold_s = hold_s
        self.held = False
        self._clean = False
        self._held_fired = False
        self._t0 = 0.0

    def feed(self, kind: str, vk: int, t: float) -> str | None:
        if kind == "down" and vk == self.toggle_vk:
            if not self.held:  # auto-repeat sends more downs; only the first counts
                self.held, self._clean, self._held_fired, self._t0 = True, True, False, t
                return "press" if self.hold else None
            return None
        if kind == "up" and vk == self.toggle_vk:
            was_held, clean, dur = self.held, self._clean, t - self._t0
            self.held = False
            if not (was_held and clean):
                return None
            if self.hold:
                return "release" if self._held_fired or dur >= self.hold_s else "tap"
            return "toggle" if dur < self.max_tap_s else None
        if self.held and kind in ("down", "mouse"):
            was_clean, self._clean = self._clean, False
            if kind == "down" and vk == VK_ESCAPE:
                return "cancel"
            if self.hold and was_clean:
                return "abort"
        return None

    def tick(self, t: float) -> str | None:
        """Called by the hook's consumer between events: fires "hold" once at hold_s."""
        if self.hold and self.held and self._clean and not self._held_fired and t - self._t0 >= self.hold_s:
            self._held_fired = True
            return "hold"
        return None
