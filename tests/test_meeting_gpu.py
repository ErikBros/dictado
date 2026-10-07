"""Stage 2 on the real GPU: a meeting in real time (criteria 0b, 5) and dictation next to a job (6)."""
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from ecoscribe import config, meeting, paths, sessions
from ecoscribe.audio import read_wav
from ecoscribe.session_rec import SessionRecorder

pytestmark = pytest.mark.gpu
FIX = Path(__file__).parent / "fixtures"
APP = Path(__file__).resolve().parent.parent
SR = 16000
PART_S = 25


class TimedSource:
    """Plays a clip on the wall clock from `start_s` after start(); silence before and after."""

    def __init__(self, clip: np.ndarray, start_s: float):
        self.clip, self.start_s, self.device_name = clip, start_s, "fixture"
        self.t0 = self.pos = 0

    def start(self):
        self.t0, self.pos = time.monotonic(), 0

    def stop(self):
        pass

    def read(self):
        now = int((time.monotonic() - self.t0) * SR)
        out = np.zeros(now - self.pos, np.float32)
        a, b = self.pos - int(self.start_s * SR), now - int(self.start_s * SR)
        lo, hi = max(a, 0), min(b, len(self.clip))
        if hi > lo:
            out[lo - a:hi - a] = self.clip[lo:hi]
        self.pos = now
        return out

    def level(self):
        return 0.1


def _clip(name):
    from faster_whisper import decode_audio
    return decode_audio(str(FIX / f"{name}.flac"), sampling_rate=SR)[: PART_S * SR]


# The latency test runs FIRST: the live-meeting test runs meeting.run in this process, and models
# are never freed (CTranslate2 aborts), so its large-v3 would stay on the GPU next to the job's
# large-v3 and dictation's turbo and push the 8 GB card into contention (seen 2026-10-05: +4.1 s).
# Production never has that: every meeting is its own process and frees the GPU on exit.
@pytest.mark.skipif(not (paths.data_dir() / "bench" / "long_60min.wav").exists(), reason="needs tools/make_long.py")
def test_dictation_latency_unchanged_during_a_job(tmp_path):
    """Criterion 6 (amended by the user 2026-10-02): within +200 ms (median) while a 60-min file job runs.
    Measured +180..195 ms; it is GPU contention, process priority does not help.
    dictado-2ta / 2so: next to the installed app's GPU work, or other apps keeping the GPU busy, it
    measures them, not this: skipped, with why."""
    from tests.gpu_busy import why_busy
    busy = why_busy()
    if busy:
        pytest.skip(f"{busy}: latency can't be measured next to it")
    from ecoscribe.config import TextCfg, WhisperCfg
    from ecoscribe.engine_proc import EngineProxy
    e = EngineProxy(WhisperCfg(on_demand=True), TextCfg(), check_s=None)
    clip = read_wav(FIX / "en_long.wav")
    e.transcribe(clip)  # cold start out of the way

    def median_ms():
        ts = []
        for _ in range(8):
            t0 = time.monotonic()
            e.transcribe(clip)
            ts.append((time.monotonic() - t0) * 1000)
        return statistics.median(ts)
    base = median_ms()
    d = sessions.create("carga", "sv", "import", tmp_path / "t")
    os.link(paths.data_dir() / "bench" / "long_60min.wav", d / "audio" / "long.wav")
    job = subprocess.Popen([sys.executable, "-m", "ecoscribe", "--transcribe", str(d)], cwd=str(APP))
    try:
        time.sleep(15)  # job past loading, transcribing
        busy = median_ms()
    finally:
        job.kill()
        e.close()
    print(f"LATENCY base_ms={base:.0f} busy_ms={busy:.0f} delta_ms={busy - base:.0f}")
    assert busy - base <= 200


def test_live_meeting_lag_and_labels(tmp_path):
    cfg = config.load(paths.config_path()).transcribe
    d = sessions.create("Reunión de prueba", "sv", "meeting", tmp_path / "t")
    system, mic = _clip("sv_meeting"), _clip("en_meeting")

    def rec_factory(sd, on_chunk):  # they talk first, then I do
        return SessionRecorder(sd, mic_factory=lambda: TimedSource(mic, PART_S),
                               loop_factory=lambda: TimedSource(system, 0), on_chunk=on_chunk)
    t_end = time.monotonic() + 2 * PART_S + 2
    assert meeting.run(d, cfg, recorder_factory=rec_factory, stop_check=lambda: time.monotonic() > t_end) == 0
    lines = [json.loads(l) for l in (d / "live.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) >= 4
    lags = [l["lag_s"] for l in lines]
    print(f"LIVE chunks={len(lines)} max_lag_s={max(lags):.2f} median_lag_s={statistics.median(lags):.2f}")
    assert max(lags) <= 8.0  # criterion 0b
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    first = [s["speaker"] for s in tr["segments"] if s["t1"] <= PART_S]
    second = [s["speaker"] for s in tr["segments"] if s["t0"] >= PART_S + 0.5]
    assert first and second
    assert first.count("Others") / len(first) >= 0.8 and second.count("Me") / len(second) >= 0.8
    assert sessions.read_meta(d)["status"] == "done"
    for f in ("mic", "system", "mix"):
        assert (d / "audio" / f"{f}.flac").stat().st_size > 10_000
