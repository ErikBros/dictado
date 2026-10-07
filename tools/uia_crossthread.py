"""t0u.37 repro attempt: UIA objects made on short-lived threads (the way context.py does it),
kept alive past their thread in reference cycles (an exception traceback is enough), then
freed by the garbage collector on ANOTHER thread. Read-only; no keys or windows.

    python uia_crossthread.py <fault.log> [rounds]
"""
import faulthandler
import gc
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
faulthandler.enable(open(sys.argv[1], "w", encoding="utf-8"), all_threads=True)  # noqa: SIM115
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 200

from ecoscribe.platform.windows import context  # noqa: E402

gc.disable()  # collect only when WE say, on the thread we pick
kept = []


def reader():
    import comtypes
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError:
        pass
    uia = context._automation()
    el = uia.GetFocusedElement()
    root = uia.ElementFromHandle(context.ctypes.windll.user32.GetForegroundWindow()) if hasattr(context, "ctypes") else el
    class Holder:  # a reference cycle holding the COM objects, like a traceback would
        pass
    h = Holder()
    h.me, h.el, h.root = h, el, root
    kept.append(None)  # thread ends; only the cycle keeps the objects alive


for i in range(rounds):
    t = threading.Thread(target=reader)
    t.start()
    t.join()
    if i % 10 == 0:
        threading.Thread(target=gc.collect).start()  # freed on a thread that never made them
    if i % 50 == 0:
        print("round", i, flush=True)
gc.collect()
print(f"survived {rounds}", flush=True)
