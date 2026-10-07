"""Build the speaker add-on (t0u.22): EcoscribeSpeakers.exe + Ecoscribe-Speakers-Setup-<ver>.exe. Windows Python.

    python build_speakers.py [--installer] [--skip-freeze]

Needs %USERPROFILE%\\ecoscribe-build\\speakers-venv (or the old dictado-build one) (torch CUDA + pyannote.audio 4 + soundfile +
pyinstaller) and the community-1 weights in ...\\speakers-model (copied from a Hugging Face
snapshot; the model is gated, so accept its terms once with your Hugging Face account).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

VERSION = "1.2.0"
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ["USERPROFILE"]) / "ecoscribe-build"
_OLD = Path(os.environ["USERPROFILE"]) / "dictado-build"  # where the venv and weights were made before the rename
VENV_PY = next((d / "speakers-venv" / "Scripts" / "python.exe" for d in (OUT, _OLD)
                if (d / "speakers-venv").is_dir()), OUT / "speakers-venv" / "Scripts" / "python.exe")
MODEL = next((d / "speakers-model" for d in (OUT, _OLD) if (d / "speakers-model").is_dir()), OUT / "speakers-model")
ISCC = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"


def freeze() -> Path:
    env = dict(os.environ, DICTADO_SPEAKERS_MODEL=str(MODEL))
    subprocess.run([str(VENV_PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(OUT / "speakers-dist"),
                    "--workpath", str(OUT / "speakers-work"), str(HERE / "speakers.spec")], check=True, env=env, cwd=str(HERE))
    exe = OUT / "speakers-dist" / "EcoscribeSpeakers" / "EcoscribeSpeakers.exe"
    size = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    print(f"built {exe}  ({size / 1e9:.2f} GB)")
    return exe


def installer() -> Path:
    subprocess.run([str(ISCC), f"/DAppVersion={VERSION}", f"/DDistDir={OUT / 'speakers-dist' / 'EcoscribeSpeakers'}",
                    f"/O{OUT}", str(HERE / "speakers.iss")], check=True)
    setup = OUT / f"Ecoscribe-Speakers-Setup-{VERSION}.exe"
    dl = Path(os.environ["USERPROFILE"]) / "Downloads" / setup.name
    shutil.copy2(setup, dl)
    print(f"installer {setup}  ({setup.stat().st_size / 1e9:.2f} GB) -> {dl}")
    return setup


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true")
    ap.add_argument("--skip-freeze", action="store_true")
    a = ap.parse_args()
    if not a.skip_freeze:
        freeze()
    if a.installer:
        installer()
