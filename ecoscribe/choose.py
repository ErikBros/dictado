"""Pure choosers: which language, which microphone."""
from __future__ import annotations


STICKY = 0.15  # dictation-languages: keep the last language unless another wins by more than this


def pick_language(probs: list[tuple[str, float]], allowed: list[str], prefer: str | None = None) -> str:
    """The most likely of `allowed`. With `prefer` (the last dictation's language) a close call
    stays with it: people dictate several times in a row in one language, and short clips are
    where detection wobbles (accented English heard as Spanish)."""
    p = {lang: pr for lang, pr in probs if lang in allowed}
    if not p:
        return prefer if prefer in allowed else allowed[0]
    top = max(p, key=p.get)
    if prefer in p and prefer != top and p[top] - p[prefer] < STICKY:
        return prefer
    return top


def pick_device(devices: list[dict], hostapis: list[dict], name: str, host: str) -> int | None:
    """Index of the input device whose name contains `name` on `host`; None = the default mic
    (also when no name is set: "" would otherwise match the first mic in the list)."""
    if not (name or "").strip():
        return None
    want, want_host = name.lower(), host.lower()
    if not want.strip() and want_host == "core audio":
        return None  # Mac: no name = the system default input (PortAudio's default device)
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) <= 0:
            continue
        if hostapis[d["hostapi"]]["name"].lower() != want_host:
            continue
        if want in d["name"].lower():
            return i
    return None
