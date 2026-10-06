# Features by platform

Dictado is one codebase. Most features live in shared code and work on Windows and macOS alike;
only the OS-specific pieces differ. Rules:

- A pull request that adds or changes a feature updates this file.
- Something OS-specific goes in `dictado/platform/base.py` **and** the platform table below, with
  the other platform done, a ticket (`dictado-xxx`), or "not needed" with the reason.
- `tests/test_platform_contract.py` checks the platform table against the code on every test run
  (and in CI on Windows and macOS), so it can't drift.

## Shared features

Built once for both. "Check on Mac" = works in tests, still to be tried for real on the Mac.

| Feature | Windows | macOS |
|---|---|---|
| Dictation: tap or hold, paste, cancel with key + Esc | done | done |
| Pill with timer, level and cancel hint | done | done |
| Window: Home, History, Meetings, Settings | done | done |
| Dictation languages: English, Swedish, Spanish, English + Spanish | done | done |
| Your words (spelling list) | done | done |
| Snippets | done | done |
| Voice commands + full list in Settings | done | check on Mac (dictado-tjn) |
| Meetings: live transcript, notes, Me / Others, exports, Copy for Claude | done | waits for system audio (dictado-qkg) |
| Meeting / file languages incl. Greek + Spanish mixed | done | done (GPU test passes on mlx) |
| Meeting names + attendees from a calendar (iCal link) | done | check on Mac (dictado-tjn) |
| File transcription (drag and drop) | done | check on Mac (dictado-tjn) |
| Crash reports, freeze traces, watchdog restart | done | done |
| Dictation recovered after a crash | done | check on Mac (dictado-tjn) |
| Home crash card, Settings > Troubleshooting | done | check on Mac (dictado-4ey) |
| Call detection tried on real calls | done | needs real calls (dictado-nhn) |

## Platform-specific

| Capability | Windows | macOS |
|---|---|---|
| Hotkey (tap / hold / combo, Esc cancel) | done (low-level keyboard hook) | done (CGEventTap, Right Command) |
| Paste text where the cursor is | done (clipboard + Ctrl+V) | done (NSPasteboard + Cmd+V) |
| Names on your screen | done (UI Automation, one COM thread) | done (Accessibility API) |
| Speech engine on the GPU | done (faster-whisper, CUDA) | done (mlx-whisper, Metal) |
| Mic list in Settings | done | done |
| Unmute the mic only while recording | done | not needed: macOS mics aren't left muted at volume 0 |
| System audio for meetings (the other side of a call) | done (WASAPI loopback) | ticket dictado-qkg (Core Audio process tap) |
| Call detection (who uses the mic, call windows) | done | done (real-call check: dictado-nhn) |
| Tray / menu bar, pill and prompt box | done | done (AppKit) |
| Start at login | done (Run key) | done (LaunchAgent) |
| Single instance | done | done |
| Settings saved -> restart signal | done | done |
| Window buttons -> background app (commands) | done | done |
| Watchdog: watch, restart, kill a frozen app | done | done |
| A frozen app can't lag the computer's input | done (hooks in their own process) | not needed: macOS times out a stuck event tap by itself |
| Speakers + Remember voices (add-on) | done | ticket dictado-4yu |
| Claude app connection (MCP) | done | ticket dictado-iej |
| Installer | done (.exe, Inno Setup) | ticket dictado-ccs (.app + .dmg) |
