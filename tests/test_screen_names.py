"""Names from the window you dictate into (t0u.27).

Measured first (tools/context_bench.py, 220 real English FLEURS clips with names, turbo, 2026-10-05):
names right 76.6 % -> 87.3 %, WER 5.75 % -> 4.44 % when the names are on screen; 5.63 % when the
screen only shows names you never say (no harm); median transcription 264 -> 258 ms (no cost).
Measured with tools/context_bench.py.
"""
import time
from types import SimpleNamespace

import numpy as np

from dictado.context import ScreenNames, names_from_text
from dictado.config import TextCfg, WhisperCfg
from dictado.engine import Engine, Result


def test_names_from_a_mail_window():
    texts = ["Johanna Lindqvist - Outlook", "Re: Budget for Q3",
             "Hi Alex, Sarah said the Denver office is closed. Thanks, Tom", "Sarah is out.", "Send", "Reply all"]
    got = names_from_text(texts)
    assert got[0] == "Sarah"  # seen most often
    assert {"Johanna", "Lindqvist", "Alex", "Denver", "Tom"} <= set(got)
    assert not {"Re", "Budget", "Send", "Reply", "Hi", "Thanks"} & set(got)


def test_sentence_starts_and_common_words_are_not_names():
    assert names_from_text(["The meeting moved. However we keep Friday."]) == []
    assert names_from_text(["Then Kristineberg called. Kristineberg is fine."]) == ["Kristineberg"]
    assert names_from_text(["deploy to AWS and pyannote", "", None]) == ["AWS"]


def test_limit_keeps_the_most_frequent():
    texts = [f"met Name{i:02d} today" for i in range(40)] + ["met Zed and Zed"]
    got = names_from_text(texts, limit=5)
    assert len(got) == 5 and got[0] == "Zed"


def test_read_never_holds_up_the_paste():
    def slow():
        time.sleep(1.0)
        return ["met Johanna"]
    s = ScreenNames(slow).start()
    t0 = time.monotonic()
    assert s.get(wait_s=0.05) == [] and time.monotonic() - t0 < 0.5
    assert ScreenNames(lambda: ["met Johanna"]).start().get(wait_s=1.0) == ["Johanna"]

    def boom():
        raise OSError("uia")
    assert ScreenNames(boom).start().get(wait_s=1.0) == []


class Model:
    def __init__(self):
        self.kw = None

    def transcribe(self, audio, **kw):
        self.kw = kw
        return iter([SimpleNamespace(text=" hi", no_speech_prob=0.01)]), SimpleNamespace(duration=1.0, duration_after_vad=1.0)


def test_engine_puts_screen_names_after_your_words():
    m = Model()
    text = TextCfg()
    text.vocabulary = ["Dictado", "Johanna"]
    e = Engine(WhisperCfg(), text, model_factory=lambda *a, **k: m)
    e.model = m
    e.transcribe(np.zeros(16000, np.float32), words=["Johanna", "Lindqvist"])
    assert m.kw["initial_prompt"] == "Dictado, Johanna, Lindqvist."
    e.transcribe(np.zeros(16000, np.float32))
    assert m.kw["initial_prompt"] == "Dictado, Johanna."


def test_worker_protocol_carries_the_words():
    from tests.test_engine_proc import audio, proxy, spawner
    spawn, _ = spawner("normal")
    e = proxy(spawn)
    assert e.transcribe(audio(), words=["Johanna", "Öberg"]).text.endswith("w=Johanna,Öberg")
    assert "w=" not in e.transcribe(audio()).text
    e.close()


def _run_app(tmp_path, on, screen_words):
    from dictado.app import App
    from dictado.config import Config
    from dictado.deliver import DeliveryResult
    from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait
    cfg = Config()
    cfg.text.screen_names = on
    seen, started = [], []

    class Eng:
        def transcribe(self, audio, words=None):
            seen.append(words)
            return Result(text="hi ", lang="en", speech_s=1.0, ms=5)

    class Screen:
        def start(self):
            started.append(1)
            return self

        def get(self, wait_s=0.0):
            return screen_words
    app = App(cfg, FakeRecorder(), Eng(), lambda t: DeliveryResult(True, "x.exe", "ok"), FakeUi(), gate=FakeGate(),
              history_path=tmp_path / "h.jsonl", screen=Screen)
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    wait(lambda: seen)
    return seen, started


def test_app_reads_the_window_at_the_tap_when_on(tmp_path):
    assert _run_app(tmp_path, True, ["Johanna"]) == ([["Johanna"]], [1])


def test_app_off_never_reads_the_window(tmp_path):
    assert _run_app(tmp_path, False, ["Johanna"]) == ([None], [])


def test_setting_round_trips(tmp_path):
    from dictado.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.get_settings()["values"]["screen_names"] is True
    assert api.save_settings({"screen_names": False})["ok"]
    assert api.get_settings()["values"]["screen_names"] is False


import pytest  # noqa: E402


@pytest.mark.real_window_texts
def test_every_uia_read_runs_on_one_permanent_thread(monkeypatch):
    """t0u.37: COM objects must never be made, used or freed on different threads."""
    import threading
    from dictado import context
    seen = []

    def fake_read(hwnd, max_elems):
        seen.append(threading.get_ident())
        return ["Sarah Lindqvist"]
    monkeypatch.setattr(context, "_read", fake_read)
    outs = []
    threads = [threading.Thread(target=lambda: outs.append(context.window_texts(hwnd=1))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(seen)) == 1 and seen[0] == context.com_thread().ident
    assert seen[0] not in {t.ident for t in threads}
    assert all(o[-1] == "Sarah Lindqvist" for o in outs)


@pytest.mark.real_window_texts
def test_a_failed_read_comes_back_as_an_error_not_a_com_object(monkeypatch):
    from dictado import context
    monkeypatch.setattr(context, "_read", lambda h, m: 1 / 0)
    with pytest.raises(RuntimeError, match="ZeroDivisionError"):
        context.window_texts(hwnd=1)
