# PyInstaller spec for Dictado.app (macOS, Apple Silicon). Build with: python tools/build_mac.py
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

HERE = Path(SPECPATH)
APP = HERE.parent.parent
VERSION = os.environ.get("DICTADO_VERSION", "0.0.0")

binaries = collect_dynamic_libs("mlx")  # dictado-systap goes into Contents/MacOS after the build
datas = (collect_data_files("mlx") + collect_data_files("mlx_whisper") + collect_data_files("faster_whisper")
         + collect_data_files("webview") + [(str(APP / "dictado" / "web"), "dictado/web"),
                                             (str(APP / "dictado" / "platform" / "macos" / "systap.swift"),
                                              "dictado/platform/macos")])

a = Analysis(
    [str(APP / "packaging" / "entry.py")],
    pathex=[str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["dateutil.rrule", "dateutil.tz", "webview.platforms.cocoa",
                   *collect_submodules("dictado.platform.macos"), *collect_submodules("mlx_whisper"),
                   # mlx.core imports these at init (mlx._reprlib_fix, mlx.__array_api_info): the scan can't see it
                   *collect_submodules("mlx"),
                   "AppKit", "Foundation", "Quartz", "ApplicationServices", "AVFoundation", "CoreAudio", "WebKit",
                   "PyObjCTools.AppHelper"],
    excludes=["torch", "tensorflow", "matplotlib", "pandas", "IPython", "pytest", "PyInstaller", "tkinter",
              "pyaudiowpatch", "win32api", "win32con", "win32event", "comtypes", "pystray"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Dictado", console=False, argv_emulation=False,
          target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Dictado")
app = BUNDLE(
    coll,
    name="Dictado.app",
    icon=str(HERE / "Dictado.icns") if (HERE / "Dictado.icns").exists() else None,
    bundle_identifier="com.erikbros.dictado",
    version=VERSION,
    info_plist={
        "CFBundleName": "Dictado",
        "CFBundleDisplayName": "Dictado",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,  # menu bar only, no Dock icon
        "LSMinimumSystemVersion": "14.4",  # Core Audio process taps (meetings' system audio)
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Dictado listens while you dictate and records your side of meetings.",
        "NSAudioCaptureUsageDescription": "Dictado records the other people in your meetings from the computer's audio.",
    },
)
