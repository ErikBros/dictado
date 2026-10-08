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


def foreground_title() -> str:
    """The focused window's title of the frontmost app (Accessibility, 50 ms messaging timeout)."""
    from AppKit import NSWorkspace
    from ApplicationServices import AXUIElementCreateApplication, AXUIElementSetMessagingTimeout
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return ""
    ax_app = AXUIElementCreateApplication(app.processIdentifier())
    AXUIElementSetMessagingTimeout(ax_app, 0.05)
    win = _attr(ax_app, "AXFocusedWindow")
    title = _attr(win, "AXTitle") if win is not None else None
    return str(title) if title else ""


# dictado-uee: localizedName is translated on a non-English macOS (Messages under its own language's name), so
# coach matches the app by bundle id: these, plus the meeting apps and browsers in detect.BUNDLES
APP_IDS = {"com.apple.mail": "mail", "com.apple.mobilesms": "messages", "com.microsoft.outlook": "outlook",
           "com.readdle.smartemail-mac": "spark", "com.anthropic.claudefordesktop": "claude", "com.openai.chat": "chatgpt",
           "com.apple.terminal": "terminal", "com.googlecode.iterm2": "iterm2", "com.mitchellh.ghostty": "ghostty",
           "dev.warp.warp-stable": "warp", "com.microsoft.vscode": "code", "dev.zed.zed": "zed"}


def app_key(bundle: str) -> str:
    """The English app name coach knows for a bundle id, or "" (the caller falls back to localizedName)."""
    from .detect import BUNDLES, app_of_bundle
    b = (bundle or "").lower()
    if b in APP_IDS:
        return APP_IDS[b]
    return app_of_bundle(b) if any(b.startswith(p) for p in BUNDLES) else ""


def foreground_app() -> str:
    """app_key of the frontmost app (read at the paste, with the window title)."""
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app_key(str(app.bundleIdentifier() or "")) if app is not None else ""


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


# dictado-cd2: is the cursor in a text box at the stop? Like Windows platform/windows/context.focus_kind.
EDIT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
NOT_TEXT_ROLES = {"AXButton", "AXCheckBox", "AXRadioButton", "AXList", "AXOutline", "AXTable", "AXRow", "AXCell",
                  "AXImage", "AXMenuItem", "AXMenuBarItem", "AXPopUpButton", "AXMenuButton", "AXSlider",
                  "AXTabGroup", "AXToolbar", "AXDisclosureTriangle", "AXBrowser", "AXGrid", "AXColumn"}


def classify_focus(role: str | None, editable_ancestor: bool, range_settable: bool) -> str:
    """"text", "other" (positively not a text box) or "unknown". Unknown pastes as before: an app with
    little accessibility (Tk, games, a remote desktop) shows nothing useful, and a paste there is
    better than a lost dictation."""
    if role in EDIT_ROLES or editable_ancestor or range_settable:
        return "text"
    if role in NOT_TEXT_ROLES:
        return "other"
    return "unknown"


def focus_kind() -> str:
    """"text" / "other" / "unknown" for whatever has keyboard focus (Accessibility, a few ms)."""
    try:
        from ApplicationServices import (AXUIElementCreateSystemWide, AXUIElementIsAttributeSettable,
                                         AXUIElementSetMessagingTimeout)
        sysw = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(sysw, 0.1)
        el = _attr(sysw, "AXFocusedUIElement")
        if el is None:
            return "unknown"
        role = _attr(el, "AXRole")
        err, settable = AXUIElementIsAttributeSettable(el, "AXSelectedTextRange", None)
        kind = classify_focus(str(role) if role else None, _attr(el, "AXEditableAncestor") is not None,
                              err == 0 and bool(settable))
        log.debug("focus role=%s -> %s", role, kind)
        return kind
    except Exception:
        log.debug("focus check failed", exc_info=True)
        return "unknown"
