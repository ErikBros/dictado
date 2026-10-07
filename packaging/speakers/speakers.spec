# PyInstaller spec for DictadoSpeakers.exe (the speaker add-on, t0u.22). Built by build_speakers.py
# with the speakers venv (torch CUDA + pyannote.audio); DICTADO_SPEAKERS_MODEL = the model folder.
import os
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], []
for pkg in ("pyannote.audio", "pyannote.core", "pyannote.pipeline", "pyannote.database", "pyannote.metrics",
            "lightning", "pytorch_lightning", "lightning_fabric", "torchmetrics", "asteroid_filterbanks",
            "soundfile", "einops", "safetensors", "huggingface_hub", "opentelemetry"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d; binaries += b; hiddenimports += h
for pkg in ("torch", "pyannote.audio", "lightning", "pytorch_lightning", "lightning_fabric", "torchmetrics",
            "huggingface_hub", "safetensors", "numpy", "scipy", "einops", "soundfile"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass
datas.append((os.environ["DICTADO_SPEAKERS_MODEL"], "model"))

a = Analysis(["speakers_main.py"], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib.tests", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
NAME = "EcoscribeSpeakers" if sys.platform == "darwin" else "DictadoSpeakers"  # the Mac add-on is renamed (dictado-c9u)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)


if sys.platform == "darwin":  # macOS: "Ecoscribe Speakers.app", no window, no Dock icon (build_speakers_mac.py)
    app = BUNDLE(coll, name="Ecoscribe Speakers.app", bundle_identifier="com.erikbros.ecoscribe.speakers",
                 version=os.environ.get("DICTADO_SPEAKERS_VERSION", "1.1.0"),
                 info_plist={"LSUIElement": True, "LSBackgroundOnly": True, "CFBundleName": "Ecoscribe Speakers",
                             "LSMinimumSystemVersion": "14.4"})
