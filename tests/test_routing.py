import pytest

from dictado import tomlw
from dictado.config import TranscribeCfg, load
from dictado.routing import LANG_NAMES, model_for


def test_routes_default():
    c = TranscribeCfg()
    assert model_for("sv", c) == "Systran/faster-whisper-large-v3"
    assert model_for("en", c) == "large-v3-turbo"
    assert model_for("es", c) == "large-v3-turbo"
    assert model_for("el", c) == "Systran/faster-whisper-large-v3"
    assert model_for("fi", c) == "Systran/faster-whisper-large-v3"


def test_auto_must_be_detected_first():
    with pytest.raises(ValueError):
        model_for("auto", TranscribeCfg())


def test_toml_override(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[transcribe]\nroutes = {sv = "large-v3-turbo", "*" = "large-v3-turbo"}\n', encoding="utf-8")
    assert model_for("sv", load(p).transcribe) == "large-v3-turbo"


def test_override_replaces_whole_table(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[transcribe]\nroutes = {"*" = "small"}\n', encoding="utf-8")
    assert model_for("sv", load(p).transcribe) == "small"


def test_defaults_and_spanish_names():
    c = load(None).transcribe
    assert c.detector_model == "large-v3-turbo" and c.compute_type == "int8_float16"
    assert c.beam_size == 5 and c.root == ""
    assert LANG_NAMES == {"sv": "Swedish", "en": "English", "es": "Spanish", "el": "Greek", "el,es": "Greek + Spanish",
                          "auto": "Detect"}


def test_config_writer_round_trips_transcribe(tmp_path):
    c = load(None)
    c.transcribe.routes = {"sv": "KBLab/kb-whisper-large", "*": "large-v3-turbo"}
    p = tmp_path / "c.toml"
    tomlw.save(c, p)
    assert load(p).transcribe.routes == {"sv": "KBLab/kb-whisper-large", "*": "large-v3-turbo"}
