"""End-to-end dictation on the real Mac desktop (uat.4/uat.13): the real key tap, the real paste.

Starts a throwaway text window (tests/targets.py) and Ecoscribe in --test mode with a fixture clip as the
mic, taps Right Command with tagged synthetic events, and checks what lands in the window.
Never while the user works: waits for 45 s of idle (HIDIdleTime) and aborts (exit 3) on any real key or
click during the run (a listen-only tap counts events without Ecoscribe's tag).

    .venv/bin/python tools/mac_e2e.py [--scenario basic|voice|recover|langkey|added|live|nobox|numpad|all]

voice: a clip made with macOS `say` ("... new line ... send it"): a real line break in the middle and
Enter pressed at the end. recover: the app is crashed (SIGSEGV) mid-dictation and started again on
the same data folder: what was said must come back in History as recovered, never pasted.
langkey: Right Command + L twice -> the next dictation's language goes auto -> English -> Spanish, and
no "l" reaches the window.
added: languages added in Settings (German, Finnish: dictado-tjn): clips spoken by `say` in each, the app
restarted with English + German + Finnish ticked; Finnish in the set puts dictation on large-v3.
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
                           "me to bring the new shoes and the chalk bag.",
            "es_climb.wav": "Mañana por la mañana voy a escalar con mis amigos en Gotemburgo."}
RCMD = 54


def idle_s() -> float:
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0.0


class RealInputGuard(threading.Thread):
    """Listen-only tap: any key/click without Ecoscribe's tag is the user."""

    def __init__(self):
        super().__init__(daemon=True)
        self.tripped = threading.Event()

    def run(self):
        import Quartz as Q
        from ecoscribe.platform.macos.keys import is_ours

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
    from ecoscribe.platform.macos import keys
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
        env = {**__import__("os").environ, "ECOSCRIBE_DATA_DIR": str(self.data)}
        self.env = env
        self.data.mkdir(parents=True, exist_ok=True)  # voice commands are a setting (off by default): on here
        (self.data / "config.toml").write_text("[text]\nvoice_commands = true\n[hotkey]\nnumpad_enter = true\n[whisper]\nlanguages = [\"en\", \"es\"]\nextra_languages = [\"es\"]\n", encoding="utf-8")
        self.log = self.data / "ecoscribe-test.log"
        self.start_app()

    def start_app(self):
        seen = self._log().count("key tap installed")
        self.app = subprocess.Popen([PY, "-m", "ecoscribe", "--test", "--test-audio", str(self.clips), "--no-sounds"],
                                    cwd=str(APP), env=self.env)
        end = time.monotonic() + 30
        while time.monotonic() < end and self._log().count("key tap installed") <= seen:
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


SAID = "Hello there. New line. This is a voice command test. Send it."


def make_say_clip(dst: Path, text: str) -> None:
    """A 16 kHz mono 16-bit wav spoken by macOS (no mic, no person needed)."""
    subprocess.run(["say", "-o", str(dst), "--file-format=WAVE", "--data-format=LEI16@16000", text], check=True)


def scenario_voice(r: Run) -> dict:
    make_say_clip(r.clips / "say_voice.wav", SAID)
    r.use("say_voice.wav")
    before = r.text()
    tap_rcmd()
    time.sleep((r.clips / "say_voice.wav").stat().st_size / 32000 + 0.6)
    tap_rcmd()
    end = time.monotonic() + 15
    while time.monotonic() < end and r.text() == before:
        time.sleep(0.1)
    time.sleep(1.0)  # the Enter comes right after the paste
    got = r.text()[len(before):]
    body = got.rstrip("\n")
    return {"got": got, "line_break_inside": "\n" in body, "enter_at_end": got.endswith("\n"),
            "no_command_words": not re.search(r"new line|send it", got, re.IGNORECASE),
            "recall": round(recall(got, "Hello there. This is a voice command test."), 2)}


