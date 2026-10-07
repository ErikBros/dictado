"""Speech coaching (dictado-9jc), computed on this computer. Invented text only: nothing from a real
history ever goes in the repo."""
from datetime import datetime

from ecoscribe import coach

NOW = datetime(2026, 10, 7, 15, 0)


def test_clarity_is_the_share_of_words_heard_clearly_and_keeps_the_unsure_ones():
    wp = [("The", 0.99), ("parcel", 0.97), ("reached", 0.42), ("Tromsø,", 0.31), ("yesterday.", 0.95)]
    c = coach.clarity(wp)
    assert c == {"clarity": 60, "heard": 5, "unsure": ["reached", "Tromsø"]}  # 3 of 5 at >= 0.8


def test_clarity_needs_a_few_words_and_skips_punctuation():
    assert coach.clarity([("Yes.", 0.99), ("-", 0.1)]) is None
    assert coach.clarity(None) is None and coach.clarity([]) is None


def row(ts, text, clarity=None, heard=0, unsure=(), lang="en"):
    r = {"ts": ts, "text": text, "lang": lang, "audio_s": 5.0, "target": "slack.exe", "pasted": True}
    if clarity is not None:
        r.update(clarity=clarity, heard=heard, unsure=list(unsure))
    return r


ROWS = [
    row("2026-09-20T10:00:00", "An older one, before clarity was saved."),
    row("2026-09-29T10:00:00", "The ferry to Tromsø leaves at nine.", 50, 8, ["Tromsø", "ferry"]),
    row("2026-10-06T10:00:00", "Tromsø again, and the ferry was late.", 75, 8, ["Tromsø"]),
    row("2026-10-07T09:00:00", "Bring the blue folder to Tromsø.", 100, 4, []),
    row("2026-10-07T09:30:00", "La reunión empieza a las diez.", 80, 5, ["reunión"], lang="es"),
]


def test_summary_weights_by_words_and_trends_by_week():
    s = coach.clarity_summary(ROWS, NOW)
    assert s["dictations"] == 4 and s["since"] == "2026-09-29"
    assert s["clarity"] == round(100 * (4 + 6 + 4 + 4) / 25)  # words heard clearly / words scored
    weeks = s["weeks"]
    assert len(weeks) == 8 and weeks[-1]["clarity"] == round(100 * (6 + 4 + 4) / 17)
    assert weeks[-2]["clarity"] == 50 and weeks[0]["clarity"] is None


def test_words_whisper_struggled_with_count_against_how_often_they_were_said():
    s = coach.clarity_summary(ROWS, NOW)
    en = next(x for x in s["words"] if x["lang"] == "en")["words"]
    assert en[0] == {"word": "Tromsø", "unsure": 2, "said": 3}
    assert {"word": "ferry", "unsure": 1, "said": 2} in en
    es = next(x for x in s["words"] if x["lang"] == "es")["words"]
    assert es == [{"word": "reunión", "unsure": 1, "said": 1}]


def test_nothing_scored_yet():
    assert coach.clarity_summary(ROWS[:1], NOW) == {"dictations": 0}


def test_audience_tells_people_from_ai_apps_by_app_and_browser_tab():
    a = coach.audience
    assert a("slack.exe") == a("Slack") == a("OUTLOOK.EXE") == a("olk.exe") == a("WhatsApp") == "people"
    assert a("claude.exe") == a("Claude") == a("WindowsTerminal.exe") == a("Code.exe") == a("iTerm2") == "ai"
    assert a("chrome.exe", "Lunch on Friday - someone@example.com - Gmail - Google Chrome") == "people"
    assert a("msedge.exe", "Plan a trip - Claude - Microsoft Edge") == "ai"
    assert a("Safari", "ChatGPT") == "ai"
    assert a("chrome.exe", "Weather in Lisbon - Google Search - Google Chrome") == "other"
    assert a("chrome.exe") == a("notepad.exe") == a(None) == "other"
    # a site name in the subject doesn't win over the site the tab is on
    assert a("chrome.exe", "Re: notes from Claude - Inbox - Outlook - Google Chrome") == "people"


def test_rows_without_a_saved_audience_fall_back_to_the_app():
    assert coach.row_audience({"target": "slack.exe"}) == "people"
    assert coach.row_audience({"target": "chrome.exe", "to": "ai"}) == "ai"


