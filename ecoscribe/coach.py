"""Speech coaching (dictado-9jc; Settings > Insights tab): help you speak more clearly, from how you dictate.

Everything is worked out here, on this computer, from the dictation history (history.jsonl).

- Clarity (9jc.1): after the paste, a second look at the recording says how sure Whisper was of each word
  (ASR confidence follows how intelligible speech is). Clarity is the share of words heard clearly; the
  words it wasn't sure of are kept, so the ones you keep swallowing show up.
- Coach me (9jc.2): your recent dictations to people (messages, email; not prompts to AI apps) as one
  prompt asking Claude for your recurring patterns, before -> after rewrites of your own sentences
  and one habit to try. The text leaves the computer only when you paste it.
- Fillers and hedges (9jc.3): per 100 words in your messages to people, week by week, and (opt-in) a
  short note on the pill right after such a message: immediate feedback cuts fillers without making
  people anxious. Neutral on purpose: fillers are normal discourse markers in speech; in writing to
  someone, hedges ("maybe", "I think", "kind of") can read as unsure.
- Pace and pauses (9jc.4): words per minute of speech (after the voice detector) and the share of the
  recording that was pauses, to people vs to AI apps. Listeners follow best at about 130-160 words a
  minute: shown as information, not as a goal.
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
# "like" only as a filler: not "I'd like", "would like", "looks like", "I like it", "I feel like" (a hedge)
LIKE = r"(?<!would )(?<!'d )(?<!’d )(?<!i )(?<!you )(?<!we )(?<!they )(?<!looks )(?<!look )(?<!feels )(?<!feel )(?<!don't )(?<!to )like"
FILLERS = {
    "en": [LIKE, "actually", "basically", "you know", "i mean", "literally", "right?", "yeah yeah"],
    "es": ["o sea", "bueno", "pues", "en plan", "vale", "sabes", "¿vale?", "tipo", "digamos"],
    "sv": ["typ", "liksom", "alltså", "asså", "ju", "ba", "va"],
    "el": ["λοιπόν", "δηλαδή", "ας πούμε", "ξέρεις", "καλά", "βασικά"],
}
HEDGES = {
    "en": ["kind of", "sort of", "maybe", "i think", "i guess", "i don't know", "perhaps", "probably", "i feel like",
           "i suppose", "a little bit"],
    "es": ["creo que", "a lo mejor", "quizás", "quizá", "tal vez", "no sé", "más o menos", "supongo", "un poco"],
    "sv": ["kanske", "jag tror", "jag vet inte", "på något sätt", "ungefär", "antagligen", "lite grann"],
    "el": ["ίσως", "νομίζω", "μάλλον", "δεν ξέρω", "κάπως", "λίγο πολύ", "πιθανόν"],
}
MIN_WEEK_WORDS = 50  # a week with fewer words to people says nothing
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


def count(text: str, phrases: list[str]) -> dict[str, int]:
    """{phrase: times} in lowercase `text`, whole words only ("like" only as a filler)."""
    out = {}
    for f in dict.fromkeys(phrases):
        pat = f if f == LIKE else re.escape(f)
        out["like" if f == LIKE else f] = len(re.findall(r"(?<!\w)" + pat + r"(?!\w)", text))
    return out


def markers(text: str, lang: str | None) -> dict:
    """{"fillers": {word: n}, "hedges": {word: n}} said in one text; a mix ("es+sv") uses each language's lists."""
    low = (text or "").lower()
    langs = str(lang or "").split("+")
    out = {}
    for kind, lists in (("fillers", FILLERS), ("hedges", HEDGES)):
        phrases = [p for code in langs for p in lists.get(code, [])]
        out[kind] = {w: k for w, k in count(low, phrases).items() if k}
    return out


def pill_note(m: dict, top: int = 3) -> str | None:
    """The pill's note after a message to a person: "like ×3 · i think · maybe", or None."""
    both = Counter({**m.get("fillers", {}), **m.get("hedges", {})})
    if not both:
        return None
    return " · ".join(f"{w} ×{k}" if k > 1 else w for w, k in both.most_common(top))


