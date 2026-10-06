"""Generate the TTS test clips (run once on Windows Python; the clips are committed).

edge-tts makes mp3s; faster-whisper's bundled PyAV decodes them to 16 kHz mono.
Each clip gets 50 ms of leading silence so speech starts right at the tap.

Meeting-length clips (MEETINGS) are several paragraphs, possibly different voices,
joined with 0.6 s of silence, written as 16 kHz mono FLAC (a 45-90 s wav is over
the 1 MB per committed file limit) plus a .txt with the exact script.

    python tools/make_fixtures.py                 # everything
    python tools/make_fixtures.py sv_meeting      # only some clips
"""
import asyncio
import sys
import tempfile
import wave
from pathlib import Path

import edge_tts
import numpy as np
from faster_whisper import decode_audio

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SR = 16000
CLIPS = {
    "en_fox": ("en-US-GuyNeural", "The quick brown fox jumps over the lazy dog, then runs back to the barn."),
    "en_long": ("en-US-GuyNeural", "I would like to schedule the climbing session for Thursday evening, "
                                   "and please remind me to bring the new shoes and the chalk bag."),
    "es_climb": ("es-ES-AlvaroNeural", "Mañana por la mañana voy a escalar con mis amigos en Gotemburgo."),
    # Short real phrases that are ALSO on Whisper's silence-hallucination list: must not be dropped.
    "en_thanks": ("en-US-GuyNeural", "Thank you."),
    "es_gracias": ("es-ES-AlvaroNeural", "Gracias."),
}

# Transcription fixtures: (voice, paragraph) pairs. Everyday spoken register, not textbook.
MEETINGS = {
    "sv_meeting": [
        ("sv-SE-MattiasNeural",
         "Hej allihopa, då kör vi igång sprintplaneringen. Vi har tre saker på agendan i dag. "
         "Först kundprojektet i Göteborg, där leveransen är flyttad till den 14 november. "
         "Anna har pratat med beställaren och de vill ha en demo redan nästa vecka, så vi behöver "
         "prioritera inloggningen och rapportsidan. Sen har vi budgeten. Vi ligger på ungefär "
         "250 000 kronor hittills, vilket är lite under plan."),
        ("sv-SE-SofieNeural",
         "Tack Mattias. Jag kan ta rapportsidan, men jag behöver hjälp med testerna. Johan är "
         "ledig till och med måndag, så vi får nog flytta retrospektiven till onsdag klockan tio. "
         "Och en sak till: kan någon boka ett möte med kunden i Malmö innan fredag? Annars hinner "
         "vi inte få någon återkoppling före nästa sprint."),
    ],
    "el_podcast": [
        ("el-GR-NestorasNeural",
         "Γεια σας και καλώς ήρθατε σε ένα ακόμα επεισόδιο. Σήμερα θα μιλήσουμε για κάτι που "
         "αγαπάμε όλοι, το φαγητό. Χθες πήγα με τον φίλο μου τον Γιώργο σε μια ταβέρνα στην Πλάκα. "
         "Παραγγείλαμε χωριάτικη σαλάτα, λίγο τζατζίκι και σουβλάκια. Ήταν πολύ νόστιμα και φτηνά. "
         "Μετά κάναμε μια βόλτα και ήπιαμε έναν φρέντο εσπρέσο. Το βράδυ είχε πολύ κόσμο, "
         "αλλά βρήκαμε ένα τραπέζι έξω, κάτω από ένα μεγάλο δέντρο."),
        ("el-GR-NestorasNeural",
         "Λοιπόν, πάμε στο θέμα της εβδομάδας. Πολλοί με ρωτάνε πώς μαθαίνω καινούριες λέξεις. "
         "Η αλήθεια είναι ότι ακούω πολύ ραδιόφωνο και μιλάω με κόσμο, στο περίπτερο, στον φούρνο, "
         "στη λαϊκή. Δεν χρειάζεται να είναι τέλειο. Φτάνει να μιλάς. Την άλλη εβδομάδα θα "
         "έχουμε καλεσμένη τη Μαρία, που ζει στη Θεσσαλονίκη. Εσείς τι κάνετε; "
         "Γράψτε μου στα σχόλια."),
    ],
    "en_meeting": [
        ("en-US-GuyNeural",
         "Okay, let's get started, thanks everyone for joining. The main thing today is the launch "
         "timeline. Engineering says the release candidate will be ready on Thursday, but QA needs "
         "at least three days for the regression tests, so realistically we're looking at the "
         "middle of next week. Sarah, can you let the customers know? And please mention that the "
         "mobile app ships a few days later."),
        ("en-US-GuyNeural",
         "Second item is the budget. We're about ten percent over on cloud costs this quarter, "
         "mostly because of the new staging environment. I'd like to shut it down at night and on "
         "weekends. If nobody objects, Tom will set that up by Friday. Last thing, the office in "
         "Denver is closed on the twentieth, so plan your demos around that. Anything else? "
         "Great, let's wrap up and meet again on Monday."),
    ],
}
PARAGRAPH_GAP_S = 0.6


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
        f.writeframes(pcm.tobytes())


