"""Process bits for Windows: adopt a worker by pid after a restart, liveness, the meeting stop
event (macOS: ecoscribe/platform/macos/procs.py)."""
from __future__ import annotations


def alive(pid) -> bool:
    import ctypes
    if not pid:
        return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


class StopEvent:
    """Local\\EcoscribeMeetingStop, manual reset (the worker opens the same one)."""

    def __init__(self, name: str = "Local\\EcoscribeMeetingStop"):
        import win32event
        self._ev = win32event
        self._h = win32event.CreateEvent(None, True, False, name)

    def set(self):
        self._ev.SetEvent(self._h)

    def reset(self):
        self._ev.ResetEvent(self._h)


class PidProc:
    """Popen-like handle on a process we did not start (adopted after a restart)."""

    def __init__(self, pid: int, handle):
        self.pid, self._h = pid, handle

    def poll(self):
        import ctypes
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(self._h, ctypes.byref(code))
        return None if code.value == 259 else int(code.value)  # STILL_ACTIVE

    def kill(self):
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(self._h, 1)

    def wait(self, timeout=None):
        import ctypes
        ctypes.windll.kernel32.WaitForSingleObject(self._h, 0xFFFFFFFF if timeout is None else int(timeout * 1000))
        return self.poll()


def attach_pid(pid: int):
    """A PidProc if `pid` is still a Ecoscribe (or dev Python) process, else None: after a
    reboot the pid in meetings.json may belong to anything."""
    import ctypes
    from ... import detect
    if not pid or detect._exe_of_pid(pid) not in ("ecoscribe", "python", "pythonw"):
        return None
    h = ctypes.windll.kernel32.OpenProcess(0x100000 | 0x1000 | 0x1, False, pid)  # SYNCHRONIZE|QUERY|TERMINATE
    return PidProc(pid, h) if h else None
