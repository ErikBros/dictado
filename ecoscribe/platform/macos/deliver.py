"""deliver on macOS: put the transcript wherever the cursor is now (see ecoscribe/deliver.py).

NSPasteboard + a synthesized Cmd+V works in every app. The text is marked transient and concealed
(the nspasteboard.org convention clipboard managers honor), the previous text comes back 0.8 s later
unless someone copied since, and a held modifier or Secure Input (a password field, some terminals)
leaves the text on the clipboard instead of firing a wrong shortcut.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from dataclasses import dataclass

from . import keys

log = logging.getLogger(__name__)
TRANSIENT = "org.nspasteboard.TransientType"
CONCEALED = "org.nspasteboard.ConcealedType"


@dataclass
class DeliveryResult:
    pasted: bool
    target_exe: str
    reason: str
    waited_ms: int = 0


class ClipboardBusy(Exception):
    pass


def _pb():
    from AppKit import NSPasteboard
    return NSPasteboard.generalPasteboard()


def _read() -> tuple[str | None, bool]:
    """(text or None, the clipboard holds something that is not text)."""
    from AppKit import NSPasteboardTypeString
    pb = _pb()
    types = list(pb.types() or [])
    text = pb.stringForType_(NSPasteboardTypeString)
    return (str(text) if text is not None else None), bool(types) and text is None


def get_clipboard_text() -> str | None:
    return _read()[0]


def set_clipboard_text(s: str | None, private: bool = True) -> None:
    from AppKit import NSPasteboardTypeString
    pb = _pb()
    pb.clearContents()
    if s is None:
        return
    if private:
        pb.declareTypes_owner_([NSPasteboardTypeString, TRANSIENT, CONCEALED], None)
        pb.setString_forType_("", TRANSIENT)
        pb.setString_forType_("", CONCEALED)
    pb.setString_forType_(s, NSPasteboardTypeString)


def change_count() -> int:
    return int(_pb().changeCount())


def foreground_exe() -> str:
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.localizedName() or app.bundleIdentifier() or "") if app else ""


_carbon = None


def secure_input() -> bool:
    """Secure Event Input on (password field, a terminal's secure keyboard entry): no synthetic keys."""
    global _carbon
    try:
        if _carbon is None:
            _carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            _carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
        return bool(_carbon.IsSecureEventInputEnabled())
    except OSError:
        return False


def can_post() -> bool:
    """Synthetic keys need the Accessibility permission; without it CGEventPost does nothing, silently."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def _wait_modifiers_released(max_s: float = 1.5) -> int:
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_s and keys.modifiers_down():
        time.sleep(0.02)
    return int((time.monotonic() - t0) * 1000)


def deliver(text: str, restore_delay_s: float = 0.8) -> DeliveryResult:
    if not text:
        return DeliveryResult(False, "", "empty")
    exe = foreground_exe()
    try:
        prior, had_non_text = _read()
        set_clipboard_text(text, private=True)
    except Exception:
        log.exception("clipboard write failed")
        return DeliveryResult(False, exe, "clipboard_busy")
    seq = change_count()
    waited = _wait_modifiers_released()
    if keys.modifiers_down():
        return DeliveryResult(False, exe, "modifier_held", waited)
    exe = foreground_exe() or exe
    if secure_input():
        return DeliveryResult(False, exe, "secure_input", waited)  # like "elevated" on Windows
    if not can_post():
        return DeliveryResult(False, exe, "no_accessibility", waited)
    keys.paste()
    if not had_non_text:
        threading.Timer(restore_delay_s, _restore, args=(prior, seq)).start()
    return DeliveryResult(True, exe, "ok", waited)


def _restore(prior: str | None, seq: int) -> None:
    try:
        if change_count() != seq:
            return  # someone copied something new since; leave it
        set_clipboard_text(prior, private=False)
    except Exception:
        log.exception("clipboard restore failed")
