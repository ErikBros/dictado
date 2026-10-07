"""The background app's surface on macOS (uat.5): main loop, pill, prompt box, menu-bar item, sounds.

Windows uses tk (pill, prompt) + pystray (tray) on separate threads. On the Mac AppKit, the status item
and the panels all want THE main thread, so one NSApplication run loop owns them (pre-mortem #2):

- Root: the few tk calls __main__ and ui.Ui make (after, mainloop, destroy, withdraw), on AppKit. after()
  is safe from any thread (it hops to the main thread), like the tk usage it replaces.
- Overlay: the pill. A borderless, non-activating, click-through panel on every Space, so it can never
  take focus from the window you dictate into. Same modes and flashes as ui.Overlay.
- PromptWindow: the box above the pill (call started, long silence, transcript ready). Clickable but
  non-activating: answering never pulls focus away from the call.
- Tray: an NSStatusItem with the same menu as the Windows tray, rebuilt each time it opens.
- Sounds: the same generated tones, played with NSSound.

ui.Ui (the thread-safe facade App talks to) is shared unchanged: it only needs root.after.
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSBezierPath,
                    NSButton, NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSImage,
                    NSMakeRect, NSMenu, NSMenuItem, NSPanel, NSPopUpButton, NSScreen, NSSound, NSStatusBar,
                    NSString, NSTextField, NSVariableStatusItemLength, NSView, NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorStationary,
                    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel)
from Foundation import NSData, NSObject
from PyObjCTools import AppHelper

from ... import meetui
from ... import palette as P

log = logging.getLogger(__name__)
W, H = 210, 44
MW, MH = 380, 56
NSStatusWindowLevel = 25
BOTTOM_GAP = 80


def color(hex_color: str, alpha: float = 1.0):
    r, g, b = P.rgb(hex_color)
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, alpha)


def font(size: float, bold: bool = False):
    return NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)


def on_main(fn, *args) -> None:
    AppHelper.callAfter(fn, *args)


# ---------------------------------------------------------------------------------------------------------------
class Root:
    """The tk calls Ecoscribe's background app makes, on the AppKit run loop."""

    def __init__(self):
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # menu bar only, no Dock icon
        self._running = False
        # No App Nap: with no visible window macOS stops firing run-loop timers for minutes (seen 2026-10-06:
        # the heartbeat stalled 168-928 s while the main thread sat idle, and the watchdog read it as a hang).
        # The key tap, the pill and every root.after() must run on time. Idle system sleep stays allowed.
        from Foundation import NSProcessInfo
        try:
            from Foundation import NSActivityUserInitiatedAllowingIdleSystemSleep as opts
        except ImportError:
            opts = 0x00EFFFFF
        self._activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            opts, "Ecoscribe waits for the dictation key")

    def after(self, ms: int, fn, *args) -> None:
        if ms <= 0:
            AppHelper.callAfter(fn, *args)
        else:
            AppHelper.callLater(ms / 1000.0, fn, *args)

    def withdraw(self) -> None:
        pass

    def mainloop(self) -> None:
        self._running = True
        AppHelper.runEventLoop(installInterrupt=True)

    def destroy(self) -> None:
        AppHelper.stopEventLoop()


# ---------------------------------------------------------------------------------------------------------------
def _panel(w: int, h: int, clickable: bool):
    p = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, w, h), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, False)
    p.setLevel_(NSStatusWindowLevel)
    p.setOpaque_(False)
    p.setBackgroundColor_(NSColor.clearColor())
    p.setHasShadow_(True)
    p.setHidesOnDeactivate_(False)
    p.setIgnoresMouseEvents_(not clickable)
    p.setBecomesKeyOnlyIfNeeded_(True)
    p.setFloatingPanel_(True)
    p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
                             | NSWindowCollectionBehaviorFullScreenAuxiliary)
    return p


def _active_screen():
    """The screen with the mouse (where the user is looking), else the main one."""
    from AppKit import NSEvent
    loc = NSEvent.mouseLocation()
    for s in NSScreen.screens():
        f = s.frame()
        if f.origin.x <= loc.x <= f.origin.x + f.size.width and f.origin.y <= loc.y <= f.origin.y + f.size.height:
            return s
    return NSScreen.mainScreen()


def _bottom_center(w: int, h: int, lift: int = 0) -> tuple[float, float]:
    vf = _active_screen().visibleFrame()
    return vf.origin.x + (vf.size.width - w) / 2, vf.origin.y + BOTTOM_GAP + lift


