"""System audio for meetings on macOS: loopback.Loopback's contract on a Core Audio process tap.

The tap lives in a small Swift helper (systap.swift -> ecoscribe-systap) that streams the mix of every
app's output, Ecoscribe's own tones excluded, as interleaved float32 after a JSON header line. This
side reuses the Windows pieces: the same mono fold + resampler to 16 kHz and the same GapFiller, so
the system track sits on the wall clock next to the mic exactly like on the PC.

Never blocks the meeting: start() spawns the helper and returns. Until audio flows (the first time,
macOS may still be waiting for the user to allow "System Audio Recording") read() gives wall-clock
zeros, the mic keeps recording, and the log says what is missing. The helper exits 3 when the
default output changes (headphones on/off); check_device() then starts a new one on the new device.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ...loopback import SR, Loopback as _Loopback

log = logging.getLogger(__name__)
SOURCE = Path(__file__).with_name("systap.swift")
NAME = "ecoscribe-systap"
NO_AUDIO_S = 10.0  # no header this long after a start: say which permission is missing (once)
RETRY_S = 30.0  # a helper that failed (exit 2) is tried again this often, not in a tight loop
CHANGED = 3  # exit code: the default output device changed


def helper_path() -> Path | None:
    """The helper binary: next to the app's executable in the .app, else built once from the source
    into the data folder (a dev setup; rebuilt when systap.swift changes). None if it can't be had."""
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).with_name(NAME)
        return p if p.exists() else None
    from ... import paths
    out = paths.data_dir() / "bin" / NAME
    if out.exists() and out.stat().st_mtime >= SOURCE.stat().st_mtime:
        return out
    swiftc = shutil.which("swiftc")
    if not swiftc:
        log.error("no swiftc to build %s (install the Xcode command line tools)", NAME)
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([swiftc, "-O", "-o", str(out), str(SOURCE)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        log.error("%s build failed: %s", NAME, r.stderr[-2000:])
        return None
    log.info("built %s", out)
    return out


def _ecoscribe_pids() -> list[int]:
    """Processes whose sound stays out of the system track: this one and the background app (tones)."""
    pids = {os.getpid()}
    try:
        from ... import paths
        pids.add(int((paths.data_dir() / "ecoscribe.pid").read_text().strip()))
    except (OSError, ValueError):
        pass
    return sorted(pids)


class Loopback(_Loopback):
    def __init__(self, clock=time.monotonic, check_s: float | None = 2.0, command=None):
        super().__init__(pa_module=object(), clock=clock, check_s=check_s)  # no PyAudio on the Mac
        self.command = command  # tests: a fake helper
        self._proc: subprocess.Popen | None = None
        self._started_at = 0.0
        self._failed_at: float | None = None
        self._got_header = False
        self._warned = False

    # ---------- the helper ----------
    def _argv(self) -> list[str] | None:
        if self.command:
            return list(self.command)
        exe = helper_path()
        return [str(exe), *map(str, _ecoscribe_pids())] if exe else None

    def _open(self) -> None:
        argv = self._argv()
        if not argv:
            raise RuntimeError(f"{NAME} unavailable")
        self._gen += 1
        gen = self._gen
        self._got_header = False
        self._started_at = self.clock()
        self._proc = proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._reader, args=(proc, gen), name="ecoscribe-systap", daemon=True).start()
        threading.Thread(target=self._errors, args=(proc,), name="ecoscribe-systap-err", daemon=True).start()

    def _reader(self, proc: subprocess.Popen, gen: int) -> None:
        line = proc.stdout.readline()
        if not line:
            return
        try:
            hdr = json.loads(line)
        except ValueError:
            log.error("%s: bad header %r", NAME, line[:200])
            return
        with self._lock:
            if gen != self._gen:
                return
            self._rate, self._ch = int(hdr["rate"]), int(hdr["channels"])
            self._resampler = None
            self.device_name = hdr.get("device", "")
            self._got_header = True
        log.info("system audio device=%s rate=%d ch=%d", self.device_name, self._rate, self._ch)
        frame = 4 * self._ch
        rest = b""
        while True:
            data = proc.stdout.read(65536)
            if not data:
                return
            data = rest + data
            cut = len(data) - len(data) % frame
            rest = data[cut:]
            if cut and gen == self._gen:
                self._q.append((data[:cut], self.clock()))

    def _errors(self, proc: subprocess.Popen) -> None:
        for line in proc.stderr:
            log.warning("%s", line.decode("utf-8", "replace").rstrip())

    def _close(self) -> None:
        p, self._proc = self._proc, None
        self._gen += 1
        if p is None:
            return
        try:
            p.stdin.close()  # the helper leaves on its own when its stdin closes
            p.wait(2)
        except Exception:
            p.kill()
            try:
                p.wait(2)
            except Exception:
                pass

    def check_device(self) -> None:
        """Restart a helper that ended (output device changed, or it failed), and say once when no
        audio comes (the permission)."""
        now = self.clock()
        p = self._proc
        if p is not None and p.poll() is None:
            if not self._got_header and not self._warned and now - self._started_at > NO_AUDIO_S:
                self._warned = True
                log.warning("no system audio after %.0f s: allow Ecoscribe in System Settings > Privacy & Security > "
                            "Screen & System Audio Recording (System Audio Recording Only). Recording the mic.",
                            now - self._started_at)
            return
        code = p.returncode if p is not None else None
        if code not in (None, CHANGED):
            if self._failed_at is None:
                self._failed_at = now
                log.warning("%s ended with %s: trying again in %.0f s", NAME, code, RETRY_S)
            if now - self._failed_at < RETRY_S:
                return
        self._failed_at = None
        log.info("system audio helper ended (%s): starting a new one", "output device changed" if code == CHANGED else code)
        with self._lock:
            self._close()
            self._drain()  # still decoded with the old device's rate and channels
            try:
                self._open()
            except Exception:
                log.exception("system audio helper not restarted")
