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
2. Open Ecoscribe from Applications. It isn't signed with a paid Apple Developer ID yet, so the first time macOS says it can't check it: click **Done** (on macOS 15, right-click > Open no longer gets past this). Then open **System Settings > Privacy & Security**, scroll down to **Security** and click **Open Anyway** next to Ecoscribe, enter your password, and click **Open Anyway** once more. Once per version: each new download is checked again until Ecoscribe has a Developer ID.
3. Allow the permissions in System Settings > Privacy & Security. Ecoscribe's window says which one is still missing:
   - **Accessibility** and **Input Monitoring**: for the Right Command key and to paste the text. After allowing them, quit Ecoscribe from its menu bar icon and open it again (macOS only hands a key watcher to an app when it starts; Ecoscribe flashes a reminder).
   - **Microphone**: macOS asks at your first dictation. Click Allow; that first dictation may come out empty, the next ones work.
   - **Screen & System Audio Recording**: macOS asks at your first meeting (the other side of the call). Not needed for dictation.
4. The first dictation downloads the speech model (a few minutes); the window shows the progress.

**Open at login:** the switch in Settings.

**Updating:** quit Ecoscribe, drag the new one over the old one in Applications, then Open Anyway once more (step 2). Your settings, history and transcripts stay, and so do the permissions (same signing certificate).

## 3. Where your files are

| What | Where |
|---|---|
| Settings, history, transcripts, crash reports | `~/Library/Application Support/Ecoscribe` |
| Speaker add-on (optional) | `Ecoscribe Speakers.app` in Applications |

## 4. Same as Windows

Everything in [FEATURES.md](../FEATURES.md) works on the Mac too; the table there says how each piece is done on each system.
