"""Unmute the dictation mic only while recording, then put it back.

Both of the user's mics were found muted at volume 0 in Windows. Rather than
silently undo a mute he may want, Ecoscribe opens the mic for the recording and
restores the previous mute/volume afterwards (unless he changed it meanwhile).
"""
from __future__ import annotations

import concurrent.futures
import gc
import logging
from typing import Callable

log = logging.getLogger(__name__)
_EPS = 0.01


def list_capture_endpoints() -> list:
    """[(friendly_name, IAudioEndpointVolume)] for active capture devices."""
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL, CoCreateInstance
    from pycaw.constants import CLSID_MMDeviceEnumerator
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IMMDeviceEnumerator

    en = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
    col = en.EnumAudioEndpoints(1, 1)  # eCapture, DEVICE_STATE_ACTIVE
    out = []
    for i in range(col.GetCount()):
        dev = col.Item(i)
        name = AudioUtilities.CreateDevice(dev).FriendlyName
        vol = cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
        out.append((name, vol))
    return out


class MicGate:
    def __init__(self, name: str, target_volume: float = 0.8, enabled: bool = True,
                 lister: Callable[[], list] = list_capture_endpoints, sync: bool = False):
        self.name = name.lower()
        self.target = target_volume
        self.enabled = enabled
        self.lister = lister
        self._saved = None  # (vol_obj, mute, volume, our_mute, our_volume)
        # COM objects must stay on one thread; give the gate its own.
        self._pool = None if sync else concurrent.futures.ThreadPoolExecutor(1, initializer=_com_init)

    def _run(self, fn):
        if self._pool is None:
            return fn()
        try:
            return self._pool.submit(fn).result(timeout=3)
        finally:  # t0u.37: COM garbage from this call is freed on the gate's own thread, not wherever GC runs
            self._pool.submit(gc.collect)

    def open(self) -> bool:
        if not self.enabled or not self.name.strip():  # "" would match every mic
            return False
        try:
            return self._run(self._open)
        except Exception:
            log.exception("mic gate open failed")
            return False

    def _open(self) -> bool:
        self._saved = None
        for fname, vol in self.lister():
            if self.name not in fname.lower():
                continue
            mute, level = int(vol.GetMute()), float(vol.GetMasterVolumeLevelScalar())
            if not mute and level >= 0.05:
                return False
            new_level = level if level >= 0.05 else self.target
            vol.SetMute(0, None)
            vol.SetMasterVolumeLevelScalar(new_level, None)
            self._saved = (vol, mute, level, 0, new_level)
            log.info("mic gate: opened %s (was mute=%s vol=%.2f)", fname, mute, level)
            return True
        return False

    def restore(self) -> None:
        # Always go through the gate's thread: it runs after any open() still in
        # flight, so a slow (or timed-out) open can't leave the mic unmuted.
        try:
            self._run(self._restore)
        except Exception:
            log.exception("mic gate restore failed")

    def _restore(self) -> None:
        if self._saved is None:
            return
        vol, mute, level, our_mute, our_level = self._saved
        self._saved = None
        cur_mute, cur_level = int(vol.GetMute()), float(vol.GetMasterVolumeLevelScalar())
        if cur_mute != our_mute or abs(cur_level - our_level) > _EPS:
            log.info("mic gate: user changed the mic during recording, leaving it")
            return
        vol.SetMasterVolumeLevelScalar(level, None)
        vol.SetMute(mute, None)


def _com_init():
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
