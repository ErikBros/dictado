"""Deploy Dictado to %USERPROFILE%\\dictado and (re)start it. Run with Windows Python.

    python deploy.py            copy, add Startup shortcut, restart, wait for ready
    python deploy.py --uninstall  stop it and remove the Startup shortcut
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "dictado"
DEST = Path(os.environ["USERPROFILE"]) / "dictado"
DATA = Path(os.environ["LOCALAPPDATA"]) / "dictado"
STARTUP = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Dictado.lnk"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")


def stop_running() -> None:
    pid_file = DATA / "dictado.pid"
    if not pid_file.exists():
        return
    pid = pid_file.read_text().strip()
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout.lower()
    if "python" in out:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
        print("stopped pid", pid)
        time.sleep(1)


def copy() -> None:
    target = DEST / "dictado"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SRC, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print("copied to", target)


def shortcut() -> None:
    import win32com.client
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(STARTUP))
    sc.TargetPath = str(PYTHONW)
    sc.Arguments = "-m dictado"
    sc.WorkingDirectory = str(DEST)
    sc.Description = "Dictado: dictado por voz (toca Ctrl derecho)"
    sc.Save()
    print("startup shortcut", STARTUP)


def launch() -> None:
    log = DATA / "dictado.log"
    start_size = log.stat().st_size if log.exists() else 0
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(PYTHONW), "-m", "dictado"], cwd=str(DEST), creationflags=flags, close_fds=True)
    end = time.monotonic() + 180
    while time.monotonic() < end:
        if log.exists():
            with open(log, encoding="utf-8", errors="replace") as f:
                f.seek(start_size)
                new = f.read()
            for line in new.splitlines():
                if "ready model=" in line or "ERROR" in line:
                    print(line)
            if "ready model=" in new:
                return
        time.sleep(0.5)
    raise SystemExit("Dictado did not report ready within 180 s; see " + str(log))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    stop_running()
    if a.uninstall:
        STARTUP.unlink(missing_ok=True)
        print("removed startup shortcut; files left in", DEST)
        return
    copy()
    shortcut()
    launch()


if __name__ == "__main__":
    main()
