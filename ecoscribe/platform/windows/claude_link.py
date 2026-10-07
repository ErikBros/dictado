"""Where the Claude desktop app keeps its config on Windows: %APPDATA%\\Claude (classic installer) and
the Microsoft Store build's LocalCache (macOS: ecoscribe/platform/macos/claude_link.py)."""
from __future__ import annotations

import os
from pathlib import Path


def config_files(appdata: Path | None = None, localappdata: Path | None = None) -> list[Path]:
    appdata = Path(appdata or os.environ.get("APPDATA", ""))
    local = Path(localappdata or os.environ.get("LOCALAPPDATA", ""))
    dirs = [d for d in sorted((local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude")) if d.is_dir()]
    if (appdata / "Claude").is_dir() or not dirs:
        dirs.append(appdata / "Claude")
    return [d / "claude_desktop_config.json" for d in dirs]
