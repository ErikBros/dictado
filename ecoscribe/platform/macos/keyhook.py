"""Global key + mouse watching on macOS: a CGEventTap on its own thread (hook.py's HookThread for the Mac).

Same contract as the Windows hook: the tap callback only timestamps the event, queues it and lets it
through; a consumer thread runs the same KeyState machine (tap, hold-to-talk, Esc cancel) and the same
ComboMatcher. Two things are swallowed, as on Windows: the Esc of the cancel combo while recording, and
a combo shortcut (the app under the cursor never sees it). Dictation key + L picks the next dictation's
language ("lang", once per press; the L is swallowed so no app sees Cmd+L), as on Windows.

Mac specifics:
- Modifier keys (Right Command, Fn...) arrive as flagsChanged; down/up comes from their device bit.
- Our own synthetic Cmd+V carries a tag (mac/keys.py MAGIC) and is ignored unless accept_injected.
- macOS disables a tap whose callback is slow, or on secure input; the callback re-enables it and a
  periodic check re-enables it too (the Windows hook's reinstall timer).
- Needs Input Monitoring (listen) and Accessibility (to swallow). Without them the tap can't be created:
  `ok` stays False and the app says which permission is missing.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

from ...keystate import KeyState
from . import keymap

log = logging.getLogger(__name__)
KC_LANG = 37  # the L key (a key position: the same key on Swedish, Spanish and US layouts)


class HookThread(threading.Thread):
    def __init__(self, on_action: Callable[[str], None], toggle_vk: int, max_tap_s: float,
                 accept_injected: bool = False, reinstall_s: float = 30.0,
                 swallow_cancel: Callable[[], bool] = lambda: False, combo=None,
                 hold: bool = False, hold_s: float = 0.5):
        super().__init__(name="ecoscribe-hook", daemon=True)
        self.on_action = on_action
        self.toggle_kc = toggle_vk  # a Mac keycode (config.KEYS on darwin)
        self.toggle_vk = keymap.to_vk(toggle_vk) if toggle_vk else 0
        self.keys = KeyState(self.toggle_vk, max_tap_s, hold=hold, hold_s=hold_s)
        self.accept_injected = accept_injected
        self.reinstall_s = reinstall_s
        self.swallow_cancel = swallow_cancel
        self.combo = combo  # hotkeys.ComboMatcher (Mac keycodes, shifted) for a shortcut like Cmd+Shift+D
        self.installs = 0
        self.ok = False  # the tap exists (both permissions granted)
        self.ready = threading.Event()
        self._toggle_down = False
        self._eat_esc_up = False
        self._lang_held = False  # L went down with the dictation key held: swallowed until it's up
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._tap = None
        self._loop = None
        self._consumer = threading.Thread(target=self._consume, name="ecoscribe-keys", daemon=True)

    # --- pure part of the callback, testable without a real tap ---
    def lang_key(self, keycode: int, down: bool, t: float) -> bool:
        """Dictation key + L: emit "lang" once per press (auto-repeat doesn't cycle again) and swallow the L,
        down and up. Lone keys only: a combo shortcut has no language key (same as Windows)."""
        if self.combo is not None or keycode != KC_LANG or not (self._toggle_down or self._lang_held):
            return False
        if down and not self._lang_held:
            self._lang_held = True
            self._q.put(("lang", keymap.to_vk(keycode), t))
        elif not down:
            self._lang_held = False
        return True

    def would_swallow(self, vk: int, down: bool) -> bool:
        if vk != keymap.VK_ESCAPE:
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

    def handle(self, kind: str, keycode: int, flags: int, ours: bool, t: float | None = None) -> bool:
        """kind: 'down' | 'up' | 'flags' | 'mouse'. Returns True to swallow the event."""
        if ours and not self.accept_injected:
            return False
        t = time.monotonic() if t is None else t
        if kind == "mouse":
            self._q.put(("mouse", 0, t))
            return False
        if kind == "flags":
            down = keymap.modifier_down(keycode, flags)
            if down is None:
                return False
        else:
            down = kind == "down"
        vk = keymap.to_vk(keycode)
        if self.combo is not None:
            fire, eat = self.combo.key(vk, down)
            if fire:
                self._q.put(("combo", vk, t))
            if eat:
                return True
        if vk == self.toggle_vk:
            self._toggle_down = down
        self._q.put(("down" if down else "up", vk, t))
        if kind != "flags" and self.lang_key(keycode, down, t):
            return True  # the app under the cursor never sees this L
        return self.would_swallow(vk, down)

    # --- the real tap ---
    def _callback(self, proxy, etype, event, refcon):
        import Quartz as Q
        try:
            if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
                log.warning("key tap disabled by macOS (%s); re-enabling", etype)
                Q.CGEventTapEnable(self._tap, True)
                return event
            from .keys import is_ours
            ours = is_ours(event)
            if etype in (Q.kCGEventLeftMouseDown, Q.kCGEventRightMouseDown, Q.kCGEventOtherMouseDown):
                self.handle("mouse", 0, 0, ours)
                return event
            kc = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
            kind = {Q.kCGEventKeyDown: "down", Q.kCGEventKeyUp: "up", Q.kCGEventFlagsChanged: "flags"}.get(etype)
            if kind and self.handle(kind, int(kc), int(Q.CGEventGetFlags(event)), ours):
                return None  # swallowed
        except Exception:
            log.exception("key tap callback failed")
        return event

    def _install(self) -> bool:
        import Quartz as Q
        mask = 0
        for et in (Q.kCGEventKeyDown, Q.kCGEventKeyUp, Q.kCGEventFlagsChanged, Q.kCGEventLeftMouseDown,
                   Q.kCGEventRightMouseDown, Q.kCGEventOtherMouseDown):
            mask |= Q.CGEventMaskBit(et)
        tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionDefault,
                                 mask, self._callback, None)
        if tap is None:
            log.error("key tap not created: Ecoscribe needs Input Monitoring and Accessibility (System Settings > "
                      "Privacy & Security)")
            return False
        self._tap = tap
        src = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
        Q.CFRunLoopAddSource(self._loop, src, Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(tap, True)
        self.installs += 1
        log.info("key tap installed")
        return True

    def run(self) -> None:
        import Quartz as Q
        self._consumer.start()
        self._loop = Q.CFRunLoopGetCurrent()
        self.ok = self._install()
        self.ready.set()
        if not self.ok:
            return
        timer = Q.CFRunLoopTimerCreate(None, Q.CFAbsoluteTimeGetCurrent() + self.reinstall_s, self.reinstall_s, 0, 0,
                                       lambda *_: self._check(), None)
        Q.CFRunLoopAddTimer(self._loop, timer, Q.kCFRunLoopCommonModes)
        Q.CFRunLoopRun()
        self._q.put(None)

    def _check(self) -> None:
        import Quartz as Q
        if self._tap is not None and not Q.CGEventTapIsEnabled(self._tap):
            log.warning("key tap found disabled; re-enabling")
            Q.CGEventTapEnable(self._tap, True)
        if (self.keys.held or self._toggle_down) and self.toggle_kc and \
                not Q.CGEventSourceKeyState(Q.kCGEventSourceStateHIDSystemState, self.toggle_kc):
            log.warning("toggle key looked held but is up; resetting")  # a missed key-up
            self.keys.held = False
            self._toggle_down = False
            self._eat_esc_up = False

    def stop(self) -> None:
        import Quartz as Q
        self.ready.wait(2)
        if self._tap is not None:
            Q.CGEventTapEnable(self._tap, False)
        if self._loop is not None:
            Q.CFRunLoopStop(self._loop)
        self._q.put(None)

    # --- consumer thread: state machine + callbacks (same as hook.py) ---
    def _consume(self) -> None:
        while True:
            try:
                ev = self._q.get(timeout=0.05) if self.keys.hold else self._q.get()
            except queue.Empty:
                ev = ()
            if ev is None:
                return
            try:
                if ev:
                    action = {"combo": "toggle", "lang": "lang"}.get(ev[0]) or self.keys.feed(*ev)
                    if action:
                        self.on_action(action)
                action = self.keys.tick(time.monotonic())
                if action:
                    self.on_action(action)
            except Exception:
                log.exception("key handling failed")
