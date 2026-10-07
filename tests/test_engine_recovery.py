"""Engine recovery when the GPU dies after startup (no real model needed)."""
from types import SimpleNamespace

import numpy as np

from ecoscribe.config import TextCfg, WhisperCfg
from ecoscribe.engine import Engine


class FakeModel:
    def __init__(self, name, device, compute_type, local_files_only=False, script=None):
        self.device = device
        self.script = script if script is not None else []

    def detect_language(self, audio, vad_filter=False):
        return "en", 0.9, [("en", 0.9)]

    def transcribe(self, audio, **kw):
        if self.script:
            raise self.script.pop(0)
        seg = SimpleNamespace(text=" hello there", no_speech_prob=0.01)
        return iter([seg]), SimpleNamespace(duration=1.0, duration_after_vad=1.0)


def factory_with(first_failures, gpu_reload_ok=True):
    made = []

    def factory(name, device, compute_type, local_files_only=False):
        if device == "cuda" and made and not gpu_reload_ok:
            raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")
        m = FakeModel(name, device, compute_type, script=list(first_failures) if not made else [])
        made.append(m)
        return m
    return factory, made


def test_cuda_error_at_runtime_reloads_and_retries():
    fails = []
    factory, made = factory_with([])
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory)
    e.load()
    # break it after warm-up, like a driver reset during sleep
    made[0].script = [RuntimeError("CUDA failed with error unspecified launch failure")]
    r = e.transcribe(np.zeros(16000, np.float32))
    assert r.text == "Hello there "
    assert len(made) == 2 and e.device == "cuda"


def test_gpu_gone_falls_back_to_cpu_and_keeps_working():
    factory, made = factory_with([], gpu_reload_ok=False)
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory)
    e.load()
    made[0].script = [RuntimeError("cuBLAS failed with status CUBLAS_STATUS_EXECUTION_FAILED")]
    r = e.transcribe(np.zeros(16000, np.float32))
    assert r.text == "Hello there "
    assert e.device == "cpu" and e.fallback_reason


def test_non_cuda_error_is_raised():
    factory, made = factory_with([])
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory)
    e.load()
    made[0].script = [ValueError("bad audio")]
    try:
        e.transcribe(np.zeros(16000, np.float32))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert len(made) == 1


def test_reload_never_destroys_the_old_model():
    """Destroying a CTranslate2 Whisper model after a long transcription aborts the
    process (uncaught C++ exception, measured 2026-10-02), so reload must retire it."""
    factory, made = factory_with([])
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory)
    e.load()
    first = made[0]
    first.script = [RuntimeError("CUDA failed with error unspecified launch failure")]
    e.transcribe(np.zeros(16000, np.float32))
    assert e.model is not first
    assert first in e._retired


def test_preview_is_greedy_and_never_waits_for_a_dictation():
    """dictado-live: the live text's quick pass is beam 1, and skipped while a dictation runs."""
    import threading
    factory, made = factory_with([])
    e = Engine(WhisperCfg(device="cuda"), TextCfg(), model_factory=factory)
    assert e.preview(np.zeros(16000, np.float32)) is None  # no model yet: skipped, not loaded
    e.load()
    seen = []
    real = made[0].transcribe
    made[0].transcribe = lambda audio, **kw: (seen.append(kw["beam_size"]), real(audio, **kw))[1]
    assert e.preview(np.zeros(16000, np.float32)).text == "Hello there "
    assert seen == [1]
    gate, inside = threading.Event(), threading.Event()
    made[0].transcribe = lambda audio, **kw: (inside.set(), gate.wait(5), real(audio, **kw))[2]
    t = threading.Thread(target=e.transcribe, args=(np.zeros(16000, np.float32),))
    t.start()
    assert inside.wait(5)
    t0 = __import__("time").monotonic()
    assert e.preview(np.zeros(16000, np.float32)) is None  # the dictation has the model
    assert __import__("time").monotonic() - t0 < 0.5
    gate.set()
    t.join(5)
