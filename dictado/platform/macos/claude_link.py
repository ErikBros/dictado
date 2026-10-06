"""Where the Claude desktop app keeps its settings on macOS (claude_link.config_files for the Mac).

One file: ~/Library/Application Support/Claude/claude_desktop_config.json (there is no Store build).
connect() and is_connected() are shared.
"""
from __future__ import annotations

from pathlib import Path


def config_files(home: Path | None = None) -> list[Path]:
    return [Path(home or Path.home()) / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
