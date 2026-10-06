"""Pure choosers: which language, which microphone."""
from __future__ import annotations


def pick_language(probs: list[tuple[str, float]], allowed: list[str]) -> str:
    best = [(p, lang) for lang, p in probs if lang in allowed]
    return max(best)[1] if best else allowed[0]


def pick_device(devices: list[dict], hostapis: list[dict], name: str, host: str) -> int | None:
    """Index of the input device whose name contains `name` on `host`; None = the default mic
    (also when no name is set: "" would otherwise match the first mic in the list)."""
    if not (name or "").strip():
        return None
    want, want_host = name.lower(), host.lower()
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) <= 0:
            continue
        if hostapis[d["hostapi"]]["name"].lower() != want_host:
            continue
        if want in d["name"].lower():
            return i
    return None
