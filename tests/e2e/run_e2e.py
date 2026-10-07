"""End-to-end test of Ecoscribe on the real Windows desktop.

Starts the real app in --test mode (accepts injected keys, wav files instead of
the mic), drives it with SendInput exactly like a person would (Right Ctrl taps,
navigation keys, window switches) and checks where the text lands.

Safety: refuses to start unless the PC has been idle >= 45 s, and aborts the
moment any REAL (non-injected) keyboard or mouse input arrives, exit code 3.

Run on Windows Python:  python run_e2e.py [--only basic,navigate] [--keep-tmp]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes as w
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
sys.path.insert(0, str(APP))

import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402

from ecoscribe.deliver import get_clipboard_text, set_clipboard_text  # noqa: E402
from ecoscribe.sendkeys import send_keys, send_wheel  # noqa: E402
from ecoscribe.win32types import (HOOKPROC, KBDLLHOOKSTRUCT, LLKHF_INJECTED, LLMHF_INJECTED,  # noqa: E402
                                MSLLHOOKSTRUCT, WH_KEYBOARD_LL, WH_MOUSE_LL, kernel32, user32)
from tests.winhelp import Target, focus  # noqa: E402

FIX = APP / "tests" / "fixtures"
R, LCTRL, SHIFT, ESC, TAB, C = 0xA3, 0xA2, 0x10, 0x1B, 0x09, 0x43
EXPECTED = {
    "en_fox.wav": "The quick brown fox jumps over the lazy dog, then runs back to the barn.",
    "en_long.wav": "I would like to schedule the climbing session for Thursday evening, "
                   "and please remind me to bring the new shoes and the chalk bag.",
    "es_climb.wav": "Mañana por la mañana voy a escalar con mis amigos en Gotemburgo.",
    "silence_3s.wav": "",
}
CLIP_S = {"en_fox.wav": 4.8, "en_long.wav": 9.0, "es_climb.wav": 4.2, "silence_3s.wav": 3.0}


class UserActive(Exception):
    pass


# ---------------------------------------------------------------- safety guard
class Guard(threading.Thread):
    """Flags any physical input. Injected events (ours) are ignored."""

    def __init__(self):
        super().__init__(daemon=True)
        self.tripped = threading.Event()
        self.what = ""
        self._kb = HOOKPROC(self._on_kb)
        self._ms = HOOKPROC(self._on_ms)

    def _on_kb(self, code, wp, lp):
        if code >= 0:
            k = ctypes.cast(lp, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (k.flags & LLKHF_INJECTED):
                self.what = f"key vk={k.vkCode:#x}"
                self.tripped.set()
        return user32.CallNextHookEx(None, code, wp, lp)

    def _on_ms(self, code, wp, lp):
        if code >= 0:
            m = ctypes.cast(lp, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (m.flags & LLMHF_INJECTED):
                self.what = f"mouse msg={wp:#x}"
                self.tripped.set()
        return user32.CallNextHookEx(None, code, wp, lp)

    def run(self):
        h = kernel32.GetModuleHandleW(None)
        self.hooks = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb, h, 0),
                      user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms, h, 0)]
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass

    def check(self):
        if self.tripped.is_set():
            raise UserActive(self.what)


GUARD = Guard()


def sleep(s: float):
    end = time.monotonic() + s
    while time.monotonic() < end:
        GUARD.check()
        time.sleep(min(0.05, max(0, end - time.monotonic())))
    GUARD.check()


def idle_seconds() -> float:
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LII(8, 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000


def release_all():
    send_keys([(R, False), (LCTRL, False), (SHIFT, False), (0x11, False), (0x12, False)])


# ---------------------------------------------------------------- app control
DATA = Path(os.environ["LOCALAPPDATA"]) / "ecoscribe"


class AppUnderTest:
    def __init__(self, tmp: Path, exe: str | None = None, extra_cfg: str = ""):
        self.tmp = tmp
        self.log = tmp / "e2e.log"
        for f in FIX.glob("*.wav"):
            shutil.copy(f, tmp / f.name)
        (tmp / "next_clip.txt").write_text("en_fox.wav")
        (tmp / "config.toml").write_text("[limits]\nhook_reinstall_s = 2.0\n" + extra_cfg, encoding="utf-8")
        args = ["--test", "--test-audio", str(tmp), "--log", str(self.log), "--config", str(tmp / "config.toml"), "--no-sounds"]
        if exe:
            self.proc = subprocess.Popen([exe, *args])
        else:
            code = ("import sys; sys.path.insert(0, r'%s'); from ecoscribe.__main__ import main; sys.exit(main(%r))"
                    % (APP, args))
            self.proc = subprocess.Popen([sys.executable, "-c", code])
        end = time.monotonic() + 600
        while time.monotonic() < end:
            if re.search(r"ready (on_demand )?model=", self.text()):
                return
            if self.proc.poll() is not None:
                raise RuntimeError(f"app exited early: {self.text()[-2000:]}")
            time.sleep(0.2)
        raise RuntimeError("app never became ready")

    def text(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def deliveries(self) -> list[dict]:
        out = []
        for m in re.finditer(r"delivered chars=(\d+) lang=(\w+) audio_s=([\d.]+) transcribe_ms=(\d+) "
                             r"stop_to_paste_ms=(\d+) target=(\S*) pasted=(\w+)", self.text()):
            out.append({"chars": int(m[1]), "lang": m[2], "audio_s": float(m[3]), "transcribe_ms": int(m[4]),
                        "stop_to_paste_ms": int(m[5]), "target": m[6], "pasted": m[7] == "True"})
        return out

    def count(self, needle: str) -> int:
        return self.text().count(needle)

    def windows(self) -> list[int]:
        found = []

        def cb(h, _):
            if win32process.GetWindowThreadProcessId(h)[1] == self.proc.pid and win32gui.IsWindowVisible(h):
                found.append(h)
            return True
        win32gui.EnumWindows(cb, None)
        return found

    def status(self) -> dict:
        try:
            return json.loads((DATA / "status-test.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def stop(self):
        try:
            self.proc.kill()
            self.proc.wait(10)
        except Exception:
            pass
        pid = self.status().get("pid")  # after a restart the live process is a different one
        if pid and pid_alive(pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def pid_alive(pid) -> bool:
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259


def words(s):
    return re.findall(r"\w+", s.lower())


def recall(got: str, want: str) -> float:
    g = set(words(got))
    ww = words(want)
    return sum(x in g for x in ww) / len(ww) if ww else (1.0 if not words(got) else 0.0)


def tap():
    assert send_keys([(R, True), (R, False)]) == 2
    time.sleep(0.03)


def use_clip(app: AppUnderTest, clip: str):
    (app.tmp / "next_clip.txt").write_text(clip)


def record(app: AppUnderTest, clip: str, during=None):
    """One full dictation cycle; `during` runs while 'speaking'."""
    use_clip(app, clip)
    tap()
    t0 = time.monotonic()
    if during:
        during()
    sleep(max(0, CLIP_S[clip] + 0.4 - (time.monotonic() - t0)))
    tap()


# ---------------------------------------------------------------- scenarios
def sc_basic(app, A, B):
    assert A.focus(), "could not focus A"
    before, n = A.text(), len(app.deliveries())
    record(app, "en_fox.wav")
    got = A.wait_text(lambda t: recall(t[len(before):], EXPECTED["en_fox.wav"]) >= 0.85, 4)[len(before):]
    d = app.deliveries()[n:]
    assert len(d) == 1, f"deliveries={d}"
    assert recall(got, EXPECTED["en_fox.wav"]) >= 0.85, f"A got {got!r}"
    return d[0]["stop_to_paste_ms"]


def sc_navigate(app, A, B):
    assert A.focus()
    a0, b0, n = A.text(), B.text(), len(app.deliveries())

    def spam():
        sleep(0.5)
        send_keys([(0x11, True), (TAB, True), (TAB, False), (0x11, False)])            # Ctrl+Tab
        sleep(0.3)
        send_keys([(0x11, True), (C, True), (C, False), (0x11, False)])                # Ctrl+C
        sleep(0.3)
        send_keys([(ESC, True), (ESC, False)])                                         # Esc
        sleep(0.3)
        send_keys([(LCTRL, True), (LCTRL, False)])                                     # lone left ctrl
        sleep(0.3)
        send_keys([(R, True), (C, True), (C, False), (R, False)])                     # RCtrl+C combo
        sleep(0.3)
        send_wheel(-120)                                                               # scroll
        sleep(0.3)
        assert B.focus(), "could not focus B mid-recording"                           # switch window
        assert "recording started" in app.text()
    record(app, "en_long.wav", during=spam)
    got_b = B.wait_text(lambda t: recall(t[len(b0):], EXPECTED["en_long.wav"]) >= 0.85, 4)[len(b0):]
    d = app.deliveries()[n:]
    assert len(d) == 1, f"expected exactly 1 delivery, got {d}"
    assert recall(got_b, EXPECTED["en_long.wav"]) >= 0.85, f"B got {got_b!r}"
    assert A.text() == a0, f"A changed: {A.text()[len(a0):]!r}"
    return d[0]["stop_to_paste_ms"]


def sc_overlay_no_focus(app, A, B):
    assert A.focus()
    use_clip(app, "en_fox.wav")
    n = len(app.deliveries())
    tap()
    sleep(0.6)
    fg = win32gui.GetForegroundWindow()
    vis = app.windows()
    styles = {h: user32.GetWindowLongW(h, -20) if hasattr(user32, "GetWindowLongW") else 0 for h in vis}
    sleep(CLIP_S["en_fox.wav"] + 0.4 - 0.6)
    tap()
    A.wait_text(lambda t: len(app.deliveries()) > n, 4)
    assert fg == A.hwnd, f"foreground moved to {win32gui.GetWindowText(fg)!r}"
    assert vis, "overlay not visible while recording"
    for h, ex in styles.items():
        assert ex & 0x08000000 and ex & 0x20, f"overlay {h} ex={ex:#x} lacks NOACTIVATE/TRANSPARENT"
    return None


def sc_modifier_held(app, A, B):
    assert A.focus()
    before, n = A.text(), len(app.deliveries())
    use_clip(app, "en_fox.wav")
    tap()
    sleep(CLIP_S["en_fox.wav"] + 0.4)
    tap()
    send_keys([(SHIFT, True)])
    sleep(0.6)
    send_keys([(SHIFT, False)])
    got = A.wait_text(lambda t: len(app.deliveries()) > n and recall(t[len(before):], EXPECTED["en_fox.wav"]) >= 0.85, 4)
    got = got[len(before):]
    assert recall(got, EXPECTED["en_fox.wav"]) >= 0.85, f"A got {got!r}"
    assert len(app.deliveries()) == n + 1
    return app.deliveries()[-1]["stop_to_paste_ms"]


def sc_clipboard_restore(app, A, B):
    set_clipboard_text("SENTINEL-E2E", private=False)
    ms = sc_basic(app, A, B)
    sleep(1.5)
    got = get_clipboard_text()
    assert got == "SENTINEL-E2E", f"clipboard is {got!r}"
    return ms


def sc_cancel(app, A, B):
    assert A.focus()
    before, n, c = A.text(), len(app.deliveries()), app.count("recording cancelled")
    use_clip(app, "en_fox.wav")
    tap()
    sleep(1.5)
    send_keys([(R, True)]); sleep(0.05)
    send_keys([(ESC, True), (ESC, False)]); sleep(0.05)
    send_keys([(R, False)])
    sleep(4)
    assert app.count("recording cancelled") == c + 1, "cancel not logged"
    assert len(app.deliveries()) == n and A.text() == before, "cancelled recording was delivered"
    return sc_basic(app, A, B)  # and the app still works afterwards


def sc_silence(app, A, B):
    assert A.focus()
    before, n = A.text(), len(app.deliveries())
    record(app, "silence_3s.wav")
    sleep(3)
    assert len(app.deliveries()) == n and A.text() == before, f"silence produced {A.text()[len(before):]!r}"
    return None


def sc_spanish(app, A, B):
    assert A.focus()
    before, n = A.text(), len(app.deliveries())
    record(app, "es_climb.wav")
    got = A.wait_text(lambda t: recall(t[len(before):], EXPECTED["es_climb.wav"]) >= 0.85, 4)[len(before):]
    d = app.deliveries()[n:]
    assert len(d) == 1 and d[0]["lang"] == "es", f"deliveries={d}"
    assert recall(got, EXPECTED["es_climb.wav"]) >= 0.85, f"A got {got!r}"
    return d[0]["stop_to_paste_ms"]


def sc_back_to_back(app, A, B):
    assert A.focus()
    before, n = A.text(), len(app.deliveries())
    record(app, "en_fox.wav")
    sleep(0.2)
    record(app, "en_long.wav")
    want = EXPECTED["en_fox.wav"] + " " + EXPECTED["en_long.wav"]
    got = A.wait_text(lambda t: len(app.deliveries()) >= n + 2 and recall(t[len(before):], want) >= 0.85, 5)
    got = got[len(before):]
    assert len(app.deliveries()) == n + 2, f"deliveries={app.deliveries()[n:]}"
    i_en, i_es = got.lower().find("quick brown"), got.lower().find("climbing session")
    assert 0 <= i_en < i_es, f"order wrong: A={got!r} B_tail={B.text()[-120:]!r} fg={win32gui.GetWindowText(win32gui.GetForegroundWindow())!r}"
    return app.deliveries()[-1]["stop_to_paste_ms"]


def sc_hook_reinstall(app, A, B):
    n0 = len(re.findall(r"hook reinstall n=", app.text()))
    sleep(6.5)
    n1 = len(re.findall(r"hook reinstall n=", app.text()))
    assert n1 - n0 >= 3, f"only {n1 - n0} reinstalls in 6.5 s"
    return sc_basic(app, A, B)


def _terminal_windows() -> set[int]:
    found = set()

    def cb(h, _):
        if win32gui.GetClassName(h) == "CASCADIA_HOSTING_WINDOW_CLASS":
            found.add(h)
        return True
    win32gui.EnumWindows(cb, None)
    return found


def sc_terminal(app, A, B):
    # Capture goes to a Windows path: WSL /tmp is not reliably the one \\wsl.localhost shows.
    out_w = Path(tempfile.gettempdir()) / "ecoscribe_e2e_wt.txt"
    drive, rest = str(out_w)[0].lower(), str(out_w)[2:].replace("\\", "/")
    out_l = f"/mnt/{drive}{rest}"
    try:
        out_w.unlink()
    except FileNotFoundError:
        pass
    before = _terminal_windows()
    subprocess.Popen(["wt.exe", "-w", "new", "wsl.exe", "-d", "Ubuntu", "--", "bash", "-c",
                      f"stty -icanon -echo && exec cat > '{out_l}'"])  # wt.exe splits commands on ";"
    hwnd = 0
    end = time.monotonic() + 20
    while time.monotonic() < end and not hwnd:
        new = _terminal_windows() - before
        hwnd = next(iter(new), 0)
        sleep(0.2)
    assert hwnd, "terminal window did not appear"
    try:
        end = time.monotonic() + 15
        while time.monotonic() < end and not out_w.exists():
            sleep(0.2)
        assert out_w.exists(), "cat in the terminal never started"
        sleep(0.5)
        assert focus(hwnd), "could not focus terminal"
        n = len(app.deliveries())
        record(app, "en_fox.wav")
        end = time.monotonic() + 5
        got = ""
        while time.monotonic() < end:
            got = out_w.read_text(encoding="utf-8", errors="replace")
            if recall(got, EXPECTED["en_fox.wav"]) >= 0.85:
                break
            sleep(0.2)
        d = app.deliveries()[n:]
        assert d and "windowsterminal" in d[0]["target"].lower(), f"deliveries={d}"
        assert recall(got, EXPECTED["en_fox.wav"]) >= 0.85, f"terminal got {got!r}"
        return d[0]["stop_to_paste_ms"]
    finally:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


# both "ready model=" (model kept loaded) and "ready on_demand model=" (1.2+, the default)
READY = " ecoscribe: ready "


def sc_settings_restart(app, A, B):
    """Saving settings restarts the engine: new pid, one instance, no window, still dictates."""
    import win32event
    assert A.focus()
    fg_before = win32gui.GetForegroundWindow()
    old = app.status().get("pid")
    assert old and pid_alive(old), f"no live test instance in status: {app.status()}"
    n_ready = app.count(READY)
    with open(app.tmp / "config.toml", "a", encoding="utf-8") as f:
        f.write("\n[whisper]\nbeam_size = 4\n")
    h = win32event.OpenEvent(0x0002, False, "Local\\EcoscribeReload-test")  # EVENT_MODIFY_STATE
    win32event.SetEvent(h)
    end = time.monotonic() + 60
    while time.monotonic() < end and app.count(READY) <= n_ready:
        sleep(0.25)
    assert app.count(READY) > n_ready, "engine did not come back after reload"
    new = app.status().get("pid")
    assert new and new != old and pid_alive(new), f"pid old={old} new={new}"
    assert not pid_alive(old), "old instance still running: two engines"
    assert win32gui.GetForegroundWindow() == fg_before, "a window took focus during the restart"
    assert win32gui.FindWindow(None, "Ecoscribe") == 0, "the Ecoscribe window opened on its own"
    return sc_basic(app, A, B)


def _engine_workers(app):
    import psutil
    return [c for c in psutil.Process(app.proc.pid).children(recursive=True)
            if "--engine-worker" in " ".join(c.cmdline())]


def sc_on_demand_idle(app, A, B):
    """Criterion 0c: dictation works from cold, the worker leaves after idle, the app stays small."""
    import psutil
    ms = sc_basic(app, A, B)
    assert _engine_workers(app), "no engine worker after a dictation"
    end = time.monotonic() + 90  # idle_exit_s 20 + idle check every 30 s
    while _engine_workers(app) and time.monotonic() < end:
        GUARD.check()
        sleep(2)
    assert not _engine_workers(app), "engine worker still running after idle_exit_s"
    rss_mb = psutil.Process(app.proc.pid).memory_info().rss / 2**20
    print(f"on_demand idle: app rss={rss_mb:.0f} MB")
    assert rss_mb < 150, f"resident app {rss_mb:.0f} MB"
    return max(ms, sc_basic(app, A, B))  # and it comes back for the next tap


def sc_hold(app, A, B):
    """t0u.28 (run with --hold): hold Right Ctrl while talking, let go: the text lands."""
    assert A.focus()
    before, n = A.text(), len(app.deliveries())
    use_clip(app, "en_fox.wav")
    assert send_keys([(R, True)]) == 1
    sleep(CLIP_S["en_fox.wav"] + 0.4)
    assert send_keys([(R, False)]) == 1
    got = A.wait_text(lambda t: recall(t[len(before):], EXPECTED["en_fox.wav"]) >= 0.85, 4)[len(before):]
    d = app.deliveries()[n:]
    assert len(d) == 1 and recall(got, EXPECTED["en_fox.wav"]) >= 0.85, f"deliveries={d} A got {got!r}"
    return d[0]["stop_to_paste_ms"]


def sc_hold_shortcut(app, A, B):
    """t0u.28: Right Ctrl+C in hold mode is a shortcut: no recording announced, nothing delivered."""
    assert A.focus()
    a0, n, dropped = A.text(), len(app.deliveries()), app.text().count("quiet start dropped")
    send_keys([(R, True), (C, True), (C, False), (R, False)])
    sleep(2.0)
    assert len(app.deliveries()) == n and A.text() == a0, "a shortcut produced text"
    assert app.text().count("quiet start dropped") == dropped + 1, "the quiet start was not dropped"
    return None


def sc_screen_names(app, A, B):
    """t0u.27: the tap reads the focused window through UI Automation, in the real (frozen) app."""
    ms = sc_basic(app, A, B)
    lines = re.findall(r"screen names n=(\d+) ms=(\d+)", app.text())
    assert lines, "no screen names read logged"
    assert "screen names failed" not in app.text(), "UI Automation failed"
    print(f"screen names: last read n={lines[-1][0]} in {lines[-1][1]} ms")
    return ms


SCENARIOS = [
    ("basic", sc_basic), ("navigate", sc_navigate), ("overlay_no_focus", sc_overlay_no_focus),
    ("modifier_held", sc_modifier_held), ("clipboard_restore", sc_clipboard_restore), ("cancel", sc_cancel),
    ("silence", sc_silence), ("back_to_back", sc_back_to_back),
    ("hook_reinstall", sc_hook_reinstall), ("terminal", sc_terminal),
    ("settings_restart", sc_settings_restart), ("on_demand_idle", sc_on_demand_idle),
    ("screen_names", sc_screen_names), ("hold", sc_hold), ("hold_shortcut", sc_hold_shortcut),
]
HOLD_ONLY = {"hold", "hold_shortcut"}
HOLD_CFG = "[hotkey]\nhold_to_talk = true\n"
ON_DEMAND_CFG = "[whisper]\non_demand = true\nidle_exit_s = 20.0\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--keep-tmp", action="store_true")
    ap.add_argument("--exe", default=None, help="test this Ecoscribe.exe instead of the source tree")
    ap.add_argument("--wait-idle", type=float, default=300, help="max seconds to wait for 45 s of idle")
    ap.add_argument("--on-demand", action="store_true", help="run with [whisper] on_demand = true")
    ap.add_argument("--hold", action="store_true", help="run with [hotkey] hold_to_talk = true (t0u.28)")
    args = ap.parse_args()
    only = set(filter(None, args.only.split(",")))
    if args.on_demand and not only:
        only = {"basic", "back_to_back", "on_demand_idle"}
    if args.hold and not only:
        only = {"basic", "navigate", "cancel", "hold", "hold_shortcut"}  # taps still work next to holds
    if not args.on_demand:
        only = (only or {n for n, _ in SCENARIOS}) - {"on_demand_idle"}
    if not args.hold:
        only -= HOLD_ONLY

    end = time.monotonic() + args.wait_idle
    while idle_seconds() < 45:
        if time.monotonic() > end:
            print("PC is in use (not idle for 45 s); not running.")
            return 3
        time.sleep(2)

    user32.GetWindowLongW.argtypes = (w.HWND, ctypes.c_int)
    user32.GetWindowLongW.restype = ctypes.c_long
    GUARD.start()
    time.sleep(0.3)
    tmp = Path(tempfile.mkdtemp(prefix="ecoscribe-e2e-"))
    results, app, A, B = [], None, None, None
    code = 0
    try:
        app = AppUnderTest(tmp, args.exe, (ON_DEMAND_CFG if args.on_demand else "") + (HOLD_CFG if args.hold else ""))
        GUARD.check()
        A = Target("EcoscribeTargetA", 80, 120)
        B = Target("EcoscribeTargetB", 700, 120)
        for name, fn in SCENARIOS:
            if only and name not in only:
                continue
            t0 = time.monotonic()
            try:
                ms = fn(app, A, B)
                results.append({"scenario": name, "pass": True, "stop_to_paste_ms": ms})
            except UserActive:
                raise
            except Exception as e:
                results.append({"scenario": name, "pass": False, "error": f"{type(e).__name__}: {e}"})
            finally:
                release_all()
                results[-1]["secs"] = round(time.monotonic() - t0, 1)
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            sleep(0.8)
    except UserActive as e:
        print(f"ABORTED: real input detected ({e}). someone is using the PC.")
        code = 3
    finally:
        release_all()
        for t in (A, B):
            if t:
                t.close()
        if app:
            app.stop()
            shutil.copy(app.log, HERE / "last_e2e.log") if app.log.exists() else None
    (HERE / "last_report.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n%-20s %-5s %s" % ("scenario", "pass", "stop->paste ms / error"))
    for r in results:
        print("%-20s %-5s %s" % (r["scenario"], "OK" if r["pass"] else "FAIL",
                                 r.get("stop_to_paste_ms") if r["pass"] else r["error"]))
    if not args.keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    if code:
        return code
    return 0 if results and all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
