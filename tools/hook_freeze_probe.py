"""t0u.37: does a frozen Ecoscribe still stall the PC's keyboard? Windows Python, idle desktop only.

    python hook_freeze_probe.py inprocess|process

Installs Ecoscribe's hooks (in this process, or in the --hook process), then freezes this
process's Python on purpose (a regex that holds the GIL for seconds, like a stuck app) while a
separate injector process presses F24 (no app uses it) and measures how long Windows takes to
deliver each press: the time until GetAsyncKeyState sees it, which happens only after every
low-level hook answered. Prints the delays in ms.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tests"))
mode = sys.argv[1]

from idle import wait_idle  # noqa: E402

if not wait_idle(45, 900):
    print("not idle; no probe")
    sys.exit(2)

from ecoscribe.platform.windows.hook import HookClient, HookThread, spawn_hook_process  # noqa: E402

RCTRL = 0xA3
if mode == "process":
    h = HookClient(lambda a: None, RCTRL, 0.3, accept_injected=True, spawn=spawn_hook_process)
else:
    h = HookThread(lambda a: None, RCTRL, 0.3, accept_injected=True)
h.start()
time.sleep(1.5)

INJECT = r'''
import ctypes, time, sys
sys.path.insert(0, r"%s")
from ecoscribe.platform.windows.win32types import INPUT, INPUT_KEYBOARD, KEYEVENTF_KEYUP, user32
VK = 0x87  # F24
def send(up):
    i = INPUT(type=INPUT_KEYBOARD); i.u.ki.wVk = VK; i.u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
out = []
time.sleep(0.5)
for n in range(4):
    t0 = time.perf_counter(); send(False)
    while not (user32.GetAsyncKeyState(VK) & 0x8000) and time.perf_counter() - t0 < 5: time.sleep(0.001)
    out.append(int((time.perf_counter() - t0) * 1000)); send(True)
    while (user32.GetAsyncKeyState(VK) & 0x8000) and time.perf_counter() - t0 < 10: time.sleep(0.001)
    time.sleep(0.2)
print(" ".join(map(str, out)), flush=True)
''' % APP
inj = subprocess.Popen([sys.executable, "-c", INJECT], stdout=subprocess.PIPE, text=True)
t = time.perf_counter()
re.match(r"(a+)+$", "a" * 27 + "b")  # holds the GIL: this process is "frozen" now
frozen_s = time.perf_counter() - t
out = inj.communicate(timeout=60)[0].strip()
print(f"{mode}: froze {frozen_s:.1f} s; F24 delivery ms during the freeze: {out}")
h.stop()
