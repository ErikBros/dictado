"""Is the installed Ecoscribe using the GPU right now? (dictado-2ta)

A GPU timing test next to the installed app's engine worker, a meeting it is recording or a file it
is transcribing measures the contention, not Ecoscribe: the 8 GB card had 4.7 GB taken and the base
latency tripled. Those tests skip with the reason instead, and never slow a live meeting down.
"""
from __future__ import annotations

import re
import subprocess
import sys

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
