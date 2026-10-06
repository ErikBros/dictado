"""Local voice memory (t0u.32): voices the user has named, recognised in later calls.

One averaged, unit-length embedding per name in %LOCALAPPDATA%\\dictado\\voices.json
(pyannote community-1 speaker embeddings from the add-on). Nothing here leaves the PC.
Threshold measured on real podcasts (spike/voice_memory, 2026-10-05): the same person in
different recordings 0.75-0.99 cosine, two different people at most 0.28.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

THRESHOLD = 0.55
MIN_SPEECH_S = 8.0  # a voice heard for less than this is too thin to store or to match


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _unit(v) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("people", {})
    except (OSError, ValueError, AttributeError):
        return {}


def _save(path: Path, people: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "people": people}), encoding="utf-8")
    os.replace(tmp, path)


def names(path: Path) -> list[str]:
    return sorted(load(path))


def learn(path: Path, name: str, emb) -> None:
    """Fold one more recording of `name`'s voice into the memory (running mean of unit vectors)."""
    people = load(path)
    cur = people.get(name)
    v = _unit(emb)
    if cur and len(cur.get("emb", [])) == len(v):
        n = int(cur.get("n", 1))
        v = _unit([(a * n + b) / (n + 1) for a, b in zip(cur["emb"], v)])
        people[name] = {"emb": v, "n": n + 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    else:
        people[name] = {"emb": v, "n": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(path, people)


def forget(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


def match(embs: dict, people: dict, threshold: float = THRESHOLD) -> dict:
    """{label: (name, score)} for the voices that sound like someone named before; each name
    goes to at most one label (the closest), each label gets at most one name."""
    pairs = sorted(((cosine(e, p["emb"]), label, name) for label, e in embs.items()
                    for name, p in people.items() if len(p.get("emb", [])) == len(e)), reverse=True)
    out, used = {}, set()
    for score, label, name in pairs:
        if score < threshold:
            break
        if label not in out and name not in used:
            out[label] = (name, round(score, 3))
            used.add(name)
    return out
