"""Window API for the Reuniones page (sessions on disk, commands faked)."""
import json
from datetime import datetime

import pytest

from dictado import meetings, sessions
from dictado.window import Api


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "transcripts"
    cfg_path = tmp_path / "cfg" / "config.toml"
    cfg_path.parent.mkdir()
    cfg_path.write_text(f'[transcribe]\nroot = "{root.as_posix()}"\n', encoding="utf-8")
    sent, copied = [], []
    api = Api(data_dir=tmp_path / "data", config_path=cfg_path, copy=copied.append, signal_reload=lambda: True,
              send_command=lambda d, cmd, args=None: sent.append((cmd, args)) or {"ok": True})
    (tmp_path / "data").mkdir()
    return api, root, sent, copied, tmp_path / "data"


def make(root, title, minute, status="done", segs=None, lang="sv"):
    d = sessions.create(title, lang, "meeting", root, now=datetime(2026, 10, 5, 14, minute))
    sessions.write_meta(d, status=status, duration_s=60.0)
    if segs is not None:
        (d / "transcript.json").write_text(json.dumps({"segments": segs}), encoding="utf-8")
    return d


def test_list_newest_first_and_search(env):
    api, root, *_ = env
    make(root, "Planering", 1)
    make(root, "Retro", 2)
    rows = api.list_sessions()["items"]
    assert [r["title"] for r in rows] == ["Retro", "Planering"]
    assert rows[0]["lang_name"] == "Swedish" and rows[0]["status"] == "done"
    assert [r["title"] for r in api.list_sessions("plan")["items"]] == ["Planering"]


def test_get_session_and_copy(env):
    api, root, _, copied, _ = env
    d = make(root, "Retro", 2, segs=[{"t0": 0, "t1": 2, "text": "Hej", "speaker": "Others"}])
    s = api.get_session(d.name)
    assert s["segments"][0]["text"] == "Hej" and s["session"]["name"] == d.name
    assert api.copy_transcript(d.name)["ok"] and "Hej" in copied[-1]
    api.copy_transcript(d.name, "claude")
    assert copied[-1].startswith("Transcript: Retro")


def test_names_cannot_escape_the_root(env):
    api, root, *_ = env
    make(root, "Retro", 2)
    with pytest.raises(FileNotFoundError):
        api.get_session("..\\..\\Windows")


def test_live_since_cursor(env):
    api, root, *_ = env
    d = make(root, "Live", 3, status="recording")
    with open(d / "live.jsonl", "w", encoding="utf-8") as f:
        for i in range(3):
            f.write(json.dumps({"t0": i, "t1": i + 1, "text": f"rad {i}"}) + "\n")
        f.write('{"t0": 9')  # being written
    a = api.get_live(d.name, 0)
    assert [l["text"] for l in a["lines"]] == ["rad 0", "rad 1", "rad 2"] and a["next"] == 3
    b = api.get_live(d.name, a["next"])
    assert b["lines"] == [] and b["next"] == 3 and b["session"]["status"] == "recording"


def test_delete_refuses_what_is_running(env):
    api, root, _, _, data = env
    rec = make(root, "Ahora", 4, status="recording")
    done = make(root, "Vieja", 1)
    (data / meetings.STATE).write_text(json.dumps({"meeting": {"dir": str(rec)}, "job": None, "queue": []}),
                                       encoding="utf-8")
    assert not api.delete_session(rec.name)["ok"] and rec.exists()
    assert api.delete_session(done.name)["ok"] and not done.exists()
    assert api.meetings_state()["meeting"]["name"] == rec.name


def test_rename_and_commands(env):
    api, root, sent, *_ = env
    d = make(root, "Reunión", 5)
    assert not api.rename_session(d.name, "  ")["ok"]
    api.rename_session(d.name, "Retro v41")
    assert sessions.read_meta(d)["title"] == "Retro v41"
    api.start_meeting("sv")
    api.stop_meeting()
    assert not api.import_files([], "el")["ok"]
    api.import_files(["C:/x/pod.mp3"], "el")
    assert sent == [("start_meeting", {"lang": "sv"}), ("stop_meeting", None),
                    ("import_files", {"paths": ["C:/x/pod.mp3"], "lang": "el"})]