class PillView(NSView):
    """Draws whatever Overlay last set in self.spec (a plain dict)."""

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        spec = getattr(self, "spec", None)
        if not spec:
            return
        w, h = spec["w"], spec["h"]
        r = h / 2
        color(P.INK, 0.93).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(0, 0, w, h), r, r).fill()
        if spec.get("dot"):
            color(spec["dot"]).setFill()
            NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(spec.get("dot_x", 16), r - 6, 12, 12)).fill()
        for text, x, y, size, bold, col, center in spec.get("texts", []):
            attrs = {NSFontAttributeName: font(size, bold), NSForegroundColorAttributeName: color(col)}
            s = NSString.stringWithString_(text)
            sz = s.sizeWithAttributes_(attrs)
            tx = (w - sz.width) / 2 if center else x
            s.drawAtPoint_withAttributes_((tx, y - sz.height / 2), attrs)
        for x, top, bottom, on in spec.get("bars", []):
            color(P.PAPER if on else P.PILL_OFF).setFill()
            NSBezierPath.fillRect_(NSMakeRect(x, top, 5, bottom - top))


def cancel_hint(hk) -> str:
    """The pill's second line while dictating, from the HotkeyCfg."""
    from ...hotkeys import combo_vks, label
    key = "⌘" if hk.key == "rcmd" else label(hk.key)
    if combo_vks(hk.key):  # a combo: press it again to finish; Esc doesn't cancel (menu bar does)
        return f"Press {key} again to finish · Cancel: menu bar"
    if hk.hold_to_talk:
        return f"Let go or tap {key} to finish · {key} + Esc cancels"
    return f"Tap {key} again to finish · Hold {key} + Esc to cancel"


class Overlay:
    """ui.Overlay for the Mac: same states (hidden / recording / busy + flash + meeting layer)."""

    def __init__(self, root=None, level_fn=lambda: 0.0, hint: str | None = None):
        self.level_fn = level_fn
        self.panel = _panel(W, H, clickable=False)
        self.view = PillView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        self.panel.setContentView_(self.view)
        self.mode = "hidden"
        self._t0 = 0.0
        self._flash_until = 0.0
        self._flash_msg = ""
        self.w, self.h = W, H
        self.meeting: dict | None = None
        self._drawn = None
        self.visible = False
        self.cancel_hint = hint or "Tap ⌘ again to finish · Hold ⌘ + Esc to cancel"  # cancel_hint() below

    # drawing primitives
    def _size(self, w: int, h: int) -> None:
        if (w, h) != (self.w, self.h):
            self.w, self.h = w, h
            self.panel.setContentSize_((w, h))
            self.view.setFrame_(NSMakeRect(0, 0, w, h))

    def _set(self, spec: dict) -> None:
        self.view.spec = spec
        self.view.setNeedsDisplay_(True)

    def _place_and_show(self) -> None:
        x, y = _bottom_center(self.w, self.h)
        self.panel.setFrameOrigin_((x, y))
        self.panel.orderFrontRegardless()  # shown without activating Ecoscribe
        self.visible = True

    def _hide(self) -> None:
        self.panel.orderOut_(None)
        self.visible = False

    def _pill(self, dot: str, label: str, bars=None) -> None:
        tw = NSString.stringWithString_(label).sizeWithAttributes_({NSFontAttributeName: font(13)}).width
        w = W if dot else max(W, int(tw) + 2 * 24)  # a flash grows to fit its words
        self._size(w, H)
        self._drawn = None
        texts = [(label, 40 if dot else 0, H / 2, 13, False, P.PAPER, not dot)]
        self._set({"w": w, "h": H, "dot": dot, "texts": texts, "bars": bars or []})

    def _meeting_pill(self, view: dict) -> None:
        key = (view["label"], view["line"], view["busy"])
        if key == self._drawn:
            return
        self._size(MW, MH)
        dot = P.AEGEAN_SOFT if view["busy"] else P.TILE
        if view["line"]:
            texts = [(view["label"], 42, 18, 12, True, P.PAPER, False), (view["line"], 42, 38, 12, False, P.LINE, False)]
        else:
            texts = [(view["label"], 42, MH / 2, 13, False, P.PAPER, False)]
        self._set({"w": MW, "h": MH, "dot": dot, "dot_x": 18, "texts": texts})
        self._place_and_show()
        self._drawn = key

    def _recording_pill(self, label: str, lvl: float) -> None:
        """Two lines while dictating: the timer, and how to cancel."""
        hint = self.cancel_hint
        tw = max(NSString.stringWithString_(t).sizeWithAttributes_({NSFontAttributeName: font(12)}).width
                 for t in (label, hint))
        w = max(W, int(tw * 1.06) + 42 + 80)  # bold label is wider; room for the level bars
        self._size(w, MH)
        self._drawn = None
        bars = []
        for i in range(5):
            hgt = 6 + i * 3
            bars.append((w - 62 + i * 9, MH / 2 - hgt / 2, MH / 2 + hgt / 2, lvl > (i + 0.5) / 5))
        texts = [(label, 42, 18, 12, True, P.PAPER, False), (hint, 42, 38, 12, False, P.LINE, False)]
        self._set({"w": w, "h": MH, "dot": P.TILE, "dot_x": 18, "texts": texts, "bars": bars})

    # the ui.Overlay API
    def _show_layer(self) -> None:
        if meetui.pill_layer(self.mode, self.meeting) == "meeting":
            self._meeting_pill(self.meeting)
        else:
            self._drawn = None
            self._hide()

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
        now = time.monotonic()
        if self.mode == "recording":
            secs = int(now - self._t0)
            lvl = min(1.0, math.sqrt(self.level_fn()) * 4)
            self._recording_pill(f"Dictating {secs // 60}:{secs % 60:02d}", lvl)
        elif self.mode == "hidden" and self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self._show_layer()
        elif self.mode == "busy" and self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self.busy()


