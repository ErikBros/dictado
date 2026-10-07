"""Is the installed Ecoscribe using the GPU right now? (dictado-2ta)

A GPU timing test next to the installed app's engine worker, a meeting it is recording or a file it
is transcribing measures the contention, not Ecoscribe: the 8 GB card had 4.7 GB taken and the base
latency tripled. Those tests skip with the reason instead, and never slow a live meeting down.
Other apps count too (dictado-2so): with another desktop app's GPU effects keeping the card 36-42 %
busy, the base latency was 704 ms instead of ~250 ms.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time

INSTALLED = re.compile(r"Ecoscribe(\.exe|\.app/)", re.IGNORECASE)  # not "python -m ecoscribe" from a test
WHAT = (("--meeting", "recording a meeting"), ("--transcribe", "transcribing a file"),
        ("--engine-worker", "holding its speech model (it lets go after 10 idle minutes)"))


def gpu_use(cmdlines: list[str]) -> str | None:
    """What the installed app is doing on the GPU, from process command lines, or None."""
    mine = [c for c in cmdlines if INSTALLED.search(c)]
    for flag, what in WHAT:
        if any(flag in c for c in mine):
            return what
    return None


def cmdlines() -> list[str]:
    if sys.platform == "win32":
        cmd = ["powershell", "-NoProfile", "-Command",
               "Get-CimInstance Win32_Process -Filter \"name='Ecoscribe.exe'\" | ForEach-Object { $_.CommandLine }"]
    else:
        cmd = ["ps", "-axo", "command"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def installed_app_gpu_use() -> str | None:
    return gpu_use(cmdlines())


BUSY_PCT = 20  # the GPU's own utilisation above this before the test: other work is on it


def gpu_utilisation(samples: int = 5, every_s: float = 0.6) -> float | None:
    """The NVIDIA GPU's mean utilisation (%) over a few seconds, or None without nvidia-smi (the Mac)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    vals = []
    for _ in range(samples):
        try:
            out = subprocess.run([exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout
            vals.append(float(out.split()[0]))
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None
        time.sleep(every_s)
    return sum(vals) / len(vals)


def busy_reason(app_use: str | None, utilisation: float | None) -> str | None:
    """Why a GPU timing test can't measure now, or None."""
    if app_use:
        return f"the installed Ecoscribe is {app_use}"
    if utilisation is not None and utilisation > BUSY_PCT:
        return f"the GPU is already {utilisation:.0f} % busy with other apps"
    return None


def why_busy() -> str | None:
    return busy_reason(installed_app_gpu_use(), gpu_utilisation())
