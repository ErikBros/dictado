"""Hook Ecoscribe's MCP server into the Claude desktop app (t0u.31).

Claude desktop reads `claude_desktop_config.json`: in %APPDATA%\\Claude for the classic
installer, under %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude for the
Microsoft Store build (the user's). connect() adds `mcpServers.ecoscribe` to every one it finds
(everything else in the file is kept; a .bak of the first version is left next to it) and drops the
`dictado` entry from before the rename (dictado-c9u); relink_old() does that on its own at start.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

NAME = "ecoscribe"
OLD_NAME = "dictado"  # before the rename (dictado-c9u)


def config_files(appdata: Path | None = None, localappdata: Path | None = None) -> list[Path]:
    appdata = Path(appdata or os.environ.get("APPDATA", ""))
    local = Path(localappdata or os.environ.get("LOCALAPPDATA", ""))
    dirs = [d for d in sorted((local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude")) if d.is_dir()]
    if (appdata / "Claude").is_dir() or not dirs:
        dirs.append(appdata / "Claude")
    return [d / "claude_desktop_config.json" for d in dirs]


def server_entry(exe: str | None = None) -> dict:
    return {"command": exe or sys.executable, "args": ["--mcp"]}


def _servers(f: Path) -> dict:
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("mcpServers", {}) or {}
    except (OSError, ValueError, AttributeError):
        return {}


def is_connected(files: list[Path]) -> bool:
    return any(NAME in _servers(f) or OLD_NAME in _servers(f) for f in files)


def relink_old(files: list[Path], entry: dict) -> list[Path]:
    """Files that still had the old `dictado` entry, now pointing at this app as `ecoscribe`."""
    return connect([f for f in files if OLD_NAME in _servers(f)], entry)


def connect(files: list[Path], entry: dict) -> list[Path]:
    done = []
    for f in files:
        data = {}
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8") or "{}")  # unreadable JSON: raise, never overwrite it
            bak = f.with_suffix(".json.bak")
            if not bak.exists():
                shutil.copyfile(f, bak)
        servers = data.setdefault("mcpServers", {})
        servers.pop(OLD_NAME, None)
        servers[NAME] = entry
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
        done.append(f)
    return done


if sys.platform == "darwin":  # ~/Library/Application Support/Claude (ecoscribe/platform/macos/claude_link.py)
    from .platform.macos.claude_link import config_files  # noqa: F811