def markers_summary(rows: list[dict], now: datetime | None = None, top: int = 5) -> dict:
    """Fillers and hedges per 100 words in dictations to people: over `rows`, per week (8 weeks, oldest
    first, None for a week under MIN_WEEK_WORDS) and the most used of each."""
    now = now or datetime.now()
    people = [r for r in rows if row_audience(r) == "people" and str(r.get("text", "")).strip()]
    if not people:
        return {"words": 0}

    def tally(rs):
        n, f, h = 0, Counter(), Counter()
        for r in rs:
            n += len(WORD.findall(r["text"]))
            m = markers(r["text"], r.get("lang"))
            f.update(m["fillers"])
            h.update(m["hedges"])
        return n, f, h

    def per_100(k, n):
        return round(100 * k / n, 1) if n else 0
    n, f, h = tally(people)
    this_week = now.date() - timedelta(days=now.weekday())
    weeks = []
    for i in range(WEEKS - 1, -1, -1):
        start = this_week - timedelta(weeks=i)
        wn, wf, wh = tally([r for r in people if (t := _ts(r)) and start <= t.date() < start + timedelta(weeks=1)])
        ok = wn >= MIN_WEEK_WORDS
        weeks.append({"week": start.isoformat(), "words": wn,
                      "fillers_per_100": per_100(sum(wf.values()), wn) if ok else None,
                      "hedges_per_100": per_100(sum(wh.values()), wn) if ok else None})
    return {"words": n, "dictations": len(people), "fillers_per_100": per_100(sum(f.values()), n),
            "hedges_per_100": per_100(sum(h.values()), n), "weeks": weeks,
            "top_fillers": [{"word": w, "count": k} for w, k in f.most_common(top)],
            "top_hedges": [{"word": w, "count": k} for w, k in h.most_common(top)]}


PACE_RANGE = (130, 160)  # words a minute where comprehension peaks (information, not a goal)
PACE_MIN_WORDS, PACE_MIN_SPEECH_S = 8, 4.0  # shorter dictations say nothing about pace
PACE_BINS = (80, 220, 10)  # histogram: 10 wpm wide, the ends gather the rest


def _paced_rows(rows):
    for r in rows:
        speech, audio = float(r.get("speech_s") or 0), float(r.get("audio_s") or 0)
        n = len(WORD.findall(str(r.get("text", ""))))
        if speech >= PACE_MIN_SPEECH_S and n >= PACE_MIN_WORDS and audio >= speech:
            yield r, n, speech, audio


def pace_summary(rows: list[dict]) -> dict:
    """Pace (words a minute of speech) and pauses (% of the recording) for dictations to people and to
    AI apps, the share of them in PACE_RANGE, and a histogram of the ones to people."""
    groups: dict[str, list] = {"people": [], "ai": []}
    for r, n, speech, audio in _paced_rows(rows):
        to = row_audience(r)
        if to in groups:
            groups[to].append((n, speech, audio))
    lo, hi = PACE_RANGE

    def summary(g):
        if not g:
            return None
        words, speech, audio = (sum(x[i] for x in g) for i in range(3))
        each = [60 * n / s for n, s, _ in g]
        return {"dictations": len(g), "wpm": round(60 * words / speech), "pauses": round(100 * (1 - speech / audio)),
                "in_range": round(100 * sum(lo <= w <= hi for w in each) / len(g))}
    start, end, width = PACE_BINS
    hist = []
    if groups["people"]:
        counts = Counter(min(max(int(60 * n / s // width * width), start), end) for n, s, _ in groups["people"])
        hist = [{"from": b, "dictations": counts.get(b, 0)} for b in range(start, end + width, width)]
    return {"people": summary(groups["people"]), "ai": summary(groups["ai"]), "range": [lo, hi], "histogram": hist}
