# Ecoscribe on Windows: setup guide

(On a Mac: [mac.md](mac.md).) Ecoscribe is a voice dictation and meeting transcription app for Windows and macOS; this guide is the Windows one. Everything runs on your own PC: no account, no subscription, and no audio or text ever leaves the computer.

- **Dictation:** tap Right Ctrl, talk, tap again. The text is typed wherever your cursor is (any app).
- **Meetings:** when Teams, Slack, Zoom, Meet, Discord, Signal, Telegram or Webex starts using the mic, Ecoscribe offers to take notes. You get a transcript that labels each line **Me** or **Others**.
- **Who said what** (optional add-on): splits the other side of a call into Speaker 1, 2, 3, and you can name them.
- **Files:** drag an audio or video file onto the window to transcribe it.

Version 1.12.0 (October 2026). The interface is in English.

---

## 1. What to download

| File | What it is | Needed? |
|---|---|---|
| `Ecoscribe-Setup-1.12.0.exe` | The app (0.54 GB) | Yes |
| `Ecoscribe-Speakers-Setup-1.2.0.exe` | Speaker add-on: tells the people on a call apart (2.1 GB download, 4.6 GB installed) | Optional |

## 2. Requirements

- **Windows 10 or 11, 64-bit.**
- **An NVIDIA graphics card is strongly recommended**, with 6 GB of graphics memory or more. Tested on an RTX 3070 Ti (8 GB). Without one, Ecoscribe still works, but on the processor with a smaller model: slower and less accurate.
- **Disk:** about 1 GB for the app, plus the speech models it downloads the first time each is needed: ~1.6 GB (English/Spanish), ~3 GB more for Swedish, Greek or meetings in those languages. Add 4.6 GB if you install the speaker add-on.
- **Internet only for the first model downloads** (from Hugging Face, public, no account needed). After that it works offline.
- A microphone. A headset works best for meetings.

## 3. Install

1. Double-click **`Ecoscribe-Setup-1.12.0.exe`**.
2. Windows will probably show **"Windows protected your PC"**. That's because the app isn't signed with a paid certificate, not because something is wrong. Click **More info**, then **Run anyway**.
3. No admin password needed. It installs for your user only, in `%LOCALAPPDATA%\Programs\Ecoscribe`.
4. Keep **"Start Ecoscribe with Windows"** ticked if you want it always ready.
5. At the end it opens Ecoscribe. The first time, it downloads the speech model (about 1.6 GB, a few minutes); the window shows the progress.

**Updating?** Install the new Setup over the old one; your settings, history and transcripts stay. If you have the speaker add-on 1.0.0, install 1.1.0 to get "Remember voices".

**Optional, the speaker add-on:** run **`Ecoscribe-Speakers-Setup-1.2.0.exe`** the same way (same SmartScreen steps). It installs separately in `%LOCALAPPDATA%\Programs\Ecoscribe Speakers` and Ecoscribe picks it up on its own. Updating Ecoscribe later never touches it.

## 4. First things to set (Ecoscribe > Settings)

- **Mic:** pick your microphone. "Windows default" works if your default is the right one. The **Test** button shows a level meter.
- **Shortcut:** Right Ctrl by default. Change it by clicking **Change** and pressing the key or combination you want (e.g. `Ctrl+L`). Right Alt isn't allowed: on many keyboards it's AltGr.
- **Language:** English, Swedish, Spanish, or English + Spanish. You can also switch it right on the **Home** page (the Language dropdown) or from the tray icon > **Dictation language**. Switching restarts Ecoscribe in a few seconds.
- **Meetings > When a call starts:** *Ask* (default), *Start by itself*, or *Don't detect*.

## 5. Everyday use

### Dictation
- **Tap Right Ctrl, talk, tap Right Ctrl again.** The text appears where your cursor is, a moment later.
- **Cancel:** hold Right Ctrl and press Esc.
- **Hold to talk** (Settings > Shortcut, off by default): hold Right Ctrl while you speak and let go to stop. A quick tap still works as above.
- While you talk you can switch apps or click around; it keeps recording.
- Text didn't show up (e.g. no text field was focused)? It's in **History**, ready to copy.
- A small pill at the bottom of the screen shows "Dictating 0:07" while recording.
- To save graphics memory, the model loads when you tap and unloads after 10 minutes without dictating. The first dictation after a pause loads it while you talk.

