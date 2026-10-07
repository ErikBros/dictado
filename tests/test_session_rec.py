"""SessionRecorder with fake sources, pumped by hand."""
import numpy as np

from ecoscribe.session_rec import SessionRecorder

SR = 16000


class Src:
    def __init__(self, level=0.2, rate=1.0, fail=False, name="fake"):
        self.level_v, self.rate, self.fail, self.device_name = level, rate, fail, name
        self.started = self.stopped = False

    def start(self):
        if self.fail:
            raise OSError("no device")
        self.started = True

    def stop(self):
        self.stopped = True

    def read(self):
        return np.full(int(1600 * self.rate), self.level_v, np.float32)

    def level(self):
        return self.level_v


class Gate:
    def __init__(self):
        self.opened = self.restored = 0

    def open(self):
        self.opened += 1
        return True

    def restore(self):
        self.restored += 1


def make(tmp_path, mic=None, loop=None, gate=None, chunks=None):
    d = tmp_path / "s"
    (d / "audio").mkdir(parents=True)
    rec = SessionRecorder(d, mic_factory=lambda: mic or Src(0.2), loop_factory=lambda: loop or Src(0.1),
                          gate=gate, on_chunk=(lambda t0, a: chunks.append((t0, len(a)))) if chunks is not None else None,
                          threaded=False)
    return d, rec


def decode(p):
    from faster_whisper import decode_audio
    return decode_audio(str(p), sampling_rate=SR)


def test_three_tracks_same_length(tmp_path):
    d, rec = make(tmp_path)
    rec.start()
    for _ in range(30):
        rec.pump()
    durs = rec.stop()
    lens = [len(decode(d / "audio" / f)) for f in ("mic.flac", "system.flac", "mix.flac")]
    assert max(lens) - min(lens) <= 1600
    assert abs(lens[2] - 3 * SR) <= 1600
    assert abs(durs["mix"] - 3.0) < 0.11


def test_mix_is_sum_of_sources(tmp_path):
    d, rec = make(tmp_path)
    rec.start()
    for _ in range(10):
        rec.pump()
    rec.stop()
    assert np.allclose(decode(d / "audio" / "mix.flac")[100:-100], 0.3, atol=0.01)


def test_missing_mic_records_system_only(tmp_path, caplog):
    d, rec = make(tmp_path, mic=Src(fail=True))
    rec.start()
    for _ in range(10):
        rec.pump()
    rec.stop()
    n = 11 * 1600  # 10 pumps + the final one in stop()
    assert len(decode(d / "audio" / "system.flac")) == n
    assert len(decode(d / "audio" / "mix.flac")) == n
    assert len(decode(d / "audio" / "mic.flac")) == n
    assert not decode(d / "audio" / "mic.flac").any()
    assert rec.warnings and "mic" in rec.warnings[0].lower()


def test_lagging_source_is_padded(tmp_path):
    """The mic stream died (delivers nothing): the mix must not stall waiting for it."""
    d, rec = make(tmp_path, mic=Src(rate=0.0))
    rec.start()
    for _ in range(30):
        rec.pump()
    rec.stop()
    assert abs(len(decode(d / "audio" / "mix.flac")) - 30 * 1600) <= 1600


def test_chunks_contiguous(tmp_path):
    chunks = []
    d, rec = make(tmp_path, chunks=chunks)
    rec.start()
    for _ in range(250):  # 25 s of constant sound: forced cuts at 8, 16, 24 s, then the flush
        rec.pump()
    rec.stop()
    t = 0.0
    for t0, n in chunks:
        assert abs(t0 - t) < 1e-6
        t += n / SR
    assert len(chunks) == 4 and abs(t - 25.0) < 0.11


def test_gate_opened_once_restored_once(tmp_path):
    g = Gate()
    d, rec = make(tmp_path, gate=g)
    rec.start()
    rec.pump()
    rec.stop()
    rec.stop()
    assert (g.opened, g.restored) == (1, 1)


def test_levels(tmp_path):
    d, rec = make(tmp_path)
    rec.start()
    assert rec.levels() == (0.2, 0.1)
    rec.stop()


def test_meeting_and_dictation_gates_share_the_mic():
    """Both open the same muted mic: dictation must not re-mute it mid-meeting; the meeting restores it."""
    from ecoscribe.micgate import MicGate

    class Vol:
        mute, level = 1, 0.0

        def GetMute(self): return self.mute
        def GetMasterVolumeLevelScalar(self): return self.level
        def SetMute(self, m, _): self.mute = m
        def SetMasterVolumeLevelScalar(self, v, _): self.level = v
    vol = Vol()
    lister = lambda: [("Microphone (Anker PowerConf C200)", vol)]  # noqa: E731
    meeting_gate = MicGate("Anker PowerConf", lister=lister, sync=True)
    dictation_gate = MicGate("Anker PowerConf", lister=lister, sync=True)
    assert meeting_gate.open() and (vol.mute, vol.level) == (0, 0.8)
    assert dictation_gate.open() is False  # already open: nothing to save
    dictation_gate.restore()
    assert (vol.mute, vol.level) == (0, 0.8)  # still open for the meeting
    meeting_gate.restore()
    assert (vol.mute, vol.level) == (1, 0.0)
