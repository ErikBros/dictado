import json
import logging
from datetime import datetime

from ecoscribe import sessions

NOW = datetime(2026, 10, 2, 14, 5)


def test_create_layout_and_meta(tmp_path):
    d = sessions.create("Reunión Q3", "sv", "meeting", tmp_path, now=NOW)
    assert d.name == "2026-10-02_1405_reunion-q3"
    assert (d / "audio").is_dir()
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert m == {"title": "Reunión Q3", "lang": "sv", "source": "meeting", "created": NOW.isoformat(timespec="seconds"),
                 "status": "new", "duration_s": None, "model": None, "compute_type": None, "slow": False}


def test_same_minute_sessions_get_distinct_dirs(tmp_path):
    a = sessions.create("Reunión", "sv", "meeting", tmp_path, now=NOW)
    b = sessions.create("Reunión", "sv", "meeting", tmp_path, now=NOW)
    c = sessions.create("Reunión", "sv", "meeting", tmp_path, now=NOW)
    assert len({a, b, c}) == 3
    assert b.name.endswith("-2") and c.name.endswith("-3")


def test_slug_strips_illegal_chars():
    assert sessions.slug('Q3: plan/"final"?') == "q3-plan-final"
    assert sessions.slug("Ελληνικά") == "sesion"
    assert sessions.slug("") == "sesion"
    assert sessions.slug("Möte i Göteborg") == "mote-i-goteborg"
    assert len(sessions.slug("a" * 100)) == 40
    assert not sessions.slug("x" * 39 + " y").endswith("-")


def test_import_file_copies_with_extension(tmp_path):
    src = tmp_path / "Podcast 12.m4a"
    src.write_bytes(b"audio")
    d = sessions.import_file(src, "el", tmp_path / "root")
    assert (d / "audio" / "Podcast 12.m4a").read_bytes() == b"audio"
    m = sessions.read_meta(d)
    assert m["title"] == "Podcast 12" and m["source"] == "import" and m["lang"] == "el"
    assert src.exists()


def test_write_meta_merges_atomically(tmp_path):
    d = sessions.create("x", "en", "import", tmp_path, now=NOW)
    m = sessions.write_meta(d, status="done", duration_s=12.5)
    assert m["status"] == "done" and m["title"] == "x"
    assert sessions.read_meta(d)["duration_s"] == 12.5
    assert not list(d.glob("*.tmp"))


def test_list_newest_first_and_skips_broken_meta(tmp_path, caplog):
    old = sessions.create("old", "en", "import", tmp_path, now=datetime(2026, 9, 1, 9, 0))
    new = sessions.create("new", "en", "import", tmp_path, now=datetime(2026, 10, 1, 9, 0))
    broken = sessions.create("broken", "en", "import", tmp_path, now=datetime(2026, 10, 2, 9, 0))
    (broken / "meta.json").write_text("{nope", encoding="utf-8")
    (tmp_path / "stray.txt").write_text("not a session")
    with caplog.at_level(logging.WARNING):
        got = sessions.list_sessions(tmp_path)
    assert [g["title"] for g in got] == ["new", "old"]
    assert got[0]["dir"] == str(new) and got[1]["dir"] == str(old)
    assert "broken" in caplog.text


def test_list_missing_root_is_empty(tmp_path):
    assert sessions.list_sessions(tmp_path / "nope") == []


def test_rename_keeps_dir(tmp_path):
    d = sessions.create("Antes", "en", "import", tmp_path, now=NOW)
    sessions.rename(d, "Después")
    assert d.exists() and sessions.read_meta(d)["title"] == "Después"
    assert d.name.endswith("antes")


def test_delete_removes_folder(tmp_path):
    d = sessions.create("x", "en", "import", tmp_path, now=NOW)
    (d / "audio" / "a.wav").write_bytes(b"1")
    sessions.delete(d)
    assert not d.exists()
    assert sessions.list_sessions(tmp_path) == []


def test_root_dir_default_and_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ECOSCRIBE_DATA_DIR", str(tmp_path / "ecoscribe"))  # macOS data dir
    assert sessions.root_dir() == tmp_path / "ecoscribe" / "transcripts"
    assert sessions.root_dir(str(tmp_path / "x")) == tmp_path / "x"
