"""Where the speaker add-on lives on macOS (diarize.addon_exe for the Mac).

"Dictado Speakers.app" (PyTorch + pyannote, a separate download like on Windows), dragged to
/Applications or ~/Applications. Its binary takes the same arguments as DictadoSpeakers.exe:
<audio> <out.json>, plus the <out>.voices.json sidecar.
"""
from __future__ import annotations

from pathlib import Path

BINARY = Path("Dictado Speakers.app") / "Contents" / "MacOS" / "DictadoSpeakers"


def addon_exe(home: Path | None = None) -> Path:
    places = [Path("/Applications"), Path(home or Path.home()) / "Applications"]
    for p in places:
        if (p / BINARY).is_file():
            return p / BINARY
    return places[0] / BINARY  # not installed: where it will be