# ---------------------------------------------------------------------------------------------------------------
class _Target(NSObject):
    """Turns AppKit target/action into a Python call."""

    def initWithFn_(self, fn):
        self = objc.super(_Target, self).init()
        if self is not None:
            self.fn = fn
        return self

    def fire_(self, sender):
        try:
            self.fn()
        except Exception:
            log.exception("ui action failed")


def _label(text: str, size: float, bold: bool, col: str):
    t = NSTextField.labelWithString_(text)
    t.setFont_(font(size, bold))
    t.setTextColor_(color(col))
    t.sizeToFit()
    return t


class PromptWindow:
    """ui.PromptWindow for the Mac (same placement rules, countdown and answers)."""

    PAD = 16

    def __init__(self, root, on_answer):
        self.root, self.on_answer = root, on_answer
        self.prompt: meetui.Prompt | None = None
        self.panel = None
        self._later: list[meetui.Prompt] = []
        self._btns: dict = {}
        self._targets: list = []
        self.lang_menu = None

    def show(self, prompt: meetui.Prompt) -> None:
        if meetui.placement(self.prompt, prompt) == "queue":
            self._later.append(prompt)
            return
        self._close()
        self.prompt = prompt
        title = _label(prompt.title, 13, True, P.INK)
        rows = [title]
        self.lang_menu = None
        if prompt.kind == "start":
            q = _label(prompt.question, 12, False, P.INK)
            pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 110, 24), False)
            for _, name in meetui.LANGS:
                pop.addItemWithTitle_(name)
            pop.selectItemWithTitle_(dict(meetui.LANGS).get(prompt.lang or "sv", "Swedish"))
            self.lang_menu = pop
            rows.append((q, pop))
        elif prompt.question:
            rows.append(_label(prompt.question, 12, False, P.INK_SOFT))
        self._btns, self._targets = {}, []
        buttons = []
        for i, (label, choice) in enumerate(prompt.buttons):
            b = NSButton.buttonWithTitle_target_action_(prompt.button_text(choice, time.monotonic()), None, None)
            t = _Target.alloc().initWithFn_(lambda c=choice: self._answer(c))
            b.setTarget_(t)
            b.setAction_("fire:")
            if i == 0:
                b.setKeyEquivalent_("")
                b.setBezelColor_(color(P.AEGEAN))
            self._targets.append(t)
            self._btns[choice] = b
            buttons.append(b)
        # layout (flipped coordinates computed by hand: AppKit's origin is bottom-left)
        width = max(320, title.frame().size.width + 2 * self.PAD)
        if prompt.kind == "start":
            q, pop = rows[1]
            width = max(width, q.frame().size.width + 120 + 2 * self.PAD)
        for b in buttons:
            b.sizeToFit()
        bh = buttons[0].frame().size.height
        height = self.PAD + title.frame().size.height + 8 + (26 if len(rows) > 1 else 0) + 12 + bh + self.PAD
        panel = _panel(int(width), int(height), clickable=True)
        content = _Box.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        panel.setContentView_(content)
        y = height - self.PAD - title.frame().size.height
        title.setFrameOrigin_((self.PAD, y))
        content.addSubview_(title)
        if len(rows) > 1:
            y -= 8 + 24
            if prompt.kind == "start":
                q, pop = rows[1]
                q.setFrameOrigin_((self.PAD, y + 3))
                pop.setFrameOrigin_((self.PAD + q.frame().size.width + 6, y))
                content.addSubview_(q)
                content.addSubview_(pop)
            else:
                rows[1].setFrameOrigin_((self.PAD, y + 3))
                content.addSubview_(rows[1])
        x = width - self.PAD
        for b in reversed(buttons):
            x -= b.frame().size.width
            b.setFrameOrigin_((x, self.PAD))
            content.addSubview_(b)
            x -= 8
        px, py = _bottom_center(int(width), int(height), lift=MH + 12)
        panel.setFrameOrigin_((px, py))
        panel.orderFrontRegardless()
        self.panel = panel

    def _lang_code(self) -> str:
        names = {n: c for c, n in meetui.LANGS}
        return names.get(str(self.lang_menu.titleOfSelectedItem()) if self.lang_menu else "", "sv")

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
        if self.panel is not None:
            self.panel.orderOut_(None)
        self.panel, self.prompt = None, None

    def hide(self) -> None:
        self._close()
        if self._later:
            nxt = self._later.pop(0)
            nxt.opened_at = time.monotonic()
            self.show(nxt)

    def tick(self) -> None:
        if self.prompt is not None:
            now = time.monotonic()
            what = self.prompt.expired(now)
            if what is not None:
                self._answer(what)
                return
            for choice, b in self._btns.items():
                text = self.prompt.button_text(choice, now)
                if str(b.title()) != text:
                    b.setTitle_(text)


