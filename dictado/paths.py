"""Where Dictado keeps its files on Windows."""
import os
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "dictado"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "dictado" / "config.toml"
