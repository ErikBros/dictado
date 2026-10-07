"""Word error rate, for the spike's model comparisons (no extra dependencies)."""
from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)  # drops , . ! ? ; · « » - and Greek ; (U+037E)


def words(text: str) -> list[str]:
    return _PUNCT.sub(" ", text.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / len(r)
