"""Small desktop helpers on macOS: open a file or folder, list mic names, the webview backend."""
from __future__ import annotations

import subprocess


def startfile(path: str) -> None:
    """os.startfile on Windows: the default app for a file, Finder for a folder."""
    subprocess.Popen(["open", str(path)])


def input_names() -> list[str]:
    """Names of the Core Audio input devices (what Settings offers as mics)."""
    import sounddevice as sd
    names = []
    for d in sd.query_devices():
        host = sd.query_hostapis(d["hostapi"])["name"]
        if host == "Core Audio" and d["max_input_channels"] > 0 and d["name"] not in names:
            names.append(d["name"])
    return names


WEBVIEW_GUI = "cocoa"
DEFAULT_MIC_LABEL = "System default"
