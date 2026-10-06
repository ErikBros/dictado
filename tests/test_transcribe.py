"""--transcribe worker with a fake model: routing, progress, OOM fallbacks, outputs."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dictado import sessions, transcribe
from dictado.config import TranscribeCfg

SR = 16000
OOM = "CUDA failed with error out of memory"


def seg(start, end, text="hola"):
    return SimpleNamespace(start=start, end=end, text=f" {text}")


class FakeModel:
    def __init__(self, path, device, compute_type, ends=(5, 10), detect="sv", fail_after=None):
        self.path, self.device, self.compute_type = path, device, compute_type
        self.ends, self.detected, self.fail_after = ends, detect, fail_after
        self.audio_len = None

    def detect_language(self, audio, **kw):
        return self.detected, 0.99, [(self.detected, 0.99)]

    def transcribe(self, audio, **kw):
        self.audio_len = len(audio)
        self.kw = kw

        def gen():
            prev = 0.0
            for e in self.ends:
                if self.fail_after is not None and prev >= self.fail_after:
                    raise RuntimeError(OOM)
                yield seg(prev, e)
                prev = e
        return gen(), SimpleNamespace(duration=len(audio) / SR)


class Factory:
    """Builds FakeModels; `fail` maps (device, compute_type) -> exception raised at load."""

    def __init__(self, fail=None, **model_kw):
        self.fail, self.model_kw, self.calls, self.models = fail or {}, model_kw, [], []

    def __call__(self, path, device, compute_type):
        self.calls.append((path, device, compute_type))
        if (device, compute_type) in self.fail:
            raise self.fail[(device, compute_type)]
        kw = dict(self.model_kw)
        if self.models and "fail_after" in kw:  # only the first model fails mid-file
            kw.pop("fail_after")
        m = FakeModel(path, device, compute_type, **kw)
        self.models.append(m)
        return m


def resolve(name, cfg):
    return Path("M:/models") / name.replace("/", "--")


def make_session(tmp_path, lang="sv", seconds=60):
    d = sessions.create("Reunión", lang, "import", tmp_path / "t")
    (d / "audio" / "a.wav").write_bytes(b"")
    return d, np.zeros(int(seconds * SR), np.float32)


def run(d, audio, factory, cfg=None, clock=None):
    t = iter(range(0, 10_000, 2))
    # float16 first: these tests exercise the full three-step fallback chain
    return transcribe.run(d, cfg or TranscribeCfg(compute_type="float16"), factory=factory, resolve=resolve,
                          decode=lambda p: audio, clock=clock or (lambda: next(t)))


def test_routes_by_meta_lang(tmp_path):
    d, audio = make_session(tmp_path, "sv")
    f = Factory()
    assert run(d, audio, f) == 0
    assert f.calls[0] == (str(resolve("Systran/faster-whisper-large-v3", None)), "cuda", "float16")
    meta = sessions.read_meta(d)
    assert meta["model"] == "Systran/faster-whisper-large-v3" and meta["status"] == "done"
    assert f.models[0].kw["language"] == "sv"


def test_auto_detects_then_routes(tmp_path):
    d, audio = make_session(tmp_path, "auto")
    f = Factory(detect="el")
    assert run(d, audio, f) == 0
    assert f.calls[0][0] == str(resolve("large-v3-turbo", None))  # detector
    assert f.calls[1][0] == str(resolve("Systran/faster-whisper-large-v3", None))
    meta = sessions.read_meta(d)
    assert meta["detected_lang"] == "el" and meta["model"] == "Systran/faster-whisper-large-v3"


def test_progress_monotonic_and_final(tmp_path, monkeypatch):
    d, audio = make_session(tmp_path, "en", seconds=60)
    seen = []
    real = transcribe._write_json

    def spy(path, data):
        if Path(path).name == "progress.json":
            seen.append(dict(data))
        real(path, data)
    monkeypatch.setattr(transcribe, "_write_json", spy)
    assert run(d, audio, Factory(ends=(5, 3, 12, 60))) == 0
    done = [p["done_s"] for p in seen]
    assert done == sorted(done)
    assert seen[-1]["pct"] == 100 and seen[-1]["total_s"] == 60


def test_oom_at_load_falls_back_int8(tmp_path):
    d, audio = make_session(tmp_path, "sv")
    f = Factory(fail={("cuda", "float16"): RuntimeError(OOM)})
    assert run(d, audio, f) == 0
    meta = sessions.read_meta(d)
    assert meta["compute_type"] == "int8_float16" and meta["device"] == "cuda" and meta["slow"] is False


def test_all_gpu_steps_fail_goes_cpu_and_marks_slow(tmp_path):
    d, audio = make_session(tmp_path, "sv")
    f = Factory(fail={("cuda", "float16"): RuntimeError(OOM), ("cuda", "int8_float16"): RuntimeError(OOM)})
    assert run(d, audio, f) == 0
    meta = sessions.read_meta(d)
    assert (meta["device"], meta["compute_type"], meta["slow"]) == ("cpu", "int8", True)


def test_oom_midway_restarts_from_last_segment(tmp_path):
    d, audio = make_session(tmp_path, "en", seconds=60)
    f = Factory(ends=(10, 20, 40), fail_after=20)
    assert run(d, audio, f) == 0
    assert f.models[1].audio_len == (60 - 20) * SR
    segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
    assert [(s["t0"], s["t1"]) for s in segs] == [(0, 10), (10, 20), (20, 30), (30, 40), (40, 60)]
    assert sessions.read_meta(d)["compute_type"] == "int8_float16"


def test_non_gpu_error_is_not_retried(tmp_path):
    d, audio = make_session(tmp_path, "en")
    f = Factory(fail={("cuda", "float16"): ValueError("bad model file")})
    assert run(d, audio, f) == 1
    assert len(f.calls) == 1


def test_failure_marks_meta_failed(tmp_path):
    d, _ = make_session(tmp_path, "en")
    rc = transcribe.run(d, TranscribeCfg(), factory=Factory(), resolve=resolve,
                        decode=lambda p: (_ for _ in ()).throw(RuntimeError("undecodable")))
    assert rc == 1
    meta = sessions.read_meta(d)
    assert meta["status"] == "failed" and "undecodable" in meta["error"]


def test_outputs_written(tmp_path):
    d, audio = make_session(tmp_path, "en")
    assert run(d, audio, Factory()) == 0
    for name in ("transcript.json", "transcript.md", "transcript.srt", "transcript.txt"):
        assert (d / name).exists(), name
    assert sessions.read_meta(d)["duration_s"] == 60


def test_no_audio_file_fails_cleanly(tmp_path):
    d = sessions.create("x", "en", "import", tmp_path / "t")
    assert transcribe.run(d, TranscribeCfg(), factory=Factory(), resolve=resolve) == 1
    assert sessions.read_meta(d)["status"] == "failed"


def test_cli_flag_parses():
    from dictado.__main__ import parse
    assert parse(["--transcribe", "C:/x"]).transcribe == "C:/x"


def test_locked_progress_file_does_not_fail_the_job(tmp_path, monkeypatch):
    """Windows: os.replace raises PermissionError while a reader (UI, antivirus) holds the file."""
    d, audio = make_session(tmp_path, "en")
    real, hits = transcribe.os.replace, []

    def flaky(src, dst):
        if Path(dst).name == "progress.json" and len(hits) < 3:
            hits.append(dst)
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)
    monkeypatch.setattr(transcribe.os, "replace", flaky)
    assert run(d, audio, Factory()) == 0
    assert hits and sessions.read_meta(d)["status"] == "done"


def test_locked_meta_is_retried(tmp_path, monkeypatch):
    d, _ = make_session(tmp_path, "en")
    real, hits = sessions.os.replace, []

    def flaky(src, dst):
        if Path(dst).name == "meta.json" and len(hits) < 2:
            hits.append(dst)
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)
    monkeypatch.setattr(sessions.os, "replace", flaky)
    sessions.write_meta(d, status="running")
    assert len(hits) == 2 and sessions.read_meta(d)["status"] == "running"


def test_default_precision_is_int8_float16():
    """Decided 2026-10-02 after the spike: same WER, about half the VRAM."""
    assert TranscribeCfg().compute_type == "int8_float16"
    assert transcribe.steps(TranscribeCfg()) == [("cuda", "int8_float16"), ("cpu", "int8")]


def test_default_loads_int8_first(tmp_path):
    d, audio = make_session(tmp_path, "sv")
    f = Factory()
    assert run(d, audio, f, cfg=TranscribeCfg()) == 0
    assert f.calls[0][1:] == ("cuda", "int8_float16")
    assert sessions.read_meta(d)["compute_type"] == "int8_float16"


def test_auto_reuses_detector_when_route_is_the_same_model(tmp_path):
    d, audio = make_session(tmp_path, "auto")
    f = Factory(detect="en")  # en routes to turbo, which is also the detector
    assert run(d, audio, f) == 0
    assert len(f.calls) == 1


def test_cache_reuses_a_preloaded_model(tmp_path):
    d, audio = make_session(tmp_path, "sv")
    f = Factory()
    cache = {}
    t = iter(range(0, 10_000, 2))
    for _ in range(2):
        assert transcribe.run(d, TranscribeCfg(), factory=f, resolve=resolve, decode=lambda p: audio,
                              clock=lambda: next(t), cache=cache) == 0
    assert len(f.calls) == 1


def test_progress_never_writable_still_finishes(tmp_path, monkeypatch):
    """The best-effort branch itself: progress.json stays locked for the whole job."""
    d, audio = make_session(tmp_path, "en")
    real = transcribe.os.replace
    monkeypatch.setattr(transcribe.sessions, "time", SimpleNamespace(sleep=lambda s: None))

    def locked(src, dst):
        if Path(dst).name == "progress.json":
            raise PermissionError(13, "Access is denied", str(dst))
        return real(src, dst)
    monkeypatch.setattr(transcribe.os, "replace", locked)
    assert run(d, audio, Factory()) == 0
    assert sessions.read_meta(d)["status"] == "done"
    assert not list(d.glob("progress.json.*.tmp"))  # no orphans left behind


def test_meeting_session_without_mix_refuses_to_guess(tmp_path):
    d = sessions.create("m", "sv", "meeting", tmp_path / "t")
    for name in ("mic.flac", "system.flac"):
        (d / "audio" / name).write_bytes(b"")
    with pytest.raises(FileNotFoundError):
        transcribe.audio_file(d)
