"""Insights: what your dictations say about how you talk (dictado-3je; Settings > Insights tab).

Everything is computed here, on this computer, from the dictation history (history.jsonl): time
saved against typing, when and where you dictate, your languages, filler words, the phrases you
repeat, names Whisper keeps spelling its own way (one click adds them to Your words), your week as
a prompt for Claude, and speech coaching (coach.py, dictado-9jc). Nothing here leaves the computer except what you copy yourself.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import datetime, timedelta

from . import coach

TYPING_WPM = 40  # an average typist; what the time saved is measured against
WORD = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)
SENTENCE_END = re.compile(r"[.!?¿¡:;\n]\s*$")
KNOWN = ["Ecoscribe", "Claude"]  # names to suggest when Whisper writes something close ("Cloud", "Echoscribe")
# capitalised but not names: languages, days, months, platforms (never suggested for Your words)
COMMON_CAPS = set("""english spanish swedish greek german french italian portuguese dutch finnish norwegian danish
    monday tuesday wednesday thursday friday saturday sunday january february march april may june july august
    september october november december mac windows linux iphone android google internet""".split())

STOP = {
    "en": set("""a an the and or but so if then than that this these those it its it's i i'm i've i'd i'll me my
        mine you you're your yours we we're our us he she him her his they them their there here is are was were be
        been being am do does did doing done have has had having not no yes to of in on at by for with from up down
        out about into over as just like can could would should will shall may might must what which who whom whose
        when where why how all any some more most other such only own same too very also now well really because
        get got go going gonna wanna want know think one two let let's okay ok yeah oh um uh don't doesn't didn't
        isn't aren't wasn't can't won't that's there's what's need make see say said way thing things lot right
        actually something something's""".split()),
    "es": set("""a al algo como con de del el ella ellas ellos en entre era es esa ese eso esta este esto estoy
        estás está están ha hay la las le les lo los me mi mis muy más ni no nos o para pero por porque que qué se
        si sin sobre su sus también te tengo tiene tu tú un una uno unos y ya yo vale bueno pues entonces así cuando
        donde dónde fue ser soy son eres hacer hace voy vas va vamos quiero puedo puede todo todos nada aquí ahí""".split()),
    "sv": set("""och att det som en ett i på är för med den till av inte om har de jag du vi ni han hon man kan
        så men eller var vad när här där nu då ju bara också mycket lite ska skulle vill måste från ut upp in över
        efter under mig dig oss er sig min din vår mitt ditt sin sitt detta denna dessa hade blir blev""".split()),
    "el": set("""και να το τα του της την τον τη η ο οι ένα μια σε με για από που ότι δεν θα είναι είμαι είσαι
        είμαστε έχω έχει αυτό αυτή αυτός εγώ εσύ εμείς μου σου μας σας τους στο στη στην στον στα αλλά ή πολύ
        πώς τι ποιος εδώ εκεί τώρα όταν αν επίσης""".split()),
}
# "like" only as a filler: not "I'd like", "would like", "looks like", "I like it"
LIKE = r"(?<!would )(?<!'d )(?<!’d )(?<!i )(?<!you )(?<!we )(?<!they )(?<!looks )(?<!look )(?<!feels )(?<!don't )(?<!to )like"
FILLERS = {
    "en": [LIKE, "actually", "basically", "you know", "i mean", "kind of", "sort of", "i don't know", "literally",
           "right?", "yeah yeah"],
    "es": ["o sea", "bueno", "pues", "en plan", "vale", "sabes", "¿vale?", "tipo", "digamos"],
    "sv": ["typ", "liksom", "alltså", "asså", "ju", "liksom", "ba", "va"],
    "el": ["λοιπόν", "δηλαδή", "ας πούμε", "ξέρεις", "καλά", "βασικά"],
}


def words(text: str) -> list[str]:
    return WORD.findall(text or "")


def _ts(r) -> datetime | None:
    try:
        return datetime.fromisoformat(str(r.get("ts", ""))[:19])
    except ValueError:
        return None


def in_range(rows: list[dict], days: int | None, now: datetime | None = None) -> list[dict]:
    if not days:
        return list(rows)
    since = (now or datetime.now()) - timedelta(days=days)
    return [r for r in rows if (t := _ts(r)) and t >= since]


def _lang(r) -> str:
    lang = str(r.get("lang") or "")
    return "mixed" if "+" in lang else lang


def totals(rows: list[dict]) -> dict:
    n_words = sum(len(words(r.get("text", ""))) for r in rows)
    talk_s = sum(float(r.get("audio_s") or 0) for r in rows)
    typing_s = n_words / TYPING_WPM * 60
    return {"dictations": len(rows), "words": n_words, "talk_s": round(talk_s),
            "wpm": round(n_words / (talk_s / 60)) if talk_s >= 30 else None,
            "saved_s": max(0, round(typing_s - talk_s)), "typing_wpm": TYPING_WPM}


