"""Swedish dictation (t0u.24): sv routes to large-v3, one active language, settings + tray switch."""
from dictado.config import TextCfg, WhisperCfg
from dictado.engine import Engine, dictation_model
from tests.test_engine_recovery import FakeModel


def loaded_with(languages):
    calls = []

    def factory(name, device, compute_type, local_files_only=False):
        calls.append((name, compute_type))
        return FakeModel(name, device, compute_type)
    cfg = WhisperCfg()
    cfg.languages = languages
    Engine(cfg, TextCfg(), model_factory=factory).load()
    return calls[0]


def test_swedish_dictation_loads_large_v3_in_int8():
    # spike 2026-10-05: turbo 8.4 % WER on Swedish, large-v3 3.4 %; int8_float16 = same WER, ~half the VRAM
    assert loaded_with(["sv"]) == ("Systran/faster-whisper-large-v3", "int8_float16")


def test_english_and_spanish_keep_turbo():
    assert loaded_with(["en"]) == ("large-v3-turbo", "float16")
    assert loaded_with(["en", "es"]) == ("large-v3-turbo", "float16")


def test_dictation_model_names_what_the_status_shows():
    cfg = WhisperCfg()
    cfg.languages = ["sv"]
    assert dictation_model(cfg)[0] == "Systran/faster-whisper-large-v3"


def test_tray_switch_saves_the_language(tmp_path):
    from dictado import config
    from dictado.window import save_dictation_languages
    path = tmp_path / "config.toml"
    assert save_dictation_languages(path, "sv") == ["sv"]
    assert config.load(path).whisper.languages == ["sv"]
    import pytest
    with pytest.raises(ValueError):
        save_dictation_languages(path, "sv,en")
    assert config.load(path).whisper.languages == ["sv"]  # a refused value changes nothing
