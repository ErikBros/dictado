import time

import numpy as np

from ecoscribe.audio import FileSource, Recorder
from ecoscribe.config import AudioCfg

WIN = {"device": "Anker PowerConf", "host": "MME"}  # the fakes below are the PC's MME devices

SR = 16000
DEVS = [{"name": "Headset (Zone Vibe 100)", "hostapi": 0, "max_input_channels": 1},
        {"name": "Microphone (Anker PowerConf C20", "hostapi": 0, "max_input_channels": 2}]
HOSTS = [{"name": "MME"}]


class FakeStream:
    instances = []

    def __init__(self, **kw):
        self.kw = kw
        self.active = False
        self.closed = False
        FakeStream.instances.append(self)

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True
        self.active = False

    def push(self, seconds, value=0.1):
        n = int(seconds * SR)
        block = 480
        for i in range(0, n, block):
            m = min(block, n - i)
            self.kw["callback"](np.full((m, 1), value, dtype=np.float32), m, None, None)


class FakeSD:
    def __init__(self, devices=DEVS):
        self.devices = devices
        FakeStream.instances = []
        self.InputStream = FakeStream

    def query_devices(self):
        return self.devices

    def query_hostapis(self):
        return HOSTS


def make(sd=None, **kw):
    warnings = []
    kw.setdefault("keep_open", True)
    r = Recorder(AudioCfg(**{**WIN, **kw}), sd_module=sd or FakeSD(), on_warning=warnings.append, monitor_s=0.1)
    r.open()
    return r, warnings


def test_opens_device_by_name():
    r, w = make()
    s = FakeStream.instances[-1]
    assert s.kw["device"] == 1 and s.kw["samplerate"] == SR and s.kw["channels"] == 1
    assert r.device_name.startswith("Microphone (Anker") and not r.fell_back and w == []
    r.close()


def test_preroll_included():
    r, _ = make()
    s = FakeStream.instances[-1]
    s.push(0.5, 0.2)
    r.begin()
    s.push(1.0, 0.1)
    a = r.end()
    assert abs(len(a) / SR - 1.4) <= 480 / SR + 1e-6
    assert a.dtype == np.float32
    assert np.isclose(a[0], 0.2) and np.isclose(a[-1], 0.1)
    r.close()


def test_not_recording_between_sessions():
    r, _ = make()
    s = FakeStream.instances[-1]
    r.begin(); s.push(0.5); r.end()
    s.push(2.0, 0.3)  # only 0.4 s of this may leak in as pre-roll
    r.begin(); a = r.end()
    assert len(a) / SR <= 0.4 + 480 / SR
    r.close()


def test_abort_discards():
    r, _ = make()
    s = FakeStream.instances[-1]
    r.begin(); s.push(1.0); r.abort()
    assert not r.recording
    r.begin(); s.push(0.2); a = r.end()
    assert len(a) / SR < 0.7
    r.close()


def test_level():
    r, _ = make()
    FakeStream.instances[-1].push(0.1, 0.5)
    assert 0.4 < r.level() <= 1.0
    r.close()


def test_missing_device_falls_back():
    r, w = make(FakeSD(devices=[DEVS[0]]))
    assert FakeStream.instances[-1].kw["device"] is None
    assert r.fell_back and len(w) == 1 and "Anker" in w[0]
    r.close()


def test_reopen_after_stream_death():
    r, _ = make()
    FakeStream.instances[-1].active = False
    end = time.monotonic() + 3
    while len(FakeStream.instances) < 2 and time.monotonic() < end:
        time.sleep(0.02)
    assert len(FakeStream.instances) >= 2 and FakeStream.instances[0].closed
    assert FakeStream.instances[-1].active
    r.close()


def test_open_failure_retries():
    class Boom(FakeStream):
        fails = 2

        def start(self):
            if Boom.fails > 0:
                Boom.fails -= 1
                raise RuntimeError("device busy")
            super().start()

    sd = FakeSD()
    sd.InputStream = Boom
    warnings = []
    r = Recorder(AudioCfg(**WIN, keep_open=True), sd_module=sd, on_warning=warnings.append, monitor_s=0.05, retry_s=0.05)
    r.open()
    end = time.monotonic() + 3
    while not (FakeStream.instances and FakeStream.instances[-1].active) and time.monotonic() < end:
        time.sleep(0.02)
    assert FakeStream.instances[-1].active
    assert len(warnings) == 1
    r.close()


def test_file_source_realtime(tmp_path):
    import wave
    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
        f.writeframes((np.ones(SR * 2) * 1000).astype("<i2").tobytes())
    fs = FileSource(p)
    fs.open(); fs.begin(); time.sleep(0.5); a = fs.end()
    assert 0.4 < len(a) / SR < 0.8
    fs.begin(); time.sleep(2.3); a = fs.end()
    assert len(a) == 2 * SR


