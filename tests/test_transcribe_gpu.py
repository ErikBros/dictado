"""--transcribe on the real GPU with real fixtures (plan criteria 2, 3, 4).

Every case runs the real worker process (`python -m ecoscribe --transcribe DIR`), one
model per process, as in production: in-process runs would pile models up (they
are never freed, by design) until VRAM and then RAM run out."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ecoscribe import config, paths, sessions
from ecoscribe.wer import wer

pytestmark = pytest.mark.gpu
FIX = Path(__file__).parent / "fixtures"
APP = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg():
    return config.load(paths.config_path()).transcribe  # the configured models_root


def _run(tmp_path, cfg, name, lang):
    d = sessions.import_file(FIX / name, lang, tmp_path / "t")
    rc = _worker(d).wait(timeout=600)
    assert rc == 0, (d / "worker.log").read_text(encoding="utf-8", errors="replace")[-2000:]
    return d, sessions.read_meta(d), json.loads((d / "transcript.json").read_text(encoding="utf-8"))


def test_sv_fixture_uses_large_v3(tmp_path, cfg):
    _, meta, tr = _run(tmp_path, cfg, "sv_meeting.flac", "sv")
    assert "faster-whisper-large-v3" in meta["model"]
    _assert_close(tr, "sv_meeting")


def test_el_fixture_uses_large_v3(tmp_path, cfg):
    _, meta, tr = _run(tmp_path, cfg, "el_podcast.flac", "el")
    assert meta["model"] == "Systran/faster-whisper-large-v3"
    _assert_close(tr, "el_podcast")


def test_en_fixture_uses_turbo(tmp_path, cfg):
    _, meta, tr = _run(tmp_path, cfg, "en_meeting.flac", "en")
    assert meta["model"] == "large-v3-turbo"
    _assert_close(tr, "en_meeting")


@pytest.mark.parametrize("ext", ["mp3", "m4a", "mp4", "opus"])
def test_import_formats(tmp_path, cfg, ext):
    _, meta, tr = _run(tmp_path, cfg, f"en_fox.{ext}", "en")
    text = " ".join(s["text"] for s in tr["segments"]).lower()
    assert "fox" in text


def _assert_close(tr, name, ceiling=0.3):
    """Loose ceiling: catches a wrong language or a garbage decode, not small model differences."""
    ref = (FIX / f"{name}.txt").read_text(encoding="utf-8")
    hyp = " ".join(s["text"] for s in tr["segments"])
    assert wer(ref, hyp) < ceiling, (wer(ref, hyp), hyp[:300])


def _worker_mem_mb() -> int:
    """macOS: unified memory, so "VRAM" is the Ecoscribe worker processes' own footprint (MB)."""
    out = subprocess.run(["pgrep", "-f", "ecoscribe --(engine-worker|transcribe|meeting)"], capture_output=True, text=True).stdout
    total = 0
    for pid in out.split():
        fp = subprocess.run(["footprint", "-p", pid], capture_output=True, text=True).stdout
        for line in fp.splitlines():
            if "phys_footprint:" in line:
                n, unit = line.split("phys_footprint:")[1].split()[:2]
                total += float(n) * {"KB": 1 / 1024, "MB": 1, "GB": 1024}.get(unit, 1)
    return int(total)


def _vram_used_mb() -> int:
    if sys.platform == "darwin":
        return _worker_mem_mb()
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout
    return int(out.strip().splitlines()[0])


def _worker(d: Path, env=None) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "ecoscribe", "--transcribe", str(d)], cwd=str(APP), env=env)


def test_worker_cli_exits_and_frees_vram(tmp_path):
    d = sessions.import_file(FIX / "el_podcast.flac", "el", tmp_path / "t")
    before = _vram_used_mb()
    p = _worker(d)
    assert p.wait(timeout=600) == 0, (d / "worker.log").read_text(encoding="utf-8", errors="replace")
    time.sleep(2)
    assert sessions.read_meta(d)["status"] == "done"
    assert _vram_used_mb() - before < 300


@pytest.mark.skipif(not os.environ.get("ECOSCRIBE_LONG"), reason="set ECOSCRIBE_LONG=1 for the 60-min run")
def test_long_file_progress(tmp_path):
    long_wav = paths.data_dir() / "bench" / "long_60min.wav"
    assert long_wav.exists(), "run tools/make_long.py first"
    d = sessions.create("long", "sv", "import", tmp_path / "t")
    os.link(long_wav, d / "audio" / long_wav.name)  # both on C:, no 115 MB copy
    t0 = time.monotonic()
    p = _worker(d)
    pcts = []
    while p.poll() is None:
        time.sleep(5)
        try:
            pcts.append(json.loads((d / "progress.json").read_text(encoding="utf-8"))["pct"])
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
    assert p.returncode == 0
    assert pcts == sorted(pcts) and pcts[-1] <= 100
    meta = sessions.read_meta(d)
    assert meta["status"] == "done"
    print(f"LONG wall_s={time.monotonic() - t0:.0f} model={meta['model']} compute={meta['compute_type']}")


def test_greek_spanish_mixed_file(tmp_path, cfg):
    """t0u.34: Greek, Spanish, Greek, "Gracias." in one file, language "el,es": every piece in
    its own language and script, on large-v3, in one model load."""
    import numpy as np
    from faster_whisper import decode_audio
    from ecoscribe.flacw import FlacWriter
    sr, gap = 16000, np.zeros(16000 * 2, np.float32)
    el = decode_audio(str(FIX / "el_podcast.flac"), sampling_rate=sr)
    es = decode_audio(str(FIX / "es_climb.wav"), sampling_rate=sr)
    thanks = decode_audio(str(FIX / "es_gracias.wav"), sampling_rate=sr)
    mix = np.concatenate([el[: 12 * sr], gap, es, gap, el[20 * sr: 32 * sr], gap, thanks]).astype(np.float32)
    src = tmp_path / "mixed.flac"
    w = FlacWriter(src)
    w.write(mix)
    w.close()
    d, meta, tr = _run(tmp_path, cfg, src, "el,es")
    assert meta["model"] == "Systran/faster-whisper-large-v3" and meta["lang_used"] == "el,es"
    segs = tr["segments"]
    (tmp_path / "mixed.txt").write_text("\n".join(f"{s['t0']:6.1f} {s['lang']} {s['text']}" for s in segs), "utf-8")
    if os.environ.get("ECOSCRIBE_MIXED_OUT"):
        Path(os.environ["ECOSCRIBE_MIXED_OUT"]).write_text((tmp_path / "mixed.txt").read_text("utf-8"), "utf-8")
    greek = lambda t: any("Ͱ" <= c <= "Ͽ" for c in t)  # noqa: E731
    es_t = " ".join(s["text"] for s in segs if s["lang"] == "es").lower()
    assert "escalar" in es_t and "gracias" in es_t
    assert all(greek(s["text"]) for s in segs if s["lang"] == "el")
    assert not any(greek(s["text"]) for s in segs if s["lang"] == "es")
    assert [s["lang"] for s in segs if s["t0"] < 12] and all(s["lang"] == "el" for s in segs if s["t0"] < 11)
