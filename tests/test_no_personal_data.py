"""No personal data in the repo: nothing the user dictated may appear in a file here or in an
unpushed commit message (the repo is public; tickets in .beads/issues.jsonl too).

Runs where a real dictation history exists (the developer's computer) and checks every 6-word piece
of every dictation against the working tree. The scripted sentences of the test recordings
(tools/make_fixtures.py, tests/fixtures) are allowed: test runs dictate them. In CI there is no
history, so it skips.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from ecoscribe import paths

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache", "shots", "embeddeddolt", "dolt"}  # the tracker DB is local, never in git
TEXT_EXT = {".py", ".md", ".js", ".mjs", ".html", ".css", ".json", ".jsonl", ".toml", ".yml", ".yaml", ".txt",
            ".iss", ".spec", ".sh", ".swift", ".srt", ""}
N = 6  # words per piece: long enough to be the user's own, short enough to catch a quote


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _pieces(text: str) -> set[str]:
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + N]) for i in range(0, max(0, len(w) - N + 1))}


def _history() -> list[str]:
    d = Path(os.environ.get("ECOSCRIBE_PERSONAL_DIR") or paths.data_dir())
    texts = []
    for f in [d / "history.jsonl", *d.glob("history*.bak")]:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    texts.append(str(json.loads(line).get("text", "")))
                except ValueError:
                    pass
        except OSError:
            pass
    return [t for t in texts if t.strip()]


def _repo_text() -> str:
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in TEXT_EXT and p.stat().st_size < 5_000_000:
                try:
                    out.append(p.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
    try:  # commits not on GitHub yet (their messages); git may not read a WSL folder from Windows
        log = subprocess.run(["git", "log", "@{upstream}..HEAD", "--format=%B"], cwd=REPO, capture_output=True,
                             text=True, encoding="utf-8", errors="ignore", timeout=20)
        if log.returncode == 0:
            out.append(log.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return _norm("\n".join(out))


def test_no_dictation_text_in_the_repo():
    texts = _history()
    if not texts:
        pytest.skip("no dictation history on this computer (CI): nothing to compare")
    allowed = set()
    for f in [REPO / "tools" / "make_fixtures.py", *(REPO / "tests" / "fixtures").glob("*.txt")]:
        allowed |= _pieces(f.read_text(encoding="utf-8", errors="ignore"))
    mine = set().union(*(_pieces(t) for t in texts)) - allowed
    repo = _repo_text()
    leaked = sorted(p for p in mine if p in repo)
    assert not leaked, f"{len(leaked)} piece(s) of real dictations are in the repo (first: {leaked[0]!r}): remove them"
