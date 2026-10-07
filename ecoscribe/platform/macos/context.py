"""Names from the window you dictate into, on macOS (uat.7): context.window_texts through Accessibility.

Read-only, local, never stored (the log only counts names), same as the UI Automation version: the focused
window's title, the titles/labels/static texts of its elements (breadth-first, capped), and the end of
the text field you are typing in. Every AX call has a short messaging timeout, so a hung app can't
stall the read; it runs at the tap while the user talks, never after the stop.
Electron/Chrome expose their web content only to assistive tech that asks for it (AXManualAccessibility);
that is not switched on here (it can slow those apps), so for them it's the window title + native parts.
"""
from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)
TEXT_ATTRS = ("AXTitle", "AXDescription", "AXValue")
TEXT_ROLES = {"AXStaticText", "AXButton", "AXLink", "AXHeading", "AXCell", "AXRow", "AXMenuButton", "AXTab",
              "AXRadioButton", "AXCheckBox", "AXPopUpButton", "AXImage", "AXGroup", "AXWindow"}


def _attr(el, name):
    from ApplicationServices import AXUIElementCopyAttributeValue
    err, val = AXUIElementCopyAttributeValue(el, name, None)
    return val if err == 0 else None


def window_texts(max_elems: int = 1500, budget_s: float = 0.25) -> list[str]:
    from AppKit import NSWorkspace
    from ApplicationServices import (AXUIElementCreateApplication, AXUIElementCreateSystemWide,
                                     AXUIElementSetMessagingTimeout)
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return []
    ax_app = AXUIElementCreateApplication(app.processIdentifier())
    AXUIElementSetMessagingTimeout(ax_app, 0.05)
    win = _attr(ax_app, "AXFocusedWindow")
    texts: list[str] = []
    if win is not None:
        title = _attr(win, "AXTitle")
        if title:
            texts.append(str(title))
        t_end = time.monotonic() + budget_s
        q, seen = deque([win]), 0
        while q and seen < max_elems and time.monotonic() < t_end:
            el = q.popleft()
            seen += 1
            role = _attr(el, "AXRole")
            if role in TEXT_ROLES:
                for a in TEXT_ATTRS:
                    v = _attr(el, a)
                    if isinstance(v, str) and v.strip() and (a != "AXValue" or role == "AXStaticText"):
                        texts.append(v[:500])
            for c in _attr(el, "AXChildren") or ():
                q.append(c)
    sysw = AXUIElementCreateSystemWide()
    AXUIElementSetMessagingTimeout(sysw, 0.05)
    focused = _attr(sysw, "AXFocusedUIElement")
    if focused is not None:
        v = _attr(focused, "AXValue")
        if isinstance(v, str) and v:
            texts.append(v[-4000:])  # what you are writing in, the end nearest the cursor
    return texts
