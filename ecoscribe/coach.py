"""Speech coaching (dictado-9jc; Settings > Insights tab): help you speak more clearly, from how you dictate.

Everything is worked out here, on this computer, from the dictation history (history.jsonl).

- Clarity (9jc.1): after the paste, a second look at the recording says how sure Whisper was of each word
  (ASR confidence follows how intelligible speech is). Clarity is the share of words heard clearly; the
  words it wasn't sure of are kept, so the ones you keep swallowing show up.
- Coach me (9jc.2): your recent dictations to people (messages, email; not prompts to AI apps) as one
  prompt asking Claude for your recurring patterns, before -> after rewrites of your own sentences
  and one habit to try. The text leaves the computer only when you paste it.
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


# Who a dictation was for (9jc.2): app names as Windows (.exe) and macOS (localized name) report them,
# lowercased with spaces, dots and ".exe" dropped.
PEOPLE_APPS = set("""slack msteams teams microsoftteams outlook olk microsoftoutlook mail thunderbird whatsapp
    whatsapproot telegram telegramdesktop signal discord messages messenger skype zoom element viber mattermost
    spark airmail superhuman""".split())
AI_APPS = set("""claude chatgpt cursor windsurf code visualstudiocode zed windowsterminal wt cmd powershell pwsh
    conhost terminal iterm2 warp ghostty alacritty wezterm weztermgui kitty devenv pycharm64 idea64 sublimetext
    perplexity copilot""".split())
BROWSERS = set("""chrome googlechrome msedge microsoftedge firefox brave arc safari opera vivaldi zen""".split())
# the site a browser tab is on, from its title's last parts ("Subject - Inbox - Gmail - Google Chrome")
PEOPLE_SITES = ("gmail", "inbox", "outlook", "mail", "slack", "whatsapp", "messenger", "linkedin", "teams",
                "discord", "telegram", "signal", "proton", "facebook", "instagram")
AI_SITES = ("claude", "chatgpt", "gemini", "perplexity", "copilot", "le chat", "mistral", "grok", "deepseek",
            "notebooklm", "poe")
TITLE_SEP = re.compile(r"\s+[-–—|·]\s+")
COACH_DAYS = 14


def _app(name) -> str:
    n = str(name or "").lower()
    n = n[:-4] if n.endswith(".exe") else n
    return re.sub(r"[\s._-]", "", n)


def audience(target, title: str = "") -> str:
    """"people" (messages, email), "ai" (AI apps, terminals, code editors) or "other", from the app
    and, in a browser, the site the tab is on (the title's parts from the end)."""
    app = _app(target)
    if app in PEOPLE_APPS:
        return "people"
    if app in AI_APPS:
        return "ai"
    if app not in BROWSERS or not title:
        return "other"
    for part in reversed(TITLE_SEP.split(title.lower())):
        if any(part == s or part.startswith(s + " ") or part.endswith(" " + s) for s in PEOPLE_SITES):
            return "people"
        if any(s in part for s in AI_SITES):
            return "ai"
    return "other"


def row_audience(r: dict) -> str:
    """Saved at the paste from 9jc.2 on; older dictations go by the app alone."""
    return r.get("to") or audience(r.get("target"))


def _recent_people(rows: list[dict], now: datetime, days: int = COACH_DAYS) -> list[dict]:
    since = now - timedelta(days=days)
    return [r for r in rows if (t := _ts(r)) and t >= since and row_audience(r) == "people"
            and str(r.get("text", "")).strip()]


def people_count(rows: list[dict], now: datetime | None = None) -> int:
    return len(_recent_people(rows, now or datetime.now()))


def coach_prompt(rows: list[dict], now: datetime | None = None, max_words: int = 4000) -> str:
    """The last two weeks of dictations to people as a coaching prompt for Claude: the newest that fit
    in `max_words`, oldest first."""
    now = now or datetime.now()
    keep, n = [], 0
    for r in sorted(_recent_people(rows, now), key=lambda r: str(r.get("ts")), reverse=True):
        k = len(WORD.findall(r["text"]))
        if keep and n + k > max_words:
            break
        keep.append(r)
        n += k
    lines = [
        "Below are messages I dictated to people (chat and email) in the last two weeks, written out by "
        "speech-to-text exactly as I said them. I want to speak more clearly and more confidently.",
        "",
        "1. Name my 3 recurring patterns that make me less clear or less confident (filler words, hedges, "
        "long run-ups, vague words, repeating myself, sentences that never land). Quote two short examples of mine for each.",
        "2. For each pattern, rewrite two of my own sentences: before -> after, in my voice, same meaning.",
        "3. Give me one habit to try this week, concrete enough to notice when I do it.",
        "",
        "Ignore speech-to-text slips (misheard words, punctuation): judge how I talk, not the transcription. "
        "Be direct and brief.",
        "",
        "---",
    ]
    for r in reversed(keep):
        t = _ts(r)
        app = str(r.get("target") or "").removesuffix(".exe")
        lines.append(f"- [{t.strftime('%a %H:%M') if t else ''}{', ' + app if app else ''}] {r['text'].strip()}")
    return "\n".join(lines) + "\n"
