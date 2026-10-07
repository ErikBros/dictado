"""Silent WASAPI loopback probe (stage 1 spike, pre-mortem #2).

Captures the default output device's loopback for N seconds with one library and
measures whether frames keep pace with the wall clock. Plays nothing; whatever
is playing gets captured but is only measured (frame counts, RMS), never saved.

    python tools/loopback_probe.py --lib soundcard|pyaudiowpatch --seconds 60 [--with-mic] [--out DIR]

Result JSON: lib, device, samplerate, frames, wall_s, drift_s (wall - frames/sr),
gaps (stretches > 200 ms with no data), max_gap_s, rms_max, mic_frames, mic_drift_s.
WASAPI loopback delivers no packets while nothing plays, so a recorder must fill
gaps by wall clock; `gaps` says how often that happens with this library.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

GAP_S = 0.2


class Tally:
    def __init__(self):
        self.lock = threading.Lock()
        self.frames, self.rms_max, self.stamps = 0, 0.0, []

    def add(self, block: np.ndarray) -> None:
        with self.lock:
            self.frames += len(block)
            if len(block):
                self.rms_max = max(self.rms_max, float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))))
            self.stamps.append(time.monotonic())


def run_soundcard(seconds: float, tally: Tally, stop: threading.Event) -> tuple[str, int]:
    import soundcard as sc
    spk = sc.default_speaker()
    mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
    sr = 48000

    def loop():
        with mic.recorder(samplerate=sr, channels=1, blocksize=1024) as rec:
            while not stop.is_set():
                tally.add(rec.record(numframes=sr // 20)[:, 0])
    threading.Thread(target=loop, daemon=True).start()
    return spk.name, sr


def run_pyaudiowpatch(seconds: float, tally: Tally, stop: threading.Event) -> tuple[str, int]:
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()
    dev = p.get_default_wasapi_loopback()
    sr, ch = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])

    def cb(data, frames, info, status):
        tally.add(np.frombuffer(data, dtype=np.float32).reshape(-1, ch)[:, 0])
        return (None, pyaudio.paContinue)
    stream = p.open(format=pyaudio.paFloat32, channels=ch, rate=sr, input=True,
                    input_device_index=dev["index"], frames_per_buffer=1024, stream_callback=cb)
    stream.start_stream()

    def closer():
        stop.wait()
        stream.stop_stream(); stream.close(); p.terminate()
    threading.Thread(target=closer, daemon=True).start()
    return dev["name"], sr


def open_mic(tally: Tally, stop: threading.Event):
    """Ecoscribe's mic, opened read-only alongside the loopback. Never unmuted here."""
    import sounddevice as sd
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from dictado.choose import pick_device
    idx = pick_device(list(sd.query_devices()), list(sd.query_hostapis()), "Anker PowerConf", "MME")
    stream = sd.InputStream(device=idx, samplerate=16000, channels=1, dtype="float32",
                            callback=lambda data, n, t, s: tally.add(data[:, 0].copy()))
    stream.start()

    def closer():
        stop.wait()
        stream.stop(); stream.close()
    threading.Thread(target=closer, daemon=True).start()


def gaps(stamps: list[float], start: float, end: float) -> tuple[int, float]:
    pts = [start, *stamps, end]
    holes = [b - a for a, b in zip(pts, pts[1:]) if b - a > GAP_S]
    return len(holes), round(max(holes, default=0.0), 3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", choices=["soundcard", "pyaudiowpatch"], required=True)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--with-mic", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    tally, mic, stop = Tally(), Tally(), threading.Event()
    start = time.monotonic()
    name, sr = (run_soundcard if a.lib == "soundcard" else run_pyaudiowpatch)(a.seconds, tally, stop)
    if a.with_mic:
        open_mic(mic, stop)
    while time.monotonic() - start < a.seconds:
        time.sleep(0.1)
    end = time.monotonic()
    stop.set()
    time.sleep(0.3)
    wall = end - start
    n_gaps, max_gap = gaps(tally.stamps, start, end)
    res = {"lib": a.lib, "device": name, "samplerate": sr, "frames": tally.frames, "wall_s": round(wall, 2),
           "drift_s": round(wall - tally.frames / sr, 3), "gaps": n_gaps, "max_gap_s": max_gap,
           "rms_max": round(tally.rms_max, 4), "with_mic": a.with_mic}
    if a.with_mic:
        res.update(mic_frames=mic.frames, mic_drift_s=round(wall - mic.frames / 16000, 3))
    text = json.dumps(res)
    print(text)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / f"loopback_{a.lib}{'_mic' if a.with_mic else ''}.json").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
