"""Start at login on macOS: a per-user LaunchAgent (works for a self-signed app; no admin, no helper)."""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

NAME = "com.erikbros.ecoscribe"
OLD_NAME = "com.erikbros.dictado"  # before the rename (dictado-c9u)


def _plist(name: str = NAME) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{name}.plist"


def app_command() -> str | None:
    """The binary the agent starts; None when not running as the installed .app."""
    if not getattr(sys, "frozen", False):
        return None
    return sys.executable


def get(name: str = NAME) -> str | None:
    try:
        return plistlib.loads(_plist(name).read_bytes())["ProgramArguments"][0]
    except (OSError, KeyError, IndexError, ValueError, plistlib.InvalidFileException):
        return None


def is_enabled(name: str = NAME) -> bool:
    return get(name) is not None


def enable(command: str, name: str = NAME) -> None:
    p = _plist(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    # RunAtLoad only: KeepAlive would fight Quit and the restart-on-save handover
    p.write_bytes(plistlib.dumps({"Label": name, "ProgramArguments": [command], "RunAtLoad": True,
                                  "ProcessType": "Interactive", "LimitLoadToSessionType": "Aqua"}))


def disable(name: str = NAME) -> None:
    p = _plist(name)
    if p.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{_uid()}", str(p)], capture_output=True)
        p.unlink(missing_ok=True)


def _uid() -> int:
    import os
    return os.getuid()