def scenario_recover(r: Run) -> dict:
    import os
    import signal
    clip = "en_long.wav"
    r.use(clip)
    before = r.text()
    tap_rcmd()
    time.sleep(4.0)  # mid-sentence: the spool has ~4 s on disk
    os.kill(r.app.pid, signal.SIGSEGV)
    r.app.wait(10)
    spooled = [p.stat().st_size for p in (r.data / "spool-test").glob("rec-*.f32")]
    r.start_app()  # the restart finds the leftover and transcribes it
    end = time.monotonic() + 40
    while time.monotonic() < end and "recovered a dictation" not in r._log():
        time.sleep(0.3)
    hist = []
    try:
        hist = [json.loads(l) for l in (r.data / "history-test.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    rec = [h for h in hist if h.get("recovered")]
    got = rec[-1]["text"] if rec else ""
    return {"spooled_bytes": spooled, "recovered": bool(rec), "got": got, "pasted": bool(rec and rec[-1].get("pasted")),
            "nothing_pasted_into_window": r.text() == before,
            "recall_of_first_half": round(recall(got, " ".join(EXPECTED[clip].split()[:10])), 2)}


def rcmd_plus_l():
    from ecoscribe.platform.macos import keys
    import Quartz as Q
    cmd = Q.kCGEventFlagMaskCommand | 0x10
    keys._post(RCMD, True, cmd)
    time.sleep(0.08)
    keys._post(37, True, cmd)  # L
    time.sleep(0.06)
    keys._post(37, False, cmd)
    time.sleep(0.06)
    keys._post(RCMD, False, 0)


def scenario_langkey(r: Run) -> dict:
    before, seen = r.text(), r._log().count("next dictation language ->")
    picks = []
    for _ in range(2):
        rcmd_plus_l()
        end = time.monotonic() + 5
        while time.monotonic() < end and r._log().count("next dictation language ->") <= seen:
            time.sleep(0.1)
        seen = r._log().count("next dictation language ->")
        m = re.findall(r"next dictation language -> (\w+)", r._log())
        picks.append(m[-1] if m else None)
        time.sleep(0.5)
    time.sleep(1.0)
    return {"picks": picks, "no_l_typed": r.text() == before}


ADDED = {"de": ("Anna", "Morgen fahren wir mit dem Zug nach Berlin und besuchen meine Schwester."),
         "fi": ("Eddy (Finnish (Finland))", "Huomenna menemme junalla Helsinkiin ja tapaamme ystäviä.")}


def scenario_added(r: Run) -> dict:
    (r.data / "config.toml").write_text('[whisper]\nlanguages = ["en", "de", "fi"]\nextra_languages = ["de", "fi"]\n',
                                        encoding="utf-8")
    r.app.terminate()
    r.app.wait(10)
    r.start_app()
    out = {}
    for code, (voice, said) in ADDED.items():
        clip = f"say_{code}.wav"
        subprocess.run(["say", "-v", voice, "-o", str(r.clips / clip), "--file-format=WAVE",
                        "--data-format=LEI16@16000", said], check=True)
        r.use(clip)
        before = r.text()
        tap_rcmd()
        time.sleep((r.clips / clip).stat().st_size / 32000 + 0.6)
        tap_rcmd()
        end = time.monotonic() + 30  # the first one loads large-v3
        while time.monotonic() < end and r.text() == before:
            time.sleep(0.1)
        got = r.text()[len(before):]
        out[code] = {"got": got, "recall": round(recall(got, said), 2)}
        time.sleep(1.5)
    m = re.findall(r"ready \S+ model=(\S+)", r._log())
    out["dictation_model"] = m[-1] if m else None
    return out


LIVE_SAID = ("I would like to schedule the climbing session for Thursday evening, and please remind me to bring "
             "the new shoes and the chalk bag, and also ask Sophie if she wants to come along after lunch.")


def scenario_live(r: Run) -> dict:
    """dictado-ayq: a long dictation shows its live text on the pill (a picture of the pill's strip of the
    screen at ~8 s), and the paste still comes right after the stop."""
    make_say_clip(r.clips / "say_live.wav", LIVE_SAID)
    r.use("say_live.wav")
    before = r.text()
    secs = (r.clips / "say_live.wav").stat().st_size / 32000
    tap_rcmd()
    time.sleep(8.0)
    shot = r.tmp / "live_pill.png"
    from AppKit import NSScreen
    f = NSScreen.mainScreen().frame()
    w, h = 700, 200  # bottom centre, where the pill sits
    subprocess.run(["screencapture", "-x", "-R", f"{int(f.size.width / 2 - w / 2)},{int(f.size.height - h)},{w},{h}",
                    str(shot)], check=False)
    time.sleep(max(0.0, secs + 0.6 - 8.0))
    tap_rcmd()
    end = time.monotonic() + 20
    while time.monotonic() < end and r.text() == before:
        time.sleep(0.1)
    got = r.text()[len(before):]
    return {"got": got, "recall": round(recall(got, LIVE_SAID), 2), "shot": str(shot) if shot.exists() else None,
            "clip_s": round(secs, 1)}


def scenario_nobox(r: Run, clip="en_fox.wav") -> dict:
    """dictado-cd2: the stop lands with a Finder window in front (no text box): nothing is pasted anywhere,
    the text stays on the clipboard and the log says no_text_box. Finder is opened with `open` (no AppleScript,
    no Automation prompt) and closed again with Cmd+W."""
    import os
    import Quartz as Q
    from AppKit import NSWorkspace
    from ecoscribe.platform.macos import deliver, keys
    ws = NSWorkspace.sharedWorkspace()
    r.use(clip)
    before, seen = r.text(), r._log().count("delivered")
    tap_rcmd()
    subprocess.run(["open", os.path.expanduser("~/Downloads")], timeout=10)
    end = time.monotonic() + 5
    while time.monotonic() < end and ws.frontmostApplication().localizedName() != "Finder":
        time.sleep(0.1)
    time.sleep(len((FIX / clip).read_bytes()) / 32000)
    tap_rcmd()
    end = time.monotonic() + 15
    while time.monotonic() < end and r._log().count("delivered") <= seen:
        time.sleep(0.1)
    time.sleep(0.3)
    line = [l for l in r._log().splitlines() if "delivered" in l][-1:] or [""]
    clip_text = deliver.get_clipboard_text() or ""
    keys._post(13, True, Q.kCGEventFlagMaskCommand)  # Cmd+W: close the Downloads window
    keys._post(13, False, Q.kCGEventFlagMaskCommand)
    time.sleep(0.5)
    return {"log": line[0][-160:], "no_text_box": "reason=no_text_box" in line[0],
            "nothing_typed": r.text() == before, "on_clipboard": round(recall(clip_text, EXPECTED[clip]), 2)}
def tap_numpad_enter():
    from ecoscribe.platform.macos import keys
    keys._post(76, True, 0)
    time.sleep(0.08)
    keys._post(76, False, 0)


def scenario_numpad(r: Run, clip="en_fox.wav") -> dict:
    """dictado-1k7: the numpad's Enter starts and stops a dictation like the key, and types no Enter."""
    r.use(clip)
    before = r.text()
    tap_numpad_enter()
    time.sleep(len((FIX / clip).read_bytes()) / 32000 + 0.6)
    tap_numpad_enter()
    end = time.monotonic() + 15
    while time.monotonic() < end and r.text() == before:
        time.sleep(0.1)
    time.sleep(0.5)
    got = r.text()[len(before):]
    return {"got": got, "recall": round(recall(got, EXPECTED[clip]), 2), "no_enter_typed": "\n" not in got}


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
    tmp = Path(tempfile.mkdtemp(prefix="ecoscribe-e2e-"))
    r = Run(tmp)
    results = {}
    todo = ["basic", "voice", "recover", "langkey"] if a.scenario == "all" else [a.scenario]
    try:
        for sc in todo:
            if guard.tripped.is_set():
                break
            if sc == "basic":
                for clip in ("en_fox.wav", "en_long.wav", "es_climb.wav"):  # English + Spanish set: detected
                    results[clip] = scenario_basic(r, clip)
                    time.sleep(1.5)
            elif sc == "voice":
                results["voice"] = scenario_voice(r)
            elif sc == "recover":
                results["recover"] = scenario_recover(r)
            elif sc == "langkey":
                results["langkey"] = scenario_langkey(r)
            elif sc == "live":
                results["live"] = scenario_live(r)
            elif sc == "nobox":
                results["nobox"] = scenario_nobox(r)
            elif sc == "numpad":
                results["numpad"] = scenario_numpad(r)
            elif sc == "added":
                results["added"] = scenario_added(r)
            time.sleep(1.5)
    finally:
        r.stop()
    results["stop_to_paste_ms"] = r.stop_to_paste()
    results["real_input_during_run"] = guard.tripped.is_set()
    print(json.dumps(results, ensure_ascii=False, indent=1))
    (tmp / "e2e_mac_last.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    if guard.tripped.is_set():
        return 3
    ok = all(v["recall"] >= 0.85 for k, v in results.items() if k.endswith(".wav"))
    if "voice" in results:
        v = results["voice"]
        ok = ok and v["line_break_inside"] and v["enter_at_end"] and v["no_command_words"] and v["recall"] >= 0.85
    if "langkey" in results:
        v = results["langkey"]
        ok = ok and v["picks"] == ["en", "es"] and v["no_l_typed"]
    if "live" in results:
        ok = ok and results["live"]["recall"] >= 0.85
    if "nobox" in results:
        v = results["nobox"]
        ok = ok and v["no_text_box"] and v["nothing_typed"] and v["on_clipboard"] >= 0.85
    if "numpad" in results:
        ok = ok and results["numpad"]["recall"] >= 0.85 and results["numpad"]["no_enter_typed"]
    if "added" in results:
        v = results["added"]
        ok = ok and v["de"]["recall"] >= 0.85 and v["fi"]["recall"] >= 0.85 and "large-v3" in (v["dictation_model"] or "") \
            and "turbo" not in v["dictation_model"]
    if "recover" in results:
        v = results["recover"]
        ok = ok and v["recovered"] and not v["pasted"] and v["nothing_pasted_into_window"] and v["recall_of_first_half"] >= 0.7
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
