"""The macOS system-audio source (platform/macos/systap.py) with a fake helper process."""
import logging
import sys
import textwrap
import time

import numpy as np
import pytest

from ecoscribe.platform.macos import systap
from ecoscribe.platform.macos.systap import Loopback

FAKE = textwrap.dedent('''
    import json, math, os, struct, sys, time
    mode, secs = sys.argv[1], float(sys.argv[2])
    if mode == "silent":            # macOS waiting for consent: no header, nothing
        time.sleep(secs); sys.exit(0)
    if mode == "fail":
        print("ecoscribe-systap: process tap not created (OSStatus 1)", file=sys.stderr); sys.exit(2)
    sys.stdout.write(json.dumps({"rate": 48000, "channels": 2, "device": "Fake Speakers"}) + "\\n"); sys.stdout.flush()
    t0, n = time.monotonic(), 0
    while time.monotonic() - t0 < secs:
        block = b"".join(struct.pack("<ff", s, s) for s in
                         (0.5 * math.sin(2 * math.pi * 440 * (n + i) / 48000) for i in range(480)))
        n += 480
        sys.stdout.buffer.write(block[:1000]); sys.stdout.buffer.flush()   # split mid-frame on purpose
        sys.stdout.buffer.write(block[1000:]); sys.stdout.buffer.flush()
        time.sleep(0.01 * float(os.environ.get("ECOSCRIBE_FAKE_SLOW", "1")))  # >1: a slow machine
    sys.exit(3 if mode == "changed" else 0)
''')


@pytest.fixture
def fake(tmp_path):
    p = tmp_path / "fake_systap.py"
    p.write_text(FAKE)
    return lambda mode, secs=5.0: [sys.executable, str(p), mode, str(secs)]


def collect(lb, secs, levels=None):
    out, end = [], time.monotonic() + secs
    while time.monotonic() < end:
        out.append(lb.read())
        if levels is not None:
            levels.append(lb.level())
        time.sleep(0.05)
    return np.concatenate(out)


def voiced_blocks(x, sr=systap.SR, block_s=0.02):
    """20 ms blocks that carry sound. A slow machine (a CI runner) makes the fake helper lag; the
    GapFiller then rightly puts silence there, so only the blocks with sound say anything about it."""
    n = int(sr * block_s)
    blocks = [x[i:i + n] for i in range(0, len(x) - n + 1, n)]
    return [b for b in blocks if float(np.sqrt(np.mean(b * b))) > 0.05]


def test_tone_comes_out_as_16k_mono_on_the_wall_clock(fake):
    lb = Loopback(command=fake("tone", 3.0), check_s=None)
    t0 = time.monotonic()
    lb.start()
    levels = []
    try:
        x = collect(lb, 1.5, levels)
        elapsed = time.monotonic() - t0
    finally:
        lb.stop()
    assert lb.device_name == "Fake Speakers"
    # placed on the wall clock (start -> last read), not by bytes received; FILL_LAG keeps the end a bit back
    assert abs(len(x) / systap.SR - elapsed) < 0.35, (len(x) / systap.SR, elapsed)
    voiced = voiced_blocks(x)
    assert len(voiced) >= 5, "no tone came through"
    # The pitch says it was resampled right (48 kHz stereo -> 16 kHz mono, not sped up or slowed down);
    # silence a slow machine adds around the tone doesn't move the peak.
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    peak_hz = float(np.argmax(spectrum[1:]) + 1) * systap.SR / len(x)
    assert abs(peak_hz - 440) <= 15, peak_hz
    # Level, loosely: a 0.5 sine is 0.354 RMS (stereo folded by averaging; summed would be 0.707)
    rms = float(np.median([np.sqrt(np.mean(b * b)) for b in voiced]))
    assert 0.15 < rms < 0.6, rms
    assert max(levels) > 0.1


def test_no_header_yet_gives_zeros_and_says_which_permission(fake, caplog, monkeypatch):
    monkeypatch.setattr(systap, "NO_AUDIO_S", 0.3)
    lb = Loopback(command=fake("silent", 5.0), check_s=None)
    lb.start()
    try:
        time.sleep(0.5)
        with caplog.at_level(logging.WARNING):
            lb.check_device()
            lb.check_device()
        x = collect(lb, 0.6)
    finally:
        lb.stop()
    assert len(x) and not x.any()
    assert sum("System Audio Recording" in r.message for r in caplog.records) == 1  # once


def test_output_device_change_starts_a_new_helper(fake):
    runs = []
    lb = Loopback(command=fake("changed", 0.4), check_s=None)
    orig = lb._open
    lb._open = lambda: (runs.append(1), orig())[1]
    lb.start()
    try:
        time.sleep(1.0)
        lb.check_device()  # helper exited 3: a new one right away
        time.sleep(0.3)
        x = collect(lb, 0.3)
    finally:
        lb.stop()
    assert len(runs) == 2 and len(x)


def test_a_failing_helper_is_retried_slowly_not_in_a_loop(fake, monkeypatch):
    t = [0.0]
    runs = []
    lb = Loopback(command=fake("fail"), check_s=None, clock=lambda: t[0])
    orig = lb._open
    lb._open = lambda: (runs.append(1), orig())[1]
    lb.start()
    try:
        lb._proc.wait(5)
        lb.check_device()
        t[0] += 10
        lb.check_device()
        assert len(runs) == 1
        t[0] += systap.RETRY_S
        lb.check_device()
        assert len(runs) == 2
    finally:
        lb.stop()


def test_stop_ends_the_helper(fake):
    lb = Loopback(command=fake("tone", 30.0), check_s=None)
    lb.start()
    p = lb._proc
    time.sleep(0.3)
    lb.stop()
    assert p.poll() is not None


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS")
def test_meeting_recorder_uses_the_process_tap_on_macos(tmp_path, monkeypatch):
    from ecoscribe import meeting
    rec = meeting._default_recorder(tmp_path, on_chunk=lambda *a: None)
    assert rec.loop_factory is Loopback
