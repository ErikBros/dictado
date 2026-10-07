# Ecoscribe on a Mac: setup guide

(On Windows: [windows.md](windows.md).) Ecoscribe is a voice dictation and meeting transcription app for Windows and macOS. On a Mac, Whisper runs on the Apple GPU (mlx): no account, no subscription, and no audio or text leaves the computer.

- **Dictation:** tap **Right Command**, talk, tap again. The text is pasted wherever your cursor is (any app). Hold Right Command and press Esc to cancel; Right Command + L picks the next dictation's language.
- **Meetings:** when a call app starts using the mic, Ecoscribe offers to take notes. You get a transcript that labels each line **Me** or **Others**.
- **Files:** drag an audio or video file onto the window to transcribe it.

## 1. Requirements

- **A Mac with Apple Silicon** (M1 or newer). Intel Macs aren't supported: the speech engine runs on the Apple GPU.
- **macOS 14.4 or newer** (meetings record the other side of a call through a Core Audio tap, new in 14.4).
- **Disk:** about 1 GB for the app, plus the speech models it downloads the first time each is needed (1.6 GB for English/Spanish, about 3 GB more for Swedish or Greek).
- **Internet only for the first model downloads** (Hugging Face, no account). After that it works offline.

## 2. Install

1. Download **`Ecoscribe-<version>.dmg`** from [Releases](https://github.com/ErikBros/ecoscribe/releases/latest), open it and drag **Ecoscribe** to **Applications**.
2. Open Ecoscribe from Applications. The app isn't signed with a paid Apple Developer ID yet, so the first time macOS says it can't check it. Open **System Settings > Privacy & Security**, scroll down and click **Open Anyway** next to Ecoscribe, then confirm. You only do this once.
3. Ecoscribe asks for permissions. Allow each one in System Settings > Privacy & Security; the window's Home page says which one is still missing and opens the right pane:
   - **Microphone**: to hear you.
   - **Accessibility** and **Input Monitoring**: for the Right Command key and to paste the text.
   - **Screen & System Audio Recording**: only for meetings (the other side of the call).
4. The first dictation downloads the speech model (a few minutes); the window shows the progress.

**Open at login:** the switch in Settings.

**Updating:** drag the new Ecoscribe over the old one in Applications. Your settings, history and transcripts stay, and so do the permissions.

## 3. Where your files are

| What | Where |
|---|---|
| Settings, history, transcripts, crash reports | `~/Library/Application Support/Ecoscribe` |
| Speaker add-on (optional) | `Ecoscribe Speakers.app` in Applications |

## 4. Not on the Mac yet

Windows has a few things the Mac doesn't yet; each has a ticket and shows in [FEATURES.md](../FEATURES.md): the numpad's Enter as a second dictation key, and keeping a dictation on the clipboard when there's no text box under the cursor.
