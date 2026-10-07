"""winutil on macOS: single instance by file lock, no CUDA, no DPI call, a hard exit without teardown."""
from __future__ import annotations

import fcntl
import logging
import os
import re
import sys
from pathlib import Path

_locks: dict[str, int] = {}  # name -> fd holding the lock
_last: str | None = None


def run_dir() -> Path:
    from ... import paths
    d = paths.data_dir() / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe(name: str) -> str:
    """'Local\\EcoscribeSingleInstance' -> 'EcoscribeSingleInstance' (a file name)."""
    return re.sub(r"[^A-Za-z0-9._-]", "", name.split("\\")[-1]) or "ecoscribe"


def single_instance(name: str) -> bool:
    """True if we now hold the lock called `name`. A lock dies with its process, so a crash never
    leaves a stale one. Like the named mutex, a second try in the same process says False."""
    global _last
    fd = os.open(run_dir() / f"{safe(name)}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _locks[name] = fd
    _last = name
    return True


def held(name: str) -> bool:
    """Does any process hold the lock called `name`? (named-mutex check, like OpenMutex)"""
    path = run_dir() / f"{safe(name)}.lock"
    if name in _locks:
        return True
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def holds(name: str) -> bool:
    return name in _locks


def release_instance(name: str | None = None) -> None:
    """Let a freshly spawned copy take the lock (the last one taken, like winutil's one mutex)."""
    global _last
    name = name or _last
    fd = _locks.pop(name, None) if name else None
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    if name == _last:
        _last = None


def add_cuda_dll_dirs() -> list[str]:
    return []


def set_dpi_aware() -> None:
    pass


def hard_exit(code: int = 0) -> None:
    """Exit without interpreter teardown (models are never destroyed; same contract as Windows)."""
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
        logging.shutdown()
    finally:
        os._exit(code)
