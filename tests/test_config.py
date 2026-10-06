import pytest

from dictado import config


def test_defaults():
    c = config.load(None)
    assert c.hotkey.key == "rctrl"
    assert c.hotkey.vk == 0xA3
    assert c.audio.device == ""  # the Windows default mic
    assert c.audio.host == "MME"
    assert c.whisper.model == "large-v3-turbo"
    assert c.whisper.languages == ["en"]
    assert c.limits.max_record_s == 600.0


def test_toml_overrides_merge(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[audio]\ndevice = "Blue Yeti"\n[whisper]\nlanguages = ["es"]\n', encoding="utf-8")
    c = config.load(p)
    assert c.audio.device == "Blue Yeti"
    assert c.audio.host == "MME"
    assert c.whisper.languages == ["es"]
    assert c.whisper.model == "large-v3-turbo"


def test_unknown_key_ignored(tmp_path, caplog):
    p = tmp_path / "config.toml"
    p.write_text('[audio]\nbogus = 1\n[nope]\nx = 2\n', encoding="utf-8")
    c = config.load(p)
    assert c.audio.device == ""  # the Windows default mic
    assert "bogus" in caplog.text


def test_ralt_forbidden(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\nkey = "ralt"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        config.load(p)


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "absent.toml").hotkey.key == "rctrl"


def test_meetings_defaults_and_round_trip(tmp_path):
    from dictado import tomlw
    c = config.load(None)
    assert (c.meetings.mode, c.meetings.grace_s, c.meetings.silence_stop_s, c.meetings.default_lang) == \
        ("prompt", 20, 180, "sv")
    c.meetings.mode, c.meetings.default_lang = "auto", "en"
    p = tmp_path / "c.toml"
    tomlw.save(c, p)
    back = config.load(p)
    assert back.meetings.mode == "auto" and back.meetings.default_lang == "en"
