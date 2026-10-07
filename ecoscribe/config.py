"""Config: dataclass defaults, optionally overridden by a TOML file."""
from __future__ import annotations

import logging
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

# Right Alt is deliberately absent: on the user's Swedish layout it is AltGr (@ { [ ]).
KEYS = {"rctrl": 0xA3, "scrolllock": 0x91, "pause": 0x13}
KEYS.update({f"f{n}": 0x7C + (n - 13) for n in range(13, 25)})
MAC = sys.platform == "darwin"
if MAC:  # Mac virtual keycodes. No Right Ctrl on a MacBook: Right Command (uat, D2). Right Option is the
    # Swedish layout's @ [ ] { } key, the AltGr of the Mac: not allowed, same rule as Windows.
    KEYS = {"rcmd": 54, "rctrl": 62, "fn": 63, "f13": 105, "f14": 107, "f15": 113, "f16": 106,
            "f17": 64, "f18": 79, "f19": 80}


@dataclass
class HotkeyCfg:
    key: str = "rcmd" if MAC else "rctrl"
    max_tap_s: float = 1.0
    # t0u.28: hold the key to talk, let go to stop (a tap still toggles). Lone keys only.
    hold_to_talk: bool = False
    hold_s: float = 0.5  # held this long with nothing else pressed = hold-to-talk
    numpad_enter: bool = False  # the numpad's Enter is a second dictation key (it no longer types Enter)

    @property
    def vk(self) -> int:
        """The lone key's vk; 0 for a combo (hotkeys.ComboMatcher handles those)."""
        return KEYS.get(self.key, 0)


@dataclass
class AudioCfg:
    device: str = ""  # part of the mic's name; "" = the system's default mic
    host: str = "Core Audio" if MAC else "MME"
    samplerate: int = 16000
    preroll_s: float = 0.4
    # Closed while idle: no permanent "app is using your microphone" icon. Costs the
    # pre-roll (which only holds silence anyway while the mic is muted) and ~25 ms.
    keep_open: bool = False
    # Both mics were found muted at volume 0; open the mic only while recording.
    unmute_while_recording: bool = not MAC  # the muted-at-0 mics were a PC thing
    unmute_volume: float = 0.8


@dataclass
class WhisperCfg:
    model: str = "large-v3-turbo"
    device: str = "mlx" if MAC else "cuda"  # mlx = Apple GPU (Metal), spike/report-mac.md
    compute_type: str = "float16"
    beam_size: int = 5
    extra_languages: list = field(default_factory=list)  # dictado-ehs: added beyond English + Swedish
    languages: list = field(default_factory=lambda: ["en"])  # English by default; add "es" to allow Spanish
    # Swedish dictation (t0u.24) runs on its own model: turbo got 8.4 % WER on Swedish, large-v3 3.4 %
    # (spike 2026-10-05); int8_float16 = same WER, ~2.3 GB instead of 3.5. Only for languages == ["sv"].
    sv_model: str = "Systran/faster-whisper-large-v3"
    sv_compute_type: str = "int8_float16"
    # true: the model lives in a worker started at the tap and stopped after idle_exit_s
    # (frees GPU memory and RAM between dictations). false: loaded at startup, kept (1.1).
    on_demand: bool = True  # 1.2 default: no model resident all day
    idle_exit_s: float = 600.0


@dataclass
class TextCfg:
    append_space: bool = True
    strip_fillers: bool = True
    vocabulary: list = field(default_factory=list)  # names/terms Whisper should spell your way (prompt)
    voice_commands: bool = False  # "new line", "new paragraph", a closing "send it" (presses Enter)
    # names on the window you dictate into go in that dictation's prompt (t0u.27: names right
    # 77 % -> 87 % on real speech, no time cost; read locally through UI Automation)
    screen_names: bool = True
    snippets: dict = field(default_factory=dict)  # t0u.29: spoken trigger -> saved text ("my email" -> ...)


