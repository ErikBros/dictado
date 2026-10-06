"""No keys, certificates or secrets in the repo (found 2026-10-06: a Mac signing identity was
committed before its .gitignore rule existed). Checks every tracked file, so CI blocks the PR."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BAD_PATH = re.compile(r"(^|/)\.signing/|\.(p12|pfx|pem|key|cer|crt|keychain(-db)?|mobileprovision)$|(^|/)\.env$", re.I)
BAD_TEXT = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|hf_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{30,}|"
                      r"calendar/ical/[^/\s\"']+/private-[0-9a-f]{20,}")


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        pytest.skip("git not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return out.stdout.splitlines()


def test_no_key_or_certificate_files_are_tracked():
    bad = [p for p in _tracked() if BAD_PATH.search(p)]
    assert not bad, f"keys/certificates must never be committed: {bad}"


def test_no_secrets_inside_tracked_files():
    hits = []
    for p in _tracked():
        f = ROOT / p
        if not f.is_file() or f.stat().st_size > 2_000_000:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if BAD_TEXT.search(text):
            hits.append(p)
    assert not hits, f"secret-looking content in {hits}"