def test_delete_refuses_queued_sessions(env):
    api, root, _, _, data = env
    q = make(root, "En cola", 6, status="queued")
    (data / meetings.STATE).write_text(json.dumps({"meeting": None, "job": None, "queue": [str(q)]}), encoding="utf-8")
    assert not api.delete_session(q.name)["ok"] and q.exists()


def test_download_goes_straight_to_downloads(env, tmp_path):
    api, root, *_ = env
    api._downloads = tmp_path / "Downloads"
    d = make(root, "Retro v41", 7, segs=[{"t0": 0, "t1": 2, "text": "Hej", "speaker": "Others"}])
    a = api.save_export(d.name, "md")
    b = api.save_export(d.name, "md")
    assert a["ok"] and b["ok"] and a["name"] != b["name"]  # never overwrites the first download
    assert (tmp_path / "Downloads" / a["name"]).read_text(encoding="utf-8").startswith("# Retro v41")
    assert a["name"].endswith("retro-v41.md")
    api.rename_session(d.name, "Sprint retro")
    c = api.save_export(d.name, "md")
    assert (tmp_path / "Downloads" / c["name"]).read_text(encoding="utf-8").startswith("# Sprint retro")


def test_rename_a_speaker_everywhere(env):
    """t0u.22: click a label, type a name: view, .md and Copy for Claude use it."""
    api, root, _, copied, _ = env
    d = make(root, "Familia", 3, segs=[{"t0": 0, "t1": 2, "text": "Hola", "speaker": "Speaker 1"},
                                       {"t0": 3, "t1": 4, "text": "Qué tal", "speaker": "Speaker 2"},
                                       {"t0": 5, "t1": 6, "text": "Bien", "speaker": "Me"}])
    sessions.write_meta(d, speakers="done", speakers_n=2)
    assert api.rename_speaker(d.name, "Speaker 2", "  Mamá ")["ok"]
    s = api.get_session(d.name)
    assert s["session"]["speaker_names"] == {"Speaker 2": "Mamá"} and s["session"]["speakers"] == "done"
    assert "**[00:00:03] Mamá:** Qué tal" in (d / "transcript.md").read_text(encoding="utf-8")
    api.copy_transcript(d.name, "claude")
    assert "Mamá:** Qué tal" in copied[-1] and "Speaker 1:** Hola" in copied[-1]
    assert api.rename_speaker(d.name, "Speaker 2", "")["ok"]  # empty = back to the label
    assert api.get_session(d.name)["session"]["speaker_names"] == {}
    assert not api.rename_speaker(d.name, "Speaker 9", "X")["ok"]  # not a label of this session


def test_speakers_setting_round_trips(env):
    api, *_ = env
    s = api.get_settings()
    assert s["values"]["speakers"] is True and s["speakers_addon"] in (True, False)
    assert api.save_settings({"speakers": False})["ok"]
    assert api.get_settings()["values"]["speakers"] is False


def test_copy_summary_prompt(env):
    """Deep dive 2026-10-05: every meeting app summarises; Dictado hands Claude a ready prompt."""
    api, root, _, copied, _ = env
    d = make(root, "Plan", 4, segs=[{"t0": 0, "t1": 2, "text": "Vi kör på fredag", "speaker": "Others"}])
    api.copy_transcript(d.name, "summary")
    assert copied[-1].startswith("Summarize this meeting") and "action items" in copied[-1]
    assert "Others:** Vi kör på fredag" in copied[-1] and "Date:" in copied[-1]


def test_voice_commands_setting_round_trips(env):
    api, *_ = env
    assert api.get_settings()["values"]["voice_commands"] is False  # off by default
    assert api.save_settings({"voice_commands": True})["ok"]
    assert api.get_settings()["values"]["voice_commands"] is True
