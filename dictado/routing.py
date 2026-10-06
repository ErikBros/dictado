"""Which Whisper model transcribes which language (the [transcribe] routes table)."""
from __future__ import annotations

from .config import TranscribeCfg, _default_routes

LANG_NAMES = {"sv": "Swedish", "en": "English", "es": "Spanish", "el": "Greek", "el,es": "Greek + Spanish",
              "auto": "Detect"}


def mixed_langs(lang: str | None) -> list[str] | None:
    """"el,es" -> ["el", "es"]: a session that switches between them, detected piece by
    piece (t0u.34). None for a single language or "auto"."""
    langs = [x for x in str(lang or "").split(",") if x]
    return langs if len(langs) > 1 else None


def model_for(lang: str, cfg: TranscribeCfg) -> str:
    """Model for `lang`: its exact route, else the "*" route. "auto" must be detected first.
    A mixed session runs on its first language's model (Greek + Spanish: large-v3)."""
    if lang == "auto":
        raise ValueError("lang 'auto': detect the language first, then route")
    lang = (mixed_langs(lang) or [lang])[0]
    routes = cfg.routes or {}
    if lang in routes:
        return routes[lang]
    return routes.get("*") or _default_routes()["*"]
