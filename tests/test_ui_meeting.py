"""Pill / tray / prompt logic for meetings (no tk needed)."""
import json
from datetime import datetime

from dictado import meetui, sessions

T0 = datetime(2026, 10, 5, 14, 0, 0)


def st(status="recording", d="D", started=T0):
    return {"meeting": {"dir": d, "app": "msteams", "lang": "sv", "started": started.isoformat(), "status": status},
            "job": None, "queue": []}


EMPTY = {"meeting": None, "job": None, "queue": []}


def test_view_elapsed_and_live_line():
    v = meetui.meeting_view(st(), now=T0.timestamp() + 12 * 60 + 4, line="hej och välkomna")
    assert v == {"label": "Taking notes 12:04", "line": "hej och välkomna", "busy": False}
    v = meetui.meeting_view(st(), now=T0.timestamp() + 3600 + 65, line=None)
    assert v["label"] == "Taking notes 1:01:05" and v["line"] == ""


def test_view_finalizing_and_none():
    assert meetui.meeting_view(st("finalizing"), now=T0.timestamp(), line="x")["label"] == "Saving…"
    assert meetui.meeting_view(st("stopping"), now=T0.timestamp(), line="x")["busy"] is True
    assert meetui.meeting_view(EMPTY, now=0, line=None) is None


def test_long_line_truncated_from_the_left():
    v = meetui.meeting_view(st(), now=T0.timestamp(), line="a" * 30 + " slutet av meningen", width=24)
    assert len(v["line"]) <= 24 and v["line"].startswith("…") and v["line"].endswith("meningen")


def test_pill_layer_state_machine():
    v = meetui.meeting_view(st(), now=T0.timestamp(), line="")
    assert meetui.pill_layer("hidden", None) == "hidden"
    assert meetui.pill_layer("hidden", v) == "meeting"
    assert meetui.pill_layer("recording", v) == "dictation"  # dictating over a meeting shows Dictando
    assert meetui.pill_layer("busy", v) == "dictation"
    assert meetui.pill_layer("hidden", v) == "meeting"  # and comes back to Tomando notas


def test_tracker_done_and_failed(tmp_path):
    d = sessions.create("Reunión", "sv", "meeting", tmp_path)
    tr = meetui.Tracker()
    assert tr.update(st(d=str(d))) == []
    sessions.write_meta(d, status="done")
    assert tr.update(EMPTY) == [("done", str(d))]
    assert tr.update(EMPTY) == []
    e = sessions.create("Reunión", "sv", "meeting", tmp_path)
    tr.update(st(d=str(e)))
    sessions.write_meta(e, status="failed")
    assert tr.update(EMPTY) == [("failed", str(e))]


def test_tracker_job_done(tmp_path):
    d = sessions.create("Podcast", "el", "import", tmp_path)
    tr = meetui.Tracker()
    tr.update({"meeting": None, "job": {"dir": str(d), "pct": 3}, "queue": []})
    sessions.write_meta(d, status="done")
    assert tr.update(EMPTY) == [("done", str(d))]


def test_tray_label_and_state():
    assert meetui.tray_meeting_label(EMPTY) == "Transcribe meeting now"
    assert meetui.tray_meeting_label(st()) == "Stop meeting"
    assert meetui.tray_meeting_label(st("finalizing")) == "Saving meeting…"
    assert meetui.tray_state("idle", st()) == "recording"  # red while a meeting records
    assert meetui.tray_state("idle", st("finalizing")) == "busy"
    assert meetui.tray_state("idle", EMPTY) == "idle"
    assert meetui.tray_state("busy", st()) == "busy"  # dictation states win


def test_last_live_line_reads_the_tail(tmp_path):
    p = tmp_path / "live.jsonl"
    assert meetui.last_live_line(tmp_path) is None
    with open(p, "w", encoding="utf-8") as f:
        for i in range(5000):
            f.write(json.dumps({"t0": i, "t1": i + 1, "text": f"rad {i}"}) + "\n")
        f.write('{"t0": 1, "t1"')  # a half-written line from the worker
    assert meetui.last_live_line(tmp_path) == "rad 4999"


