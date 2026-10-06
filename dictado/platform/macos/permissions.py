"""Which macOS privacy permissions Dictado has (pre-mortem #3: never fail silently after a rebuild).

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


def missing(needed=("accessibility", "input", "microphone")) -> list[str]:
    """Labels of the permissions dictation needs and doesn't have (system audio only matters for meetings)."""
    st = status()
    return [PANES[k][0] for k in needed if not st.get(k)]


def open_pane(key: str) -> None:
    import subprocess
    subprocess.Popen(["open", PANES[key][1]])