class _Box(NSView):
    """The prompt's card: paper background, ink hairline, rounded."""

    def drawRect_(self, rect):
        b = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, 10, 10)
        color(P.PAPER).setFill()
        path.fill()
        color(P.LINE).setStroke()
        path.setLineWidth_(1)
        path.stroke()


# ---------------------------------------------------------------------------------------------------------------
def _nsimage(pil_img, template: bool = False, size: int = 18):
    import io
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    img = NSImage.alloc().initWithData_(data)
    img.setSize_((size, size))
    img.setTemplate_(template)
    return img


def menu_icon(state: str):
    """Idle: a template mic (follows the light/dark menu bar, like every Mac menu bar icon). Recording /
    busy: the coloured disc, so a running dictation or meeting is visible at a glance, like on Windows."""
    from ...icon import tray_image
    if state == "idle":
        return _nsimage(_template_mic(), template=True)
    return _nsimage(tray_image(state))


def _template_mic():
    """Black mic glyph on transparent (the circle's mic, without the disc)."""
    from ...icon import mic_image
    img = mic_image(64, bg=P.INK, fg=P.PAPER, shape="circle").convert("RGBA")
    px = img.load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            r, g, b, a = px[x, y]
            light = (r + g + b) / 3 > 160  # the paper-coloured glyph
            px[x, y] = (0, 0, 0, a if light else 0)
    return img


class _MenuDelegate(NSObject):
    def initWithBuild_(self, build):
        self = objc.super(_MenuDelegate, self).init()
        if self is not None:
            self.build = build
        return self

    def menuNeedsUpdate_(self, menu):
        try:
            self.build(menu)
        except Exception:
            log.exception("menu build failed")