def test_prompt_texts_and_timeout():
    p = meetui.Prompt("start", "msteams", "sv", opened_at=100.0)
    assert p.title == "Are you in a meeting? Take notes?"
    assert p.question == "Teams is using the mic. Language:"
    assert p.buttons == [("Take notes", "transcribir"), ("Not now", "ahora_no")]
    assert p.expired(109.9) is None
    assert p.expired(110.0) == "ahora_no"  # no answer in 10 s = Not now (t0u.21)
    assert p.countdown(100.0) == 10 and p.countdown(105.5) == 5 and p.countdown(109.9) == 1
    assert p.button_text("ahora_no", 103.2) == "Not now (7)" and p.button_text("transcribir", 103.2) == "Take notes"
    e = meetui.Prompt("end?", None, None, opened_at=0.0)
    assert e.title == "Did the meeting end?"
    assert e.buttons == [("Stop", "parar"), ("Keep going", "seguir")]
    assert e.expired(59.0) is None and e.expired(61.0) == "hide"  # the watcher stops it by itself
    assert e.countdown(10.0) is None and e.button_text("seguir", 10.0) == "Keep going"
    d = meetui.Prompt("done", "C:/x/2026-10-05_1400_reunion", None, opened_at=0.0)
    assert d.title == "Transcript ready" and d.buttons[0] == ("Open", "abrir")
    assert meetui.app_name("slack") == "Slack" and meetui.app_name("chrome") == "Chrome"


def test_no_em_dashes_in_strings():
    import inspect
    assert "\u2014" not in inspect.getsource(meetui)


import time

import pytest


@pytest.mark.win
def test_tk_meeting_pill_and_prompt_box():
    """Real tk: the meeting layer resizes the pill, dictation wins it, the prompt answers.
    Opens two no-activate windows for under a second; no OS input is injected."""
    import tkinter as tk
    from dictado import ui
    root = tk.Tk()
    root.withdraw()
    try:
        ov = ui.Overlay(root)
        view = meetui.meeting_view(st(), now=T0.timestamp() + 5, line="hej")
        ov.set_meeting(view)
        assert (ov.w, ov.h) == (ui.MW, ui.MH) and ov._drawn == ("Taking notes 0:05", "hej", False)
        ov.recording(0.0)
        assert (ov.w, ov.h) == (ui.RW, ui.RH)  # Dictando wins, with the cancel line (t0u.36)
        ov.idle()
        assert (ov.w, ov.h) == (ui.MW, ui.MH)  # back to Tomando notas
        ov.set_meeting(None)
        assert ov._drawn is None
        answers = []
        pw = ui.PromptWindow(root, lambda p, c, lang: answers.append((p.kind, c, lang)))
        meetui.set_langs(["es", "el"])  # Greek and Spanish added (dictado-ehs)
        pw.show(meetui.Prompt("start", "msteams", "el", opened_at=0.0))
        root.update()
        assert pw.top.winfo_exists() and pw._lang_code() == "el"
        pw._answer("transcribir")
        assert answers == [("start", "transcribir", "el")] and pw.top is None
        pw.show(meetui.Prompt("start", "slack", "sv", opened_at=-1e9))
        pw.tick()  # long expired: Ahora no
        assert answers[-1] == ("start", "ahora_no", "sv")
        pw.show(meetui.Prompt("start", "signal", "es", opened_at=time.monotonic() - 3.2))
        pw.tick()
        assert pw._btns["ahora_no"].cget("text") == "Not now (7)"  # t0u.21: the countdown on screen
        pw._answer("ahora_no")
    finally:
        root.destroy()


def test_a_note_never_hides_a_question():
    start = meetui.Prompt("start", "msteams", "sv", 0.0)
    end = meetui.Prompt("end?", None, None, 0.0)
    done = meetui.Prompt("done", "C:/x/d", None, 0.0)
    assert meetui.placement(None, start) == "show"
    assert meetui.placement(start, done) == "queue"  # job finished as a call started: the call prompt stays
    assert meetui.placement(end, done) == "queue"
    assert meetui.placement(done, start) == "show"  # a call prompt replaces a mere note
    assert meetui.placement(start, end) == "displace"


def test_tray_language_submenu():
    assert [n for _, n, _ in meetui.tray_lang_items("sv")] == ["English", "Swedish", "English + Swedish", "Detect"]
    meetui.set_langs(["es", "el"])  # dictado-ehs: the user's added languages join the list
    try:
        items = meetui.tray_lang_items("el")
        assert [n for _, n, _ in items] == ["English", "Swedish", "Spanish", "Greek", "Mixed: EN · SV · ES · EL", "Detect"]
        assert [c for c, _, ticked in items if ticked] == ["el"]  # the last language used is ticked
    finally:
        meetui.set_langs([])
    assert meetui.tray_recording(EMPTY) is False and meetui.tray_recording(st()) is True