def write_flac(path: Path, audio: np.ndarray) -> None:
    import av
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").reshape(1, -1)
    with av.open(str(path), "w", format="flac") as c:
        st = c.add_stream("flac", rate=SR, layout="mono")
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = SR
        for pkt in st.encode(frame):
            c.mux(pkt)
        for pkt in st.encode(None):
            c.mux(pkt)


async def tts(voice: str, text: str, tmp: Path) -> np.ndarray:
    mp3 = tmp / "clip.mp3"
    await edge_tts.Communicate(text, voice).save(str(mp3))
    audio = decode_audio(str(mp3), sampling_rate=SR)
    idx = int(np.argmax(np.abs(audio) > 0.01))  # trim TTS leading silence
    return audio[max(0, idx - 160):]


async def make_meetings(only=None) -> None:
    gap = np.zeros(int(PARAGRAPH_GAP_S * SR), np.float32)
    with tempfile.TemporaryDirectory() as tmp:
        for name, paras in MEETINGS.items():
            if only and name not in only:
                continue
            parts = []
            for voice, text in paras:
                if parts:
                    parts.append(gap)
                parts.append(await tts(voice, text, Path(tmp)))
            audio = np.concatenate([np.zeros(int(0.05 * SR), np.float32)] + parts)
            write_flac(OUT / f"{name}.flac", audio)
            (OUT / f"{name}.txt").write_text("\n\n".join(t for _, t in paras) + "\n", encoding="utf-8")
            print(name, f"{len(audio) / SR:.2f}s", (OUT / f"{name}.flac").stat().st_size, "bytes")


async def main(only=None) -> None:
    await make_meetings(only)
    if only and not (only & set(CLIPS)):
        return
    OUT.mkdir(parents=True, exist_ok=True)
    lead = np.zeros(int(0.05 * SR), np.float32)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (voice, text) in CLIPS.items():
            if only and name not in only:
                continue
            mp3 = Path(tmp) / f"{name}.mp3"
            await edge_tts.Communicate(text, voice).save(str(mp3))
            audio = decode_audio(str(mp3), sampling_rate=SR)
            # trim TTS leading silence, then add exactly 50 ms
            idx = int(np.argmax(np.abs(audio) > 0.01))
            audio = np.concatenate([lead, audio[max(0, idx - 160):]])
            if name == "en_long" and len(audio) < 9 * SR:
                audio = np.concatenate([audio, np.zeros(9 * SR - len(audio), np.float32)])
            write_wav(OUT / f"{name}.wav", audio)
            print(name, f"{len(audio) / SR:.2f}s")
    if only:
        return
    rng = np.random.default_rng(0)
    write_wav(OUT / "silence_3s.wav", rng.normal(0, 0.001, 3 * SR).astype(np.float32))
    print("silence_3s 3.00s")


if __name__ == "__main__":
    sys.exit(asyncio.run(main(set(sys.argv[1:]))))
