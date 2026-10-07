"""The platform contract: everything a platform must provide, and where each one does (dictado-8tf).

Shared code (engine logic, text, meetings, sessions, calendar, crash reports, the window) works on
every platform by itself. What differs per OS is listed here. Each capability names, per platform:

- "module:Name[,Name...]"  where it lives (checked from the source: the file defines those names)
- "file:path"              a file that must exist (packaging scripts)
- ("ticket", "dictado-xxx") not built yet; the ticket must be open and listed in FEATURES.md
- ("not_needed", "reason")  the OS doesn't need it; the reason shows in FEATURES.md

tests/test_platform_contract.py fails when a capability lacks an entry for a platform, when an
entry points at code that isn't there, or when FEATURES.md doesn't list it. Add a capability here
the moment one platform gets something OS-specific, with a ticket for the other.
"""
from __future__ import annotations

PLATFORMS = ("windows", "macos")

CAPABILITIES: dict[str, dict] = {
    "Hotkey (tap / hold / combo, Esc cancel)": {
        "windows": "ecoscribe.hook:HookThread",
        "macos": "ecoscribe.platform.macos.keyhook:HookThread",
    },
    "Language key (dictation key + L picks the next language)": {
        "windows": "ecoscribe.hook:VK_LANG",
        "macos": "ecoscribe.platform.macos.keyhook:KC_LANG,HookThread",  # Right Command + L
    },
    "Paste text where the cursor is": {
        "windows": "ecoscribe.deliver:deliver,set_clipboard_text",
        "macos": "ecoscribe.platform.macos.deliver:deliver,set_clipboard_text",
    },
    "Names on your screen": {
        "windows": "ecoscribe.context:window_texts",
        "macos": "ecoscribe.platform.macos.context:window_texts",
    },
    "Speech engine on the GPU": {
        "windows": "ecoscribe.engine:Engine",  # faster-whisper / CTranslate2 on CUDA
        "macos": "ecoscribe.platform.macos.mlx_engine:MlxWhisperModel",  # mlx-whisper on Metal
    },
    "Mic list in Settings": {
        "windows": "ecoscribe.window:_mme_input_names",
        "macos": "ecoscribe.platform.macos.desktop:input_names",
    },
    "Unmute the mic only while recording": {
        "windows": "ecoscribe.micgate:MicGate",
        "macos": ("not_needed", "macOS mics aren't left muted at volume 0; the option is hidden"),
    },
    "System audio for meetings (the other side of a call)": {
        "windows": "ecoscribe.loopback:Loopback",
        "macos": "ecoscribe.platform.macos.systap:Loopback",  # Core Audio process tap (ecoscribe-systap helper)
    },
    "Call detection (who uses the mic, call windows)": {
        "windows": "ecoscribe.detect:read_consent,window_titles,running_apps",
        "macos": "ecoscribe.platform.macos.detect:read_consent,window_titles,running_apps",
    },
    "Tray / menu bar, pill and prompt box": {
        "windows": "ecoscribe.ui:Tray,Overlay",
        "macos": "ecoscribe.platform.macos.shell:Tray,Overlay,PromptWindow",
    },
    "Start at login": {
        "windows": "ecoscribe.startup:enable,disable,is_enabled",
        "macos": "ecoscribe.platform.macos.startup:enable,disable,is_enabled",
    },
    "Single instance": {
        "windows": "ecoscribe.winutil:single_instance",
        "macos": "ecoscribe.platform.macos.sysutil:single_instance",
    },
    "Settings saved -> restart signal": {
        "windows": "ecoscribe.ipc:ReloadWatcher",
        "macos": "ecoscribe.platform.macos.ipc:ReloadWatcher",
    },
    "Window buttons -> background app (commands)": {
        "windows": "ecoscribe.commands:Watcher",
        "macos": "ecoscribe.platform.macos.commands:Watcher",
    },
    "Watchdog: watch, restart, kill a frozen app": {
        "windows": "ecoscribe.supervise:WinProc",
        "macos": "ecoscribe.supervise:MacProc",
    },
    "A frozen app can't lag the computer's input": {
        "windows": "ecoscribe.hook:HookClient",  # hooks in their own process
        "macos": ("not_needed", "macOS times out a stuck event tap by itself and Ecoscribe re-enables it"),
    },
    "Speakers + Remember voices (add-on)": {
        "windows": "file:packaging/speakers/speakers_main.py",
        "macos": "ecoscribe.platform.macos.speakers:addon_exe",  # Ecoscribe Speakers.app (the old Dictado Speakers.app still found), pyannote on MPS
    },
    "Claude app connection (MCP)": {
        "windows": "ecoscribe.claude_link:config_files,connect",
        "macos": "ecoscribe.platform.macos.claude_link:config_files",  # connect() is shared
    },
    "Installer": {
        "windows": "file:packaging/ecoscribe.iss",
        "macos": "file:tools/build_mac.py",  # Ecoscribe.app + .dmg, signed so permissions survive updates
    },
}
