"""Rule-based transcript cleanup. No LLM: speed is the product."""
from __future__ import annotations

import re

_FILLERS = r"(?:um+|uh+|erm|er|hmm+|mm+|eh|em|ehm)"
_FILLER_RE = re.compile(rf"(?<![\w'])({_FILLERS})(?![\w'])[,.]?", re.IGNORECASE)
_SPACE_PUNCT = re.compile(r"\s+([,.!?;:])")
_DOUBLE_COMMA = re.compile(r",\s*([,.!?])")

# Whisper invents these on silence. Only dropped with barely any speech or a high no-speech prob.
_HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching",
    "subtitles by the amaraorg community", "you", "gracias", "gracias por ver el video",
    "subtítulos realizados por la comunidad de amaraorg",
}


def clean(s: str, strip_fillers: bool = True, append_space: bool = True) -> str:
    s = s.strip()
    if strip_fillers:
        s = _FILLER_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _SPACE_PUNCT.sub(r"\1", s)
    s = _DOUBLE_COMMA.sub(r"\1", s)
    s = s.lstrip(",.;: ").strip()
    if not re.search(r"\w", s):
        return ""
    s = s[0].upper() + s[1:]
    return s + " " if append_space else s


VOCAB_MAX_CHARS = 400  # Whisper's prompt is at most half its 448-token window: keep it short


def vocab_prompt(words) -> str | None:
    """The user's word list as a Whisper prompt ("Dictado, pyannote, Göteborg."), or None when empty.
    A prompt steers spelling without forcing words in (faster-whisper's `hotwords` broke large-v3)."""
    seen, out = set(), []
    for w in words or []:
        w = " ".join(str(w).split())
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    while out and len(", ".join(out)) + 1 > VOCAB_MAX_CHARS:
        out.pop()
    return ", ".join(out) + "." if out else None


# Spoken commands ([text] voice_commands, off by default). A command only counts as its own
# clause: after the start or a punctuation mark, and before one or the end. "We need a new line
# of products" and "did you send it to her" stay text.
# One table for the matcher AND the list in Settings (t0u.38), so the two can't drift apart.
VOICE_COMMANDS = [
    ("paragraph", "Paragraph break", {"en": ["new paragraph"], "es": ["nuevo párrafo", "punto y aparte"],
                                      "sv": ["nytt stycke"]}),
    ("line", "Line break", {"en": ["new line"], "es": ["nueva línea"], "sv": ["ny rad"]}),
    ("enter", "Press Enter after the text (at the very end only)",
     {"en": ["send it", "press enter"], "es": ["envíalo", "enviar"], "sv": ["skicka"]}),
]
_ACCENTS = {"á": "[aá]", "é": "[eé]", "í": "[ií]", "ó": "[oó]", "ú": "[uú]"}


def _phrases(key: str) -> str:
    """Alternation for one command, accent-tolerant ("envialo" = "envíalo")."""
    words = [p for k, _, langs in VOICE_COMMANDS if k == key for ps in langs.values() for p in ps]
    rx = lambda p: r"\s+".join("".join(_ACCENTS.get(c, re.escape(c)) for c in w) for w in p.split())  # noqa: E731
    return "|".join(rx(p) for p in sorted(words, key=len, reverse=True))


_B = r"(^|[.,;:!?])\s*"
_E = r"\s*([.,;:!?]|$)\s*"
_PARAGRAPH = re.compile(_B + f"(?:{_phrases('paragraph')})" + _E, re.IGNORECASE)
_LINE = re.compile(_B + f"(?:{_phrases('line')})" + _E, re.IGNORECASE)
_ENTER = re.compile(_B + f"(?:{_phrases('enter')})" + r"\s*[.!]?\s*$", re.IGNORECASE)


def _end(punct: str) -> str:
    return punct if punct in ".!?" else ("." if punct else "")


def voice_commands(s: str) -> tuple[str, bool]:
    """"new line" -> line break, "new paragraph" -> blank line, a closing "send it" -> (text, press Enter)."""
    enter = False
    m = _ENTER.search(s)
    if m:
        s, enter = s[:m.start()] + _end(m.group(1)), True
    for rx, brk in ((_PARAGRAPH, "\n\n"), (_LINE, "\n")):
        s = rx.sub(lambda m: _end(m.group(1)) + brk, s)
    s = re.sub(r"\n([a-zà-ÿ])", lambda m: "\n" + m.group(1).upper(), s)
    s = s.lstrip("\n")
    return (s.rstrip() if enter else s), enter


def snippets(s: str, table) -> str:
    """Snippets (t0u.29): a clause that is exactly a trigger ("my email") becomes its saved text.
    Same clause rule as voice commands; case is ignored; the longest trigger wins. The
    punctuation Whisper put after the trigger is dropped: the snippet brings its own."""
    if not table or not s:
        return s
    trig = {" ".join(k.lower().split()): v for k, v in table.items() if k and k.strip()}
    if not trig:
        return s
    alts = "|".join(r"\s+".join(map(re.escape, k.split())) for k in sorted(trig, key=len, reverse=True))
    rx = re.compile(rf"(?:^|(?<=[.,;:!?]))(\s*)({alts})(?:\s*[.,;:!?]|\s*$)", re.IGNORECASE)
    return rx.sub(lambda m: m.group(1) + trig[" ".join(m.group(2).lower().split())], s)


def _norm(s: str) -> str:
    return re.sub(r"[^\w ]", "", s.lower()).strip()


def is_hallucination(s: str, speech_s: float, no_speech_prob: float = 0.0) -> bool:
    """True for Whisper's classic silence inventions ("Thank you.", "Gracias.").

    A real spoken "Thank you." has ~0.5-1 s of speech, so length alone can't
    decide: drop a listed phrase only with almost no speech, or when Whisper
    itself says the segment is probably not speech.
    """
    n = _norm(s)
    if not n:
        return True
    return n in _HALLUCINATIONS and (speech_s < 0.3 or no_speech_prob > 0.6)
