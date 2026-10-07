"""window_texts on Windows: the focused window's title and control texts through UI Automation
(macOS: ecoscribe/platform/macos/context.py). Shared name picking lives in ecoscribe/context.py."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


# ---------- Windows: read the focused window ----------
# t0u.37: two crashes in 1.4.0 were "a COM method call on an already freed object"
# (_ctypes.c:4180, PyCFuncPtr_call reading a dead vtable). Every UI Automation object now
# lives and dies on ONE thread for the life of the app, and that thread collects its own
# garbage after each read, so the cyclic GC can never release a COM object somewhere else.
_uia = None


class _ComThread:
    """One MTA thread that owns every UIA object. call(fn) runs fn there and waits."""

    def __init__(self):
        import queue
        self._q: "queue.SimpleQueue" = queue.SimpleQueue()
        self._t = threading.Thread(target=self._loop, name="ecoscribe-uia", daemon=True)
        self._t.start()

    @property
    def ident(self):
        return self._t.ident

    def _loop(self) -> None:
        import gc
        try:
            import comtypes
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except Exception:
            log.debug("COM init on the UIA thread", exc_info=True)
        while True:
            fn, box, done = self._q.get()
            try:
                box["value"] = fn()
            except BaseException as e:  # noqa: BLE001  (handed back to the caller as text only)
                box["error"] = f"{type(e).__name__}: {e}"
            finally:
                done.set()
                fn = None  # noqa: F841
                gc.collect()  # COM garbage from this read dies HERE, on its own thread

    def call(self, fn, timeout: float):
        box, done = {}, threading.Event()
        self._q.put((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError("screen read took too long")
        if "error" in box:
            raise RuntimeError(box["error"])
        return box["value"]


_com: "_ComThread | None" = None


_com_lock = threading.Lock()


def com_thread() -> _ComThread:
    global _com
    with _com_lock:
        if _com is None:
            _com = _ComThread()
        return _com


def _automation():
    """The CUIAutomation object; only ever called on the UIA thread."""
    global _uia
    if _uia is None:
        import comtypes
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        _uia = comtypes.CoCreateInstance(CUIAutomation._reg_clsid_, interface=IUIAutomation,
                                         clsctx=comtypes.CLSCTX_INPROC_SERVER)
    return _uia


def _read(hwnd: int, max_elems: int) -> list[str]:
    """Runs on the UIA thread. Returns plain strings only: no COM object leaves this function."""
    import comtypes
    texts: list[str] = []
    uia = _automation()
    from comtypes.gen.UIAutomationClient import (IUIAutomationValuePattern, TreeScope_Descendants,
                                                 TreeScope_Element, UIA_NamePropertyId, UIA_ValuePatternId)
    cache = found = el = vp = None
    try:
        cache = uia.CreateCacheRequest()
        cache.AddProperty(UIA_NamePropertyId)
        cache.TreeScope = TreeScope_Element
        found = uia.ElementFromHandle(hwnd).FindAllBuildCache(TreeScope_Descendants, uia.ControlViewCondition, cache)
        for i in range(min(found.Length, max_elems)):
            el = found.GetElement(i)
            name = el.CachedName
            if name:
                texts.append(str(name))
    except (comtypes.COMError, ValueError, OSError):
        log.debug("uia read failed")  # no exc_info: a traceback would keep COM objects alive
    finally:
        cache = found = el = None
    try:
        vp = uia.GetFocusedElement().GetCurrentPattern(UIA_ValuePatternId)
        if vp:
            val = vp.QueryInterface(IUIAutomationValuePattern).CurrentValue
            if val:
                texts.append(str(val)[-4000:])  # what you are writing in, the end nearest the cursor
    except (comtypes.COMError, ValueError, OSError, AttributeError):
        pass
    finally:
        vp = None
    return texts


def window_texts(max_elems: int = 1500, hwnd: int | None = None, timeout: float = 2.0) -> list[str]:
    """Title + control names of the foreground window (or `hwnd`) + the text you are writing in.
    One cached FindAll: 5-25 ms on the user's windows (Terminal, Chrome, Explorer, Discord, 2026-10-05)."""
    import ctypes
    from ctypes import wintypes as w
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # own instance: never touch windll's shared argtypes
    user32.GetForegroundWindow.restype = w.HWND
    user32.GetWindowTextLengthW.argtypes = (w.HWND,)
    user32.GetWindowTextW.argtypes = (w.HWND, w.LPWSTR, ctypes.c_int)
    hwnd = hwnd or user32.GetForegroundWindow()
    if not hwnd:
        return []
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    title = buf.value
    return [title] + com_thread().call(lambda: _read(hwnd, max_elems), timeout)
