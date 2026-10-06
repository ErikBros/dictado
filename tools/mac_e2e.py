"""End-to-end dictation on the real Mac desktop (uat.4/uat.13): the real key tap, the real paste.

Starts a throwaway text window (tests/targets.py) and Dictado in --test mode with a fixture clip as the
mic, taps Right Command with tagged synthetic events, and checks what lands in the window.
Never while the user works: waits for 45 s of idle (HIDIdleTime) and aborts (exit 3) on any real key or
click during the run (a listen-only tap counts events without Dictado's tag).

    .venv/bin/python tools/mac_e2e.py [--scenario basic|navigate|cancel|all]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
PY = sys.executable
FIX = APP / "tests" / "fixtures"
EXPECTED = {"en_fox.wav": "The quick brown fox jumps over the lazy dog, then runs back to the barn.",
            "en_long.wav": "I would like to schedule the climbing session for Thursday evening, and please remind "
                           "me to bring the new shoes and the chalk bag."}
RCMD = 54


def idle_s() -> float:
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0.0


class RealInputGuard(threading.Thread):
    """Listen-only tap: any key/click without Dictado's tag is the user."""

    def __init__(self):
        super().__init__(daemon=True)
        self.tripped = threading.Event()

    def run(self):
        import Quartz as Q
        from dictado.platform.macos.keys import is_ours

        def cb(proxy, etype, ev, ref):
            if etype in (Q.kCGEventKeyDown, Q.kCGEventFlagsChanged, Q.kCGEventLeftMouseDown,
                         Q.kCGEventRightMouseDown) and not is_ours(ev):
                self.tripped.set()
            return ev
        mask = 0
        for et in (Q.kCGEventKeyDown, Q.kCGEventFlagsChanged, Q.kCGEventLeftMouseDown, Q.kCGEventRightMouseDown):
            mask |= Q.CGEventMaskBit(et)
        tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGTailAppendEventTap, Q.kCGEventTapOptionListenOnly,
                                 mask, cb, None)
        if tap is None:
            raise SystemExit("no Input Monitoring permission for this terminal")
        Q.CFRunLoopAddSource(Q.CFRunLoopGetCurrent(), Q.CFMachPortCreateRunLoopSource(None, tap, 0),
                             Q.kCFRunLoopCommonModes)
        Q.CGEventTapEnable(tap, True)
        Q.CFRunLoopRun()


def tap_rcmd():
    from dictado.platform.macos import keys
    import Quartz as Q
    keys._post(RCMD, True, Q.kCGEventFlagMaskCommand | 0x10)
    time.sleep(0.08)
    keys._post(RCMD, False, 0)
    # flagsChanged needs the key event type: post through CGEventCreateKeyboardEvent works for modifiers too


def words(s):
    return re.findall(r"\w+", s.lower())


def recall(got, want):
    g = set(words(got))
    w = words(want)
    return sum(x in g for x in w) / len(w)


class Run:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.data = tmp / "data"
        self.clips = tmp / "clips"
        self.clips.mkdir(parents=True)
        for f in EXPECTED:
            (self.clips / f).write_bytes((FIX / f).read_bytes())
        self.out = tmp / "target.json"
        self.target = subprocess.Popen([PY, str(APP / "tools" / "mac_target.py"), "--out", str(self.out)])
        env = {**__import__("os").environ, "DICTADO_DATA_DIR": str(self.data)}
        self.app = subprocess.Popen([PY, "-m", "dictado", "--test", "--test-audio", str(self.clips), "--no-sounds"],
                                    cwd=str(APP), env=env)
        self.log = self.data / "dictado-test.log"
        end = time.monotonic() + 30
        while time.monotonic() < end and "key tap installed" not in self._log():
            time.sleep(0.2)
        time.sleep(1.0)

    def _log(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def use(self, clip: str):
        (self.clips / "next_clip.txt").write_text(clip, encoding="utf-8")

    def text(self) -> str:
        try:
            return json.loads(self.out.read_text(encoding="utf-8")).get("text", "")
        except (OSError, ValueError):
            return ""

    def stop_to_paste(self) -> list[int]:
        return [int(x) for x in re.findall(r"stop_to_paste_ms=(\d+)", self._log())]

    def stop(self):
        for p in (self.app, self.target):
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


def scenario_basic(r: Run, clip="en_fox.wav") -> dict:
    r.use(clip)
    before = r.text()
    tap_rcmd()
    time.sleep(len((FIX / clip).read_bytes()) / 32000 + 0.6)  # the clip's length at 16 kHz s16
    tap_rcmd()
    end = time.monotonic() + 15
    while time.monotonic() < end and r.text() == before:
        time.sleep(0.1)
    got = r.text()[len(before):]
    return {"clip": clip, "got": got, "recall": round(recall(got, EXPECTED[clip]), 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="basic")
    ap.add_argument("--min-idle", type=float, default=45)
    a = ap.parse_args()
    i = idle_s()
    if i < a.min_idle:
        print(f"Someone is using the Mac (idle {i:.0f} s < {a.min_idle:.0f} s): not running")
        return 3
    guard = RealInputGuard()
    guard.start()
    tmp = Path(tempfile.mkdtemp(prefix="dictado-e2e-"))
    r = Run(tmp)
    results = {}
    try:
        for clip in ("en_fox.wav", "en_long.wav"):
            if guard.tripped.is_set():
                break
            results[clip] = scenario_basic(r, clip)
            time.sleep(1.5)
    finally:
        r.stop()
    results["stop_to_paste_ms"] = r.stop_to_paste()
    results["real_input_during_run"] = guard.tripped.is_set()
    print(json.dumps(results, ensure_ascii=False, indent=1))
    (APP / "spike" / "e2e_mac_last.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    if guard.tripped.is_set():
        return 3
    ok = all(v["recall"] >= 0.85 for k, v in results.items() if k.endswith(".wav"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
