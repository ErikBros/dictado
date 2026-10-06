"""Reproduce the screen-names crash (t0u.37) without touching the desktop. Windows Python.

    python uia_stress.py <fault.log> [rounds] [--gc]

Runs context.ScreenNames exactly as a dictation does (one short-lived thread per read of
the foreground window), `rounds` times, with faulthandler writing every thread's stack to
<fault.log> if the process dies natively. --gc also runs gc.collect() on other threads, the
way garbage collection lands on whatever thread happens to allocate in the real app.
Read-only: no keys, no clicks, no windows. Exit 0 = survived.
"""
import faulthandler
import gc
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

fault = open(sys.argv[1], "w", encoding="utf-8")  # noqa: SIM115 (open for the whole run)
faulthandler.enable(fault, all_threads=True)
rounds = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 300
use_gc = "--gc" in sys.argv

from dictado.context import ScreenNames  # noqa: E402

t0 = time.monotonic()
for i in range(rounds):
    s = ScreenNames().start()
    s._done.wait(3)
    s.get(0)
    if use_gc:
        threading.Thread(target=gc.collect, daemon=True).start()
    if i % 50 == 0:
        print(f"round {i} names={len(s.get(0))} t={time.monotonic() - t0:.1f}s", flush=True)
print(f"survived {rounds} rounds in {time.monotonic() - t0:.1f}s", flush=True)
