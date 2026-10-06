"""Desktop helpers shared by the Windows tests and the E2E harness."""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import win32con
import win32gui
import win32process

HERE = Path(__file__).resolve().parent
user32 = ctypes.windll.user32


class Target:
    def __init__(self, title: str, x: int = 200, y: int = 200):
        self.title = title
        self.out = Path(tempfile.mkdtemp(prefix="dictado-")) / f"{title}.json"
        self.proc = subprocess.Popen([sys.executable, str(HERE / "targets.py"), "--title", title,
                                      "--out", str(self.out), "--x", str(x), "--y", str(y)])
        self.hwnd = 0
        end = time.monotonic() + 15
        while time.monotonic() < end:
            self.hwnd = win32gui.FindWindow(None, title)
            if self.hwnd and self.out.exists():
                break
            time.sleep(0.05)
        assert self.hwnd, f"target {title} did not appear"

    def text(self) -> str:
        try:
            return json.loads(self.out.read_text(encoding="utf-8"))["text"]
        except (OSError, json.JSONDecodeError, KeyError):  # PermissionError while the target replaces the file
            return ""

    def pastes(self) -> list:
        try:
            return json.loads(self.out.read_text(encoding="utf-8")).get("pastes", [])
        except (OSError, json.JSONDecodeError):
            return []

    def wait_text(self, pred, timeout: float = 3.0) -> str:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            t = self.text()
            if pred(t):
                return t
            time.sleep(0.05)
        return self.text()

    def focus(self) -> bool:
        return focus(self.hwnd)

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait(5)


def focus(hwnd: int, timeout: float = 2.0) -> bool:
    """Bring hwnd to the foreground despite the foreground lock."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        fg = win32gui.GetForegroundWindow()
        if fg == hwnd:
            return True
        cur = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        tgt_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        for t in {fg_thread, tgt_thread} - {0, cur}:
            user32.AttachThreadInput(cur, t, True)
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE if win32gui.IsIconic(hwnd) else win32con.SW_SHOW)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for t in {fg_thread, tgt_thread} - {0, cur}:
                user32.AttachThreadInput(cur, t, False)
        time.sleep(0.1)
    return win32gui.GetForegroundWindow() == hwnd
