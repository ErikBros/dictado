"""Manual check: open the configured mic by name (unmuting it for the probe like
Ecoscribe does), print its level for 3 s, then restore the mute state."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dictado.audio import Recorder  # noqa: E402
from dictado.config import AudioCfg  # noqa: E402
from dictado.micgate import MicGate, list_capture_endpoints  # noqa: E402


def state():
    return [(n, int(v.GetMute()), round(float(v.GetMasterVolumeLevelScalar()), 2)) for n, v in list_capture_endpoints()]


print("before:", state())
cfg = AudioCfg()
gate = MicGate(cfg.device)
r = Recorder(cfg, on_warning=lambda m: print("WARNING:", m))
r.open()
print("device:", r.device_name, "fell_back:", r.fell_back)
print("gate opened:", gate.open())
time.sleep(0.3)
r.begin()
peak = 0.0
for _ in range(30):
    time.sleep(0.1)
    peak = max(peak, r.level())
a = r.end()
gate.restore()
r.close()
print(f"captured {len(a) / 16000:.2f}s  peak_rms={peak:.5f}  mean_abs={float(abs(a).mean()):.5f}")
print("after:", state())
