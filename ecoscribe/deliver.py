"""Put the transcript into whatever window has focus right now.

Clipboard + Ctrl+V works in every app (terminals, Electron, browsers, Office).
The previous clipboard text is restored afterwards, the transcript is kept out
of Windows clipboard history, and we wait for physically held modifiers so a
held Shift/Alt can't turn Ctrl+V into another shortcut.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes as w
from dataclasses import dataclass

WINDOWS = sys.platform != "darwin"
if WINDOWS:
    import win32clipboard
    import win32con

    from .sendkeys import send_keys
    from .win32types import kernel32, user32

log = logging.getLogger(__name__)
MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # shift, ctrl, alt, lwin, rwin
VK_LCONTROL, VK_V = 0xA2, 0x56
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

if WINDOWS:
    kernel32.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    kernel32.OpenProcess.restype = w.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD))
    kernel32.CloseHandle.argtypes = (w.HANDLE,)

_PRIVATE_FORMATS = {
    "ExcludeClipboardContentFromMonitorProcessing": b"\0",
    "CanIncludeInClipboardHistory": b"\0\0\0\0",
    "CanUploadToCloudClipboard": b"\0\0\0\0",
}


@dataclass
class DeliveryResult:
    pasted: bool
    target_exe: str
    reason: str
    waited_ms: int = 0


class ClipboardBusy(Exception):
    pass


def _open_clipboard(tries: int = 10, delay: float = 0.02) -> None:
    for _ in range(tries):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            time.sleep(delay)
    raise ClipboardBusy()


def _read() -> tuple[str | None, bool]:
    """(text or None, clipboard holds something that is not text)."""
    _open_clipboard()
    try:
        has_text = win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
        text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) if has_text else None
        has_any = win32clipboard.EnumClipboardFormats(0) != 0
        return text, (has_any and not has_text)
    finally:
        win32clipboard.CloseClipboard()


def get_clipboard_text() -> str | None:
    return _read()[0]


def set_clipboard_text(s: str | None, private: bool = True) -> None:
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        if s is not None:
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, s)
            if private:
                for name, data in _PRIVATE_FORMATS.items():
                    win32clipboard.SetClipboardData(win32clipboard.RegisterClipboardFormat(name), data)
    finally:
        win32clipboard.CloseClipboard()


def foreground_pid() -> int:
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def foreground_exe() -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, foreground_pid())
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = w.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        kernel32.CloseHandle(h)


def _is_elevated_pid(pid: int) -> bool:
    import win32api
    import win32security

    try:
        h = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        tok = win32security.OpenProcessToken(h, win32security.TOKEN_QUERY)
        return bool(win32security.GetTokenInformation(tok, win32security.TokenElevation))
    except Exception:
        return True  # can't even query it: treat as higher integrity than us


def _we_are_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


if WINDOWS:
    user32.GetOpenClipboardWindow.restype = w.HWND


def _wait_clipboard_quiet(quiet_s: float = 0.04, max_s: float = 0.4, owner=None,
                          clock=time.monotonic, sleep=time.sleep) -> float:
    """Wait until nobody has had the clipboard open for quiet_s.

    Measured 2026-10-01: every write is read within 1-5 ms by clipboard
    watchers (Logitech Options+, WSLg's msrdc, clipboard history). A Ctrl+V
    landing in that window makes the target's read fail and the paste vanishes.
    """
    owner = owner or user32.GetOpenClipboardWindow
    t0 = clock()
    quiet_since = t0
    while clock() - t0 < max_s:
        if owner():
            quiet_since = clock()
        elif clock() - quiet_since >= quiet_s:
            break
        sleep(0.002)
    return clock() - t0


def _modifiers_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in MODIFIERS)


def _wait_modifiers_released(max_s: float = 1.5) -> int:
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_s and _modifiers_down():
        time.sleep(0.02)
    return int((time.monotonic() - t0) * 1000)


def deliver(text: str, restore_delay_s: float = 0.8) -> DeliveryResult:
    if not text:
        return DeliveryResult(False, "", "empty")
    exe = foreground_exe()
    try:
        prior, had_non_text = _read()
        set_clipboard_text(text, private=True)
    except ClipboardBusy:
        log.warning("clipboard busy, could not deliver")
        return DeliveryResult(False, exe, "clipboard_busy")
    seq = win32clipboard.GetClipboardSequenceNumber()
    waited = _wait_modifiers_released()
    if _modifiers_down():
        # Ctrl+V now would become Ctrl+Alt+V / Win+Ctrl+V etc. Leave it on the clipboard.
        return DeliveryResult(False, exe, "modifier_held", waited)
    _wait_clipboard_quiet()
    exe = foreground_exe() or exe
    if not _we_are_elevated() and _is_elevated_pid(foreground_pid()):
        # Windows blocks synthetic input into admin windows: leave it on the clipboard.
        return DeliveryResult(False, exe, "elevated", waited)
    sent = send_keys([(VK_LCONTROL, True), (VK_V, True), (VK_V, False), (VK_LCONTROL, False)])
    if sent != 4:
        log.warning("SendInput accepted %d/4 events", sent)
        return DeliveryResult(False, exe, "blocked", waited)
    if not had_non_text:
        threading.Timer(restore_delay_s, _restore, args=(prior, seq)).start()
    return DeliveryResult(True, exe, "ok", waited)


def _restore(prior: str | None, seq: int) -> None:
    try:
        if win32clipboard.GetClipboardSequenceNumber() != seq:
            return  # someone copied something new since; leave it
        set_clipboard_text(prior, private=False)
    except Exception:
        log.exception("clipboard restore failed")


if not WINDOWS:  # NSPasteboard + Cmd+V (ecoscribe/platform/macos/deliver.py)
    from .platform.macos.deliver import (ClipboardBusy, DeliveryResult, _read, _restore, deliver, foreground_exe,  # noqa: F811,F401
                              get_clipboard_text, set_clipboard_text)
