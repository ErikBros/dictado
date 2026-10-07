"""Build the speaker add-on for macOS: "Ecoscribe Speakers.app" + Ecoscribe-Speakers-<ver>.dmg.

    DICTADO_SPEAKERS_MODEL=<community-1 folder> python packaging/speakers/build_speakers_mac.py \
        --python <speakers venv python> [--no-dmg]

The speakers venv: torch + pyannote.audio 4 + soundfile + pyinstaller (macOS wheels; pyannote runs on
the Apple GPU through MPS). The weights folder is the community-1 snapshot (gated on Hugging Face:
accept its terms once, then copy the snapshot); it is bundled, never committed. Signed with the same
identity as Ecoscribe.app (tools/build_mac.py), so nothing new to allow.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent
sys.path.insert(0, str(APP / "tools"))
import build_mac  # noqa: E402

VERSION = "1.1.0"
OUT = APP / "build" / "mac-speakers"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", required=True, help="the speakers venv's python")
    ap.add_argument("--no-dmg", action="store_true")
    a = ap.parse_args(argv)
    model = os.environ.get("DICTADO_SPEAKERS_MODEL")
    if not model or not (Path(model) / "config.yaml").exists():
        raise SystemExit("set DICTADO_SPEAKERS_MODEL to the community-1 folder (config.yaml, embedding, plda, segmentation)")
    env = {**os.environ, "DICTADO_SPEAKERS_VERSION": VERSION}
    build_mac.run([a.python, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", OUT / "dist",
                   "--workpath", OUT / "work", HERE / "speakers.spec"], env=env, cwd=HERE)
    app = OUT / "dist" / "Ecoscribe Speakers.app"
    identity = build_mac.ensure_identity()
    build_mac.sign(app, identity, build_mac.KEYCHAIN)
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file() and not f.is_symlink())
    print(f"app: {app}  ({size / 1e9:.2f} GB)")
    if not a.no_dmg:
        dmg = OUT / f"Ecoscribe-Speakers-{VERSION}.dmg"
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "Ecoscribe Speakers"
            stage.mkdir()
            build_mac.run(["ditto", app, stage / app.name])
            (stage / "Applications").symlink_to("/Applications")
            dmg.unlink(missing_ok=True)
            build_mac.run(["hdiutil", "create", "-volname", "Ecoscribe Speakers", "-srcfolder", stage, "-ov",
                           "-format", "UDZO", dmg])
        print(f"dmg: {dmg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
