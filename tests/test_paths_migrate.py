"""Rename phase 2 (dictado-c9u): the Dictado folders move to the Ecoscribe ones on first start."""
import json
import sys

import pytest

from ecoscribe import paths


def _old(tmp_path):
    old = tmp_path / "dictado"
    (old / "transcripts" / "2026-10-05_1535_meeting").mkdir(parents=True)
    (old / "history.jsonl").write_text('{"text": "hola"}\n', encoding="utf-8")
    return old


def test_moves_when_new_is_missing(tmp_path):
    old, new = _old(tmp_path), tmp_path / "ecoscribe"
    assert paths.migrate(old, new, lambda: False) == "moved"
    assert not old.exists() and (new / "history.jsonl").read_text(encoding="utf-8") == '{"text": "hola"}\n'
    assert (new / "transcripts" / "2026-10-05_1535_meeting").is_dir()


def test_nothing_to_do_without_an_old_folder(tmp_path):
    assert paths.migrate(tmp_path / "dictado", tmp_path / "ecoscribe", lambda: False) == "none"
    assert not (tmp_path / "ecoscribe").exists()


def test_keeps_both_when_new_has_data(tmp_path):
    old, new = _old(tmp_path), tmp_path / "ecoscribe"
    new.mkdir()
    (new / "history.jsonl").write_text("new\n", encoding="utf-8")
    assert paths.migrate(old, new, lambda: False) == "kept"
    assert (new / "history.jsonl").read_text(encoding="utf-8") == "new\n"
    assert (old / "history.jsonl").exists()  # left alone, never merged or deleted


@pytest.mark.parametrize("early", [[], ["mcp.log"], ["mcp.log", "ecoscribe.log"]])
def test_an_empty_or_log_only_new_folder_does_not_block_the_move(tmp_path, early):
    old, new = _old(tmp_path), tmp_path / "ecoscribe"
    new.mkdir()  # an early data_dir() call, e.g. the Claude app's --mcp while the old app still ran
    for name in early:
        (new / name).write_text("early\n", encoding="utf-8")
    assert paths.migrate(old, new, lambda: False) == "moved"
    assert (new / "history.jsonl").exists()


def test_waits_while_the_old_app_runs(tmp_path):
    old, new = _old(tmp_path), tmp_path / "ecoscribe"
    new.mkdir()
    (new / "mcp.log").write_text("in use\n", encoding="utf-8")
    assert paths.migrate(old, new, lambda: True) == "busy"
    assert old.exists() and (new / "mcp.log").exists()  # nothing touched while it runs
    assert paths.migrate(old, new, lambda: False) == "moved"  # next start


def test_queued_jobs_follow_the_folder(tmp_path):
    old, new = _old(tmp_path), tmp_path / "ecoscribe"
    job = old / "transcripts" / "2026-10-05_1535_meeting"
    (old / "meetings.json").write_text(json.dumps(
        {"meeting": None, "job": None, "queue": [{"dir": str(job)}], "next_meeting": None,
         "note": str(tmp_path / "dictado-other")}), encoding="utf-8")
    assert paths.migrate(old, new, lambda: False) == "moved"
    state = json.loads((new / "meetings.json").read_text(encoding="utf-8"))
    assert state["queue"][0]["dir"] == str(new / "transcripts" / "2026-10-05_1535_meeting")
    assert state["note"] == str(tmp_path / "dictado-other")  # only paths inside the old folder


@pytest.mark.skipif(sys.platform == "darwin", reason="Windows folders (macOS: the Mac session's darwin test)")
def test_windows_pairs_are_data_and_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "L"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "R"))
    assert paths.renamed_dirs() == [(tmp_path / "L" / "dictado", tmp_path / "L" / "ecoscribe"),
                                    (tmp_path / "R" / "dictado", tmp_path / "R" / "ecoscribe")]
    _old(tmp_path / "L")
    (tmp_path / "R" / "dictado").mkdir(parents=True)
    (tmp_path / "R" / "dictado" / "config.toml").write_text("[whisper]\n", encoding="utf-8")
    done = paths.migrate_all(lambda: False)
    assert [r for _, _, r in done] == ["moved", "moved"]
    assert paths.config_path().read_text(encoding="utf-8") == "[whisper]\n"
    assert (paths.data_dir() / "history.jsonl").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the old app's named mutex")
def test_old_app_running_sees_the_old_mutex():
    import win32api
    import win32event
    if paths.old_app_running():
        pytest.skip("a real Dictado runs on this PC")
    h = win32event.CreateMutex(None, False, paths.OLD_INSTANCE)
    try:
        assert paths.old_app_running() is True
    finally:
        win32api.CloseHandle(h)
    assert paths.old_app_running() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS folders")
def test_mac_pair_is_application_support(tmp_path, monkeypatch):
    monkeypatch.delenv("ECOSCRIBE_DATA_DIR", raising=False)
    support = paths.Path.home() / "Library" / "Application Support"
    assert paths.renamed_dirs() == [(support / "Dictado", support / "Ecoscribe")]
    monkeypatch.setenv("ECOSCRIBE_DATA_DIR", str(tmp_path))  # a test data dir: never touch the real folders
    assert paths.renamed_dirs() == []


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS folders")
def test_mac_move_brings_config_and_data(tmp_path, monkeypatch):
    old, new = tmp_path / "Dictado", tmp_path / "Ecoscribe"
    monkeypatch.setattr(paths, "renamed_dirs", lambda: [(old, new)])
    _old(tmp_path).rename(old)
    (old / "config.toml").write_text("[whisper]\n", encoding="utf-8")
    (old / "run").mkdir()
    (old / "run" / "DictadoSingleInstance.lock").write_text("")  # left by the old app, which has quit
    assert [r for _, _, r in paths.migrate_all(lambda: False)] == ["moved"]
    assert (new / "config.toml").read_text(encoding="utf-8") == "[whisper]\n"
    assert (new / "history.jsonl").exists() and not old.exists()
