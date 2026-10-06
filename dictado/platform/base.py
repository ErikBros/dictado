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
        "windows": "dictado.hook:HookThread",
        "macos": "dictado.platform.macos.keyhook:HookThread",
    },
    "Language key (dictation key + L picks the next language)": {
        "windows": "dictado.hook:VK_LANG",
        "macos": ("ticket", "dictado-982"),
    },
    "Paste text where the cursor is": {
        "windows": "dictado.deliver:deliver,set_clipboard_text",
        "macos": "dictado.platform.macos.deliver:deliver,set_clipboard_text",
    },
    "Names on your screen": {
        "windows": "dictado.context:window_texts",
        "macos": "dictado.platform.macos.context:window_texts",
    },
    "Speech engine on the GPU": {
        "windows": "dictado.engine:Engine",  # faster-whisper / CTranslate2 on CUDA
        "macos": "dictado.platform.macos.mlx_engine:MlxWhisperModel",  # mlx-whisper on Metal
    },
    "Mic list in Settings": {
        "windows": "dictado.window:_mme_input_names",
        "macos": "dictado.platform.macos.desktop:input_names",
    },
    "Unmute the mic only while recording": {
        "windows": "dictado.micgate:MicGate",
        "macos": ("not_needed", "macOS mics aren't left muted at volume 0; the option is hidden"),
    },
    "System audio for meetings (the other side of a call)": {
        "windows": "dictado.loopback:Loopback",
        "macos": "dictado.platform.macos.systap:Loopback",  # Core Audio process tap (dictado-systap helper)
    },
    "Call detection (who uses the mic, call windows)": {
        "windows": "dictado.detect:read_consent,window_titles,running_apps",
        "macos": "dictado.platform.macos.detect:read_consent,window_titles,running_apps",
    },
    "Tray / menu bar, pill and prompt box": {
        "windows": "dictado.ui:Tray,Overlay",
        "macos": "dictado.platform.macos.shell:Tray,Overlay,PromptWindow",
    },
    "Start at login": {
        "windows": "dictado.startup:enable,disable,is_enabled",
        "macos": "dictado.platform.macos.startup:enable,disable,is_enabled",
    },
    "Single instance": {
        "windows": "dictado.winutil:single_instance",
        "macos": "dictado.platform.macos.sysutil:single_instance",
    },
    "Settings saved -> restart signal": {
        "windows": "dictado.ipc:ReloadWatcher",
        "macos": "dictado.platform.macos.ipc:ReloadWatcher",
    },
    "Window buttons -> background app (commands)": {
        "windows": "dictado.commands:Watcher",
        "macos": "dictado.platform.macos.commands:Watcher",
    },
    "Watchdog: watch, restart, kill a frozen app": {
        "windows": "dictado.supervise:WinProc",
        "macos": "dictado.supervise:MacProc",
    },
    "A frozen app can't lag the computer's input": {
        "windows": "dictado.hook:HookClient",  # hooks in their own process
        "macos": ("not_needed", "macOS times out a stuck event tap by itself and Dictado re-enables it"),
    },
    "Speakers + Remember voices (add-on)": {
        "windows": "file:packaging/speakers/speakers_main.py",
        "macos": ("ticket", "dictado-4yu"),
    },
    "Claude app connection (MCP)": {
        "windows": "dictado.claude_link:config_files,connect",
        "macos": "dictado.platform.macos.claude_link:config_files",  # connect() is shared
    },
    "Installer": {
        "windows": "file:packaging/dictado.iss",
        "macos": "file:tools/build_mac.py",  # Dictado.app + .dmg, signed so permissions survive updates
    },
}
