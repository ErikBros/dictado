"""Call detection on Windows: Windows' own record of who uses the microphone, window titles and
running apps (macOS: ecoscribe/platform/macos/detect.py). The rules live in ecoscribe/detect.py.

HKCU\\...\\CapabilityAccessManager\\ConsentStore\\microphone keeps, per app,
LastUsedTimeStart / LastUsedTimeStop (FILETIME). Stop == 0 with a Start set
means "using the mic right now". Packaged apps are subkeys named by package
family (MSTeams_8wekyb3d8bbwe); desktop apps live under NonPackaged with the exe
path as key name, '#' for '\\' (one key per installed version: slack app-4.x.y).
Read-only: nothing here prompts, records or touches the desktop.
"""
from __future__ import annotations

from ...detect import MicUse, app_from_nonpackaged, uses_from_entries


KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _entries(root, path: str, nonpackaged: bool):
    import winreg
    try:
        k = winreg.OpenKey(root, path)
    except OSError:
        return
    with k:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(k, i)
            except OSError:
                return
            i += 1
            if name == "NonPackaged" and not nonpackaged:
                continue
            try:
                with winreg.OpenKey(k, name) as sk:
                    vals = []
                    for v in ("LastUsedTimeStart", "LastUsedTimeStop"):
                        try:
                            vals.append(int(winreg.QueryValueEx(sk, v)[0]))
                        except OSError:
                            vals.append(0)
            except OSError:
                continue
            yield name, vals[0], vals[1], nonpackaged


def foreground_app() -> str:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return _exe_of_pid(pid.value) if pid.value else ""


def read_consent() -> list[MicUse]:
    import winreg
    hk = winreg.HKEY_CURRENT_USER
    return uses_from_entries(list(_entries(hk, KEY, False)) + list(_entries(hk, KEY + r"\NonPackaged", True)))


def _exe_of_pid(pid: int) -> str:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return ""
        return app_from_nonpackaged(buf.value.replace("\\", "#"))
    finally:
        k32.CloseHandle(h)


def window_titles() -> list[tuple[str, str]]:
    """(title, exe name) of visible top-level windows (read-only EnumWindows)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    out: list[tuple[str, str]] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    out.append((buf.value, _exe_of_pid(pid.value)))
        return True
    user32.EnumWindows(proc(cb), 0)
    return out


def running_apps() -> set[str]:
    """Exe names (lowercase, no .exe) of running processes (Toolhelp snapshot, read-only)."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    out: set[str] = set()
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.add(app_from_nonpackaged(e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out
