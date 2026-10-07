"""Build Ecoscribe.exe (and optionally the installer). Run with Windows Python.

    python build.py              -> %USERPROFILE%\\ecoscribe-build\\dist\\Ecoscribe\\Ecoscribe.exe
    python build.py --installer  -> also Ecoscribe-Setup-<ver>.exe (copied to Downloads)
"""
from __future__ import annotations

import argparse
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
PKG = APP / "packaging" / "windows"
OUT = Path(os.environ["USERPROFILE"]) / "ecoscribe-build"
ISCC = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"


def version() -> str:
    ns = {}
    exec((APP / "ecoscribe" / "__init__.py").read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def freeze() -> Path:
    env = dict(os.environ, ECOSCRIBE_SITE=site.getsitepackages()[-1])
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--distpath", str(OUT / "dist"), "--workpath", str(OUT / "work"), str(PKG / "ecoscribe.spec")]
    subprocess.run(cmd, check=True, env=env, cwd=str(OUT))
    exe = OUT / "dist" / "Ecoscribe" / "Ecoscribe.exe"
    size = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    print(f"built {exe}  ({size / 1e9:.2f} GB)")
    return exe


def installer() -> Path:
    v = version()
    subprocess.run([str(ISCC), f"/DAppVersion={v}", f"/DDistDir={OUT / 'dist' / 'Ecoscribe'}",
                    f"/O{OUT}", str(PKG / "ecoscribe.iss")], check=True)
    setup = OUT / f"Ecoscribe-Setup-{v}.exe"
    dl = Path(os.environ["USERPROFILE"]) / "Downloads" / setup.name
    shutil.copy2(setup, dl)
    print(f"installer {setup}  ({setup.stat().st_size / 1e9:.2f} GB) -> {dl}")
    return setup


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true")
    ap.add_argument("--skip-freeze", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if not a.skip_freeze:
        freeze()
    if a.installer:
        installer()