class Tray:
    """ui.Tray for the Mac: an NSStatusItem with the same items, rebuilt each time the menu opens."""

    def __init__(self, app_ref, log_path: Path, on_quit, open_window=None, meeting_label=None, on_meeting=None,
                 open_meetings=None, meeting_state=None, last_lang=None, start_meeting=None,
                 dict_langs=None, dict_lang=None, set_dict_lang=None):
        self.a = dict(app_ref=app_ref, log_path=log_path, on_quit=on_quit, open_window=open_window,
                      meeting_label=meeting_label, on_meeting=on_meeting, open_meetings=open_meetings,
                      meeting_state=meeting_state, last_lang=last_lang, start_meeting=start_meeting,
                      dict_langs=dict_langs, dict_lang=dict_lang, set_dict_lang=set_dict_lang)
        self._images = {s: menu_icon(s) for s in ("idle", "recording", "busy")}
        self._targets: list = []
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.item.button().setImage_(self._images["idle"])
        self.item.button().setToolTip_("Ecoscribe")
        self.menu = NSMenu.alloc().init()
        self.menu.setAutoenablesItems_(False)
        self._delegate = _MenuDelegate.alloc().initWithBuild_(self._build)
        self.menu.setDelegate_(self._delegate)
        self.item.setMenu_(self.menu)
        self._build(self.menu)

    def entries(self) -> list:
        """The menu as data: (title, action | None, checked, submenu entries | None); None = separator.
        Same items and order as the Windows tray (ui.Tray)."""
        a = self.a
        out = [("Open Ecoscribe", a["open_window"], False, None), None]
        if a["dict_langs"] and a["dict_lang"] and a["set_dict_lang"]:
            cur = a["dict_lang"]()
            out.append(("Dictation language", None, False,
                        [(n, (lambda c=c: a["set_dict_lang"](c)), cur == c, None) for c, n in a["dict_langs"]]))
        if a["meeting_label"] and a["on_meeting"] and a["meeting_state"] and a["start_meeting"]:
            if meetui.tray_recording(a["meeting_state"]()):
                out.append((a["meeting_label"](), a["on_meeting"], False, None))
            else:
                last = a["last_lang"]() if a["last_lang"] else "sv"
                out.append(("Transcribe meeting now", None, False,
                            [(n, (lambda c=c: a["start_meeting"](c)), checked, None)
                             for c, n, checked in meetui.tray_lang_items(last)]))
            out.append(("Open Meetings", a["open_meetings"], False, None))
            out.append(None)
        out += [("Copy last", lambda: a["app_ref"]().copy_last(), False, None),
                ("Cancel recording", lambda: a["app_ref"]().on_action("cancel"), False, None),
                ("Open log", lambda: _open(a["log_path"]), False, None),
                ("Quit Ecoscribe", a["on_quit"], False, None)]
        return out

    def _fill(self, menu, entries) -> None:
        menu.removeAllItems()
        for e in entries:
            if e is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            title, fn, checked, sub = e
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            if sub is not None:
                m = NSMenu.alloc().init()
                self._fill(m, sub)
                item.setSubmenu_(m)
            elif fn is not None:
                t = _Target.alloc().initWithFn_(fn)
                self._targets.append(t)
                item.setTarget_(t)
                item.setAction_("fire:")
            item.setState_(1 if checked else 0)
            menu.addItem_(item)

    def _build(self, menu) -> None:
        self._targets = []
        self._fill(menu, self.entries())

    def set_state(self, state: str) -> None:
        img = self._images.get(state, self._images["idle"])
        on_main(self.item.button().setImage_, img)

    def refresh(self) -> None:
        pass  # rebuilt every time it opens

    def stop(self) -> None:
        try:
            NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        except Exception:
            pass


def _open(path) -> None:
    import subprocess
    subprocess.Popen(["open", str(path)])


# ---------------------------------------------------------------------------------------------------------------
class Sounds:
    def __init__(self, folder: Path, enabled: bool = True):
        from ...ui import _tone
        self.enabled = enabled
        self.files = {}
        self._snd = {}
        folder.mkdir(parents=True, exist_ok=True)
        for name, (f0, f1, ms) in {"start": (660, 880, 70), "stop": (880, 660, 70),
                                   "cancel": (440, 440, 120), "error": (330, 220, 160)}.items():
            p = folder / f"{name}.wav"
            if not p.exists():
                _tone(p, f0, f1, ms)
            self.files[name] = p

    def play(self, name: str) -> None:
        if not self.enabled or name not in self.files:
            return
        on_main(self._play, name)

    def _play(self, name: str) -> None:
        s = self._snd.get(name)
        if s is None:
            s = self._snd[name] = NSSound.alloc().initWithContentsOfFile_byReference_(str(self.files[name]), True)
        s.stop()
        s.play()


def snapshot(view, path: Path) -> None:
    """PNG of a view as drawn, without putting anything on screen (design checks; no permission needed)."""
    rep = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
    view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), rep)
    from AppKit import NSBitmapImageFileTypePNG
    rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(str(path), True)
