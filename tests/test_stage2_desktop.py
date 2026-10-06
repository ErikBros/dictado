"""Stage 2 on the real devices. Marked `win`: conftest waits for 45 s of idle first.
Nothing here plays sound or touches the keyboard; the mic opens without unmuting."""
import time

import numpy as np
import pytest

from dictado.config import AudioCfg

pytestmark = pytest.mark.win
SR = 16000


def test_real_loopback_and_mic_stay_on_the_wall_clock(tmp_path):
    from faster_whisper import decode_audio
    from dictado.loopback import Loopback
    from dictado.session_rec import MicSource, SessionRecorder
    rec = SessionRecorder(tmp_path / "s", mic_factory=lambda: MicSource(AudioCfg()), loop_factory=Loopback)
    t0 = time.monotonic()
    rec.start()
    time.sleep(60)
    durs = rec.stop()
    wall = time.monotonic() - t0
    lens = {f: len(decode_audio(str(tmp_path / "s" / "audio" / f"{f}.flac"), sampling_rate=SR)) / SR
            for f in ("mic", "system", "mix")}
    system = decode_audio(str(tmp_path / "s" / "audio" / "system.flac"), sampling_rate=SR)
    print(f"DESKTOP wall={wall:.2f} lens={lens} system_rms={float(np.sqrt(np.mean(system ** 2))):.4f} warn={rec.warnings}")
    assert not rec.warnings
    for f, s in lens.items():
        assert abs(s - wall) <= 0.6, (f, s, wall)  # startup latency included


def test_dictation_stream_opens_while_a_meeting_holds_the_mic():
    import sounddevice as sd
    from dictado.choose import pick_device
    from dictado.session_rec import MicSource
    meeting_mic = MicSource(AudioCfg())
    meeting_mic.start()
    got = []
    try:
        idx = pick_device(list(sd.query_devices()), list(sd.query_hostapis()), "Anker PowerConf", "MME")
        with sd.InputStream(device=idx, samplerate=SR, channels=1, dtype="float32", blocksize=480,
                            callback=lambda d, n, t, s: got.append(n)):
            time.sleep(5)
        meeting = len(meeting_mic.read()) / SR
    finally:
        meeting_mic.stop()
    print(f"DESKTOP shared mic: dictation={sum(got) / SR:.2f}s meeting={meeting:.2f}s")
    assert sum(got) / SR >= 4.5 and meeting >= 4.5
