"""The speaker add-on on macOS: where Dictado finds it, and which device the add-on tries (dictado-4yu)."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dictado.platform.macos import speakers

MAIN = Path(__file__).resolve().parent.parent / "packaging" / "speakers" / "speakers_main.py"


def _main_module():
    spec = importlib.util.spec_from_file_location("speakers_main", MAIN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fake_torch(cuda=False, mps=None):
    backends = SimpleNamespace() if mps is None else SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps))
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda), backends=backends)


def test_device_order():
    m = _main_module()
    assert m.devices(fake_torch(cuda=True, mps=True)) == ["cuda"]
    assert m.devices(fake_torch(mps=True)) == ["mps", "cpu"]  # Apple GPU, CPU if MPS fails
    assert m.devices(fake_torch(mps=False)) == ["cpu"]
    assert m.devices(fake_torch()) == ["cpu"]  # an old torch without MPS


def test_addon_found_in_applications_or_home(tmp_path, monkeypatch):
    sysapps = tmp_path / "sys"
    monkeypatch.setattr(speakers, "Path", lambda *a: Path(*a) if a != ("/Applications",) else sysapps)
    home = tmp_path / "home"
    assert speakers.addon_exe(home) == sysapps / speakers.BINARY  # nowhere: where it will be
    (home / "Applications" / speakers.BINARY).parent.mkdir(parents=True)
    (home / "Applications" / speakers.BINARY).write_text("")
    assert speakers.addon_exe(home) == home / "Applications" / speakers.BINARY
    (sysapps / speakers.BINARY).parent.mkdir(parents=True)
    (sysapps / speakers.BINARY).write_text("")
    assert speakers.addon_exe(home) == sysapps / speakers.BINARY


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS")
def test_diarize_uses_the_mac_path():
    from dictado import diarize
    assert diarize.addon_exe is speakers.addon_exe