### Getting names and words right
- **Your words** (Settings): a list of names and terms, one per line, that Ecoscribe should spell your way. Used for dictation, meetings and files.
- **Names on your screen** (Settings, on by default): when you tap, Ecoscribe reads the names in the window you're typing into (an email's sender, the people in a chat) and spells them the same way. In a test on 220 real recordings it got 87% of names right instead of 77%, with no extra wait. It's read on your PC, never stored or sent. Turn it off in Settings > Your words.
- **Snippets** (Settings > Snippets): save a text under a name, like "my email" or "my signature". Say the name on its own ("...thanks for today. My signature.") and Ecoscribe types the saved text. Inside a sentence ("what's my email?") it stays as you said it.
- **Voice commands** (Settings > Behaviour, off by default): "new line", "new paragraph", and "send it" at the end to press Enter. Spanish and Swedish work too.

### Meetings
- When a call app takes the mic, a box asks **"Are you in a meeting? Take notes?"** with a language choice. It disappears after 10 seconds if you ignore it, and counts as "Not now".
- **While recording**, the pill says "Taking notes" with the latest words and the tray icon turns red. **Ecoscribe > Meetings** shows the live transcript and a **Stop** button.
- **When the call ends** (the app releases the mic for 20 s) it stops by itself and makes the final, better transcript, with each line labelled **Me** (your mic) or **Others** (the computer's sound).
- **Start or stop by hand:** tray icon > *Transcribe meeting now* / *Stop meeting*, or the button on the Meetings page.
- **Your notes:** while the call runs (or after), type in the notes box above the transcript. It saves itself, and Copy for Claude, the summary prompt and the .md download include it, so Claude's summary follows what you cared about.
- **Afterwards:** open a session for Copy all, **Copy for Claude** (the transcript with date, app and language, ready to paste into Claude for a summary), downloads as .txt / .md / .srt, rename, delete.
- With the speaker add-on: the other side becomes **Speaker 1, 2, 3…**. Click a speaker's label to type their name; every line and every export updates. On a 1-to-1 call it stays "Others".
- **Remember voices** (on by default, needs the add-on 1.1.0): once you've named a speaker, Ecoscribe recognises that voice in later calls and names them by itself. The voices are stored only on your PC (`%LOCALAPPDATA%\ecoscribe\voices.json`); Settings > Meetings has "Forget all voices" and the switch to turn it off.
- **Please tell the people on the call that you're transcribing.** In many places that's expected, and in some it's required.

### Ask Claude about your meetings
If you use the Claude desktop app: Settings > Meetings > Claude app > **Connect**, then quit and reopen Claude. Now you can ask it "summarize yesterday's call" or "what did Ana say about the budget?". It can only read your transcripts (and your notes), never change them, and it runs on your PC. To undo, remove the `ecoscribe` entry under `mcpServers` in Claude's `claude_desktop_config.json`.

### Insights and speech coaching
Settings > **Insights tab** adds a tab with what your dictations say about how you talk, worked out on your PC from your history:
- **How clearly you speak:** after each dictation Ecoscribe takes a second look at how sure it was of every word (a fraction of a second, after the paste). You see the share heard clearly week by week and the words it keeps struggling with, per language.
- **In your messages to people:** filler words and hedges ("maybe", "I think", "kind of") per 100 words in what you dictate to people (chat, email), not in prompts to AI apps. Switch on **Note filler words after a message** and the pill shows them right after such a message.
- **Pace and pauses:** words a minute and how much of the time you pause, to people and to AI apps. 130-160 words a minute is where listeners follow most easily: information, not a goal.
- **In your meetings:** your share of the talking, turns of yours over 90 seconds, the questions you ask.
- **Coach me:** copies your recent messages to people as a prompt; paste it into Claude for your three recurring patterns, before → after rewrites of your own sentences and one habit to try. Nothing leaves your PC unless you paste it.

### Files
Drag an mp3, m4a, wav, ogg, opus, flac, mp4 or webm onto the window, or use **Import file**. One job runs at a time; the rest wait in the queue.

## 6. Where things live

| What | Where |
|---|---|
| The app | `%LOCALAPPDATA%\Programs\Ecoscribe` |
| Speaker add-on | `%LOCALAPPDATA%\Programs\Ecoscribe Speakers` |
| Settings | `%APPDATA%\ecoscribe\config.toml` |
| History, transcripts, models, logs | `%LOCALAPPDATA%\ecoscribe\` |
| Meeting transcripts | `%LOCALAPPDATA%\ecoscribe\transcripts\<date>_<title>\` (audio FLACs, transcript .txt/.md/.srt) |

Paste a path like `%LOCALAPPDATA%\ecoscribe` into the File Explorer address bar to open it.

## 7. Uninstall

Windows Settings > Apps > **Ecoscribe** > Uninstall (and **Ecoscribe speaker add-on** if you installed it). Your history, transcripts and settings stay in the folders above; delete them by hand if you want them gone.

## 8. Troubleshooting

| Problem | Try this |
|---|---|
| Nothing happens when I tap Right Ctrl | Look for the tray icon (near the clock, maybe under ^). If it's missing, start **Ecoscribe** from the Start menu. The Home page says "Ready" when it can dictate. |
| Engine says "CPU · slow" | No NVIDIA card found, or its driver is old. Update the NVIDIA driver and restart Ecoscribe. |
| Text is wrong or in the wrong language | Check the Language dropdown on Home. For Swedish, pick Swedish on its own. |
| The meeting box never appears | Settings > Meetings must be on *Ask* or *Start by itself*. Some apps only take the mic once the call connects. |
| Meeting transcript only has "Me" | Your computer's sound wasn't captured. Play the call through the default Windows output device. |
| Installing an update says a meeting is recording | Stop the meeting first, wait for it to show Ready, then click Retry. Setup won't cut a recording. |
| Anything else | See the next section, or open the log: tray icon > **Open log**. |

## 9. For your Claude (paste this section when asking for help)

Ecoscribe is a Windows app (PyInstaller-frozen Python 3.12, faster-whisper/CTranslate2 on CUDA, pywebview window, pystray tray, low-level keyboard hook). One background process owns the hook, the tray and the meetings controller. It starts workers for the dictation model (`--engine-worker`, on demand), meetings (`--meeting DIR`), file jobs (`--transcribe DIR`) and the speakers pass (`--speakers DIR`, runs `EcoscribeSpeakers.exe <audio> <out.json>`, pyannote).

Files to read when something fails:
- `%LOCALAPPDATA%\ecoscribe\ecoscribe.log`: background app (startup, ready line, meetings controller, reloads)
- `%LOCALAPPDATA%\ecoscribe\engine-worker.log`: dictation model load and errors
- `%LOCALAPPDATA%\ecoscribe\status.json`: current state, version, device, model, mic
- `%LOCALAPPDATA%\ecoscribe\meetings.json`: what is recording / transcribing / queued
- `%LOCALAPPDATA%\ecoscribe\detect.log` and `detector.log`: call detection decisions
- `%LOCALAPPDATA%\ecoscribe\transcripts\<session>\worker.log` and `meta.json`: one meeting or file
- `%LOCALAPPDATA%\ecoscribe\mcp.log`: the Claude app connection (`Ecoscribe.exe --mcp`, read-only MCP server over stdio)
- `%APPDATA%\ecoscribe\config.toml`: settings. Sections: `[hotkey] key, hold_to_talk`, `[audio] device`, `[whisper] languages, model, on_demand, idle_exit_s`, `[text] vocabulary, screen_names, voice_commands, snippets`, `[meetings] mode, default_lang, speakers, voice_memory`, `[transcribe] routes, root`.
- `%LOCALAPPDATA%\ecoscribe\voices.json`: voices learned for "Remember voices" (one averaged speaker embedding per name; delete it or use Settings > Forget all voices). Per call: `<session>\voices.json`, `notes.md`. After editing by hand, quit from the tray and start Ecoscribe again.

Notes: Swedish dictation uses `Systran/faster-whisper-large-v3` (int8_float16); English/Spanish use `large-v3-turbo`. Never install an update while `meetings.json` shows a meeting (Setup refuses anyway). pyannote's usage telemetry is switched off in the add-on (`PYANNOTE_METRICS_ENABLED=false`).

## 10. Credits and licenses

- Speech recognition: OpenAI **Whisper** models (MIT) via **faster-whisper** and **CTranslate2** (MIT); model files from Systran and mobiuslabs on Hugging Face (MIT).
- Speaker add-on: **pyannote.audio** (MIT) and **pyannote/speaker-diarization-community-1** by pyannoteAI, licensed **CC BY 4.0** (https://huggingface.co/pyannote/speaker-diarization-community-1).
- Built by ErikBros with Claude. MIT license, no warranty.
