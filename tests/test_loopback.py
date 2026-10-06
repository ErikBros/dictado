"""WASAPI loopback source with fake PyAudioWPatch: resampling, gap fill, device changes."""
import numpy as np

from dictado.loopback import GapFiller, Loopback

SR = 16000


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeStream:
    def __init__(self, cb, rate, ch):
        self.cb, self.rate, self.ch, self.closed, self.started = cb, rate, ch, False, False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True

    def feed(self, seconds, value=0.25):
        n = int(seconds * self.rate)
        data = np.full(n * self.ch, value, np.float32).tobytes()
        self.cb(data, n, {}, 0)


class FakePA:
    """Stands in for the pyaudiowpatch module; `default` is the current output's name."""
    paFloat32, paContinue = 1, 0

    def __init__(self):
        self.default, self.streams = "Headphones", []
        mod = self

        class PyAudio:
            def get_default_wasapi_loopback(self):
                return {"name": f"{mod.default} [Loopback]", "index": 7, "defaultSampleRate": 48000.0,
                        "maxInputChannels": 2}

            def open(self, rate, channels, stream_callback, **kw):
                s = FakeStream(stream_callback, rate, channels)
                mod.streams.append(s)
                return s

            def terminate(self):
                pass
        self.PyAudio = PyAudio


def make(clock=None):
    pa, clock = FakePA(), clock or Clock()
    lb = Loopback(pa_module=pa, clock=clock, check_s=None)  # device checks driven by the test
    lb.start()
    return lb, pa, clock


def test_resamples_48k_stereo_to_16k_mono():
    lb, pa, clock = make()
    clock.t += 1.0
    pa.streams[0].feed(1.0, 0.25)
    out = lb.read()
    assert abs(len(out) - SR) < 400  # resampler latency
    assert np.allclose(out[200:-200], 0.25, atol=0.02)


def test_silence_fills_by_wall_clock():
    lb, pa, clock = make()
    clock.t += 2.0  # nothing playing: WASAPI sends no packets
    out = lb.read()
    assert abs(len(out) - 2 * SR) <= 0.15 * SR
    assert not out.any()


def test_data_after_silence_lands_at_its_time():
    lb, pa, clock = make()
    clock.t += 2.0
    first = lb.read()
    clock.t += 1.0
    pa.streams[0].feed(1.0, 0.25)
    total = len(first) + len(lb.read())
    assert abs(total - 3 * SR) <= 0.15 * SR


def test_read_never_runs_ahead_of_clock():
    lb, pa, clock = make()
    got = 0
    for _ in range(20):
        clock.t += 0.1
        pa.streams[0].feed(0.1)
        got += len(lb.read())
        assert got <= (clock.t - 100.0) * SR + 0.11 * SR


def test_default_device_change_reopens():
    lb, pa, clock = make()
    assert lb.device_name.startswith("Headphones")
    pa.default = "Speakers"
    lb.check_device()
    assert pa.streams[0].closed and len(pa.streams) == 2 and pa.streams[1].started
    assert lb.device_name.startswith("Speakers")
    lb.check_device()  # unchanged: no reopen
    assert len(pa.streams) == 2


def test_level_tracks_last_block():
    lb, pa, clock = make()
    clock.t += 0.5
    pa.streams[0].feed(0.5, 0.5)
    lb.read()
    assert lb.level() > 0.3


def test_gapfiller_small_jitter_is_not_a_gap():
    g = GapFiller(SR)
    g.start(0.0)
    g.push(np.ones(1600, np.float32), 0.1)
    g.push(np.ones(1600, np.float32), 0.205)  # 5 ms late
    out = g.pull(0.21)
    assert len(out) == 3200 and out.all()
