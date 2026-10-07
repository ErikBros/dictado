# Features by platform

Ecoscribe is one codebase. Most features live in shared code and work on Windows and macOS alike;
only the OS-specific pieces differ. Rules:

- A pull request that adds or changes a feature updates this file.
- Something OS-specific goes in `ecoscribe/platform/base.py` **and** the platform table below, with
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
| Languages: English + Swedish built in, "Add a language" for any of Whisper's 100; dictation auto-detects among the ticked ones | done | done (auto-detect: English + Spanish at the Mac desktop, 100 % recall; "Add a language": German + Finnish added in the real Settings page, saved, in the menu bar and meeting lists, removed again (tools/mac_lang_check.py); dictated at the desktop, 100 % recall, Finnish moves dictation to large-v3) |
| Several languages in one dictation (Spanish + Greek...): each piece between pauses in its own language | done (a breath at the switch is enough; +0.1-0.6 s) | check on Mac (dictado-1tw: shared code, mlx detects each piece the full way) |
| Pill shows the language it heard, tray "Next dictation in" | done | check on Mac |
| Your words (spelling list) | done | done |
| Snippets | done | done |
| Voice commands + full list in Settings | done | done (real desktop run: line break + Enter, no command words typed) |
| Meetings: live transcript, notes, Me / Others, exports, Copy for Claude | done | check on Mac (dictado-tjn): needs the System Audio Recording permission |
| Meeting / file languages incl. Greek + Spanish mixed | done | done (GPU test passes on mlx) |
| Meeting names + attendees from a calendar (iCal link) | done | check on Mac (dictado-tjn) |
| File transcription (drag and drop) | done | done (installed app: Greek file on the Apple GPU, 2.4% WER) |
| Crash reports, freeze traces, watchdog restart | done | done |
| Dictation recovered after a crash | done | done (real crash mid-dictation: back in History, not pasted) |
| Home crash card, Settings > Troubleshooting | done | done (real SIGSEGV of the installed app: report, restart, card) |
| Call detection tried on real calls | done | needs real calls (dictado-nhn) |

## Platform-specific

| Capability | Windows | macOS |
|---|---|---|
| Hotkey (tap / hold / combo, Esc cancel) | done (low-level keyboard hook) | done (CGEventTap, Right Command) |
| Language key (dictation key + L picks the next language) | done (Right Ctrl + L, swallowed) | done (Right Command + L, swallowed; real desktop run) |
| Numpad Enter as a second dictation key | done (Settings > Numpad Enter dictates too; swallowed, the main Enter untouched) | to do (dictado-1k7) |
| No text box at the stop: keep it on the clipboard, say so | done (UI Automation: desktop, file lists, buttons; unknown windows still get the paste) | to do (dictado-cd2) |
| Paste text where the cursor is | done (clipboard + Ctrl+V) | done (NSPasteboard + Cmd+V) |
| Names on your screen | done (UI Automation, one COM thread) | done (Accessibility API) |
| Speech engine on the GPU | done (faster-whisper, CUDA) | done (mlx-whisper, Metal) |
| Mic list in Settings | done | done |
| Unmute the mic only while recording | done | not needed: macOS mics aren't left muted at volume 0 |
| System audio for meetings (the other side of a call) | done (WASAPI loopback) | done (Core Audio process tap; real capture: check on Mac, dictado-tjn) |
| Call detection (who uses the mic, call windows) | done | done (real-call check: dictado-nhn) |
| Tray / menu bar, pill and prompt box | done | done (AppKit) |
| Live text on the pill while dictating | done (a quick pass every 2 s; the careful one is still what gets pasted) | to do (dictado-ayq): the shared part works, the Mac pill needs its live() |
| Start at login | done (Run key; the old "Dictado" value moves to "Ecoscribe") | done (LaunchAgent com.erikbros.ecoscribe; the old com.erikbros.dictado one moves over) |
| Single instance | done | done |
| Settings saved -> restart signal | done | done |
| Window buttons -> background app (commands) | done | done |
| Watchdog: watch, restart, kill a frozen app | done | done |
| A frozen app can't lag the computer's input | done (hooks in their own process) | not needed: macOS times out a stuck event tap by itself |
| Speakers + Remember voices (add-on) | done (Ecoscribe Speakers; the old Dictado Speakers still found) | done (Ecoscribe Speakers.app, the old Dictado Speakers.app still found; pyannote on the Apple GPU, same results as CPU, 2x faster) |
| Claude app connection (MCP) | done | done (~/Library/Application Support/Claude) |
| Installer | done (.exe, Inno Setup) | done (Ecoscribe.app + .dmg, com.erikbros.ecoscribe, self-signed: this Mac only; a public build needs a Developer ID) |
