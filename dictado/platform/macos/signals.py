"""Named events on macOS: one Unix datagram socket per name in <data>/run.

Windows uses named kernel events (Local\\DictadoReload, Local\\DictadoCommand...). Here the
process that waits binds <name>.sock; signal() sends it one datagram and says whether anyone was
listening (same as OpenEvent failing when nobody created the event). Auto-reset by nature: each
datagram wakes one wait().
"""
from __future__ import annotations

import os
import socket
import threading

from .sysutil import run_dir, safe


def sock_path(name: str) -> str:
    """A short private folder in /tmp (Unix socket paths max out at 104 bytes), one per data dir, so a
    test instance and the real app never share a name."""
    import hashlib
    key = hashlib.sha1(str(run_dir()).encode()).hexdigest()[:10]
    d = f"/tmp/dictado-{os.getuid()}-{key}"
    os.makedirs(d, mode=0o700, exist_ok=True)
    return f"{d}/{safe(name)}.sock"


def signal(name: str, payload: bytes = b"1") -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        s.sendto(payload, sock_path(name))
        return True
    except OSError:  # nobody listening (no file, or a stale one from a crash)
        return False
    finally:
        s.close()


class Listener:
    def __init__(self, name: str):
        self.path = sock_path(name)
        try:
            os.unlink(self.path)  # a stale socket from a crashed owner
        except FileNotFoundError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(self.path)
        self._closed = threading.Event()

    def wait(self, timeout: float | None = None) -> bytes | None:
        """The payload of the next signal, or None on timeout / after close()."""
        if self._closed.is_set():
            return None
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except (socket.timeout, OSError):
            return None
        return None if self._closed.is_set() else data

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.sendto(b"", self.path)  # wake a blocked wait()
        except OSError:
            pass
        self.sock.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
