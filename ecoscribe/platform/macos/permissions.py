"""Which macOS privacy permissions Ecoscribe has (pre-mortem #3: never fail silently after a rebuild).

Each entry: key -> (label the user sees in System Settings, the Settings pane URL, granted?).
"""
from __future__ import annotations

PANES = {
    "accessibility": ("Accessibility", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    "input": ("Input Monitoring", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"),
    "microphone": ("Microphone", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"),
    "audio": ("Screen & System Audio Recording",
              "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"),
}


def status() -> dict[str, bool]:
    out = {}
    try:
        from ApplicationServices import AXIsProcessTrusted
        out["accessibility"] = bool(AXIsProcessTrusted())
    except Exception:
        out["accessibility"] = False
    try:
        import Quartz
        out["input"] = bool(Quartz.CGPreflightListenEventAccess())
        out["audio"] = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        out["input"] = out["audio"] = False
    try:
        import AVFoundation as AV
        out["microphone"] = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio) == 3
    except Exception:
        out["microphone"] = False
    return out


DICTATION = ("accessibility", "input", "microphone")


def missing(needed=DICTATION, st: dict | None = None) -> list[str]:
    """Labels of the permissions dictation needs and doesn't have (system audio only matters for meetings)."""
    st = status() if st is None else st
    return [PANES[k][0] for k in needed if not st.get(k)]


def watch(on_change, interval: float = 15.0, stop=None, check=status) -> None:
    """Check now, then again every `interval` s while anything is still off, and call
    on_change(new, old) on every change (old is None the first time). A permission granted
    while Ecoscribe runs (the mic is asked for at the first dictation) shows up within seconds,
    not at the next start (dictado-6qp). Returns when everything is on, or when `stop` is set."""
    import threading
    stop = stop or threading.Event()
    last = None
    while True:
        st = check()
        if st != last:
            on_change(st, last)
            last = st
        if all(st.values()) or stop.wait(interval):
            return


def open_pane(key: str) -> None:
    import subprocess
    subprocess.Popen(["open", PANES[key][1]])
