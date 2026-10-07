"""Personal vocabulary (market deep dive, 2026-10-05): words Whisper should spell your way.

Measured on real Swedish audio: giving Whisper the word as a prompt fixed "riksdagsledarmöter" ->
"riksdagsledamöter" on turbo and large-v3; faster-whisper's `hotwords` broke large-v3's output.
"""
from types import SimpleNamespace

import numpy as np

from ecoscribe.config import TextCfg, WhisperCfg
from ecoscribe.engine import Engine
from ecoscribe.text import vocab_prompt


def test_prompt_from_the_word_list():
    assert vocab_prompt([]) is None and vocab_prompt(["  ", ""]) is None
    assert vocab_prompt(["Ecoscribe", " pyannote ", "Ecoscribe", "Göteborg"]) == "Ecoscribe, pyannote, Göteborg."
    long = vocab_prompt([f"word{i:03d}" for i in range(200)])
    assert len(long) <= 400  # Whisper's prompt window is small: the first words win


class Model:
    def __init__(self):
        self.kw = None

    def transcribe(self, audio, **kw):
        self.kw = kw
        return iter([SimpleNamespace(text=" hej", no_speech_prob=0.01)]), SimpleNamespace(duration=1.0, duration_after_vad=1.0)


def dictate(words):
    m = Model()
    text = TextCfg()
    text.vocabulary = words
    e = Engine(WhisperCfg(), text, model_factory=lambda *a, **k: m)
    e.model = m
    e._run(np.zeros(16000, np.float32))
    return m.kw


def test_dictation_passes_the_vocabulary_as_the_prompt():
    assert dictate(["Ecoscribe", "Kristineberg"])["initial_prompt"] == "Ecoscribe, Kristineberg."
    assert dictate([]).get("initial_prompt") is None  # empty list: exactly today's call


def test_files_and_meetings_get_the_prompt(tmp_path):
    from pathlib import Path
    from ecoscribe import sessions, transcribe
    from ecoscribe.config import TranscribeCfg
    seen = []

    class M:
        def transcribe(self, audio, **kw):
            seen.append(kw.get("initial_prompt"))
            return iter([SimpleNamespace(start=0.0, end=1.0, text=" hej")]), SimpleNamespace(duration=1.0)
    d = sessions.create("x", "sv", "import", tmp_path / "t")
    (d / "audio" / "a.flac").write_bytes(b"x")
    rc = transcribe.run(d, TranscribeCfg(), factory=lambda *a: M(), resolve=lambda n, c: Path("M:/") / n,
                        decode=lambda p: np.zeros(16000, np.float32), prompt="Ecoscribe, Göteborg.")
    assert rc == 0 and seen == ["Ecoscribe, Göteborg."]


def test_vocabulary_setting_round_trips(tmp_path):
    from ecoscribe.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.save_settings({"vocabulary": "Ecoscribe\n  pyannote \n\nGöteborg\nEcoscribe"})["ok"]
    assert api.get_settings()["values"]["vocabulary"] == "Ecoscribe\npyannote\nGöteborg"
