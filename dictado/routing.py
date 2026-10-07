"""Which Whisper model transcribes which language (the [transcribe] routes table)."""
from __future__ import annotations

from .config import TranscribeCfg, _default_routes
from .languages import ALL, name


class _Names(dict):
    """Old LANG_NAMES lookups keep working for any code or mix (dictado-ehs)."""

    def get(self, key, default=None):
        return name(key) if key and (key == "auto" or all(c in ALL for c in str(key).split(","))) else default

    def __getitem__(self, key):
        return self.get(key, key)


LANG_NAMES = _Names()


def mixed_langs(lang: str | None) -> list[str] | None:
    """"el,es" -> ["el", "es"]: a session that switches between them, detected piece by
    piece (t0u.34). None for a single language or "auto"."""
    langs = [x for x in str(lang or "").split(",") if x]
    return langs if len(langs) > 1 else None


def model_for(lang: str, cfg: TranscribeCfg) -> str:
    """Model for `lang`: its exact route, else the "*" route. "auto" must be detected first.
    A mixed session runs on the strongest model any of its languages needs (English + Swedish:
    large-v3, because Swedish needs it), never on a weaker one."""
    if lang == "auto":
        raise ValueError("lang 'auto': detect the language first, then route")
    routes = cfg.routes or {}
    star = routes.get("*") or _default_routes()["*"]
    models = [routes.get(c, star) for c in (mixed_langs(lang) or [lang])]
    return next((m for m in models if "turbo" not in m), models[0])
