import threading
import time
import uuid

from dictado import winutil
from dictado.restart import do_restart


def run(spawn_ok=True, failing_step=None):
    calls = []

    def spawn():
        calls.append("spawn")
        if not spawn_ok:
            raise OSError("cannot start")

    def step(name):
        def f():
            calls.append(name)
            if name == failing_step:
                raise RuntimeError("boom")
        return f

    ok = do_restart(spawn, [(n, step(n)) for n in ("app", "hook", "gate", "mic", "tray")],
                    release=lambda: calls.append("release"), exit_fn=lambda c: calls.append(f"exit{c}"),
                    on_spawn_fail=lambda: calls.append("spawn_failed"))
    return ok, calls


def test_spawns_replacement_before_tearing_down():
    ok, calls = run()
    assert ok and calls == ["spawn", "app", "hook", "gate", "mic", "tray", "release", "exit0"]


def test_spawn_failure_keeps_the_engine_running():
    ok, calls = run(spawn_ok=False)
    assert not ok and calls == ["spawn", "spawn_failed"]  # nothing torn down, no exit


def test_one_cleanup_step_failing_does_not_stop_the_rest():
    ok, calls = run(failing_step="hook")
    assert ok and calls[-3:] == ["tray", "release", "exit0"] and "gate" in calls


def test_single_instance_becomes_free_after_holder_releases():
    """The --restarted copy polls single_instance(); it must not keep the mutex alive itself."""
    import win32api
    import win32event
    name = f"Local\\DictadoTestMutex-{uuid.uuid4().hex[:6]}"
    held = threading.Event()
    release = threading.Event()

    def holder():
        h = win32event.CreateMutex(None, False, name)
        held.set()
        release.wait(5)
        win32api.CloseHandle(h)
    t = threading.Thread(target=holder)
    t.start()
    held.wait(2)
    try:
        assert winutil.single_instance(name) is False
        assert winutil.single_instance(name) is False
        release.set()
        t.join(5)
        end = time.monotonic() + 2
        while not winutil.single_instance(name) and time.monotonic() < end:
            time.sleep(0.05)
        assert winutil._mutex is not None, "should own the mutex now"
    finally:
        release.set()
        winutil.release_instance()
