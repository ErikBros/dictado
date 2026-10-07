"""Start with Windows: the HKCU Run key (shows up in Task Manager > Startup apps)."""
from __future__ import annotations

import sys

if sys.platform != "darwin":
    import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Ecoscribe"
OLD_NAME = "Dictado"  # before the rename (dictado-c9u)


def app_command() -> str | None:
    """The command the Run key should hold; None when not running as the installed exe."""
    if not getattr(sys, "frozen", False):
        return None
    return f'"{sys.executable}"'


def get(name: str = NAME) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def is_enabled(name: str = NAME) -> bool:
    return get(name) is not None


def enable(command: str, name: str = NAME) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command)


def disable(name: str = NAME) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


if sys.platform == "darwin":  # a LaunchAgent instead of the Run key (ecoscribe/platform/macos/startup.py)
    from .platform.macos.startup import NAME, app_command, disable, enable, get, is_enabled  # noqa: F811,F401
