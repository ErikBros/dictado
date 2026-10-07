"""Meeting detection from Windows' own record of who uses the microphone.

HKCU\\...\\CapabilityAccessManager\\ConsentStore\\microphone keeps, per app,
LastUsedTimeStart / LastUsedTimeStop (FILETIME). Stop == 0 with a Start set
means "using the mic right now". Packaged apps are subkeys named by package
family (MSTeams_8wekyb3d8bbwe); desktop apps live under NonPackaged with the exe
path as key name, '#' for '\\' (one key per installed version: slack app-4.x.y).

A call app holding the mic is a meeting. A browser holding the mic is a meeting
only with a second signal (a meeting window title): a Chrome tab can sit on the
mic for hours with no call. The meeting ends when its app has let go for
grace_s in a row (mute toggles and quick rejoins must not end it). A start needs
debounce_polls polls in a row (a Telegram voice note is not a call). A meeting
title only counts in a window owned by a browser. A desktop app's entry that says
"in use" while the app isn't running is a leftover from a crash and is ignored.
Read-only: nothing here prompts, records or touches the desktop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

CALL_APPS = {"msteams", "ms-teams", "teams", "slack", "zoom", "discord", "signal", "telegram", "webex",
             "ciscocollabhost", "whatsapp"}
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera"}
MEETING_TITLE = re.compile(r"\bMeet\b|Zoom|Microsoft Teams|Whereby|Jitsi|Google Meet|Huddle", re.I)


@dataclass(frozen=True)
class MicUse:
    app: str
    in_use: bool
    start: int
    stop: int
    nonpackaged: bool = False  # desktop app: `app` is its exe name, checkable against running processes


@dataclass(frozen=True)
class Event:
    kind: str  # "start" | "end"
    app: str
    at: float


def app_from_nonpackaged(key: str) -> str:
    """'C:#Program Files#Slack#slack.exe' -> 'slack'."""
    base = key.replace("/", "#").split("#")[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def app_from_packaged(key: str) -> str:
    """'MSTeams_8wekyb3d8bbwe' -> 'msteams'; 'com.notion.app.desktop.notion_x' -> 'notion'."""
    return key.split("_")[0].split(".")[-1].lower()


def is_call_app(app: str) -> bool:
    # prefix match: packaged names carry suffixes (whatsappdesktop)
    return app in CALL_APPS or any(app.startswith(c) for c in CALL_APPS)


def uses_from_entries(entries) -> list[MicUse]:
    """entries: (key name, start, stop, nonpackaged). One MicUse per app; in use if ANY entry is."""
    by: dict[str, MicUse] = {}
    for name, start, stop, nonpackaged in entries:
        app = app_from_nonpackaged(name) if nonpackaged else app_from_packaged(name)
        u = MicUse(app=app, in_use=bool(start) and stop == 0, start=int(start or 0), stop=int(stop or 0),
                   nonpackaged=bool(nonpackaged))
        prev = by.get(app)
        if prev is None or (u.in_use and not prev.in_use) or (u.in_use == prev.in_use and u.start > prev.start):
            by[app] = u
    return list(by.values())


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


def call_app_now(uses: list[MicUse], running: set[str] | None = None, foreground: str = "") -> str | None:
    """The call app holding the mic right now (t0u.33, for meetings started by hand): the
    foreground one if several, else the one that took the mic last. None if no call app has it."""
    live = [u for u in uses if u.in_use and is_call_app(u.app)
            and not (running is not None and u.nonpackaged and u.app not in running)]
    if not live:
        return None
    for u in live:
        if foreground and u.app == foreground:
            return u.app
    return max(live, key=lambda u: u.start).app


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


if __import__("sys").platform == "darwin":  # Core Audio process objects + Accessibility (dictado/platform/macos/detect.py)
    from .platform.macos.detect import foreground_app, read_consent, running_apps, window_titles  # noqa: F811
    from .platform.macos.procs import exe_of_pid as _exe_of_pid  # noqa: F811
    CALL_APPS = CALL_APPS | {"facetime"}
    BROWSERS = BROWSERS | {"safari"}


class Detector:
    """Feed it a poll every couple of seconds; it returns start / end events."""

    def __init__(self, grace_s: float = 20.0, own_apps=("dictado", "python", "pythonw"), debounce_polls: int = 2):
        self.grace_s = grace_s
        # python/pythonw are excluded because Ecoscribe runs as Python in development; neither is a
        # call app nor a browser, so this can never hide a real meeting.
        self.own = {a.lower() for a in own_apps}
        self.debounce = max(1, debounce_polls)
        self.app: str | None = None  # the app whose meeting is running
        self.released_at: float | None = None
        self._cand: str | None = None
        self._cand_n = 0

    def _active(self, app: str, in_use: set[str], titled: bool) -> bool:
        if app not in in_use:
            return False
        # a browser meeting needs its title too: the tab may keep the mic after the call
        return titled if app in BROWSERS else True

    def update(self, uses: list[MicUse], titles: list, now: float, running: set[str] | None = None) -> Event | None:
        """titles: (title, exe) pairs, or bare titles (owner unknown, treated as a browser's)."""
        in_use = {u.app for u in uses if u.in_use and u.app not in self.own
                  and not (running is not None and u.nonpackaged and u.app not in running)}
        titled = any(MEETING_TITLE.search(t if isinstance(t, str) else t[0])
                     for t in titles if isinstance(t, str) or t[1] in BROWSERS)
        if self.app is None:
            calls = sorted(a for a in in_use if is_call_app(a))
            browsers = sorted(a for a in in_use if a in BROWSERS)
            app = calls[0] if calls else (browsers[0] if browsers and titled else None)
            if app is None or app != self._cand:
                self._cand, self._cand_n = app, (1 if app else 0)
            else:
                self._cand_n += 1
            if app is None or self._cand_n < self.debounce:
                return None
            self.app, self.released_at, self._cand, self._cand_n = app, None, None, 0
            return Event("start", app, now)
        if self._active(self.app, in_use, titled):
            self.released_at = None
            return None
        if self.released_at is None:
            self.released_at = now
        if now - self.released_at >= self.grace_s:
            app, self.app, self.released_at = self.app, None, None
            return Event("end", app, now)
        return None