def test_file_source_next_clip(tmp_path):
    import wave
    for name, secs in (("x.wav", 1), ("y.wav", 2)):
        with wave.open(str(tmp_path / name), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
            f.writeframes(np.zeros(SR * secs, dtype="<i2").tobytes())
    (tmp_path / "next_clip.txt").write_text("y.wav")
    fs = FileSource(tmp_path)
    fs.begin(); time.sleep(2.2)
    assert len(fs.end()) == 2 * SR


def test_on_demand_opens_only_while_recording():
    sd = FakeSD()
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=sd, monitor_s=0.05)
    r.open()
    assert FakeStream.instances == []  # nothing open while idle: no mic-in-use icon
    r.begin()
    s = FakeStream.instances[-1]
    assert s.active
    s.push(0.5, 0.1)
    a = r.end()
    assert abs(len(a) / SR - 0.5) < 0.05
    assert s.closed
    r.begin(); FakeStream.instances[-1].push(0.2); r.abort()
    assert FakeStream.instances[-1].closed
    time.sleep(0.2)
    assert all(x.closed for x in FakeStream.instances)  # monitor never reopens while idle
    r.close()


def test_on_demand_reopens_if_stream_dies_mid_recording():
    sd = FakeSD()
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=sd, monitor_s=0.05)
    r.open(); r.begin()
    FakeStream.instances[-1].active = False
    end = time.monotonic() + 2
    while len(FakeStream.instances) < 2 and time.monotonic() < end:
        time.sleep(0.02)
    assert len(FakeStream.instances) >= 2 and FakeStream.instances[-1].active
    r.end(); r.close()


def test_on_demand_resolves_and_warns_at_startup():
    warnings = []
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=FakeSD(devices=[DEVS[0]]), on_warning=warnings.append)
    r.open()
    assert FakeStream.instances == [] and r.fell_back and len(warnings) == 1
    r.close()
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=FakeSD())
    r.open()
    assert r.device_name.startswith("Microphone (Anker")
    r.close()


class SlowStream(FakeStream):
    """start() takes a while, like a real MME open, to widen race windows."""

    def start(self):
        time.sleep(0.03)
        super().start()


def test_no_orphan_streams_under_monitor_race():
    sd = FakeSD()
    sd.InputStream = SlowStream
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=sd, monitor_s=0.001, retry_s=0.001)
    r.open()
    for _ in range(40):
        r.begin()
        time.sleep(0.01)
        r.end()
    time.sleep(0.3)
    alive = [s for s in FakeStream.instances if not s.closed]
    assert alive == [], f"{len(alive)} streams left open"
    r.close()


def test_stale_stream_blocks_are_dropped():
    sd = FakeSD()
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=sd, monitor_s=10)
    r.open()
    r.begin(); old = FakeStream.instances[-1]; old.push(0.2, 0.9); r.end()
    r.begin()
    old.push(0.5, 0.9)  # a draining old stream still calls back
    FakeStream.instances[-1].push(0.2, 0.1)
    a = r.end()
    assert abs(len(a) / SR - 0.2) < 0.05 and float(abs(a).max()) < 0.5
    r.close()


def test_last_stream_ok_sampled_before_close():
    r = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=FakeSD(), monitor_s=10)
    r.open(); r.begin(); r.end()
    assert r.last_stream_ok is True and not r.stream_open()

    class Boom(FakeStream):
        def start(self):
            raise RuntimeError("no device")
    sd = FakeSD(); sd.InputStream = Boom
    r2 = Recorder(AudioCfg(**WIN, keep_open=False), sd_module=sd, monitor_s=10, retry_s=10)
    r2.open(); r2.begin(); r2.end()
    assert r2.last_stream_ok is False
    r.close(); r2.close()


def test_no_mic_chosen_means_the_windows_default_without_a_warning():
    """Public default (t0u.39): config device "" uses the system default mic, silently."""
    from ecoscribe.choose import pick_device
    devs = [{"name": "Microphone (USB)", "hostapi": 0, "max_input_channels": 1}]
    assert pick_device(devs, [{"name": "MME"}], "", "MME") is None
    assert pick_device(devs, [{"name": "MME"}], "  ", "MME") is None


def test_file_source_hands_the_spool_what_it_heard_so_far(tmp_path, monkeypatch):
    from ecoscribe import audio
    clip = np.arange(16000 * 2, dtype=np.float32)
    monkeypatch.setattr(audio, "read_wav", lambda p: clip)
    t = [100.0]
    monkeypatch.setattr(audio.time, "monotonic", lambda: t[0])
    src = audio.FileSource(tmp_path / "x.wav")
    assert src.chunks_since(0) == ([], 0)  # not recording
    src.begin()
    t[0] += 0.35
    chunks, n = src.chunks_since(0)
    assert n == 3 and np.array_equal(np.concatenate(chunks), clip[:4800])
    t[0] += 5  # past the end of the clip
    chunks, n = src.chunks_since(n)
    assert n == 20 and np.array_equal(np.concatenate(chunks), clip[4800:])
