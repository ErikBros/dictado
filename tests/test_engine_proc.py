"""EngineProxy against a fake worker process that speaks the real protocol."""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from ecoscribe.config import TextCfg, WhisperCfg
from ecoscribe.engine_proc import EngineProxy

HERE = Path(__file__).resolve().parent


def spawner(*modes):
    """Each spawn uses the next mode (the last one repeats); records every process."""
    procs, modes = [], list(modes)

    def spawn():
        mode = modes.pop(0) if len(modes) > 1 else modes[0]
        p = subprocess.Popen([sys.executable, str(HERE / "fake_engine_worker.py"), mode],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        procs.append(p)
        return p
    return spawn, procs


def audio(n=16000):
    return np.zeros(n, np.float32)


def proxy(spawn, **kw):
    return EngineProxy(WhisperCfg(on_demand=True), TextCfg(), spawn=spawn, check_s=None, **kw)


def test_round_trip():
    spawn, procs = spawner("normal")
    e = proxy(spawn)
    r = e.transcribe(audio(32000))
    assert r.text.endswith("n32000") and r.lang == "en" and e.device == "cuda"
    e.close()


def test_warm_then_transcribe_reuses_process():
    spawn, procs = spawner("slow_ready")
    e = proxy(spawn)
    e.warm()
    e.warm()  # a second tap while loading must not spawn again
    r1 = e.transcribe(audio())
    r2 = e.transcribe(audio())
    assert len(procs) == 1 and r1.text.split()[0] == r2.text.split()[0]
    e.close()


def test_idle_exit_frees_worker():
    spawn, procs = spawner("normal")
    t = [0.0]
    e = EngineProxy(WhisperCfg(on_demand=True, idle_exit_s=600), TextCfg(), spawn=spawn, check_s=None,
                    clock=lambda: t[0])
    e.transcribe(audio())
    t[0] = 599
    e.check_idle()
    assert procs[0].poll() is None
    t[0] = 601
    e.check_idle()
    procs[0].wait(timeout=5)
    assert procs[0].poll() is not None
    e.transcribe(audio())  # next dictation respawns
    assert len(procs) == 2
    e.close()


def test_dead_worker_respawns():
    spawn, procs = spawner("die_after_first", "normal")
    e = proxy(spawn)
    first = e.transcribe(audio())
    second = e.transcribe(audio())  # worker dies mid-request: respawn + retry once
    assert len(procs) == 2 and second.text.split()[0] != first.text.split()[0]
    e.close()


def test_hung_worker_killed():
    spawn, procs = spawner("hang", "normal")
    e = proxy(spawn, reply_timeout_s=1.0)
    t0 = time.monotonic()
    r = e.transcribe(audio())
    assert time.monotonic() - t0 < 15
    assert procs[0].poll() is not None and r.text
    e.close()


def test_app_warms_engine_at_recording_start():
    from ecoscribe.app import App
    from ecoscribe.config import Config

    class Eng:
        warmed = 0

        def warm(self):
            self.warmed += 1

    class Rec:
        def begin(self): pass
        def abort(self): pass

    class Ui:
        def __getattr__(self, n):
            return lambda *a, **k: None
    eng = Eng()
    app = App(Config(), Rec(), eng, None, Ui())
    app.on_action("toggle")
    assert eng.warmed == 1
    app.shutdown()


def test_on_demand_on_by_default():  # 1.2: no model resident all day
    assert WhisperCfg().on_demand is True


def test_warm_does_not_wait_for_a_transcription_in_flight():
    """A tap while the previous utterance is still transcribing must start recording at once."""
    import threading
    spawn, procs = spawner("slow")
    e = proxy(spawn)
    e.transcribe(audio())  # worker up
    t = threading.Thread(target=e.transcribe, args=(audio(),))
    t.start()
    time.sleep(0.5)  # now inside the 3 s transcription
    t0 = time.monotonic()
    e.warm()
    assert time.monotonic() - t0 < 0.2
    t.join()
    e.close()


def test_close_does_not_wait_for_a_transcription_in_flight():
    import threading
    spawn, procs = spawner("hang")
    e = proxy(spawn, reply_timeout_s=60)
    threading.Thread(target=lambda: _swallow(e.transcribe, audio()), daemon=True).start()
    time.sleep(1.0)
    t0 = time.monotonic()
    e.close()
    assert time.monotonic() - t0 < 2 and procs[0].wait(timeout=5) is not None
    time.sleep(1.5)
    assert len(procs) == 1  # the interrupted request did not respawn a worker after close


def test_stray_stdout_in_worker_does_not_corrupt_the_protocol(tmp_path):
    """The real worker_main moves fd 1 away from the protocol pipe."""
    spawn, procs = spawner("noisy")
    e = proxy(spawn, reply_timeout_s=5)
    r = e.transcribe(audio())
    assert r.text
    e.close()


def _swallow(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


def test_preview_skips_until_the_worker_is_ready_then_round_trips():
    """dictado-live: a preview never starts or waits for the worker; once it's up it answers."""
    spawn, procs = spawner("slow_ready")
    e = proxy(spawn)
    assert e.preview(audio()) is None and procs == []  # nothing running: not spawned for a preview
    e.warm()
    assert e.preview(audio()) is None  # still loading: skipped at once
    r = e.transcribe(audio(32000))
    assert r.text.endswith("n32000")
    p = e.preview(audio(16000), lang="es")
    assert p.text == "preview n16000" and p.lang == "es"
    assert e.transcribe(audio(8000)).text.endswith("n8000")  # replies stay paired
    e.close()
