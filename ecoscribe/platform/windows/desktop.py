"""Small desktop helpers on Windows: open a file or folder, list mic names, the webview backend
(macOS: ecoscribe/platform/macos/desktop.py)."""
from __future__ import annotations

import os


def startfile(path: str) -> None:
    """The default app for a file, Explorer for a folder."""
    os.startfile(path)


def input_names() -> list[str]:
    """Names of the MME input devices (what Settings offers as mics)."""
    import sounddevice as sd
    names = []
    for d in sd.query_devices():
        host = sd.query_hostapis(d["hostapi"])["name"]
        if host == "MME" and d["max_input_channels"] > 0 and "Sound Mapper" not in d["name"]:
            if d["name"] not in names:
                names.append(d["name"])
    return names


WEBVIEW_GUI = "edgechromium"
DEFAULT_MIC_LABEL = "Windows default"
