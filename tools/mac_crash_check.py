"""Real crash check on macOS: the background app is crashed for real; the watchdog (supervise.py) must
turn it into a report folder and restart it, and must leave it alone when it was quit or killed.

Nothing on screen: a temp data dir (Welcome marked done), no menu bar item (ECOSCRIBE_NO_TRAY, inherited by the restarted
copy), no overlay, no sounds, hotkey F19 (never pressed), meetings off.
1. SIGSEGV (a native crash): report folder with fault.log (every thread's stack), restart, the new
   copy logs "restarted after a crash".
2. SIGTERM (logout, Activity Monitor > Quit): a quit; the watchdog leaves, no restart.
3. A fresh start, then SIGKILL (Force Quit): killed, not a crash; no report, no restart.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
PY = sys.executable


def wait(cond, s):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.5)
    return False


def status(d):
    try:
        return json.loads((d / "status.json").read_text())
    except (OSError, ValueError):
        return {}


def alive(p):
    if not p:
        return False
    try:
        os.kill(p, 0)
    except OSError:
        return False
    return subprocess.run(["ps", "-o", "stat=", "-p", str(p)], capture_output=True, text=True).stdout.strip()[:1] not in ("Z", "")


def supervisor_pids(d):
    out = subprocess.run(["pgrep", "-f", "ecoscribe --supervise"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if f"ECOSCRIBE_DATA_DIR={d}" in subprocess.run(
        ["ps", "eww", "-o", "command=", "-p", p], capture_output=True, text=True).stdout]


def start(d, env):
    subprocess.Popen([PY, "-m", "ecoscribe"], cwd=str(APP), env=env, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    assert wait(lambda: status(d).get("state") == "ready" and alive(status(d).get("pid")), 60), "app did not start"
    assert wait(lambda: supervisor_pids(d), 20), "watchdog did not start"
    return status(d)["pid"]


def main():
    d = Path(tempfile.mkdtemp(prefix="dcrash-"))
    (d / "config.toml").write_text('[hotkey]\nkey = "f19"\n[ui]\noverlay = false\nsounds = false\n'
                                   '[meetings]\nmode = "off"\n')
    (d / "welcome_done").write_text("x")  # a fresh data dir would open the Welcome window on screen
    env = {**os.environ, "ECOSCRIBE_DATA_DIR": str(d), "ECOSCRIBE_NO_TRAY": "1"}
    res = {"data": str(d)}
    try:
        old = start(d, env)
        t0 = time.monotonic()
        os.kill(old, signal.SIGSEGV)
        back = wait(lambda: status(d).get("pid") not in (None, old) and status(d).get("state") == "ready"
                    and alive(status(d)["pid"]), 60)
        reports = sorted(p for p in (d / "crashes").iterdir() if p.is_dir() and p.name != "live") \
            if (d / "crashes").exists() else []
        rep = reports[-1] if reports else None
        res["sigsegv"] = {"restarted": back, "after_s": round(time.monotonic() - t0, 1), "reports": len(reports),
                          "report_md": bool(rep and (rep / "report.md").exists()),
                          "native_stack": bool(rep and (rep / "fault.log").exists()
                                               and "Segmentation fault" in (rep / "fault.log").read_text()),
                          "restart_logged": "restarted after a crash" in (d / "ecoscribe.log").read_text()}
        cur = status(d)["pid"]
        os.kill(cur, signal.SIGTERM)
        res["sigterm"] = {"app_gone": wait(lambda: not alive(cur), 15),
                          "watchdog_left": wait(lambda: not supervisor_pids(d), 15),
                          "state": status(d).get("state")}
        time.sleep(3)
        res["sigterm"]["not_restarted"] = status(d).get("pid") == cur
        cur = start(d, env)
        n_reports = len(reports)
        os.kill(cur, signal.SIGKILL)
        res["sigkill"] = {"watchdog_left": wait(lambda: not supervisor_pids(d), 15)}
        time.sleep(3)
        res["sigkill"]["not_restarted"] = status(d).get("pid") == cur and not alive(cur)
        res["sigkill"]["no_report"] = len([p for p in (d / "crashes").iterdir()
                                          if p.is_dir() and p.name != "live"]) == n_reports
    finally:
        for p in supervisor_pids(d) + [status(d).get("pid")]:
            if alive(p):
                os.kill(p, signal.SIGKILL)
    print(json.dumps(res, indent=1))
    ok = all(all(v.values()) if isinstance(v, dict) else True for k, v in res.items()
             if k != "sigterm") and res["sigterm"]["app_gone"] and res["sigterm"]["watchdog_left"] \
        and res["sigterm"]["not_restarted"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
