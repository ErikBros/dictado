"""Where the speaker add-on lives on macOS (diarize.addon_exe for the Mac).

"Ecoscribe Speakers.app" (PyTorch + pyannote, a separate download like on Windows), dragged to
/Applications or ~/Applications. Its binary takes the same arguments as DictadoSpeakers.exe:
<audio> <out.json>, plus the <out>.voices.json sidecar. Before the rename (dictado-c9u) it was
"Dictado Speakers.app": still found when the new one isn't there.
"""
from __future__ import annotations

from pathlib import Path

BINARY = Path("Ecoscribe Speakers.app") / "Contents" / "MacOS" / "EcoscribeSpeakers"
OLD_BINARY = Path("Dictado Speakers.app") / "Contents" / "MacOS" / "DictadoSpeakers"


def addon_exe(home: Path | None = None) -> Path:
    places = [Path("/Applications"), Path(home or Path.home()) / "Applications"]
    for b in (BINARY, OLD_BINARY):
        for p in places:
            if (p / b).is_file():
                return p / b
    return places[0] / BINARY  # not installed: where it will be
