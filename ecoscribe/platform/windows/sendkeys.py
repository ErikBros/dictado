"""Synthesize key presses with SendInput (used for Ctrl+V and by the tests)."""
from __future__ import annotations

import ctypes

from .win32types import (INPUT, INPUT_KEYBOARD, INPUT_MOUSE, KEYEVENTF_EXTENDEDKEY,
                         KEYEVENTF_KEYUP, MOUSEEVENTF_WHEEL, user32)

# Keys whose scan code needs the E0 prefix flag (right-hand modifiers, nav cluster).
EXTENDED = {0xA3, 0xA5, 0x5B, 0x5C, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}


def send_keys(events: list[tuple[int, bool]], extended: set[int] | None = None) -> int:
    """events: (vk, is_down) in order. Returns how many events Windows accepted."""
    ext = EXTENDED if extended is None else extended
    arr = (INPUT * len(events))()
    for i, (vk, down) in enumerate(events):
        flags = 0 if down else KEYEVENTF_KEYUP
        if vk in ext:
            flags |= KEYEVENTF_EXTENDEDKEY
        arr[i].type = INPUT_KEYBOARD
        arr[i].u.ki.wVk = vk
        arr[i].u.ki.wScan = user32.MapVirtualKeyW(vk, 0) & 0xFF
        arr[i].u.ki.dwFlags = flags
    return user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))


def send_wheel(delta: int = -120) -> int:
    arr = (INPUT * 1)()
    arr[0].type = INPUT_MOUSE
    arr[0].u.mi.mouseData = ctypes.c_uint32(delta).value
    arr[0].u.mi.dwFlags = MOUSEEVENTF_WHEEL
    return user32.SendInput(1, arr, ctypes.sizeof(INPUT))