def rhythm(rows: list[dict], now: datetime | None = None, days: int = 14) -> dict:
    """Dictations per hour of the day, and words per day for the last `days` days (oldest first)."""
    now = now or datetime.now()
    hours = [0] * 24
    per_day: Counter = Counter()
    for r in rows:
        t = _ts(r)
        if t is None:
            continue
        hours[t.hour] += 1
        per_day[t.date()] += len(words(r.get("text", "")))
    day_list = [(now.date() - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    streak = 0
    for d in reversed(day_list):
        if per_day.get(d):
            streak += 1
        elif d != now.date():  # today without a dictation yet doesn't break it
            break
    return {"hours": hours, "days": [{"date": d.isoformat(), "words": per_day.get(d, 0)} for d in day_list],
            "streak": streak}


def by_language(rows: list[dict]) -> list[dict]:
    c: Counter = Counter()
    for r in rows:
        c[_lang(r) or "?"] += len(words(r.get("text", "")))
    return [{"lang": k, "words": v} for k, v in c.most_common()]


def by_app(rows: list[dict], top: int = 6) -> list[dict]:
    c = Counter(str(r.get("target") or "") for r in rows if r.get("target"))
    return [{"app": k, "dictations": v} for k, v in c.most_common(top)]


def habits(rows: list[dict], min_words: int = 150) -> list[dict]:
    """Filler words per 100 words, per language with enough words to say anything."""
    out = []
    for lang, fillers in FILLERS.items():
        text = " ".join(r.get("text", "") for r in rows if _lang(r) == lang).lower()
        n = len(words(text))
        if n < min_words:
            continue
        counts = {("like" if f == LIKE else f): len(re.findall(r"(?<!\w)" + (f if f == LIKE else re.escape(f)) + r"(?!\w)",
                                                              text)) for f in dict.fromkeys(fillers)}
        top = sorted(((f, k) for f, k in counts.items() if k), key=lambda x: -x[1])[:5]
        total = sum(counts.values())
        out.append({"lang": lang, "words": n, "per_100": round(100 * total / n, 1),
                    "top": [{"word": f, "count": k} for f, k in top]})
    return out


def phrases(rows: list[dict], n: int = 3, top: int = 8, min_count: int = 3) -> list[dict]:
    c: Counter = Counter()
    for r in rows:
        w = [x.lower() for x in words(r.get("text", ""))]
        c.update(" ".join(w[i:i + n]) for i in range(len(w) - n + 1))
    return [{"phrase": p, "count": k} for p, k in c.most_common(top) if k >= min_count]


def name_suggestions(rows: list[dict], vocabulary: list[str], min_count: int = 2, top: int = 10) -> list[dict]:
    """Names Whisper writes that aren't in Your words: capitalised mid-sentence, said at least twice.
    A spelling close to one you have (or to Ecoscribe itself) is suggested as that one."""
    have = {v.lower() for v in vocabulary}
    targets = [v for v in [*vocabulary, *KNOWN] if v]
    c: Counter = Counter()
    for r in rows:
        text = r.get("text", "")
        stop = STOP.get(_lang(r), set()) | STOP["en"]
        for m in WORD.finditer(text):
            w = m.group(0)
            before = text[:m.start()]
            if not w[0].isupper() or not before.strip() or SENTENCE_END.search(before):
                continue  # lowercase, or the first word of a sentence
            if w.lower() in stop or w.lower() in COMMON_CAPS or len(w) < 3 or w.isupper() and len(w) <= 3:
                continue
            c[w] += 1
    out = []
    for w, k in c.most_common():
        if k < min_count:
            break
        close = difflib.get_close_matches(w.lower(), [t.lower() for t in targets], n=1, cutoff=0.7)
        close = [next(t for t in targets if t.lower() == close[0])] if close else []
        suggest = close[0] if close else w
        if suggest.lower() in have:
            continue  # already in Your words (Whisper still slipped: nothing to add)
        out.append({"heard": w, "count": k, "suggest": suggest})
        if len(out) >= top:
            break
    return out


def week_for_claude(rows: list[dict], now: datetime | None = None) -> str:
    """The last 7 days of dictations as a prompt: what did I talk about, decide, leave open?"""
    week = sorted(in_range(rows, 7, now), key=lambda r: str(r.get("ts")))
    lines = ["Here is everything I dictated this week (with Ecoscribe, most of it to an AI assistant). "
             "Summarise the themes, the decisions I made, what I keep coming back to, and anything I said "
             "I'd do but may have left open. Be brief and concrete.", ""]
    day = None
    for r in week:
        t = _ts(r)
        if t and t.date() != day:
            day = t.date()
            lines += ["", f"## {t.strftime('%A %d %B')}"]
        lines.append(f"- {t.strftime('%H:%M') if t else ''} {str(r.get('text', '')).strip()}")
    return "\n".join(lines).strip() + "\n"


def compute(rows: list[dict], vocabulary: list[str], days: int | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    sel = in_range(rows, days, now)
    rh = rhythm(sel, now)
    rh_all = rhythm(rows, now)  # the last 14 days and the streak whatever the range
    rh["days"], rh["streak"] = rh_all["days"], rh_all["streak"]
    return {"days": days, "totals": totals(sel), "rhythm": rh, "languages": by_language(sel),
            "apps": by_app(sel), "habits": habits(sel), "phrases": phrases(sel),
            "suggestions": name_suggestions(sel, vocabulary), "clarity": coach.clarity_summary(sel, now),
            "first": str(rows[0].get("ts", ""))[:10] if rows else None}