@dataclass
class UiCfg:
    overlay: bool = True
    live_text: bool = True  # dictado-live: the pill shows what it has heard so far while you dictate
    sounds: bool = True
    debug_log: bool = False  # t0u.37: Settings > Troubleshooting > Detailed logging (DEBUG level)


@dataclass
class LimitsCfg:
    max_record_s: float = 600.0
    min_audio_s: float = 0.3
    hook_reinstall_s: float = 30.0
    hook_process: bool = True  # t0u.37: keyboard/mouse hooks in their own process (a frozen app can't stall the PC)


def _default_routes() -> dict:
    # sv on large-v3, not KB-Whisper: on real Swedish podcast speech, played back and through
    # loopback, large-v3 had 3.5% WER vs KB 5.8 to 8.8% (spike/sv_real, 2026-10-05). KB stays
    # available as a route ("KBLab/kb-whisper-large") for dialect-heavy audio.
    return {"sv": "Systran/faster-whisper-large-v3", "en": "large-v3-turbo", "es": "large-v3-turbo",
            "*": "Systran/faster-whisper-large-v3"}


@dataclass
class TranscribeCfg:
    """Meeting / file transcription. `routes` maps a language code to a model ("*" = any other).
    A [transcribe] routes table in config.toml REPLACES the whole default table (load() sets
    each key as a whole value), so an override must include "*"; routing falls back to the
    default "*" model if it does not."""
    routes: dict = field(default_factory=_default_routes)
    detector_model: str = "large-v3-turbo"
    compute_type: str = "int8_float16"  # spike 2026-10-02: same WER as float16, about half the VRAM
    beam_size: int = 5
    root: str = ""  # empty: %LOCALAPPDATA%\ecoscribe\transcripts
    # Where the big transcription models live (HF cache in <models_root>\hf, mirrors next to it,
    # one drive so the mirror can hard-link). Empty: %LOCALAPPDATA%\ecoscribe\models.
    models_root: str = ""


@dataclass
class MeetingsCfg:
    """Call detection (detect.py + meetwatch.py). mode: "prompt" asks near the pill,
    "auto" starts recording by itself, "off" never looks."""
    mode: str = "prompt"
    grace_s: float = 20  # mic released this long = the call ended (mute toggles, quick rejoins)
    silence_stop_s: float = 180  # backup when the end is missed: both tracks silent this long
    default_lang: str = "sv"
    speakers: bool = True  # tell remote voices apart after a call (needs the speaker add-on)
    voice_memory: bool = True  # t0u.32: name a voice once, recognised in later calls (local voices.json)
    calendar_url: str = ""  # t0u.35: secret iCal link; names meetings from the event happening now


@dataclass
class Config:
    hotkey: HotkeyCfg = field(default_factory=HotkeyCfg)
    audio: AudioCfg = field(default_factory=AudioCfg)
    whisper: WhisperCfg = field(default_factory=WhisperCfg)
    text: TextCfg = field(default_factory=TextCfg)
    ui: UiCfg = field(default_factory=UiCfg)
    limits: LimitsCfg = field(default_factory=LimitsCfg)
    transcribe: TranscribeCfg = field(default_factory=TranscribeCfg)
    meetings: MeetingsCfg = field(default_factory=MeetingsCfg)


def load(path: Path | None) -> Config:
    cfg = Config()
    if path is None or not Path(path).exists():
        return cfg
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section, values in data.items():
        target = getattr(cfg, section, None)
        if target is None or not isinstance(values, dict):
            log.warning("config: unknown section [%s] ignored", section)
            continue
        names = {f.name for f in fields(target)}
        for key, value in values.items():
            if key not in names:
                log.warning("config: unknown key %s.%s ignored", section, key)
                continue
            setattr(target, key, value)
    from . import hotkeys  # lone keys (KEYS) or combos like "ctrl+l"
    cfg.hotkey.key = hotkeys.normalize(cfg.hotkey.key)  # raises ValueError with the reason
    return cfg
