# Ecoscribe

Local voice dictation and meeting transcription for **Windows and macOS**. Tap a key, talk, and the text appears wherever your cursor is. Record calls and get a transcript with who said what. Everything runs on your own computer with Whisper on the GPU: no account, no subscription, and no audio or text leaves the computer.

## Download

Get the latest version from **[Releases](https://github.com/ErikBros/ecoscribe/releases/latest)**:

| | Windows | Mac |
|---|---|---|
| File | `Ecoscribe-Setup-<version>.exe` | `Ecoscribe-<version>.dmg` |
| Needs | Windows 10 or 11, 64-bit; an NVIDIA GPU with 6 GB+ strongly recommended | Apple Silicon (M1 or newer), macOS 14.4 or newer |
| Dictation key | Right Ctrl | Right Command |
| First open | SmartScreen: **More info > Run anyway** | System Settings > Privacy & Security: **Open Anyway**, then allow the permissions it asks for |
| Full guide | [docs/windows.md](docs/windows.md) | [docs/mac.md](docs/mac.md) |

Neither installer is signed with a paid certificate yet, which is why each OS warns once the first time.

## What it does

- **Dictation anywhere.** Tap the dictation key, talk, tap again: the text is pasted where your cursor is, in any app. Keep using the computer while you talk. Hold the key and press Esc to cancel; optional hold-to-talk. The pill shows the text live while you speak.
- **Your languages, even mixed.** English and Swedish built in; add any of Whisper's ~100. Dictation detects which one you're speaking, and a dictation that switches language (Spanish, then Greek) gets each part in its own language.
- **Meetings.** When Teams, Slack, Zoom, Meet, Discord, Signal, Telegram or Webex starts using the mic, Ecoscribe offers to take notes. It records your mic and the computer's audio, shows a live transcript, and after the call writes a full transcript labelled **Me** / **Others**.
- **Who said what** (optional add-on): splits the other side into Speaker 1, 2, 3 with pyannote; name a speaker once and later calls recognise that voice.
- **Files.** Drag audio or video onto the window to transcribe it.
- **Your words, snippets, voice commands.** Names spelled your way (also the names on the window you're typing into), "my email." types the saved text, "new line" / "send it".
- **Claude.** "Copy for Claude" on every transcript, and a read-only MCP server so the Claude desktop app can search your meetings.
- **Never silent when it breaks.** A watchdog restarts the app after a crash or a freeze, keeps the dictation you were in the middle of, and writes a crash report.

What each platform has, feature by feature: **[FEATURES.md](FEATURES.md)**.

## How the code is organised

One codebase for both systems. Most of Ecoscribe (speech engine, meetings, the window, history, settings) is shared; only the pieces that talk to the operating system differ, and those live in one folder per OS.

| Path | What |
|---|---|
| `ecoscribe/` | **Shared** app code. `__main__.py` starts the background app and its workers |
| `ecoscribe/web/` | **Shared** window (HTML/CSS/JS, shown with pywebview) |
| `ecoscribe/platform/windows/` | **Windows only**: keyboard hook, paste, tray and pill, UI Automation, Run key, named mutex |
| `ecoscribe/platform/macos/` | **Mac only**: event tap, paste, menu bar and pill, Accessibility, LaunchAgent, mlx engine, system-audio tap |
| `ecoscribe/platform/base.py` | The list of every OS-specific capability and where each platform has it |
| `packaging/windows/`, `packaging/macos/` | Installer builds per OS (Inno Setup `.exe`, PyInstaller `.app` + `.dmg`); `packaging/speakers/` the speaker add-on |
| `docs/` | User guides per OS |
| `tests/` | pytest suite (`e2e/` real-desktop scenarios, `ui/` the window in jsdom) |
| `tools/` | Builds, screenshots, benchmarks (`tools/mac_*` and `build_mac.py` are the Mac ones) |

A capability added on one OS needs the other one done, a ticket, or a "not needed" reason; `tests/test_platform_contract.py` checks that against `platform/base.py` and FEATURES.md. GitHub Actions runs the unit tests on Windows and macOS for every pull request.

## Build from source

Python 3.12.

**Windows** (developed from WSL against a Windows Python):

```bash
. tools/winpy.sh                                   # WINPY (Windows python.exe) and APP_W (this folder)
wtest "$APP_W\\tests" -q -m "not gpu and not win"   # unit tests
wtest "$APP_W\\tests" -q -m gpu                     # needs an NVIDIA GPU and the models
wtest "$APP_W\\tests" -q -m win                     # real desktop: waits for 45 s of nobody touching the PC
wpy "$APP_W\\tools\\build.py" --installer            # Ecoscribe-Setup-<version>.exe (needs Inno Setup 6)
```

Packages: `requirements-win.txt`.

**Mac** (Apple Silicon):

```bash
pip install -r requirements-mac.txt
tools/mac_check.sh            # the test suite
python tools/build_mac.py     # Ecoscribe.app + Ecoscribe-<version>.dmg
```

**Both:** `npm install && npm run smoke` tests the window's JavaScript. The speaker add-on builds separately (`packaging/speakers/`) and needs the gated `pyannote/speaker-diarization-community-1` weights from Hugging Face.

## Privacy

Audio, transcripts, voices and settings stay on your computer. The only network traffic is the first download of each speech model from Hugging Face and, if you set one, your calendar link. pyannote's usage telemetry is switched off.

## Credits and license

Speech recognition: OpenAI Whisper models via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / CTranslate2 (Windows) and [mlx-whisper](https://github.com/ml-explore/mlx-examples) (Mac), all MIT. Speakers: [pyannote.audio](https://github.com/pyannote/pyannote-audio) (MIT) with `pyannote/speaker-diarization-community-1` (CC BY 4.0).

Ecoscribe is released under the [MIT license](LICENSE). Built by ErikBros with Claude.
