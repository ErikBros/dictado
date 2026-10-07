"""EcoscribeSpeakers.exe <audio> <out.json>: who spoke when, for Ecoscribe's speakers pass (t0u.22).

pyannote speaker-diarization-community-1 with its weights bundled in model/ (no Hugging
Face token at runtime), on CUDA when there is one; on a Mac on the Apple GPU (MPS), else the CPU. Writes [[t0, t1, "SPEAKER_00"], ...]
atomically; exit 0 = done, 2 = bad arguments, 1 = failed (traceback on stderr).
1.1.0 (t0u.32, voice memory): also <out stem>.voices.json = {"SPEAKER_00": [256 floats], ...},
pyannote's centroid embedding per speaker, so Ecoscribe can recognise a voice it was told the
name of. A sidecar, so Ecoscribe 1.3 (which reads only out.json) keeps working.
1.2.0 (dictado-jtv): renamed from DictadoSpeakers.exe, nothing else changed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# pyannote 4 sends usage telemetry (model name, audio duration) to otel.pyannote.ai unless this
# is false: Ecoscribe keeps everything on the PC. Set before pyannote is imported.
os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"  # the weights are bundled: never reach for the Hub
# Apple GPU: an op MPS doesn't have runs on the CPU instead of failing the whole pass
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def model_dir() -> Path:
    if os.environ.get("DICTADO_SPEAKERS_MODEL"):  # dev runs, unfrozen
        return Path(os.environ["DICTADO_SPEAKERS_MODEL"])
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "model"


def devices(torch) -> list[str]:
    """Where to try, in order: the NVIDIA GPU (Windows), the Apple GPU then the CPU (Mac), the CPU."""
    if torch.cuda.is_available():
        return ["cuda"]
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return ["mps", "cpu"]
    return ["cpu"]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    audio, out = argv[1], argv[2]
    import numpy as np
    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline
    t = time.time()
    x, sr = sf.read(audio, dtype="float32", always_2d=True)
    wav = torch.from_numpy(np.ascontiguousarray(x.mean(1)))[None]
    pipe = Pipeline.from_pretrained(str(model_dir()))
    # Measured 2026-10-05 on the 3070 Ti: cuDNN's default conv algorithms for the embedding model ate
    # all 8 GB (free 0 MB) and Windows paged to shared memory: 30 s for a 2.5-min call. benchmark: 6.5 s.
    torch.backends.cudnn.benchmark = True
    tries = devices(torch)
    for device in tries:
        try:
            pipe.to(torch.device(device))
            res = pipe({"waveform": wav, "sample_rate": sr})
            break
        except Exception as e:
            if device == tries[-1]:
                raise
            print(f"speakers on {device} failed ({type(e).__name__}: {e}); trying {tries[tries.index(device) + 1]}",
                  file=sys.stderr)
    ann = getattr(res, "speaker_diarization", res)
    turns = [[round(s.start, 2), round(s.end, 2), spk] for s, _, spk in ann.itertracks(yield_label=True)]
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(turns, f)
    emb = getattr(res, "speaker_embeddings", None)
    if emb is not None:
        voices = {spk: [round(float(v), 6) for v in emb[i]] for i, spk in enumerate(ann.labels())
                  if i < len(emb) and np.isfinite(emb[i]).all()}
        vout = str(Path(out).with_suffix("")) + ".voices.json"
        with open(vout + ".tmp", "w", encoding="utf-8") as f:
            json.dump(voices, f)
        os.replace(vout + ".tmp", vout)
    os.replace(tmp, out)
    print(f"speakers={len(ann.labels())} turns={len(turns)} audio_s={wav.shape[1] / sr:.0f} device={device} "
          f"secs={time.time() - t:.1f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
