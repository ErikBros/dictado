"""Install / uninstall / reinstall checks for Dictado-Setup-*.exe (Windows Python).

    python install_check.py <setup.exe> [--keep-installed]

Opens no windows of its own; the installed app's window only opens in the
"second launch" check, which waits for idle and closes it again.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from tests.idle import wait_idle  # noqa: E402

LOCAL = Path(os.environ["LOCALAPPDATA"])
APPDIR = LOCAL / "Programs" / "Dictado"
EXE = APPDIR / "Dictado.exe"
DATA = LOCAL / "dictado"
STARTMENU = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Dictado.lnk"
OLD_LNK = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Dictado.lnk"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINST = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C1B3F2E-5D4A-4E8B-9A61-D1C7A0D1C7A0}_is1"
FIX = HERE.parent / "fixtures" / "en_long.wav"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""), flush=True)
    return cond


def reg(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def procs(image="Dictado.exe") -> list[str]:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if image.lower() in l.lower()]


def status() -> dict:
    try:
        return json.loads((DATA / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_ready(after_ts: float, timeout=120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        s = status()
        if s.get("state") == "ready" and s.get("ts", 0) > after_ts:
            return s
        time.sleep(0.5)
    return status()


def install(setup: str) -> None:
    t0 = time.time()
    r = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=startup", "/LOG=" + str(DATA / "install.log")],
                       timeout=900)
    check("installer exit code 0", r.returncode == 0, str(r.returncode))
    print(f"     install took {time.time() - t0:.0f} s", flush=True)


def uninstall() -> None:
    un = APPDIR / "unins000.exe"
    r = subprocess.run([str(un), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
    check("uninstaller exit code 0", r.returncode == 0, str(r.returncode))
    time.sleep(3)


def installed_state_checks(t_install: float) -> None:
    check("exe installed", EXE.exists(), str(EXE))
    check("CUDA DLLs installed", (APPDIR / "_internal" / "nvidia" / "cublas" / "bin" / "cublasLt64_12.dll").exists())
    check("web UI installed", (APPDIR / "_internal" / "dictado" / "web" / "index.html").exists())
    check("Start menu shortcut", STARTMENU.exists(), str(STARTMENU))
    check("Run key points at the installed exe", (reg(RUN, "Dictado") or "").strip('"').lower() == str(EXE).lower(),
          str(reg(RUN, "Dictado")))
    check("Apps & Features entry", reg(UNINST, "DisplayName") == "Dictado", str(reg(UNINST, "DisplayName")))
    check("Apps & Features icon", (reg(UNINST, "DisplayIcon") or "").lower().startswith(str(EXE).lower()))
    check("old script Startup shortcut gone", not OLD_LNK.exists())
    s = wait_ready(t_install)
    check("app launched after install and is ready on CUDA", s.get("state") == "ready" and s.get("device") == "cuda", json.dumps(s))
    check("exactly one Dictado.exe running", len(procs()) == 1, str(procs()))


def selftest_installed() -> None:
    out = DATA / "selftest-installed.json"
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = r"C:\Windows\System32;C:\Windows"
    r = subprocess.run([str(EXE), "--selftest", str(FIX), "--out", str(out)], env=env, timeout=240)
    d = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    check("selftest from installed dir with clean PATH: cuda + right text",
          r.returncode == 0 and d.get("device") == "cuda" and "climbing session" in d.get("text", ""), json.dumps(d)[:300])
    check("selftest under 1 s", d.get("ms", 9999) < 1000, str(d.get("ms")))


def second_launch_opens_window_not_engine() -> None:
    import win32con
    import win32gui
    if not wait_idle(45, 600):
        check("second launch (skipped: PC in use)", True)
        return
    before = status().get("pid")
    subprocess.Popen([str(EXE)])
    hwnd = 0
    end = time.time() + 20
    while time.time() < end and not hwnd:
        hwnd = win32gui.FindWindow(None, "Dictado")
        time.sleep(0.3)
    check("second launch opens the window", bool(hwnd))
    time.sleep(3)
    if hwnd:
        capture(hwnd, HERE / "real-window.png")
    check("still exactly one engine (same pid)", status().get("pid") == before, f"{before} -> {status().get('pid')}")
    check("two processes: engine + window", len(procs()) == 2, str(procs()))
    subprocess.Popen([str(EXE), "--ui"])
    time.sleep(4)
    n = []
    win32gui.EnumWindows(lambda h, _: (n.append(h) if win32gui.GetWindowText(h) == "Dictado" and win32gui.IsWindowVisible(h) else None) or True, None)
    check("opening again focuses the same window (one window)", len(n) == 1, str(n))
    if hwnd:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(3)
    check("window closed, engine untouched", len(procs()) == 1 and status().get("pid") == before, str(procs()))


def capture(hwnd, path) -> None:
    """PrintWindow with PW_RENDERFULLCONTENT renders WebView2 content even if covered."""
    import ctypes

    import win32gui
    import win32ui
    from PIL import Image
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    info, bits = bmp.GetInfo(), bmp.GetBitmapBits(True)
    Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1).save(path)
    mem.DeleteDC(); src.DeleteDC(); win32gui.ReleaseDC(hwnd, hdc); win32gui.DeleteObject(bmp.GetHandle())
    print(f"     captured real window -> {path.name} (PrintWindow ok={ok}, {w}x{h})", flush=True)


def uninstalled_checks() -> None:
    check("app folder removed", not APPDIR.exists())
    check("Start menu shortcut removed", not STARTMENU.exists())
    check("Run key removed", reg(RUN, "Dictado") is None)
    check("Apps & Features entry removed", reg(UNINST, "DisplayName") is None)
    check("no Dictado.exe running", len(procs()) == 0, str(procs()))
    check("history kept", (DATA / "history.jsonl").exists())


def main():
    setup = sys.argv[1]
    keep = "--keep-installed" in sys.argv
    t = time.time()
    install(setup)
    installed_state_checks(t)
    selftest_installed()
    second_launch_opens_window_not_engine()
    uninstall()
    uninstalled_checks()
    if keep:
        t = time.time()
        install(setup)
        installed_state_checks(t)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
