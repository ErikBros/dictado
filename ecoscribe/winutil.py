"""Process helpers: logging here; single instance, CUDA DLL dirs, DPI and hard exit per platform."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(path: Path, level: int = logging.INFO) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


if sys.platform == "darwin":  # macOS: file lock, no CUDA/DPI, os._exit (ecoscribe/platform/macos/sysutil.py)
    from .platform.macos.sysutil import add_cuda_dll_dirs, hard_exit, release_instance, set_dpi_aware, single_instance  # noqa: F401
else:  # named mutex, CUDA DLL dirs, TerminateProcess (ecoscribe/platform/windows/sysutil.py)
    from .platform.windows.sysutil import add_cuda_dll_dirs, hard_exit, release_instance, set_dpi_aware, single_instance  # noqa: F401
