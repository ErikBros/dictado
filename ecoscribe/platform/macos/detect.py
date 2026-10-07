"""Who holds the mic on macOS (uat.9): detect.py's readers, for the shared Detector.

Windows reads the ConsentStore registry. macOS 14+ lists audio "process objects" (kAudioHardwarePropertyProcessObjectList)
and says per process whether it is capturing right now (kAudioProcessPropertyIsRunningInput) plus its bundle id.
Read-only, no permission needed. Bundle ids map to the same short app names the Windows detector uses
(msteams, slack, zoom, signal, chrome...), so Detector, the prompt texts and meeting_langs.json are shared.
Browser meeting tabs: window titles of running browsers, read through Accessibility.
"""
from __future__ import annotations

import ctypes
import logging
import time

log = logging.getLogger(__name__)

# bundle id prefix -> detect.py app name (longest prefix wins)
BUNDLES = {
    "com.microsoft.teams": "msteams", "com.microsoft.teams2": "msteams", "us.zoom.xos": "zoom",
    "com.tinyspeck.slackmacgap": "slack", "org.whispersystems.signal-desktop": "signal",
    "ru.keepcoder.telegram": "telegram", "org.telegram.desktop": "telegram", "com.hnc.discord": "discord",
    "net.whatsapp.whatsapp": "whatsapp", "desktop.whatsapp": "whatsapp", "com.cisco.webexmeetingsapp": "webex",
    "cisco-systems.spark": "webex", "com.apple.facetime": "facetime",
    "com.google.chrome": "chrome", "com.microsoft.edgemac": "msedge", "org.mozilla.firefox": "firefox",
    "com.brave.browser": "brave", "com.operasoftware.opera": "opera", "com.apple.safari": "safari",
    "com.apple.webkit": "safari",  # Safari's mic is held by its WebKit GPU/WebContent process
}


def app_of_bundle(bundle: str) -> str:
    b = (bundle or "").lower()
    best = ""
    for prefix in BUNDLES:
        if b.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    if best:
        return BUNDLES[best]
    return b.rsplit(".", 1)[-1] if b else ""


# ---------- Core Audio through ctypes ----------
class _Addr(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mElement", ctypes.c_uint32)]


def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


_CA = None
SYSTEM = 1  # kAudioObjectSystemObject


def _ca():
    global _CA
    if _CA is None:
        _CA = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        for fn in (_CA.AudioObjectGetPropertyDataSize, _CA.AudioObjectGetPropertyData):
            fn.restype = ctypes.c_int32
    return _CA


def _get(obj: int, sel: str, ctype, n: int | None = None):
    ca = _ca()
    addr = _Addr(_fourcc(sel), _fourcc("glob"), 0)
    size = ctypes.c_uint32(0)
    if ca.AudioObjectGetPropertyDataSize(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size)):
        return None
    count = n if n is not None else max(1, size.value // ctypes.sizeof(ctype))
    buf = (ctype * count)()
    size = ctypes.c_uint32(ctypes.sizeof(buf))
    if ca.AudioObjectGetPropertyData(ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size), buf):
        return None
    return list(buf)[: size.value // ctypes.sizeof(ctype)]


def _cfstring(ptr: int) -> str:
    if not ptr:
        return ""
    import objc
    s = objc.objc_object(c_void_p=ptr)
    out = str(s)
    ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation").CFRelease(ctypes.c_void_p(ptr))
    return out


def mic_users() -> list[tuple[int, str]]:
    """(pid, bundle id) of every process capturing audio right now."""
    out = []
    for obj in _get(SYSTEM, "prs#", ctypes.c_uint32) or []:
        running = _get(obj, "piri", ctypes.c_uint32, 1)
        if not running or not running[0]:
            continue
        pid = (_get(obj, "ppid", ctypes.c_int32, 1) or [0])[0]
        bundle = _cfstring((_get(obj, "pbid", ctypes.c_void_p, 1) or [0])[0] or 0)
        out.append((int(pid), bundle))
    return out


def _exe(pid: int) -> str:
    from .procs import exe_of_pid
    return exe_of_pid(pid)


_first_seen: dict[str, float] = {}


def read_consent() -> list:
    """detect.read_consent for the Mac: one MicUse per app capturing now (start = when we first saw it)."""
    from ...detect import MicUse
    now = time.time()
    apps = {}
    for pid, bundle in mic_users():
        app = app_of_bundle(bundle) if bundle else _exe(pid)  # no bundle (a CLI, dev Python): its exe name
        if app:
            apps[app] = pid
    for gone in [a for a in _first_seen if a not in apps]:
        del _first_seen[gone]
    uses = []
    for app in apps:
        start = _first_seen.setdefault(app, now)
        uses.append(MicUse(app=app, in_use=True, start=int(start * 1000), stop=0, nonpackaged=False))
    return uses


def running_apps() -> set[str]:
    from AppKit import NSWorkspace
    return {app_of_bundle(str(a.bundleIdentifier() or "")) for a in NSWorkspace.sharedWorkspace().runningApplications()}


def foreground_app() -> str:
    from AppKit import NSWorkspace
    a = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app_of_bundle(str(a.bundleIdentifier() or "")) if a else ""


BROWSER_APPS = {"chrome", "msedge", "firefox", "brave", "opera", "safari"}


def window_titles() -> list[tuple[str, str]]:
    """(title, app) of the windows of running browsers (Accessibility; only they matter to the detector)."""
    from AppKit import NSWorkspace
    from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                     AXUIElementSetMessagingTimeout)
    out = []
    for a in NSWorkspace.sharedWorkspace().runningApplications():
        app = app_of_bundle(str(a.bundleIdentifier() or ""))
        if app not in BROWSER_APPS:
            continue
        el = AXUIElementCreateApplication(a.processIdentifier())
        AXUIElementSetMessagingTimeout(el, 0.05)
        err, wins = AXUIElementCopyAttributeValue(el, "AXWindows", None)
        for w in (wins or []) if err == 0 else []:
            e2, title = AXUIElementCopyAttributeValue(w, "AXTitle", None)
            if e2 == 0 and title:
                out.append((str(title), app))
    return out
