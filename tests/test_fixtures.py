"""The transcription fixtures exist and have the shape the worker and the bench expect."""
import wave
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
MEETINGS = ["sv_meeting", "el_podcast", "en_meeting"]
FORMATS = ["mp3", "m4a", "mp4", "opus"]


def meeting_audio(name: str) -> Path:
    """Meeting clips are committed as FLAC (lossless, about half the size of wav)."""
    return FIX / f"{name}.flac"


@pytest.mark.parametrize("name", MEETINGS)
def test_meeting_clip_shape(name):
    import av
    p = meeting_audio(name)
    assert p.exists(), p
    assert p.stat().st_size < 1_000_000, f"{p.name} is {p.stat().st_size} bytes"
    with av.open(str(p)) as c:
        s = c.streams.audio[0]
        assert s.rate == 16000
        assert s.channels == 1
        frames = sum(f.samples for f in c.decode(s))
    dur = frames / 16000
    assert 45 <= dur <= 90, dur
    txt = FIX / f"{name}.txt"
    assert txt.exists() and txt.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("ext", FORMATS)
def test_import_formats_decode(ext):
    from faster_whisper import decode_audio
    p = FIX / f"en_fox.{ext}"
    assert p.exists(), p
    audio = decode_audio(str(p), sampling_rate=16000)
    assert len(audio) / 16000 > 3


def test_fox_wav_is_the_source():
    with wave.open(str(FIX / "en_fox.wav")) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
