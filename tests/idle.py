"""Is someone using the PC? Desktop tests (keys, clipboard, windows) must only run when nobody is.

On 2026-10-01 desktop tests ran while the developer was typing and pasted test words into their work.
"""
import ctypes
import time


class _LII(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    li = _LII(8, 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000


def wait_idle(min_idle_s: float = 45, max_wait_s: float = 600) -> bool:
    """Wait until nobody has touched keyboard/mouse for min_idle_s. False if that never happens."""
    end = time.monotonic() + max_wait_s
    while idle_seconds() < min_idle_s:
        if time.monotonic() > end:
            return False
        time.sleep(2)
    return True


class RealInputGuard:
    """Low-level hook that notices only REAL (non-injected) keyboard/mouse input.
    Our own SendInput events carry the injected flag and are ignored."""

    def __init__(self):
        import threading
        from ctypes import wintypes as w

        from ecoscribe.win32types import (HOOKPROC, KBDLLHOOKSTRUCT, LLKHF_INJECTED, LLMHF_INJECTED,
                                        MSLLHOOKSTRUCT, WH_KEYBOARD_LL, WH_MOUSE_LL, kernel32, user32)
        self.tripped = threading.Event()
        self.what = ""

        def on_kb(code, wp, lp):
            if code >= 0 and not (ctypes.cast(lp, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.flags & LLKHF_INJECTED):
                self.what = "keyboard"
                self.tripped.set()
            return user32.CallNextHookEx(None, code, wp, lp)

        def on_ms(code, wp, lp):
            if code >= 0 and not (ctypes.cast(lp, ctypes.POINTER(MSLLHOOKSTRUCT)).contents.flags & LLMHF_INJECTED):
                self.what = "mouse"
                self.tripped.set()
            return user32.CallNextHookEx(None, code, wp, lp)

        self._procs = (HOOKPROC(on_kb), HOOKPROC(on_ms))

        def run():
            h = kernel32.GetModuleHandleW(None)
            self._hooks = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._procs[0], h, 0),
                           user32.SetWindowsHookExW(WH_MOUSE_LL, self._procs[1], h, 0)]
            msg = w.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass

        threading.Thread(target=run, daemon=True, name="real-input-guard").start()
        time.sleep(0.2)
