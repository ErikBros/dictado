"""Insights (dictado-3je): what the dictation history says, computed on this computer.
Invented dictations only: nothing from a real history ever goes in the repo."""
from datetime import datetime

from ecoscribe import insights

NOW = datetime(2026, 10, 7, 15, 0)


def row(ts, text, lang="en", audio_s=10.0, target="slack.exe"):
    return {"ts": ts, "text": text, "lang": lang, "audio_s": audio_s, "target": target, "pasted": True}


ROWS = [
    row("2026-10-05T09:10:00", "So I'd like to move the standup. Like, we could ask Ecoskribe support first.", audio_s=8),
    row("2026-10-06T09:40:00", "Basically the deploy failed again, like, twice. You know how it is with Klaude.", audio_s=7),
    row("2026-10-07T14:05:00", "Vi ses vid sjön i morgon, typ vid tio.", "sv", 6, "outlook.exe"),
    row("2026-10-07T14:30:00", "Das Wetter ist heute schön und der Zug ist pünktlich.", "de", 5),
    row("2026-10-07T15:00:00", "Ring mig efter lunch. Ecoskribe and Ecoskribe again, then Klaude.", "en+sv", 6),
]


def test_time_saved_against_typing():
    t = insights.totals(ROWS)
    assert t["dictations"] == 5 and t["talk_s"] == 32
    assert t["saved_s"] == round(t["words"] / 40 * 60 - 32)  # typing at 40 wpm minus the time talking
    assert t["wpm"] == round(t["words"] / (32 / 60))


def test_ranges_rhythm_and_streak():
    assert len(insights.in_range(ROWS, 1, NOW)) == 3
    r = insights.rhythm(ROWS, NOW)
    assert r["hours"][9] == 2 and r["hours"][14] == 2 and sum(r["hours"]) == 5
    assert r["days"][-1]["date"] == "2026-10-07" and len(r["days"]) == 14
    assert r["streak"] == 3  # the 5th, 6th and 7th


def test_languages_apps_and_mixed():
    langs = {x["lang"]: x["words"] for x in insights.by_language(ROWS)}
    assert set(langs) == {"en", "sv", "de", "mixed"}
    assert insights.by_app(ROWS)[0] == {"app": "slack.exe", "dictations": 4}


def test_like_is_a_filler_only_when_it_is_one():
    h = insights.habits(ROWS, min_words=1)
    en = next(x for x in h if x["lang"] == "en")
    top = {x["word"]: x["count"] for x in en["top"]}
    assert top["like"] == 2  # "Like, we could" and "again, like," but not "I'd like"
    assert top["basically"] == 1 and top["you know"] == 1
    sv = next(x for x in h if x["lang"] == "sv")
    assert {x["word"] for x in sv["top"]} == {"typ"}


def test_names_to_add_are_mid_sentence_and_close_misspellings_point_at_the_right_name():
    s = insights.name_suggestions(ROWS, vocabulary=[])
    assert {x["heard"]: x["suggest"] for x in s} == {"Ecoskribe": "Ecoscribe", "Klaude": "Claude"}
    assert insights.name_suggestions(ROWS, vocabulary=["Ecoscribe", "Claude"]) == []  # already in Your words


def test_week_for_claude_is_a_prompt_with_every_dictation_of_the_week():
    text = insights.week_for_claude(ROWS, NOW)
    assert text.startswith("Here is everything I dictated this week")
    assert "## Wednesday 07 October" in text and "- 14:05 Vi ses vid sjön" in text
    assert text.count("\n- ") == 5


def test_empty_history_is_fine():
    d = insights.compute([], [], None, NOW)
    assert d["totals"]["words"] == 0 and d["totals"]["wpm"] is None and d["first"] is None


def test_clarity_is_part_of_insights_and_empty_until_saved():
    """dictado-9jc.1: dictations from before clarity was saved have none; the card says so."""
    assert insights.compute(ROWS, [], now=NOW)["clarity"] == {"dictations": 0}
    scored = [*ROWS, {**ROWS[0], "ts": "2026-10-07T15:10:00", "clarity": 90, "heard": 10, "unsure": ["Ecoskribe"]}]
    c = insights.compute(scored, [], days=7, now=NOW)["clarity"]
    assert c["dictations"] == 1 and c["clarity"] == 90 and c["words"][0]["words"][0]["word"] == "Ecoskribe"
