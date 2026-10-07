"""A stand-in --engine-worker for test_engine_proc: speaks the real protocol.

    python fake_engine_worker.py normal|die_after_first|hang|slow_ready
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecoscribe import engine_proc  # noqa: E402
from ecoscribe.engine import Result  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
calls = {"n": 0}


class FakeEngine:
    device, fallback_reason = "cuda", None

    def load(self):
        if mode == "slow_ready":
            time.sleep(1.0)

    def transcribe(self, audio, words=None):
        calls["n"] += 1
        if mode == "die_after_first" and calls["n"] > 1:
            os._exit(3)
        if mode == "hang":
            time.sleep(60)
        if mode == "slow":
            time.sleep(3)
        if mode == "noisy":
            print("a native library banner on stdout", flush=True)
        tail = f" w={','.join(words)}" if words else ""
        return Result(text=f"pid{os.getpid()} n{len(audio)}{tail}", lang="en", speech_s=len(audio) / 16000, ms=5)


    def word_confidence(self, audio, lang=None, words=None):
        return [("hola", 0.9), (lang or "?", 0.4)]

    def preview(self, audio, lang=None, prefer=None):
        return Result(text=f"preview n{len(audio)}", lang=lang or "en", speech_s=len(audio) / 16000, ms=1)


e = FakeEngine()
e.load()
engine_proc.serve(e, *engine_proc.std_pipes())
