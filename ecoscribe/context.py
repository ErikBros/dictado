"""Names from the window you dictate into ([text] screen_names, t0u.27).

At the tap, a background thread reads the focused window's title and the text of its
controls through UI Automation / Accessibility (local, nothing leaves the PC) and keeps the
words that look like names: capitalised mid-sentence, or with a capital inside
(McDonald, pyannote stays out). They go after "Your words" in that dictation's
Whisper prompt, so a name on screen is spelled the way the screen spells it.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter

log = logging.getLogger(__name__)

MAX_NAMES = 25
# Capitalised words that are not names: sentence starters, UI chrome, weekdays and months.
_COMMON = set("""
a an and are as at be but by can do for from has have he her his how i if in is it its let me my no
not of on or our she so that the their them then there these they this to up us was we what when
where which who why will with you your yes ok okay hi hello hey thanks thank dear best regards
new open close save cancel edit view file help home search settings send reply forward delete
inbox draft drafts sent archive more share copy paste undo redo back next today yesterday tomorrow
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december am pm
el la los las un una y o de del en con por para que es no si hola gracias
och att det som en ett jag du han hon vi ni de är på för med till av inte hej tack
""".split())
_WORD = re.compile(r"[^\W\d_][\w'’\-]*", re.UNICODE)
_SENT_END = re.compile(r"[.!?:;]\s*$")
_SEGMENT = re.compile(r"\s*(?:[\n\r\t|•·–—]| - )\s*")


def _looks_named(w: str) -> bool:
    return (w[0].isupper() or any(c.isupper() for c in w[1:])) and len(w) > 1 and not w.isupper() \
        or (w.isupper() and 2 <= len(w) <= 6)  # acronyms: AWS, GDPR


def names_from_text(texts, limit: int = MAX_NAMES) -> list[str]:
    """Name-like words from on-screen texts, most frequent first.

    A capitalised word at the start of a sentence only counts if the same word also shows
    up capitalised mid-sentence somewhere ("Sarah said" at the start of one line and
    "thanks Sarah" in another). Common words are always dropped."""
    mid, start = Counter(), Counter()
    for t in texts:
        for seg in _SEGMENT.split(str(t or "")):
            words = [m for m in _WORD.finditer(seg)]
            # a short all-capitalised label ("Johanna Lindqvist", a title part) is a name as a whole
            label = 0 < len(words) <= 4 and all(m.group(0)[0].isupper() for m in words)
            for m in words:
                w = m.group(0).strip("'’-")
                if len(w) < 2 or w.lower() in _COMMON or not _looks_named(w):
                    continue
                before = seg[:m.start()]
                at_start = not label and (not before.strip() or _SENT_END.search(before))
                (start if at_start else mid)[w] += 1
    for w, n in start.items():
        if w in mid:
            mid[w] += n
    return [w for w, _ in mid.most_common(limit)]


if __import__("sys").platform == "darwin":  # Accessibility (ecoscribe/platform/macos/context.py)
    from .platform.macos.context import window_texts
else:  # UI Automation (ecoscribe/platform/windows/context.py)
    from .platform.windows.context import window_texts


class ScreenNames:
    """Started at the tap, read at the stop: never adds time after you stop talking."""

    def __init__(self, reader=None):
        self.reader = reader or (lambda: window_texts())  # late-bound: tests swap window_texts
        self._names: list[str] = []
        self._done = threading.Event()

    def start(self) -> "ScreenNames":
        threading.Thread(target=self._run, name="ecoscribe-screen", daemon=True).start()
        return self

    def _run(self) -> None:
        t0 = time.monotonic()
        try:
            self._names = names_from_text(self.reader())
        except Exception:
            log.exception("screen names failed")
        finally:
            self._done.set()
        log.info("screen names n=%d ms=%d", len(self._names), (time.monotonic() - t0) * 1000)

    def get(self, wait_s: float = 0.05) -> list[str]:
        """The names, or [] if the read is not done yet (never holds up the paste)."""
        return list(self._names) if self._done.wait(wait_s) else []
