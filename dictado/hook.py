"""Global keyboard + mouse low-level hooks on a dedicated thread.

The hook callback only timestamps the event, queues it and passes it on.
Windows silently unhooks LL hooks whose callbacks are slow, and sleep/lock can
drop them too, so the hooks are re-installed every reinstall_s seconds.
Every event goes on to CallNextHookEx, with one exception: the Esc of the
cancel combo (toggle key + Esc) while recording. With Right Ctrl held that Esc
is Ctrl+Esc, which Windows turns into "open Start", so it must not get through.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes as w
from typing import Callable

from .keystate import VK_ESCAPE, KeyState
from .win32types import (HOOKPROC, KBDLLHOOKSTRUCT, LLKHF_INJECTED, LLMHF_INJECTED,
                         MOUSE_PRESS_MSGS, MSLLHOOKSTRUCT, WH_KEYBOARD_LL, WH_MOUSE_LL,
                         WM_KEYDOWN, WM_KEYUP, WM_QUIT, WM_SYSKEYDOWN, WM_SYSKEYUP, WM_TIMER,
                         kernel32, user32)

log = logging.getLogger(__name__)
_DOWN = {WM_KEYDOWN, WM_SYSKEYDOWN}
_UP = {WM_KEYUP, WM_SYSKEYUP}


class HookThread(threading.Thread):
    def __init__(self, on_action: Callable[[str], None], toggle_vk: int, max_tap_s: float,
                 accept_injected: bool = False, reinstall_s: float = 30.0,
                 swallow_cancel: Callable[[], bool] = lambda: False, combo=None,
                 hold: bool = False, hold_s: float = 0.5, emit=None, consume: bool = True):
        super().__init__(name="dictado-hook", daemon=True)
        self.on_action = on_action
        self.keys = KeyState(toggle_vk, max_tap_s, hold=hold, hold_s=hold_s)
        self.accept_injected = accept_injected
        self.reinstall_s = reinstall_s
        self.installs = 0
        self.swallow_cancel = swallow_cancel
        self.toggle_vk = toggle_vk
        self.combo = combo  # hotkeys.ComboMatcher when the shortcut is a combo like Ctrl+L
        self._toggle_down = False  # tracked inside the hook callback itself
        self._eat_esc_up = False
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._emit = emit or self._q.put  # the hook process sends events over a pipe instead (t0u.37)
        self._consume_events = consume
        self._hooks: list = []
        self._kb_proc = HOOKPROC(self._kb)
        self._ms_proc = HOOKPROC(self._ms)
        self._consumer = threading.Thread(target=self._consume, name="dictado-keys", daemon=True)
        self._running = True

    def would_swallow(self, vk: int, down: bool) -> bool:
        if vk != VK_ESCAPE:
            return False
        if down:
            if self._toggle_down and self.swallow_cancel():
                self._eat_esc_up = True
                return True
            return False
        if self._eat_esc_up:
            self._eat_esc_up = False
            return True
        return False

    # --- runs inside the hook thread; keep it tiny ---
    def _kb(self, code, wparam, lparam):
        if code >= 0:
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if self.accept_injected or not (k.flags & LLKHF_INJECTED):
                down = wparam in _DOWN
                if down or wparam in _UP:
                    if self.combo is not None:
                        fire, eat = self.combo.key(k.vkCode, down)
                        if fire:
                            self._emit(("combo", k.vkCode, time.monotonic()))
                        if eat:
                            return 1  # the app under the cursor never sees the shortcut
                    if k.vkCode == self.toggle_vk:
                        self._toggle_down = down
                    self._emit(("down" if down else "up", k.vkCode, time.monotonic()))
                    if self.would_swallow(k.vkCode, down):
                        return 1
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _ms(self, code, wparam, lparam):
        if code >= 0 and wparam in MOUSE_PRESS_MSGS:
            m = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if self.accept_injected or not (m.flags & LLMHF_INJECTED):
                self._emit(("mouse", 0, time.monotonic()))
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _install(self) -> None:
        hmod = kernel32.GetModuleHandleW(None)
        new = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, hmod, 0),
               user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, hmod, 0)]
        if not all(new):
            err = ctypes.get_last_error()
            for h in new:
                if h:
                    user32.UnhookWindowsHookEx(h)
            log.error("hook install failed (err=%s); keeping previous hooks", err)
            return
        for h in self._hooks:
            user32.UnhookWindowsHookEx(h)
        self._hooks = new
        self.installs += 1
        if self.installs == 1:
            log.info("hook installed")
        else:
            log.debug("hook reinstall n=%d", self.installs)

    def run(self) -> None:
        if self._consume_events:
            self._consumer.start()
        self._install()
        user32.SetTimer(None, 0, int(self.reinstall_s * 1000), None)
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message != WM_TIMER:
                continue
            if (self.keys.held or self._toggle_down) and not (user32.GetAsyncKeyState(self.toggle_vk) & 0x8000):
                # we missed the key-up (hook dropped mid-press): unstick so taps and Esc work again
                log.warning("toggle key looked held but is up; resetting")
                self.keys.held = False
                self._toggle_down = False
                self._eat_esc_up = False
                if not self._consume_events:  # in the hook process: tell the app the key is up
                    self._emit(("up", self.toggle_vk, time.monotonic()))
            if not self.keys.held:
                self._install()
        for h in self._hooks:
            user32.UnhookWindowsHookEx(h)
        self._hooks = []
        self._running = False
        if self._consume_events:
            self._q.put(None)

    def stop(self) -> None:
        # The thread may not have created its message queue yet; retry briefly.
        for _ in range(50):
            if self.native_id and user32.PostThreadMessageW(self.native_id, WM_QUIT, 0, 0):
                return
            time.sleep(0.02)

    # --- consumer thread: state machine + callbacks ---
    def _consume(self) -> None:
        while True:
            try:  # hold mode needs a clock: "hold" fires while the key just sits there
                ev = self._q.get(timeout=0.05) if self.keys.hold else self._q.get()
            except queue.Empty:
                ev = ()
            if ev is None:
                return
            try:
                if ev:
                    action = "toggle" if ev[0] == "combo" else self.keys.feed(*ev)
                    if action:
                        self.on_action(action)
                action = self.keys.tick(time.monotonic())  # also between auto-repeat downs
                if action:
                    self.on_action(action)
            except Exception:
                log.exception("key handling failed")



class HookClient(HookThread):
    """The hooks in their own process (t0u.37): `Dictado.exe --hook`. Windows makes every key
    and click on the PC wait for a low-level hook's answer; in the app's own process that
    answer needs Python's lock, so a frozen app froze the whole PC's input. The hook process
    only hooks and answers; events come here over its stdout, the recording state goes to it
    over its stdin. If it dies it is restarted; if it can't start, the hooks run here as before."""

    MAX_RESPAWNS = 5

    def __init__(self, *a, spawn=None, **kw):
        super().__init__(*a, **kw)
        self.spawn = spawn  # (args) -> Popen with stdin/stdout pipes
        self.proc = None
        self.mode = "process"
        self._stopping = False

    def _hook_args(self) -> list[str]:
        a = ["--hook", str(self.toggle_vk), f"{self.keys.max_tap_s}", f"{self.reinstall_s}"]
        if self.accept_injected:
            a.append("--hook-injected")
        if self.combo is not None:
            a += ["--hook-combo", self.combo.spec]
        return a

    def _push_state(self) -> None:
        last = None
        while not self._stopping:
            try:
                cur = bool(self.swallow_cancel())
                p = self.proc
                if p is not None and cur != last:
                    p.stdin.write(b"rec 1\n" if cur else b"rec 0\n")
                    p.stdin.flush()
                    last = cur
            except Exception:
                last = None  # the process is being replaced: send it again
            time.sleep(0.03)

    def run(self) -> None:
        self._consumer.start()
        threading.Thread(target=self._push_state, name="dictado-hookstate", daemon=True).start()
        spawned = 0
        while not self._stopping:
            try:
                self.proc = self.spawn(self._hook_args())
            except Exception:
                log.exception("hook process did not start; hooks run in the app instead")
                break
            spawned += 1
            log.info("hook process started pid=%s", getattr(self.proc, "pid", None))
            for line in self.proc.stdout:
                parts = line.split()
                if len(parts) == 3:
                    try:
                        self._q.put((parts[0].decode(), int(parts[1]), float(parts[2])))
                    except ValueError:
                        pass
                elif parts[:1] == [b"ready"]:
                    log.info("hook installed (own process)")
            if self._stopping:
                break
            log.error("hook process ended (exit %s); restarting it", self.proc.poll())
            if spawned >= self.MAX_RESPAWNS:
                log.error("hook process keeps dying; hooks run in the app instead")
                break
            time.sleep(0.2)
        if not self._stopping:  # fall back: the old in-process hooks, so the key always works
            self.mode = "inprocess"
            self._emit = self._q.put
            HookThread.run(self)
        else:
            self._q.put(None)

    def stop(self) -> None:
        self._stopping = True
        p = self.proc
        if p is not None:
            try:
                p.stdin.close()  # the hook process exits on EOF
            except Exception:
                pass
            try:
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        if self.mode == "inprocess":
            HookThread.stop(self)


