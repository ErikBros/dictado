"""dictado-cd2: no text box under the cursor at the stop on the Mac -> no Cmd+V, the text stays on the clipboard."""
import sys

import pytest

from ecoscribe.platform.macos.context import classify_focus


def test_text_boxes_are_text():
    assert classify_focus("AXTextField", False, True) == "text"
    assert classify_focus("AXTextArea", False, True) == "text"  # Notes, Terminal, an editor
    assert classify_focus("AXGroup", True, False) == "text"  # a contenteditable box in a web page
    assert classify_focus("AXWebArea", False, True) == "text"  # a page that takes typed text


def test_clearly_not_a_text_box():
    assert classify_focus("AXList", False, False) == "other"  # Finder icons / the desktop
    assert classify_focus("AXOutline", False, False) == "other"  # a Finder list view
    assert classify_focus("AXButton", False, False) == "other"


def test_unknown_still_pastes():
    assert classify_focus(None, False, False) == "unknown"  # nothing reported (Tk, a game, a remote desktop)
    assert classify_focus("AXWindow", False, False) == "unknown"
    assert classify_focus("AXWebArea", False, False) == "unknown"


@pytest.mark.skipif(sys.platform != "darwin", reason="the Mac paste")
def test_deliver_leaves_it_on_the_clipboard_when_there_is_no_text_box(monkeypatch):
    from ecoscribe.platform.macos import deliver as dl
    clip, pasted = [], []
    monkeypatch.setattr(dl, "foreground_exe", lambda: "Finder")
    monkeypatch.setattr(dl, "_read", lambda: ("before", False))
    monkeypatch.setattr(dl, "set_clipboard_text", lambda s, private=True: clip.append(s))
    monkeypatch.setattr(dl, "change_count", lambda: 1)
    monkeypatch.setattr(dl.keys, "modifiers_down", lambda: False)
    monkeypatch.setattr(dl, "secure_input", lambda: False)
    monkeypatch.setattr(dl, "can_post", lambda: True)
    monkeypatch.setattr(dl.keys, "paste", lambda: pasted.append(1))
    monkeypatch.setattr(dl, "focus_kind", lambda: "other")
    r = dl.deliver("hola ")
    assert not r.pasted and r.reason == "no_text_box" and pasted == [] and clip == ["hola "]
    monkeypatch.setattr(dl, "focus_kind", lambda: "unknown")
    assert dl.deliver("hola ", restore_delay_s=60).pasted and pasted == [1]  # unknown: pasted as before
