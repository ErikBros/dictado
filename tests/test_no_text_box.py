"""dictado-bhe: no text box under the cursor at the stop -> no Ctrl+V, the text stays on the clipboard."""
import sys

import pytest

from ecoscribe.platform.windows.context import classify_focus

EDIT, DOCUMENT, TEXT, LIST, LISTITEM, BUTTON, PANE, CUSTOM = 50004, 50030, 50020, 50008, 50007, 50000, 50033, 50025


def test_text_boxes_are_text():
    assert classify_focus(EDIT, True, False) == "text"
    assert classify_focus(DOCUMENT, None, True) == "text"  # a browser page / Word
    assert classify_focus(TEXT, None, True) == "text"  # Windows Terminal (measured 2026-10-07)
    assert classify_focus(CUSTOM, True, False) == "text"  # anything with an editable value


def test_clearly_not_a_text_box():
    assert classify_focus(LIST, None, False) == "other"  # the desktop's icons (measured)
    assert classify_focus(LISTITEM, False, False) == "other"  # a file in Explorer: Ctrl+V would paste files
    assert classify_focus(BUTTON, None, False) == "other"


def test_unknown_still_pastes():
    """A remote desktop (WSLg, mstsc), a game or an app without accessibility is a plain pane."""
    assert classify_focus(PANE, None, False) == "unknown"  # the taskbar too (measured)
    assert classify_focus(CUSTOM, None, False) == "unknown"


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows paste")
def test_deliver_leaves_it_on_the_clipboard_when_there_is_no_text_box(monkeypatch):
    from ecoscribe.platform.windows import deliver as dl
    clip, keys = [], []
    monkeypatch.setattr(dl, "foreground_exe", lambda: "explorer.exe")
    monkeypatch.setattr(dl, "_read", lambda: ("before", False))
    monkeypatch.setattr(dl, "set_clipboard_text", lambda s, private=True: clip.append(s))
    monkeypatch.setattr(dl, "_modifiers_down", lambda: False)
    monkeypatch.setattr(dl, "_wait_clipboard_quiet", lambda *a, **k: 0.0)
    monkeypatch.setattr(dl.win32clipboard, "GetClipboardSequenceNumber", lambda: 1)
    monkeypatch.setattr(dl, "send_keys", lambda ev: keys.append(ev) or len(ev))
    monkeypatch.setattr(dl, "focus_kind", lambda: "other")
    r = dl.deliver("hola ")
    assert not r.pasted and r.reason == "no_text_box" and keys == [] and clip == ["hola "]
    monkeypatch.setattr(dl, "focus_kind", lambda: "unknown")
    monkeypatch.setattr(dl, "_we_are_elevated", lambda: True)
    assert dl.deliver("hola ", restore_delay_s=60).pasted and len(keys) == 1  # unknown: pasted as before
