"""Where the speaker add-on lives on Windows (diarize.addon_exe; macOS: platform/macos/speakers.py).

Its own installer puts EcoscribeSpeakers.exe in %LOCALAPPDATA%\\Programs\\Ecoscribe Speakers. Before
the rename (dictado-jtv) it was Dictado Speakers\\DictadoSpeakers.exe: still found when the new one
isn't there, so an installed 1.1.0 add-on keeps working.
"""
from __future__ import annotations

import os
from pathlib import Path

NEW = ("Ecoscribe Speakers", "EcoscribeSpeakers.exe")
OLD = ("Dictado Speakers", "DictadoSpeakers.exe")


def addon_exe(localappdata: Path | None = None) -> Path:
    progs = Path(localappdata or os.environ.get("LOCALAPPDATA", "")) / "Programs"
    for folder, exe in (NEW, OLD):
        if (progs / folder / exe).is_file():
            return progs / folder / exe
    return progs / NEW[0] / NEW[1]  # not installed: where it will be
