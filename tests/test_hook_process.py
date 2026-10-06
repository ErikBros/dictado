"""Hooks in their own process (t0u.37), with a fake hook process."""
import io
import queue
import threading
import time

from dictado import hook as hookmod
from dictado.hook import HookClient

RCTRL = 0xA3


class FakeProc:
    """stdout = the lines the hook process would print; stdin collects what the app sends."""

    def __init__(self, lines, hold=None):
        self.pid = 4242
        self.lines, self.hold = lines, hold
        self.sent = []
        outer = self

        class In:
            def write(self, b):
                outer.sent.append(b)

            def flush(self):
                pass

            def close(self):
                outer.closed = True
        self.stdin = In()
        self.closed = False

    @property
    def stdout(self):
        for l in self.lines:
            yield l
        if self.hold is not None:  # stay alive until the test lets go
            self.hold.wait(5)

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def client(spawn, actions, rec=lambda: False):
    return HookClient(actions.append, RCTRL, 0.3, swallow_cancel=rec, spawn=spawn)


def test_a_tap_from_the_hook_process_toggles():
    t = time.monotonic()
    hold = threading.Event()
    procs = []

    def spawn(args):
        procs.append(args)
        return FakeProc([b"ready\n", f"down {RCTRL} {t:.4f}\n".encode(), f"up {RCTRL} {t + 0.1:.4f}\n".encode()], hold)
    actions = []
    c = client(spawn, actions)
    c.start()
    end = time.monotonic() + 2
    while time.monotonic() < end and not actions:
        time.sleep(0.01)
    assert actions == ["toggle"]
    assert procs[0][:2] == ["--hook", str(RCTRL)]
    c._stopping = True
    hold.set()


def test_recording_state_reaches_the_hook_process():
    hold = threading.Event()
    made = []

    def spawn(args):
        made.append(FakeProc([b"ready\n"], hold))
        return made[-1]
    rec = {"on": False}
    c = client(spawn, [], rec=lambda: rec["on"])
    c.start()
    time.sleep(0.15)
    rec["on"] = True
    time.sleep(0.15)
    rec["on"] = False
    time.sleep(0.15)
    assert made[0].sent == [b"rec 0\n", b"rec 1\n", b"rec 0\n"]
    c._stopping = True
    hold.set()


def test_a_dead_hook_process_is_restarted_then_falls_back(monkeypatch):
    spawned = []
    fell_back = threading.Event()
    monkeypatch.setattr(hookmod.HookThread, "run", lambda self: fell_back.set())

    def spawn(args):
        spawned.append(1)
        return FakeProc([b"ready\n"])  # ends at once: a crash
    c = client(spawn, [])
    c.start()
    assert fell_back.wait(5)
    assert len(spawned) == HookClient.MAX_RESPAWNS and c.mode == "inprocess"


def test_no_hook_process_at_all_falls_back_at_once(monkeypatch):
    fell_back = threading.Event()
    monkeypatch.setattr(hookmod.HookThread, "run", lambda self: fell_back.set())

    def spawn(args):
        raise OSError("blocked")
    c = client(spawn, [])
    c.start()
    assert fell_back.wait(3) and c.mode == "inprocess"
