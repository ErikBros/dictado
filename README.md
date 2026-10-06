# Dictado

Local voice dictation and meeting transcription for Windows. Tap a key, talk, and the text appears wherever your cursor is. Record calls and get a transcript with who said what. Everything runs on your own PC with Whisper on the GPU: no account, no subscription, and no audio or text leaves the computer.

## What it does

- **Dictation anywhere.** Tap Right Ctrl, talk, tap again: about half a second later the text is pasted where your cursor is, in any app. Keep using the computer while you talk; switching windows or using shortcuts never cuts the recording. Hold Right Ctrl and press Esc to cancel. Optional hold-to-talk.
- **Meetings.** When Teams, Slack, Zoom, Meet, Discord, Signal, Telegram or Webex starts using the mic, Dictado offers to take notes. It records your mic and the computer's audio, shows a live transcript, and after the call writes a full-quality transcript labelled **Me** / **Others**. Swedish, English, Spanish, Greek, Greek + Spanish mixed, or detected.
- **Who said what** (optional add-on): splits the other side into Speaker 1, 2, 3 with pyannote; name a speaker once and later calls recognise that voice.
- **Files.** Drag audio or video onto the window to transcribe it.
- **Your words.** A list of names and terms to spell your way, plus names read from the window you're typing into (Windows UI Automation, never stored).
- **Snippets and voice commands.** Say "my email." and get the saved text; "new line", "new paragraph", "send it" (English, Spanish, Swedish).
- **Calendar names.** Paste a calendar's secret iCal link and recorded calls take the name of the event happening then.
- **Claude.** "Copy for Claude" on every transcript, and a read-only MCP server (`Dictado.exe --mcp`) so the Claude desktop app can search and read your meetings.
- **Never silent when it breaks.** A watchdog restarts the app after a crash, keeps the dictation you were in the middle of, and writes a crash report with every thread's stack (Settings > Troubleshooting > Copy debug info).

## Requirements

- Windows 10 or 11, 64-bit.
- An NVIDIA GPU with 6 GB or more is strongly recommended (tested on an RTX 3070 Ti, 8 GB). Without one it runs on the CPU with a smaller model: slower and less accurate.
- About 1 GB for the app plus the speech models it downloads the first time each is needed (about 1.6 GB for English/Spanish, 3 GB more for Swedish/Greek). The speaker add-on needs 4.6 GB.
- A microphone. A headset works best for meetings.

## Install

Download `Dictado-Setup-<version>.exe` from [Releases](../../releases) and run it. It installs for your user only (no admin), adds Dictado to the Start menu and, if you keep the box ticked, starts it with Windows. The installer isn't signed, so Windows SmartScreen will warn: **More info > Run anyway**.

The full guide (settings, meetings, troubleshooting, where files live) is in [`packaging/DICTADO-SETUP.md`](packaging/DICTADO-SETUP.md).

## Build from source

Dictado is Python 3.12 (faster-whisper / CTranslate2 on CUDA, pywebview window, pystray tray, low-level keyboard hook in its own process). It is developed from WSL against a Windows Python install:

```bash
. tools/winpy.sh                                # WINPY (Windows python.exe) and APP_W (this folder, Windows path)
wtest "$APP_W\\tests" -q -m "not gpu and not win"  # unit tests (~500)
wtest "$APP_W\\tests" -q -m gpu                  # needs an NVIDIA GPU and the models
wtest "$APP_W\\tests" -q -m win                  # real desktop: waits until nobody has touched the PC for 45 s
npm install && npm run smoke                     # the window's JavaScript in jsdom
wpy "$APP_W\\tools\\build.py" --installer         # Dictado.exe + Dictado-Setup-<version>.exe (needs Inno Setup 6)
```

Windows Python needs the packages in the build spec (`packaging/dictado.spec`): faster-whisper, numpy, sounddevice, pyaudiowpatch, pywin32, comtypes, pycaw, pystray, Pillow, pywebview, python-dateutil, tzdata, pyinstaller. The speaker add-on builds separately (`packaging/speakers/`) and needs the gated `pyannote/speaker-diarization-community-1` weights from Hugging Face.

## Windows and macOS stay in step

One codebase; OS-specific code is listed in [`dictado/platform/base.py`](dictado/platform/base.py) and
[`FEATURES.md`](FEATURES.md). A capability added on one platform needs the other one done, a ticket,
or a "not needed" reason, or `tests/test_platform_contract.py` fails. GitHub Actions runs the unit
tests on Windows and macOS for every push and pull request.

## Layout

| Path | What |
|---|---|
| `dictado/` | The app. `__main__.py` starts the background app and every worker (`--engine-worker`, `--meeting`, `--transcribe`, `--speakers`, `--hook`, `--supervise`, `--mcp`) |
| `dictado/web/` | The window (HTML/CSS/JS, served to pywebview) |
| `tests/` | pytest suite; `tests/e2e/` real-desktop scenarios; `tests/ui/` jsdom smoke test |
| `tools/` | Build, screenshots, benchmarks, crash/freeze probes |
| `packaging/` | PyInstaller spec, Inno Setup scripts, the user guide |

Settings live in `%APPDATA%\dictado\config.toml`; logs, history, transcripts and crash reports in `%LOCALAPPDATA%\dictado\`.

## Privacy

Audio, transcripts, voices and settings stay on your PC. The only network traffic is the first download of each speech model from Hugging Face and, if you set one, your calendar link. pyannote's usage telemetry is switched off.

## Credits and license

Speech recognition: OpenAI Whisper models via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and CTranslate2 (MIT). Speakers: [pyannote.audio](https://github.com/pyannote/pyannote-audio) (MIT) with `pyannote/speaker-diarization-community-1` (CC BY 4.0).

Dictado is released under the [MIT license](LICENSE). Built by ErikBros with Claude.