def spawn_hook_process(args: list[str]):
    import os
    import subprocess
    import sys
    frozen = getattr(sys, "frozen", False)
    argv = [sys.executable] if frozen else [sys.executable, "-m", "dictado"]
    cwd = None if frozen else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.Popen(argv + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def hook_process_main(argv: list[str]) -> int:
    """`Dictado.exe --hook <vk> <max_tap_s> <reinstall_s> [--hook-injected] [--hook-combo SPEC]`:
    hooks only; events as lines "down 163 1234.5678" on stdout; "rec 1|0" on stdin."""
    import sys
    vk, max_tap, reinstall = int(argv[0]), float(argv[1]), float(argv[2])
    combo = None
    if "--hook-combo" in argv:
        from .hotkeys import ComboMatcher
        combo = ComboMatcher(argv[argv.index("--hook-combo") + 1])
    state = {"rec": False}
    out_q: queue.SimpleQueue = queue.SimpleQueue()
    out = sys.stdout.buffer

    def writer():
        while True:
            ev = out_q.get()
            try:
                out.write(f"{ev[0]} {ev[1]} {ev[2]:.4f}\n".encode())
                out.flush()
            except Exception:
                os_exit(0)  # the app is gone

    def reader():
        for line in sys.stdin.buffer:
            if line.startswith(b"rec "):
                state["rec"] = line.strip().endswith(b"1")
        os_exit(0)  # stdin closed: the app quit or died

    def os_exit(code):
        import os
        os._exit(code)
    h = HookThread(None, vk, max_tap, accept_injected="--hook-injected" in argv, reinstall_s=reinstall,
                   swallow_cancel=lambda: state["rec"], combo=combo, emit=out_q.put, consume=False)
    threading.Thread(target=writer, name="hook-writer", daemon=True).start()
    threading.Thread(target=reader, name="hook-reader", daemon=True).start()
    out.write(b"ready\n")
    out.flush()
    h.run()  # this thread runs the hooks' message loop
    return 0
