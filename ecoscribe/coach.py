"""Speech coaching (dictado-9jc; Settings > Insights tab): help you speak more clearly, from how you dictate.

Everything is worked out here, on this computer, from the dictation history (history.jsonl).

- Clarity (9jc.1): after the paste, a second look at the recording says how sure Whisper was of each word
  (ASR confidence follows how intelligible speech is). Clarity is the share of words heard clearly; the
  words it wasn't sure of are kept, so the ones you keep swallowing show up.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

CLEAR_P = 0.8  # a word Whisper gave at least this probability was heard clearly
UNSURE_P = 0.5  # under this, a word it struggled with
MIN_WORDS = 3  # fewer words say nothing about clarity
MAX_UNSURE = 20  # per dictation
WEEKS = 8
WORD = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def _word(w: str) -> str:
    m = WORD.search(w or "")
    return m.group(0) if m else ""


def clarity(word_probs) -> dict | None:
    """{"clarity": % of words heard clearly, "heard": words scored, "unsure": [words]} for one dictation,
    from [(word, probability)]; None when there's too little to say anything."""
    ws = [(_word(w), float(p)) for w, p in (word_probs or [])]
    ws = [(w, p) for w, p in ws if w]
    if len(ws) < MIN_WORDS:
        return None
    clear = sum(p >= CLEAR_P for _, p in ws)
    return {"clarity": round(100 * clear / len(ws)), "heard": len(ws),
            "unsure": [w for w, p in ws if p < UNSURE_P][:MAX_UNSURE]}


def _ts(r) -> datetime | None:
    try:
        return datetime.fromisoformat(str(r.get("ts", ""))[:19])
    except ValueError:
        return None


def _clear(r) -> float:
    return r["clarity"] * r["heard"] / 100


def _lang(r) -> str:
    lang = str(r.get("lang") or "")
    return "mixed" if "+" in lang else lang or "?"


def clarity_summary(rows: list[dict], now: datetime | None = None, top: int = 12) -> dict:
    """Clarity over the dictations that have it (saved from 9jc.1 on): overall and per week (oldest
    first, None for a week without any), and per language the words Whisper struggled with most,
    with how often each was said."""
    now = now or datetime.now()
    scored = [r for r in rows if r.get("heard") and r.get("clarity") is not None]
    if not scored:
        return {"dictations": 0}
    heard = sum(r["heard"] for r in scored)
    this_week = now.date() - timedelta(days=now.weekday())
    weeks = []
    for i in range(WEEKS - 1, -1, -1):
        start = this_week - timedelta(weeks=i)
        wk = [r for r in scored if (t := _ts(r)) and start <= t.date() < start + timedelta(weeks=1)]
        n = sum(r["heard"] for r in wk)
        weeks.append({"week": start.isoformat(), "clarity": round(100 * sum(map(_clear, wk)) / n) if n else None,
                      "dictations": len(wk)})
    unsure: dict[str, Counter] = defaultdict(Counter)
    said: dict[str, Counter] = defaultdict(Counter)
    shown: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))  # how it's written
    for r in scored:
        lang = _lang(r)
        said[lang].update(w.lower() for w in WORD.findall(r.get("text", "")))
        for w in r.get("unsure") or []:
            unsure[lang][w.lower()] += 1
            shown[lang][w.lower()][w] += 1
    words = []
    for lang, c in sorted(unsure.items(), key=lambda kv: -sum(kv[1].values())):
        top_words = [{"word": shown[lang][w].most_common(1)[0][0], "unsure": k, "said": max(k, said[lang][w])}
                     for w, k in c.most_common(top)]
        if top_words:
            words.append({"lang": lang, "words": top_words})
    first = min((t for r in scored if (t := _ts(r))), default=None)
    return {"dictations": len(scored), "clarity": round(100 * sum(map(_clear, scored)) / heard),
            "since": first.date().isoformat() if first else None, "weeks": weeks, "words": words}
