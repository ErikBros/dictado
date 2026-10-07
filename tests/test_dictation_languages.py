"""Dictation in your languages (dictado-bvf): any mix of en/es/sv/el, auto-detected among them,
sticky to the last one on close calls, forced per dictation with the dictation key + L."""
import sys
import time

import numpy as np
import pytest

from ecoscribe.app import App
from ecoscribe.choose import pick_language
from ecoscribe.config import Config, WhisperCfg
from ecoscribe.deliver import DeliveryResult
from ecoscribe.engine import Result, dictation_model
from ecoscribe.window import parse_languages
from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait

RCTRL = 0xA3
SR = 16000


def test_any_mix_of_your_languages():
    extra = ["es", "el"]  # added on top of English + Swedish (dictado-ehs)
    assert parse_languages("en,es,sv,el", extra) == ["en", "sv", "es", "el"]
    assert parse_languages("el", extra) == ["el"] and parse_languages("sv,en") == ["en", "sv"]
    for bad in ("", "fr", "en,xx", "el"):  # "el" without Greek added
        with pytest.raises(ValueError):
            parse_languages(bad, extra if bad != "el" else [])


def test_swedish_or_greek_in_the_mix_runs_on_large_v3():
    assert dictation_model(WhisperCfg(languages=["en", "es"]))[0] == "large-v3-turbo"
    for langs in (["sv"], ["el"], ["en", "es", "sv", "el"], ["en", "el"]):
        assert "large-v3" in dictation_model(WhisperCfg(languages=langs))[0] and "turbo" not in dictation_model(
            WhisperCfg(languages=langs))[0]


def test_close_calls_stay_with_the_last_language():
    probs = [("es", 0.48), ("en", 0.40), ("pt", 0.9)]
    allowed = ["en", "es", "sv", "el"]
    assert pick_language(probs, allowed) == "es"  # pt isn't one of yours
    assert pick_language(probs, allowed, prefer="en") == "en"  # 0.08 apart: stays English
    assert pick_language([("es", 0.8), ("en", 0.1)], allowed, prefer="en") == "es"  # clearly Spanish
    assert pick_language([], allowed, prefer="el") == "el"


class LangEngine:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        lang = kw.get("lang") or "es"
        return Result(text=f"hola {lang} ", lang=lang, speech_s=1.0, ms=5)


def make(langs):
    cfg = Config()
    cfg.whisper.languages = langs
    eng, ui = LangEngine(), FakeUi()
    app = App(cfg, FakeRecorder(1.0), eng, lambda t: DeliveryResult(True, "x.exe", "ok"), ui, gate=FakeGate())
    app.start()
    return app, eng, ui


def dictate(app, eng):
    n = len(eng.calls)
    app.on_action("toggle")
    app.on_action("toggle")
    assert wait(lambda: len(eng.calls) > n)
    time.sleep(0.05)
    return eng.calls[-1]


def test_key_cycles_the_next_dictation_and_it_is_one_shot():
    app, eng, ui = make(["en", "es", "sv", "el"])
    for want in ("en", "es"):
        app.on_action("lang")
    assert app.next_lang == "es" and ("flash", "Next dictation: Spanish", 2.5) in ui.events
    assert dictate(app, eng) == {"lang": "es"}
    assert app.next_lang is None  # back to auto
    assert dictate(app, eng) == {"prefer": "es"}  # auto, leaning to the last one
    assert ("flash", "✓ ES", 1.2) in ui.events
    for _ in range(5):
        app.on_action("lang")  # en es sv el -> auto
    assert app.next_lang is None and ("flash", "Next dictation: auto", 2.5) in ui.events


def test_one_language_set_says_so():
    app, eng, ui = make(["en"])
    app.on_action("lang")
    assert app.next_lang is None and any("One language set" in str(e) for e in ui.events)
    assert dictate(app, eng) == {}  # no detection, no flash
    assert not any(str(e).startswith("('flash', '✓") for e in ui.events)


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the Windows keyboard hook (macOS: dictado-982)")


@windows_only
def test_hook_swallows_L_only_with_the_dictation_key_held():
    from ecoscribe.hook import VK_LANG, HookThread
    events = []
    h = HookThread(lambda a: None, RCTRL, 0.3, emit=events.append, consume=False)
    assert not h.lang_key(VK_LANG, True)  # a normal L: typed as usual
    h._toggle_down = True
    assert h.lang_key(VK_LANG, True) and h.lang_key(VK_LANG, True)  # swallowed, auto-repeat too
    assert [e[0] for e in events] == ["lang"]  # but only one cycle
    h._toggle_down = False  # Right Ctrl released before L
    assert h.lang_key(VK_LANG, False) and not h._lang_held  # its up is swallowed too
    assert not h.lang_key(0x43, True)  # Right Ctrl + C is untouched


@windows_only
def test_combo_hotkeys_keep_L():
    from ecoscribe.hook import VK_LANG, HookThread
    from ecoscribe.hotkeys import ComboMatcher
    h = HookThread(lambda a: None, RCTRL, 0.3, emit=lambda e: None, consume=False, combo=ComboMatcher("ctrl+shift+d"))
    h._toggle_down = True
    assert not h.lang_key(VK_LANG, True)
