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
