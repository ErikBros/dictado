"""winutil on Windows: single instance by named mutex, CUDA DLL dirs, DPI, a hard exit without DLL detach."""
from __future__ import annotations

import ctypes
import os
import site
import sys
from pathlib import Path


_mutex = None


def single_instance(name: str) -> bool:
    """True if we are the only holder of the named mutex."""
    global _mutex
    import win32api
    import win32event
    import winerror

    h = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(h)  # don't keep someone else's mutex alive (the restart wait loop polls this)
        return False
    _mutex = h
    return True


def release_instance() -> None:
    """Let a freshly spawned copy take the single-instance mutex."""
    global _mutex
    if _mutex is not None:
        import win32api
        win32api.CloseHandle(_mutex)
        _mutex = None


def add_cuda_dll_dirs() -> list[str]:
    """Make the pip-installed CUDA 12 DLLs (nvidia/*/bin) loadable by ctranslate2."""
    roots = []
    if getattr(sys, "frozen", False):  # PyInstaller: DLLs are bundled next to the exe
        roots.append(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    roots += list(site.getsitepackages())
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    added = []
    for root in roots:
        nv = Path(root) / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                continue
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            added.append(str(bin_dir))
    return added


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def hard_exit(code: int = 0) -> None:
    """Exit without interpreter teardown.

    CTranslate2/CUDA crash with 0xC0000409 in their DLL detach code after a long
    (>30 s) transcription, measured 2026-10-02 in frozen and plain Python, even
    with os._exit. TerminateProcess skips DLL detach. Callers clean up first (mic,
    mute, tray); this flushes logs and ends the process.
    """
    import logging
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
        logging.shutdown()
    finally:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
        os._exit(code)  # not reached
