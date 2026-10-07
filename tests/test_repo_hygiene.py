"""No signing secrets in the repo, ever (2026-10-06: a local signing key was committed by accident).

Fails if any tracked file looks like a private key or keychain: tools/build_mac.py keeps its
self-signed identity in .signing/ (ignored), and nothing like it may be committed.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
SECRET = re.compile(r"(^|/)\.signing/|\.(p12|pfx|pem|key|keychain|keychain-db|cer|mobileprovision)$", re.IGNORECASE)


def tracked() -> list[str]:
    if not shutil.which("git") or not (APP / ".git").exists():
        pytest.skip("not a git checkout")
    r = subprocess.run(["git", "ls-files"], cwd=APP, capture_output=True, text=True)
    if r.returncode != 0:  # e.g. Windows git refusing a WSL folder (exit 128): CI and the Mac still check
        pytest.skip(f"git can't read this checkout: {r.stderr.strip()[:200]}")
    return r.stdout.splitlines()


def test_no_signing_secrets_are_tracked():
    bad = [p for p in tracked() if SECRET.search(p)]
    assert not bad, f"signing secrets tracked by git: {bad}"


def test_signing_folder_is_ignored():
    assert ".signing/" in (APP / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_pattern_catches_what_build_mac_makes():
    for p in (".signing/identity.p12", ".signing/dictado-signing.keychain-db", ".signing/cert.pem", "x/.signing/a"):
        assert SECRET.search(p), p
    assert not SECRET.search("dictado/platform/macos/systap.swift")
