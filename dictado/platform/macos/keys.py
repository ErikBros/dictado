"""Synthesized keys on macOS (CGEvent), tagged so Dictado's own key tap can tell them from real ones."""
from __future__ import annotations

import Quartz as Q

MAGIC = 0x44494354  # "DICT" in kCGEventSourceUserData: ours, like LLKHF_INJECTED on Windows
KC_V, KC_RETURN, KC_ESCAPE = 9, 36, 53
KC_CMD, KC_RCMD, KC_SHIFT, KC_OPTION, KC_CTRL = 55, 54, 56, 58, 59
MOD_FLAGS = {"cmd": Q.kCGEventFlagMaskCommand, "shift": Q.kCGEventFlagMaskShift,
             "alt": Q.kCGEventFlagMaskAlternate, "ctrl": Q.kCGEventFlagMaskControl}
ALL_MODS = Q.kCGEventFlagMaskCommand | Q.kCGEventFlagMaskShift | Q.kCGEventFlagMaskAlternate | Q.kCGEventFlagMaskControl


def _post(keycode: int, down: bool, flags: int = 0, tap=Q.kCGHIDEventTap) -> None:
    src = Q.CGEventSourceCreate(Q.kCGEventSourceStatePrivate)
    ev = Q.CGEventCreateKeyboardEvent(src, keycode, down)
    Q.CGEventSetFlags(ev, flags)
    Q.CGEventSetIntegerValueField(ev, Q.kCGEventSourceUserData, MAGIC)
    Q.CGEventPost(tap, ev)


def send_keys(events: list[tuple[int, bool]], flags: int = 0) -> int:
    """events: (mac keycode, is_down) in order, all with `flags` held. Returns how many were posted."""
    for kc, down in events:
        _post(kc, down, flags)
    return len(events)


def paste() -> int:
    return send_keys([(KC_V, True), (KC_V, False)], flags=Q.kCGEventFlagMaskCommand)


def press_enter() -> None:
    send_keys([(KC_RETURN, True), (KC_RETURN, False)])


def modifiers_down() -> bool:
    """A modifier physically held right now (it would turn Cmd+V into another shortcut)."""
    return bool(Q.CGEventSourceFlagsState(Q.kCGEventSourceStateHIDSystemState) & ALL_MODS)


def is_ours(event) -> bool:
    return Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData) == MAGIC
