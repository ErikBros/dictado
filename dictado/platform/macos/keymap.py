"""Mac virtual keycodes (positions, layout independent) and the modifier bits CGEvent flags carry.

KeyState (keystate.py) was written with Windows VK codes and compares against VK_ESCAPE (0x1B).
Mac keycode 0x1B is the minus key, so Mac keycodes are fed to it shifted by OFFSET, with Escape
mapped to 0x1B: a lone tap, hold, Esc-cancel and "another key was pressed" all keep their meaning.
"""
from __future__ import annotations

OFFSET = 0x100
KC_ESCAPE = 53
VK_ESCAPE = 0x1B


def to_vk(keycode: int) -> int:
    return VK_ESCAPE if keycode == KC_ESCAPE else keycode + OFFSET


# modifier keys: keycode -> device-dependent flag bit (NX_DEVICE*KEYMASK), so left and right differ
MOD_BITS = {
    59: 0x00000001,  # left control
    56: 0x00000002,  # left shift
    60: 0x00000004,  # right shift
    55: 0x00000008,  # left command
    54: 0x00000010,  # right command
    58: 0x00000020,  # left option
    61: 0x00000040,  # right option
    62: 0x00002000,  # right control
    63: 0x00800000,  # fn / globe (kCGEventFlagMaskSecondaryFn)
}
# device-independent masks: which modifier is held, either side
FLAG = {"ctrl": 0x00040000, "shift": 0x00020000, "alt": 0x00080000, "cmd": 0x00100000}

LETTERS = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
           "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38,
           "k": 40, "n": 45, "m": 46}
DIGITS = {"1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29}
FKEYS = {"f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
         "f10": 109, "f11": 103, "f12": 111, "f13": 105, "f14": 107, "f15": 113, "f16": 106, "f17": 64,
         "f18": 79, "f19": 80}
MAIN = {**LETTERS, **DIGITS, **FKEYS}


def modifier_down(keycode: int, flags: int) -> bool | None:
    """For a flagsChanged event: is this modifier key now down? None if it isn't a modifier we know."""
    bit = MOD_BITS.get(keycode)
    return None if bit is None else bool(flags & bit)


def mods_held(flags: int) -> set[str]:
    return {name for name, bit in FLAG.items() if flags & bit}