def test_coach_prompt_has_only_recent_dictations_to_people_oldest_first():
    rows = [
        {"ts": "2026-09-01T10:00:00", "text": "Too old to include.", "target": "slack.exe"},
        {"ts": "2026-10-06T09:00:00", "text": "Hey, so, I think maybe we could move the call?", "target": "slack.exe"},
        {"ts": "2026-10-06T10:00:00", "text": "Refactor the parser and add tests.", "target": "claude.exe"},
        {"ts": "2026-10-07T08:00:00", "text": "Thanks for the notes, I kind of agree.", "target": "chrome.exe", "to": "people"},
    ]
    p = coach.coach_prompt(rows, NOW)
    assert "3 recurring patterns" in p and "before" in p and "one habit" in p.lower()
    assert "Too old" not in p and "Refactor the parser" not in p
    assert p.index("move the call") < p.index("Thanks for the notes")
    assert coach.people_count(rows, NOW) == 2


def test_coach_prompt_keeps_the_newest_when_there_is_too_much():
    rows = [{"ts": f"2026-10-0{d}T10:00:00", "text": f"Message number {d} " + "word " * 300, "target": "slack.exe"}
            for d in range(1, 8)]
    p = coach.coach_prompt(rows, NOW, max_words=700)
    assert "Message number 7" in p and "Message number 6" in p and "Message number 1" not in p


def test_coach_me_copies_the_prompt_or_says_there_is_nothing(tmp_path, monkeypatch):
    import json as _json
    from datetime import datetime as _dt

    from ecoscribe.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    copied = []
    monkeypatch.setattr(api, "_copy", copied.append)
    assert api.coach_me()["ok"] is False and copied == []
    now = _dt.now().strftime("%Y-%m-%dT%H:%M:%S")
    rows = [{"ts": now, "text": "See you at the station at six.", "target": "WhatsApp.exe", "to": "people"},
            {"ts": now, "text": "Summarise this file.", "target": "claude.exe", "to": "ai"}]
    (tmp_path / "history.jsonl").write_text("".join(_json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    r = api.coach_me()
    assert r["ok"] and "station at six" in copied[0] and "Summarise this file" not in copied[0]


def test_fillers_and_hedges_are_counted_apart_per_language():
    m = coach.markers("So, like, I think we could maybe, kind of, move it. I'd like that. You know?", "en")
    assert m["fillers"] == {"like": 1, "you know": 1}  # not "I'd like"
    assert m["hedges"] == {"i think": 1, "maybe": 1, "kind of": 1}
    m = coach.markers("Bueno, creo que a lo mejor llego tarde. Kanske imorgon.", "es+sv")
    assert m["fillers"] == {"bueno": 1} and m["hedges"] == {"creo que": 1, "a lo mejor": 1, "kanske": 1}
    assert coach.markers("Plain sentence.", "de") == {"fillers": {}, "hedges": {}}


def test_the_pill_note_is_short_neutral_and_only_when_there_is_something():
    assert coach.pill_note(coach.markers("Like, I think, like, maybe. Like.", "en")) == "like ×3 · maybe · i think"
    assert coach.pill_note(coach.markers("All set for Friday.", "en")) is None


def test_markers_trend_is_for_messages_to_people_per_week():
    rows = [
        {"ts": "2026-09-29T10:00:00", "text": "I think maybe we should go. " * 10, "lang": "en", "to": "people"},
        {"ts": "2026-10-06T10:00:00", "text": "We should go at noon today, see you there. " * 10, "lang": "en", "to": "people"},
        {"ts": "2026-10-06T11:00:00", "text": "Like, basically, refactor it, you know. " * 10, "lang": "en", "to": "ai"},
    ]
    s = coach.markers_summary(rows, NOW)
    assert s["words"] == 60 + 90 and s["dictations"] == 2
    assert s["hedges_per_100"] == round(100 * 20 / 150, 1) and s["fillers_per_100"] == 0
    assert s["weeks"][-2]["hedges_per_100"] == round(100 * 20 / 60, 1) and s["weeks"][-1]["hedges_per_100"] == 0
    assert s["weeks"][0]["hedges_per_100"] is None
    assert s["top_hedges"] == [{"word": "maybe", "count": 10}, {"word": "i think", "count": 10}]
    assert coach.markers_summary(rows[2:], NOW) == {"words": 0}


def test_the_pill_note_setting_round_trips_and_is_off_by_default(tmp_path):
    from ecoscribe.window import Api
    api = Api(data_dir=tmp_path, config_path=tmp_path / "config.toml", signal_reload=lambda: True)
    assert api.get_settings()["values"]["speech_feedback"] is False
    assert api.save_settings({"speech_feedback": True})["ok"]
    assert api.get_settings()["values"]["speech_feedback"] is True
