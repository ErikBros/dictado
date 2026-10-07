"""Build Dictado.app and Dictado-<version>.dmg on an Apple Silicon Mac.

    python tools/build_mac.py [--no-dmg] [--identity NAME]

1. dictado-systap (the system-audio helper) with swiftc
2. Dictado.icns from icon.mic_image
3. PyInstaller: packaging/macos/dictado-mac.spec -> build/mac/dist/Dictado.app
4. the helper into Contents/MacOS (next to the app's executable, where systap.helper_path looks)
5. signing with a stable identity: macOS ties its permission grants (Accessibility, Input
   Monitoring, Microphone, System Audio Recording) to the signing certificate, so a rebuild signed
   with the same certificate keeps them. With no --identity, a self-signed "Dictado Local Signing"
   certificate is made once in its own keychain (.signing/, never committed): no login keychain, no
   password prompt. It isn't trusted by other Macs: fine for this one; a public release needs a paid
   Developer ID + notarization.
6. a .dmg with the app and an Applications link
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
OUT = APP / "build" / "mac"
SIGNING = Path(os.environ.get("ECOSCRIBE_SIGNING_DIR", APP / ".signing"))
KEYCHAIN = SIGNING / "dictado-signing.keychain-db"
IDENTITY = "Dictado Local Signing"
KC_PASS = "ecoscribe-local"  # protects nothing secret: the key only signs this Mac's own builds


def run(cmd, **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(list(map(str, cmd)), check=True, **kw)


def version() -> str:
    from ecoscribe import __version__
    return __version__


def build_helper() -> Path:
    out = OUT / "dictado-systap"
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["swiftc", "-O", "-target", "arm64-apple-macos14.4", "-o", out,
         APP / "ecoscribe" / "platform" / "macos" / "systap.swift"])
    return out


def build_icon() -> Path:
    from ecoscribe.icon import mic_image
    icns = APP / "packaging" / "macos" / "Dictado.icns"
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Dictado.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                mic_image(px).save(iconset / name)
        run(["iconutil", "-c", "icns", "-o", icns, iconset])
    return icns


def freeze() -> Path:
    env = {**os.environ, "DICTADO_VERSION": version()}
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", OUT / "dist",
         "--workpath", OUT / "work", APP / "packaging" / "macos" / "dictado-mac.spec"], env=env, cwd=APP)
    return OUT / "dist" / "Dictado.app"


def ensure_identity() -> str:
    """The self-signed code-signing identity in its own keychain (made once, then reused)."""
    SIGNING.mkdir(parents=True, exist_ok=True)
    if not KEYCHAIN.exists():
        key, crt, p12 = SIGNING / "key.pem", SIGNING / "cert.pem", SIGNING / "identity.p12"
        cnf = SIGNING / "openssl.cnf"
        cnf.write_text("[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=" + IDENTITY +
                       "\n[ext]\nbasicConstraints=critical,CA:false\nkeyUsage=critical,digitalSignature\n"
                       "extendedKeyUsage=critical,codeSigning\n")
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-keyout", key,
             "-out", crt, "-config", cnf])
        run(["openssl", "pkcs12", "-export", "-inkey", key, "-in", crt, "-out", p12, "-passout",
             f"pass:{KC_PASS}", "-name", IDENTITY, "-legacy"])
        run(["security", "create-keychain", "-p", KC_PASS, KEYCHAIN])
        run(["security", "set-keychain-settings", KEYCHAIN])  # no auto-lock
        run(["security", "unlock-keychain", "-p", KC_PASS, KEYCHAIN])
        run(["security", "import", p12, "-k", KEYCHAIN, "-P", KC_PASS, "-T", "/usr/bin/codesign"])
        run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:", "-s", "-k", KC_PASS, KEYCHAIN],
            stdout=subprocess.DEVNULL)
        key.unlink()  # the key lives in the keychain now
    run(["security", "unlock-keychain", "-p", KC_PASS, KEYCHAIN])
    # codesign takes an untrusted (self-signed) identity only by its SHA-1, not by name
    out = subprocess.run(["security", "find-identity", "-p", "codesigning", str(KEYCHAIN)],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f'"{IDENTITY}"' in line:
            return line.split()[1]
    raise SystemExit(f"no {IDENTITY} identity in {KEYCHAIN}")


def _search_list() -> list[str]:
    out = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True, text=True).stdout
    return [l.strip().strip('"') for l in out.splitlines() if l.strip()]


def sign(app: Path, identity: str, keychain: Path | None) -> None:
    """codesign finds identities only through the keychain search list: the signing keychain is on it
    for the signing alone, then the list is put back exactly as it was."""
    before = _search_list()
    if keychain:
        run(["security", "list-keychains", "-d", "user", "-s", *before, keychain])
    try:
        # inside out: every Mach-O in the bundle, then the bundle (no hardened runtime: not notarized)
        machos = [p for p in app.rglob("*") if p.is_file() and not p.is_symlink() and _is_macho(p)]
        for p in sorted(machos, key=lambda p: len(p.parts), reverse=True):
            ident = ["--identifier", "com.erikbros.dictado.systap"] if p.name == "dictado-systap" else []
            subprocess.run(["codesign", "--force", "--sign", identity, *ident, "--timestamp=none", str(p)],
                           check=True, capture_output=True)
        run(["codesign", "--force", "--sign", identity, "--timestamp=none", app])
    finally:
        if keychain:
            run(["security", "list-keychains", "-d", "user", "-s", *before])
    run(["codesign", "--verify", "--deep", "--strict", app])


def _is_macho(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    return magic in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf", b"\xbe\xba\xfe\xca")


def dmg(app: Path) -> Path:
    out = OUT / f"Dictado-{version()}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "Dictado"
        stage.mkdir()
        run(["ditto", app, stage / "Dictado.app"])
        (stage / "Applications").symlink_to("/Applications")
        out.unlink(missing_ok=True)
        run(["hdiutil", "create", "-volname", "Dictado", "-srcfolder", stage, "-ov", "-format", "UDZO", out],
            stdout=subprocess.DEVNULL)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dmg", action="store_true")
    ap.add_argument("--identity", help="a code-signing identity already in your keychains (e.g. Developer ID)")
    a = ap.parse_args(argv)
    helper = build_helper()
    build_icon()
    app = freeze()
    shutil.copy2(helper, app / "Contents" / "MacOS" / "dictado-systap")
    identity = a.identity or ensure_identity()
    print(f"signing with {identity}")
    sign(app, identity, None if a.identity else KEYCHAIN)
    print(f"app: {app}")
    if not a.no_dmg:
        print(f"dmg: {dmg(app)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
