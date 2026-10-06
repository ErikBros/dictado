"""Dictation shortcut: a lone key (tap rule, keystate.py) or a combo like "ctrl+l".

Combos are modifiers (ctrl, alt, shift, win) + one letter, digit or F-key. The combo
toggles on the press and is swallowed, so the app under the cursor never sees it.
Refused: combos Windows or basic editing need (Win+L, Alt+Tab, Ctrl+C...) and any
Ctrl+Alt combo, which is AltGr on the user's Swedish layout.
"""
from __future__ import annotations

from .config import KEYS

MODS = ("ctrl", "alt", "shift", "win")
MOD_VKS = {"ctrl": (0xA2, 0xA3), "shift": (0xA0, 0xA1), "alt": (0xA4, 0xA5), "win": (0x5B, 0x5C)}
MAIN = {chr(c): 0x41 + c - ord("a") for c in range(ord("a"), ord("z") + 1)}
MAIN.update({str(d): 0x30 + d for d in range(10)})
MAIN.update({f"f{n}": 0x6F + n for n in range(1, 25)})
RESERVED = {"win+l", "alt+tab", "alt+f4", "ctrl+esc", "alt+esc", "win+d", "win+tab", "win+r", "win+e"} | \
    {f"ctrl+{k}" for k in "cvxzyasfpwnt"}
LABEL = {"rctrl": "Right Ctrl", "scrolllock": "Scroll Lock", "pause": "Pause"}


def parse(s: str) -> tuple[frozenset[str], str]:
    """'Ctrl + Shift + D' -> ({'ctrl', 'shift'}, 'd'). Raises ValueError with a reason the user can read."""
    parts = [p.strip().lower() for p in str(s or "").replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty shortcut")
    *mods, main = parts
    if not mods:
        if main in KEYS:
            return frozenset(), main
        raise ValueError(f"{main!r} alone is not allowed: use Right Ctrl, F13-F24, Pause or Scroll Lock, or a combo like Ctrl+L")
    bad = [m for m in mods if m not in MODS]
    if bad or len(set(mods)) != len(mods):
        raise ValueError(f"unknown modifier in {s!r}")
    if main not in MAIN:
        raise ValueError(f"{main!r} can't be the key of a combo (use a letter, a digit or an F-key)")
    ms = frozenset(mods)
    if {"ctrl", "alt"} <= ms:
        raise ValueError("Ctrl+Alt is AltGr on a Swedish keyboard: pick another combo")
    if canonical(ms, main) in RESERVED:
        raise ValueError(f"{label(canonical(ms, main))} is taken by Windows or by editing: pick another combo")
    return ms, main


def canonical(mods, main: str) -> str:
    return "+".join([m for m in MODS if m in mods] + [main])


def normalize(s: str) -> str:
    return canonical(*parse(s))


def label(s: str) -> str:
    if s in LABEL:
        return LABEL[s]
    return "+".join(p.capitalize() if len(p) > 1 and not p.startswith("f") else p.upper() for p in s.split("+"))


def cancel_hint(s: str) -> str:
    """The pill's second line while dictating (t0u.36). Hold the key + Esc cancels a lone
    key; a combo has no Esc cancel, only the tray's Cancel recording."""
    return "Cancel from the tray icon" if "+" in s else f"{label(s)} + Esc to cancel"


def combo_vks(s: str):
    """(main_vk, {modifier: (left_vk, right_vk)}) for a combo, None for a lone key."""
    mods, main = parse(s)
    if not mods:
        return None
    return MAIN[main], {m: MOD_VKS[m] for m in mods}


class ComboMatcher:
    """Runs inside the keyboard hook (keep it tiny). Tracks held modifiers itself; the
    combo fires on the main key's first press with exactly its modifiers held, and that
    press, its auto-repeats and its release are swallowed."""

    def __init__(self, shortcut: str):
        self.spec = shortcut  # the hook process rebuilds the matcher from it (t0u.37)
        self.main, self.mods = combo_vks(shortcut)
        self._all_mods = {vk for pair in MOD_VKS.values() for vk in pair}
        self._held: set[int] = set()
        self._eating = False

    def _mods_now(self) -> set[str]:
        return {m for m, vks in MOD_VKS.items() if self._held & set(vks)}

    def key(self, vk: int, down: bool) -> tuple[bool, bool]:
        """-> (fire, swallow) for one key event."""
        if vk in self._all_mods:
            (self._held.add if down else self._held.discard)(vk)
            return False, False
        if vk != self.main:
            return False, False
        if down:
            if self._eating:
                return False, True  # auto-repeat of the combo
            if self._mods_now() == set(self.mods):
                self._eating = True
                return True, True
            return False, False
        if self._eating:
            self._eating = False
            return False, True
        return False, False


def how(s: str) -> str:
    """'tap Right Ctrl' for a lone key, 'press Ctrl+L' for a combo (pill and tray texts)."""
    return f"press {label(s)}" if "+" in s else f"tap {label(s)}"
