"""Spoken commands (market deep dive 2026-10-05): "new line", "new paragraph", "send it".

Off by default ([text] voice_commands = false): today's text is unchanged unless the user turns it on.
"""
from ecoscribe.text import voice_commands


def test_new_line_and_paragraph_in_three_languages():
    assert voice_commands("Hello team. New line. The deploy is fixed. ") == ("Hello team.\nThe deploy is fixed. ", False)
    assert voice_commands("First point, new paragraph, second point. ") == ("First point.\n\nSecond point. ", False)
    assert voice_commands("Hola. Nueva línea. Qué tal. ") == ("Hola.\nQué tal. ", False)
    assert voice_commands("Hej. Ny rad. Vi ses. ") == ("Hej.\nVi ses. ", False)


def test_send_it_at_the_end_presses_enter():
    assert voice_commands("Run the tests again, send it. ") == ("Run the tests again.", True)
    assert voice_commands("Check the logs. Press enter.") == ("Check the logs.", True)
    assert voice_commands("Vale, envíalo. ") == ("Vale.", True)
    assert voice_commands("Send it. ") == ("", True)  # only the command: just press Enter


def test_words_inside_a_sentence_are_left_alone():
    assert voice_commands("Did you send it to her yesterday? ") == ("Did you send it to her yesterday? ", False)
    assert voice_commands("We need a new line of products. ") == ("We need a new line of products. ", False)


def _app(tmp_path, said, on):
    from ecoscribe.app import App
    from ecoscribe.config import Config
    from ecoscribe.deliver import DeliveryResult
    from ecoscribe.engine import Result
    from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait
    cfg = Config()
    cfg.text.voice_commands = on
    delivered, enters = [], []

    class Eng:
        def transcribe(self, audio):
            return Result(text=said, lang="en", speech_s=1.0, ms=5)
    app = App(cfg, FakeRecorder(), Eng(), lambda t: delivered.append(t) or DeliveryResult(True, "x.exe", "ok"),
              FakeUi(), gate=FakeGate(), history_path=tmp_path / "h.jsonl", press_enter=lambda: enters.append(1))
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    wait(lambda: delivered or enters)
    import time
    time.sleep(0.3)
    return delivered, enters


def test_app_pastes_then_presses_enter_when_on(tmp_path):
    assert _app(tmp_path, "Run the tests again, send it. ", True) == (["Run the tests again."], [1])


def test_off_by_default_pastes_exactly_what_was_said(tmp_path):
    assert _app(tmp_path, "Run the tests again, send it. ", False) == (["Run the tests again, send it. "], [])


def test_settings_list_comes_from_the_matcher_table(tmp_path):
    """t0u.38: every phrase in the Settings list is one the matcher really understands."""
    from ecoscribe.text import VOICE_COMMANDS, voice_commands
    from ecoscribe.window import Api
    rows = Api(data_dir=tmp_path, config_path=tmp_path / "c.toml", signal_reload=lambda: True).get_settings()["voice_command_list"]
    assert [r["what"] for r in rows] == [w for _, w, _ in VOICE_COMMANDS]
    assert rows[0]["es"] == '"nuevo párrafo", "punto y aparte"'
    for key, _, langs in VOICE_COMMANDS:
        for phrases in langs.values():
            for p in phrases:
                out, enter = voice_commands(f"Hola. {p}.")
                assert (enter if key == "enter" else "\n" in out), p
