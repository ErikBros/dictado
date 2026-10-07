"""Ecoscribe's own copy of the Whisper model, as plain files.

The Hugging Face cache stores model files as symlinks into a blobs folder. The
copy of Ecoscribe started by the installer could not open them ("Unable to open
file 'model.bin'", 2026-10-02) while the same exe launched otherwise could. So
the model is mirrored into %LOCALAPPDATA%\\ecoscribe\\models\\<name> with hard links
to the real blobs (no extra disk space, nothing to resolve at load time); copies
if hard links are impossible.

Repo ids (`KBLab/kb-whisper-large`) mirror to `models/KBLab--kb-whisper-large` and
download with huggingface_hub.snapshot_download; short names (`large-v3-turbo`)
go through faster-whisper's own download_model as before.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from fnmatch import fnmatch
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)
DONE = ".complete"
_lock = threading.Lock()


CT2_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def safe_name(name: str) -> str:
    return name.replace("/", "--")


def _dir_bytes(d: Path) -> int:
    total = 0
    for f in Path(d).rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _repo_total(repo: str) -> int | None:
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
        return sum(s.size or 0 for s in info.siblings if any(fnmatch(s.rfilename, p) for p in CT2_FILES)) or None
    except Exception:
        log.warning("could not read the size of %s", repo, exc_info=True)
        return None


def _snapshot(repo: str, progress=None, cache_dir=None) -> str:
    from huggingface_hub import constants, snapshot_download
    try:
        return snapshot_download(repo, allow_patterns=CT2_FILES, local_files_only=True, cache_dir=cache_dir)
    except Exception:
        log.info("model %s not in the HF cache, downloading", repo)
    if progress is None:
        return snapshot_download(repo, allow_patterns=CT2_FILES, cache_dir=cache_dir)
    total = _repo_total(repo)
    blobs = Path(cache_dir or constants.HF_HUB_CACHE) / f"models--{safe_name(repo)}" / "blobs"
    stop = threading.Event()

    def poll():  # finished blobs + the .incomplete ones being written
        while not stop.wait(1.0):
            progress(_dir_bytes(blobs) if blobs.exists() else 0, total)
    t = threading.Thread(target=poll, name="model-progress", daemon=True)
    t.start()
    try:
        return snapshot_download(repo, allow_patterns=CT2_FILES, cache_dir=cache_dir)
    finally:
        stop.set()
        t.join()


def _hf_download(name: str, progress=None, cache_dir=None) -> str:
    if "/" in name:
        return _snapshot(name, progress, cache_dir)
    from faster_whisper.utils import download_model
    try:
        return download_model(name, local_files_only=True, cache_dir=cache_dir)
    except Exception:
        log.info("model %s not in the HF cache, downloading", name)
        return download_model(name, cache_dir=cache_dir)


class _monotonic:
    """Progress hook that never reports less than before; finish() reports done == total."""

    def __init__(self, fn):
        self.fn, self.done = fn, 0

    def __call__(self, done, total):
        self.done = max(self.done, int(done))
        self.fn(self.done, total)

    def finish(self, n):
        n = max(self.done, int(n))
        self.done = n
        self.fn(n, n)


def is_local(name: str, root: Path | None = None) -> bool:
    """True when `name` is an existing path or a complete mirror (no download needed)."""
    if os.path.isdir(name):
        return True
    root = Path(root) if root else paths.data_dir() / "models"
    out = root / safe_name(name)
    return (out / DONE).exists() and (out / "model.bin").exists()


def ensure_local(name: str, root: Path | None = None, download=_hf_download, progress=None,
                 cache_dir: Path | None = None) -> Path:
    """Directory with real model files for `name` (a model name, a repo id or an existing path).

    progress(done_bytes, total_bytes | None) is called while downloading, and always once
    at the end with done == total."""
    if os.path.isdir(name):
        return Path(name)
    if progress:
        progress = _monotonic(progress)
    root = Path(root) if root else paths.data_dir() / "models"
    out = root / safe_name(name)
    if is_local(name, root):
        if progress:
            progress.finish(_dir_bytes(out))
        return out
    kw = {}
    if progress:
        kw["progress"] = progress
    if cache_dir is not None:
        kw["cache_dir"] = str(cache_dir)
    src = Path(download(name, **kw))
    tmp = root / f".{safe_name(name)}.{os.getpid()}.{threading.get_ident()}.tmp"  # per caller: no shared scratch dir
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for f in src.iterdir():
        real = Path(os.path.realpath(f))
        if not real.is_file():
            continue
        try:
            os.link(real, tmp / f.name)
        except OSError:
            shutil.copy2(real, tmp / f.name)
    (tmp / DONE).write_text(str(src), encoding="utf-8")
    with _lock:
        if (out / DONE).exists() and (out / "model.bin").exists():  # another caller finished first
            shutil.rmtree(tmp, ignore_errors=True)
            return out
        shutil.rmtree(out, ignore_errors=True)
        try:
            os.replace(tmp, out)
        except OSError:
            if (out / DONE).exists() and (out / "model.bin").exists():
                shutil.rmtree(tmp, ignore_errors=True)
                return out
            raise
    log.info("model %s mirrored to %s", name, out)
    if progress:
        progress.finish(_dir_bytes(out))
    return out


def for_transcribe(name: str, cfg, download=_hf_download, progress=None) -> Path:
    """ensure_local for a transcription model, honoring TranscribeCfg.models_root."""
    if not cfg.models_root or is_local(name):  # e.g. dictation's turbo, already in the default dir
        return ensure_local(name, download=download, progress=progress)
    root = Path(cfg.models_root)
    return ensure_local(name, root=root, download=download, progress=progress, cache_dir=root / "hf")
