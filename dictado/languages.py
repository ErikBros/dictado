"""Languages as add-ons (dictado-ehs).

Ecoscribe comes with English and Swedish. Any other language Whisper knows can be added in
Settings ("Add a language"); nothing is downloaded, the speech models already know them all.
Every language list in the app (dictation, meetings, files, tray, the call prompt) is built
from the built-in two plus what the user added.
"""
from __future__ import annotations

BASE = ("en", "sv")

# Whisper's languages: the same 100 codes as faster_whisper.tokenizer._LANGUAGE_CODES (a test checks).
ALL: dict[str, str] = {
    "en": "English", "zh": "Chinese", "de": "German", "es": "Spanish", "ru": "Russian", "ko": "Korean",
    "fr": "French", "ja": "Japanese", "pt": "Portuguese", "tr": "Turkish", "pl": "Polish", "ca": "Catalan",
    "nl": "Dutch", "ar": "Arabic", "sv": "Swedish", "it": "Italian", "id": "Indonesian", "hi": "Hindi",
    "fi": "Finnish", "vi": "Vietnamese", "he": "Hebrew", "uk": "Ukrainian", "el": "Greek", "ms": "Malay",
    "cs": "Czech", "ro": "Romanian", "da": "Danish", "hu": "Hungarian", "ta": "Tamil", "no": "Norwegian",
    "th": "Thai", "ur": "Urdu", "hr": "Croatian", "bg": "Bulgarian", "lt": "Lithuanian", "la": "Latin",
    "mi": "Maori", "ml": "Malayalam", "cy": "Welsh", "sk": "Slovak", "te": "Telugu", "fa": "Persian",
    "lv": "Latvian", "bn": "Bengali", "sr": "Serbian", "az": "Azerbaijani", "sl": "Slovenian", "kn": "Kannada",
    "et": "Estonian", "mk": "Macedonian", "br": "Breton", "eu": "Basque", "is": "Icelandic", "hy": "Armenian",
    "ne": "Nepali", "mn": "Mongolian", "bs": "Bosnian", "kk": "Kazakh", "sq": "Albanian", "sw": "Swahili",
    "gl": "Galician", "mr": "Marathi", "pa": "Punjabi", "si": "Sinhala", "km": "Khmer", "sn": "Shona",
    "yo": "Yoruba", "so": "Somali", "af": "Afrikaans", "oc": "Occitan", "ka": "Georgian", "be": "Belarusian",
    "tg": "Tajik", "sd": "Sindhi", "gu": "Gujarati", "am": "Amharic", "yi": "Yiddish", "lo": "Lao",
    "uz": "Uzbek", "fo": "Faroese", "ht": "Haitian Creole", "ps": "Pashto", "tk": "Turkmen", "nn": "Nynorsk",
    "mt": "Maltese", "sa": "Sanskrit", "lb": "Luxembourgish", "my": "Myanmar", "bo": "Tibetan", "tl": "Tagalog",
    "mg": "Malagasy", "as": "Assamese", "tt": "Tatar", "haw": "Hawaiian", "ln": "Lingala", "ha": "Hausa",
    "ba": "Bashkir", "jw": "Javanese", "su": "Sundanese", "yue": "Cantonese",
}

# Languages the fast model (turbo) handles about as well as large-v3. Anything else in the set
# moves dictation to large-v3: measured for Swedish and Greek (2026-10-05), and the usual pattern
# for lower-resource languages, where turbo's 4-layer decoder loses most.
TURBO_OK = {"en", "es", "fr", "de", "it", "pt", "nl", "ca", "pl", "ru", "ja", "zh", "ko"}


def name(code: str | None) -> str:
    """'es' -> 'Spanish', 'en,sv' -> 'English + Swedish', 'auto' -> 'Detect'."""
    if not code:
        return ""
    if code == "auto":
        return "Detect"
    parts = [c for c in str(code).split(",") if c]
    return " + ".join(ALL.get(c, c) for c in parts)


def available(extra) -> list[str]:
    """The built-in two plus the added ones, no repeats, unknown codes dropped."""
    out = list(BASE)
    for c in extra or []:
        if c in ALL and c not in out:
            out.append(c)
    return out


def valid_extra(extra) -> list[str]:
    """Added languages as saved: known codes, not built-in, no repeats."""
    out: list[str] = []
    for c in extra or []:
        c = str(c).strip().lower()
        if c not in ALL:
            raise ValueError(f"unknown language: {c}")
        if c not in BASE and c not in out:
            out.append(c)
    return out


def needs_big_model(langs) -> bool:
    return any(c not in TURBO_OK for c in langs or [])


def meeting_options(avail: list[str]) -> list[tuple[str, str]]:
    """Meeting / file language choices: each language, then all of them mixed (detected piece by
    piece) when there's more than one, then Detect (any language)."""
    opts = [(c, ALL.get(c, c)) for c in avail]
    if len(avail) > 1:
        opts.append((",".join(avail), name(",".join(avail)) if len(avail) == 2
                     else "Mixed: " + " · ".join(c.upper() for c in avail)))
    opts.append(("auto", "Detect"))
    return opts


def valid_meeting_lang(code: str) -> bool:
    """Any known language, any mix of known languages (a saved 'el,es' keeps working), or auto."""
    if code == "auto":
        return True
    parts = [c for c in str(code or "").split(",") if c]
    return bool(parts) and all(c in ALL for c in parts)
