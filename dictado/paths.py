"""Where Dictado keeps its files: %LOCALAPPDATA%/%APPDATA% on Windows, Application Support on macOS."""
import os
import sys
from pathlib import Path

MAC_DIR = Path.home() / "Library" / "Application Support" / "Dictado"


def data_dir() -> Path:
    if sys.platform == "darwin":
        d = Path(os.environ.get("DICTADO_DATA_DIR") or MAC_DIR)
    else:
        d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "dictado"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    if sys.platform == "darwin":
        return Path(os.environ.get("DICTADO_DATA_DIR") or MAC_DIR) / "config.toml"
    return Path(os.environ.get("APPDATA", Path.home())) / "dictado" / "config.toml"


def downloads_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"
