"""Snippets (t0u.29): say a snippet's name as its own clause and get the saved text.

Local and deterministic, like voice commands: "my email" alone between punctuation marks is
replaced; "what's my email again" stays text. Matching ignores case; the longest trigger wins.
Empty list (the default) = text unchanged.
"""
from dictado.text import snippets

S = {"my email": "alex@example.com", "signature": "Best,\nAlex", "my email at work": "alex@work.example"}


def test_a_clause_that_is_a_trigger_is_replaced():
    assert snippets("Send it to my email. ", S) == "Send it to my email. "  # inside a sentence: text
    assert snippets("My email. ", S) == "alex@example.com "
    assert snippets("Thanks for today, signature. ", S) == "Thanks for today, Best,\nAlex "
    assert snippets("Write to me here: my email. See you. ", S) == "Write to me here: alex@example.com See you. "


def test_longest_trigger_wins_and_case_is_ignored():
    assert snippets("MY EMAIL AT WORK. ", S) == "alex@work.example "


def test_inside_a_sentence_is_left_alone():
    assert snippets("What's my email again? ", S) == "What's my email again? "
    assert snippets("The signature is missing. ", S) == "The signature is missing. "


def test_no_snippets_no_change():
    assert snippets("My email. ", {}) == "My email. "
    assert snippets("My email. ", None) == "My email. "


def test_app_applies_snippets(tmp_path):
    from dictado.app import App
    from dictado.config import Config
    from dictado.deliver import DeliveryResult
    from dictado.engine import Result
    from tests.test_app import FakeGate, FakeRecorder, FakeUi, wait
    cfg = Config()
    cfg.text.snippets = {"my email": "alex@example.com"}
    out = []

    class Eng:
        def transcribe(self, audio):
            return Result(text="My email. ", lang="en", speech_s=1.0, ms=5)
    app = App(cfg, FakeRecorder(), Eng(), lambda t: out.append(t) or DeliveryResult(True, "x.exe", "ok"), FakeUi(),
              gate=FakeGate(), history_path=tmp_path / "h.jsonl")
    app.start()
    app.on_action("toggle"); app.on_action("toggle")
    assert wait(lambda: out == ["alex@example.com "])


def test_setting_round_trips(tmp_path):
    from dictado.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.get_settings()["values"]["snippets"] == []
    rows = [{"trigger": "  My   Email ", "text": "alex@example.com"}, {"trigger": "sig", "text": "Best,\nAlex"},
            {"trigger": "", "text": "dropped"}, {"trigger": "my email", "text": "dup dropped"}]
    assert api.save_settings({"snippets": rows})["ok"]
    assert api.get_settings()["values"]["snippets"] == [{"trigger": "my email", "text": "alex@example.com"},
                                                        {"trigger": "sig", "text": "Best,\nAlex"}]
