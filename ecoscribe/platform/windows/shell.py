"""The Windows shell: overlay pill, prompt box and tray icon (macOS: ecoscribe/platform/macos/shell.py).

The overlay must never take focus or clicks, otherwise it would steal the
very window you navigated to: it is a no-activate, click-through, tool window
shown only with SW_SHOWNOACTIVATE. Other threads never touch tk directly;
they post to a queue the tk main loop drains.
"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
import time
import tkinter as tk
from ctypes import wintypes as w
from pathlib import Path

from ... import meetui
from ... import palette as P

log = logging.getLogger(__name__)
u32 = ctypes.windll.user32
u32.GetWindowLongW.argtypes = (w.HWND, ctypes.c_int)
u32.SetWindowLongW.argtypes = (w.HWND, ctypes.c_int, ctypes.c_long)
u32.ShowWindow.argtypes = (w.HWND, ctypes.c_int)
u32.SetWindowPos.argtypes = (w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT)
u32.MonitorFromWindow.argtypes = (w.HWND, w.DWORD)
u32.MonitorFromWindow.restype = w.HANDLE
u32.GetForegroundWindow.restype = w.HWND

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x08000000, 0x80, 0x8
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = w.HWND(-1)
SWP_NOSIZE, SWP_NOACTIVATE = 0x1, 0x10
W, H = 210, 44
RW, RH = 230, 54  # the dictating pill: timer + how to cancel (t0u.36)
MW, MH = 380, 56  # the meeting pill: label + latest live line
KEY = "#010203"  # transparent color key, gives the pill round ends


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


class Overlay:
    def __init__(self, root: tk.Tk, level_fn=lambda: 0.0, hint: str = "Right Ctrl + Esc to cancel"):
        self.level_fn = level_fn
        self.hint = hint
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", 0.93)
        self.top.attributes("-transparentcolor", KEY)
        self.top.geometry(f"{W}x{H}+0+0")
        self.c = tk.Canvas(self.top, width=W, height=H, bg=KEY, highlightthickness=0, bd=0)
        self.c.pack()
        self.top.update_idletasks()
        self.hwnd = int(self.top.wm_frame(), 16)
        ex = u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                           ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        u32.ShowWindow(self.hwnd, SW_HIDE)
        self.mode = "hidden"
        self._t0 = 0.0
        self._flash_until = 0.0
        self._flash_msg = ""
        self.w, self.h = W, H
        self.meeting: dict | None = None  # meetui.meeting_view(); shown whenever dictation isn't
        self._drawn = None  # what the meeting layer last drew (no redraw, no flicker)

    def ex_style(self) -> int:
        return u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)

    def _place_and_show(self) -> None:
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = u32.MonitorFromWindow(u32.GetForegroundWindow(), 2)
        if mon and u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcWork
            x, y = (r.left + r.right - self.w) // 2, r.bottom - self.h - 80
        else:
            x, y = 600, 900
        u32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        u32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def _size(self, w_: int, h_: int) -> None:
        if (w_, h_) != (self.w, self.h):
            self.w, self.h = w_, h_
            self.top.geometry(f"{w_}x{h_}")
            self.c.config(width=w_, height=h_)

    def _pill(self, dot: str, label: str) -> None:
        self._size(W, H)
        self._drawn = None
        c = self.c
        c.delete("all")
        r = H // 2
        bg = P.INK
        c.create_oval(0, 0, H, H, fill=bg, outline=bg)
        c.create_oval(W - H, 0, W, H, fill=bg, outline=bg)
        c.create_rectangle(r, 0, W - r, H, fill=bg, outline=bg)
        if dot:
            c.create_oval(16, r - 6, 28, r + 6, fill=dot, outline=dot)
        c.create_text(40 if dot else W // 2, r, text=label, fill=P.PAPER,
                      font=("Segoe UI", 11), anchor="w" if dot else "center")

    def _dictating_pill(self, secs: int, level: float) -> None:
        """Two lines: the timer, and how to cancel; level bars on the right."""
        self._size(RW, RH)
        self._drawn = None
        c = self.c
        c.delete("all")
        r, bg = RH // 2, P.INK
        c.create_oval(0, 0, RH, RH, fill=bg, outline=bg)
        c.create_oval(RW - RH, 0, RW, RH, fill=bg, outline=bg)
        c.create_rectangle(r, 0, RW - r, RH, fill=bg, outline=bg)
        c.create_oval(17, 13, 29, 25, fill=P.TILE, outline=P.TILE)
        c.create_text(40, 19, text=f"Dictating {secs // 60}:{secs % 60:02d}", fill=P.PAPER,
                      font=("Segoe UI", 11), anchor="w")
        c.create_text(40, 38, text=self.hint, fill=P.LINE, font=("Segoe UI", 9), anchor="w")
        for i in range(5):
            on = level > (i + 0.5) / 5
            x = RW - 62 + i * 9
            hgt = 6 + i * 3
            c.create_rectangle(x, 19 + hgt // 2, x + 5, 19 - hgt // 2, fill=P.PAPER if on else P.PILL_OFF, outline="")

    def _meeting_pill(self, view: dict) -> None:
        key = (view["label"], view["line"], view["busy"])
        if key == self._drawn:
            return
        self._size(MW, MH)
        c = self.c
        c.delete("all")
        r, bg = MH // 2, P.INK
        c.create_oval(0, 0, MH, MH, fill=bg, outline=bg)
        c.create_oval(MW - MH, 0, MW, MH, fill=bg, outline=bg)
        c.create_rectangle(r, 0, MW - r, MH, fill=bg, outline=bg)
        dot = P.AEGEAN_SOFT if view["busy"] else P.TILE
        c.create_oval(18, r - 6, 30, r + 6, fill=dot, outline=dot)
        if view["line"]:
            c.create_text(42, 18, text=view["label"], fill=P.PAPER, font=("Segoe UI", 10, "bold"), anchor="w")
            c.create_text(42, 38, text=view["line"], fill=P.LINE, font=("Segoe UI", 10), anchor="w")
        else:
            c.create_text(42, r, text=view["label"], fill=P.PAPER, font=("Segoe UI", 11), anchor="w")
        self._place_and_show()
        self._drawn = key

    def _show_layer(self) -> None:
        """Dictation idle and no flash: the meeting pill, or nothing."""
        if meetui.pill_layer(self.mode, self.meeting) == "meeting":
            self._meeting_pill(self.meeting)
        else:
            self._drawn = None
            u32.ShowWindow(self.hwnd, SW_HIDE)

    def set_meeting(self, view: dict | None) -> None:
        self.meeting = view
        if self.mode == "hidden" and time.monotonic() >= self._flash_until:
            self._show_layer()

    def recording(self, t0: float) -> None:
        self.mode, self._t0 = "recording", t0
        self._place_and_show()
        self.tick()

    def busy(self) -> None:
        self.mode = "busy"
        self._pill(P.AEGEAN_SOFT, "Transcribing…")
        self._place_and_show()

    def idle(self) -> None:
        self.mode = "hidden"
        if time.monotonic() >= self._flash_until:
            self._show_layer()

    def flash(self, msg: str, seconds: float = 2.0) -> None:
        self._flash_msg, self._flash_until = msg, time.monotonic() + seconds
        if self.mode == "recording":
            return
        self._pill("", msg)
        self._place_and_show()

    def tick(self) -> None:
        """Called every 50 ms by the UI loop."""
        now = time.monotonic()
        if self.mode == "recording":
            self._dictating_pill(int(now - self._t0), min(1.0, math.sqrt(self.level_fn()) * 4))
        elif self.mode == "hidden" and self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self._show_layer()
        elif self.mode == "busy" and self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self.busy()


class PromptWindow:
    """The clickable box above the pill: a call started, long silence, transcript ready.
    No-activate (clicking it never takes focus from the call window), not click-through."""

    def __init__(self, root: tk.Tk, on_answer):
        self.root, self.on_answer = root, on_answer
        self.prompt: meetui.Prompt | None = None
        self.top = None
        self._later: list[meetui.Prompt] = []  # done/failed notes waiting behind a question
        self._btns: dict = {}  # choice -> button label, for the countdown

    def show(self, prompt: meetui.Prompt) -> None:
        """A question (start, end?) is never replaced by a note (done, failed): the note waits.
        A question over a question just replaces it (the detector sees one call at a time, so
        the old one is already moot; answering it here could suppress the new call)."""
        if meetui.placement(self.prompt, prompt) == "queue":
            self._later.append(prompt)
            return
        self._close()
        self.prompt = prompt
        top = self.top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=P.INK)
        box = tk.Frame(top, bg=P.PAPER, padx=16, pady=12)
        box.pack(padx=1, pady=1)
        tk.Label(box, text=prompt.title, bg=P.PAPER, fg=P.INK, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.lang = tk.StringVar(value=dict(meetui.LANGS).get(prompt.lang or "sv", "Swedish"))
        if prompt.kind == "start":
            row = tk.Frame(box, bg=P.PAPER)
            row.pack(anchor="w", pady=(6, 0))
            tk.Label(row, text=prompt.question, bg=P.PAPER, fg=P.INK, font=("Segoe UI", 10)).pack(side="left")
            om = tk.OptionMenu(row, self.lang, *[n for _, n in meetui.LANGS])
            om.config(bg=P.PAPER, fg=P.INK, activebackground=P.AEGEAN_SOFT, highlightthickness=0, bd=1,
                      relief="solid", font=("Segoe UI", 10))
            om["menu"].config(bg=P.PAPER, fg=P.INK, activebackground=P.AEGEAN, activeforeground=P.PAPER)
            om.pack(side="left", padx=(6, 0))
        elif prompt.question:
            tk.Label(box, text=prompt.question, bg=P.PAPER, fg=P.INK_SOFT, font=("Segoe UI", 10)).pack(anchor="w")
        btns = tk.Frame(box, bg=P.PAPER)
        btns.pack(anchor="e", pady=(10, 0))
        self._btns = {}
        for i, (label, choice) in enumerate(prompt.buttons):
            primary = i == 0
            b = self._btns[choice] = tk.Label(btns, text=prompt.button_text(choice, time.monotonic()), bg=P.AEGEAN if primary else P.LINE, fg=P.PAPER if primary else P.INK,
                         font=("Segoe UI", 10, "bold" if primary else "normal"), padx=14, pady=5, cursor="hand2")
            b.bind("<Button-1>", lambda _e, c=choice: self._answer(c))
            b.pack(side="left", padx=(8 if i else 0, 0))
        top.update_idletasks()
        hwnd = int(top.wm_frame(), 16)
        ex = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = u32.MonitorFromWindow(u32.GetForegroundWindow(), 2)
        pw, ph = top.winfo_reqwidth(), top.winfo_reqheight()
        if mon and u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            r = mi.rcWork
            x, y = (r.left + r.right - pw) // 2, r.bottom - MH - 80 - ph - 12
        else:
            x, y = 600, 760
        u32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

    def _lang_code(self) -> str:
        names = {n: c for c, n in meetui.LANGS}
        return names.get(self.lang.get(), "sv")

    def _answer(self, choice: str) -> None:
        p = self.prompt
        lang = self._lang_code() if p and p.kind == "start" else None
        self.hide()
        if p is not None and choice != "hide":
            try:
                self.on_answer(p, choice, lang)
            except Exception:
                log.exception("prompt answer failed")

    def dismiss(self, kind: str = "start") -> None:
        if self.prompt is not None and self.prompt.kind == kind:
            self.hide()

    def _close(self) -> None:
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
        self.top, self.prompt = None, None

    def hide(self) -> None:
        self._close()
        if self._later:
            nxt = self._later.pop(0)
            nxt.opened_at = time.monotonic()  # a note that waited still gets its full time on screen
            self.show(nxt)

    def tick(self) -> None:
        if self.prompt is not None:
            now = time.monotonic()
            what = self.prompt.expired(now)
            if what is not None:
                self._answer(what)
                return
            for choice, b in self._btns.items():  # "Not now (7)": the countdown
                text = self.prompt.button_text(choice, now)
                if b.cget("text") != text:
                    b.config(text=text)


class Tray:
    def __init__(self, app_ref, log_path: Path, on_quit, open_window=None, meeting_label=None, on_meeting=None,
                 open_meetings=None, meeting_state=None, last_lang=None, start_meeting=None,
                 dict_langs=None, dict_lang=None, set_dict_lang=None):
        import pystray

        from ...icon import TRAY, tray_image
        self._images = {state: tray_image(state) for state in TRAY}
        meeting_items = []
        if meeting_label and on_meeting and meeting_state and start_meeting:
            # idle: "Transcribe meeting now >" with a language submenu (last one ticked);
            # recording: "Stop meeting" / "Saving meeting..." (the user 2026-10-05: no language choice from the tray)
            def lang_item(code, name):
                return pystray.MenuItem(name, lambda: start_meeting(code),
                                        checked=lambda _i: (last_lang() if last_lang else "sv") == code, radio=True)
            langs = pystray.Menu(*[lang_item(c, n) for c, n, _ in meetui.tray_lang_items("sv")])
            idle = lambda _i: not meetui.tray_recording(meeting_state())  # noqa: E731
            meeting_items = [pystray.MenuItem("Transcribe meeting now", langs, visible=idle),
                             pystray.MenuItem(lambda _i: meeting_label(), lambda: on_meeting(),
                                              visible=lambda _i: meetui.tray_recording(meeting_state())),
                             pystray.MenuItem("Open Meetings", lambda: open_meetings and open_meetings()),
                             pystray.Menu.SEPARATOR]
        dict_items = []
        if dict_langs and dict_lang and set_dict_lang:  # t0u.24: switch without opening the window
            def dict_item(code, name):
                return pystray.MenuItem(name, lambda: set_dict_lang(code),
                                        checked=lambda _i: dict_lang() == code, radio=True)
            dict_items = [pystray.MenuItem("Next dictation in", pystray.Menu(*[dict_item(c, n) for c, n in dict_langs]))]
        menu = pystray.Menu(
            pystray.MenuItem("Open Ecoscribe", lambda: open_window and open_window(), default=True),
            pystray.Menu.SEPARATOR,
            *dict_items,
            *meeting_items,
            pystray.MenuItem("Copy last", lambda: app_ref().copy_last()),
            pystray.MenuItem("Cancel recording", lambda: app_ref().on_action("cancel")),
            pystray.MenuItem("Open log", lambda: os.startfile(str(log_path))),
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        self.icon = pystray.Icon("ecoscribe", self._images["idle"], "Ecoscribe", menu)
        threading.Thread(target=self.icon.run, name="ecoscribe-tray", daemon=True).start()

    def set_state(self, state: str) -> None:
        try:
            self.icon.icon = self._images.get(state, self._images["idle"])
        except Exception:
            pass

    def refresh(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
