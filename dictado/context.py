"""Names from the window you dictate into ([text] screen_names, t0u.27).

At the tap, a background thread reads the focused window's title and the text of its
controls through Windows UI Automation (local, nothing leaves the PC) and keeps the
words that look like names: capitalised mid-sentence, or with a capital inside
(McDonald, pyannote stays out). They go after "Your words" in that dictation's
Whisper prompt, so a name on screen is spelled the way the screen spells it.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter

log = logging.getLogger(__name__)

MAX_NAMES = 25
# Capitalised words that are not names: sentence starters, UI chrome, weekdays and months.
_COMMON = set("""
a an and are as at be but by can do for from has have he her his how i if in is it its let me my no
not of on or our she so that the their them then there these they this to up us was we what when
where which who why will with you your yes ok okay hi hello hey thanks thank dear best regards
new open close save cancel edit view file help home search settings send reply forward delete
inbox draft drafts sent archive more share copy paste undo redo back next today yesterday tomorrow
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december am pm
el la los las un una y o de del en con por para que es no si hola gracias
och att det som en ett jag du han hon vi ni de är på för med till av inte hej tack
""".split())
_WORD = re.compile(r"[^\W\d_][\w'’\-]*", re.UNICODE)
_SENT_END = re.compile(r"[.!?:;]\s*$")
_SEGMENT = re.compile(r"\s*(?:[\n\r\t|•·–—]| - )\s*")


def _looks_named(w: str) -> bool:
    return (w[0].isupper() or any(c.isupper() for c in w[1:])) and len(w) > 1 and not w.isupper() \
        or (w.isupper() and 2 <= len(w) <= 6)  # acronyms: AWS, GDPR


def names_from_text(texts, limit: int = MAX_NAMES) -> list[str]:
    """Name-like words from on-screen texts, most frequent first.

    A capitalised word at the start of a sentence only counts if the same word also shows
    up capitalised mid-sentence somewhere ("Sarah said" at the start of one line and
    "thanks Sarah" in another). Common words are always dropped."""
    mid, start = Counter(), Counter()
    for t in texts:
        for seg in _SEGMENT.split(str(t or "")):
            words = [m for m in _WORD.finditer(seg)]
            # a short all-capitalised label ("Johanna Lindqvist", a title part) is a name as a whole
            label = 0 < len(words) <= 4 and all(m.group(0)[0].isupper() for m in words)
            for m in words:
                w = m.group(0).strip("'’-")
                if len(w) < 2 or w.lower() in _COMMON or not _looks_named(w):
                    continue
                before = seg[:m.start()]
                at_start = not label and (not before.strip() or _SENT_END.search(before))
                (start if at_start else mid)[w] += 1
    for w, n in start.items():
        if w in mid:
            mid[w] += n
    return [w for w, _ in mid.most_common(limit)]


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
        self._t = threading.Thread(target=self._loop, name="dictado-uia", daemon=True)
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


class ScreenNames:
    """Started at the tap, read at the stop: never adds time after you stop talking."""

    def __init__(self, reader=None):
        self.reader = reader or (lambda: window_texts())  # late-bound: tests swap window_texts
        self._names: list[str] = []
        self._done = threading.Event()

    def start(self) -> "ScreenNames":
        threading.Thread(target=self._run, name="dictado-screen", daemon=True).start()
        return self

    def _run(self) -> None:
        t0 = time.monotonic()
        try:
            self._names = names_from_text(self.reader())
        except Exception:
            log.exception("screen names failed")
        finally:
            self._done.set()
        log.info("screen names n=%d ms=%d", len(self._names), (time.monotonic() - t0) * 1000)

    def get(self, wait_s: float = 0.05) -> list[str]:
        """The names, or [] if the read is not done yet (never holds up the paste)."""
        return list(self._names) if self._done.wait(wait_s) else []
