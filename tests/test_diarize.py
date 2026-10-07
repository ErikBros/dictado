"""Speakers pass (t0u.22): the add-on's turns -> Speaker 1..N on the remote segments."""
import json
from pathlib import Path

from ecoscribe import diarize, sessions
from ecoscribe.config import Config


def seg(t0, t1, speaker, text="x"):
    return {"t0": t0, "t1": t1, "text": text, "speaker": speaker}


TURNS = [[0.0, 5.0, "SPEAKER_01"], [5.5, 9.0, "SPEAKER_00"], [20.0, 25.0, "SPEAKER_01"]]


def test_remote_segments_take_the_speaker_they_overlap_most():
    segs = [seg(0.5, 4.0, "Others"), seg(4.0, 7.0, "Others"), seg(10.0, 12.0, "Me"), seg(21.0, 23.0, "Others")]
    assert diarize.assign(segs, TURNS, "Others") == 2
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2", "Me", "Speaker 1"]  # numbered by first voice


def test_no_overlap_takes_the_nearest_turn_within_2_s_else_stays():
    segs = [seg(0.0, 2.0, "Others"), seg(10.5, 11.0, "Others"), seg(15.0, 16.0, "Others"), seg(6.0, 8.0, "Others")]
    diarize.assign(segs, TURNS, "Others")
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2", "Others", "Speaker 2"]


def test_one_remote_voice_changes_nothing():
    segs = [seg(0.5, 4.0, "Others"), seg(21.0, 23.0, "Others"), seg(10.0, 12.0, "Me")]
    assert diarize.assign(segs, TURNS, "Others") == 1
    assert [s["speaker"] for s in segs] == ["Others", "Others", "Me"]  # a 1:1 call looks like today


def test_imports_label_the_unlabelled_segments():
    segs = [seg(0.5, 4.0, None), seg(6.0, 8.0, None)]
    assert diarize.assign(segs, TURNS, None) == 2
    assert [s["speaker"] for s in segs] == ["Speaker 1", "Speaker 2"]


def session(tmp_path, source="meeting", segs=None):
    d = sessions.create("Call", "es", source, tmp_path / "t")
    (d / "audio" / ("system.flac" if source == "meeting" else "call.m4a")).write_bytes(b"x")
    if source == "meeting":
        (d / "audio" / "mix.flac").write_bytes(b"x")
    segs = segs or [seg(0.5, 4.0, "Others" if source == "meeting" else None, "hola"),
                    seg(6.0, 8.0, "Others" if source == "meeting" else None, "qué tal")]
    (d / "transcript.json").write_text(json.dumps({"segments": segs, "lang": "es", "model": "m"}), encoding="utf-8")
    sessions.write_meta(d, status="done", duration_s=25.0, speakers="pending")
    return d


def fake_addon(turns, rc=0, calls=None):
    def run(audio, out):
        if calls is not None:
            calls.append(Path(audio).name)
        if rc == 0:
            Path(out).write_text(json.dumps(turns), encoding="utf-8")
        return rc
    return run


def test_run_labels_the_meeting_from_the_system_track_and_rewrites_exports(tmp_path):
    d, calls = session(tmp_path), []
    assert diarize.run(d, fake_addon(TURNS, calls=calls)) == 0
    assert calls == ["system.flac"]  # the user is the mic track: only the others are diarized
    tr = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    assert [s["speaker"] for s in tr["segments"]] == ["Speaker 1", "Speaker 2"]
    meta = sessions.read_meta(d)
    assert meta["speakers"] == "done" and meta["speakers_n"] == 2 and meta["status"] == "done"
    assert "Speaker 2:** qué tal" in (d / "transcript.md").read_text(encoding="utf-8")


def test_an_import_the_addon_cant_read_goes_through_a_temporary_flac(tmp_path):
    d, calls, conv = session(tmp_path, source="import"), [], []

    def convert(src, dst):
        conv.append(Path(src).name)
        Path(dst).write_bytes(b"flac")
    diarize.run(d, fake_addon(TURNS, calls=calls), convert=convert)
    assert conv == ["call.m4a"] and calls == ["speakers-input.flac"]
    assert not (d / "speakers-input.flac").exists()  # cleaned up
    assert [p.name for p in (d / "audio").iterdir()] == ["call.m4a"]  # never a second source in audio/


def test_a_flac_or_wav_import_goes_straight_in(tmp_path):
    d = session(tmp_path, source="import")
    (d / "audio" / "call.m4a").rename(d / "audio" / "call.wav")
    calls = []
    diarize.run(d, fake_addon(TURNS, calls=calls), convert=lambda s, t: 1 / 0)
    assert calls == ["call.wav"]


def test_a_failing_addon_leaves_the_transcript_alone(tmp_path):
    d = session(tmp_path)
    before = (d / "transcript.json").read_text(encoding="utf-8")
    assert diarize.run(d, fake_addon(TURNS, rc=3)) == 1
    meta = sessions.read_meta(d)
    assert meta["speakers"] == "failed" and meta["status"] == "done" and "3" in meta["speakers_error"]
    assert (d / "transcript.json").read_text(encoding="utf-8") == before


def test_available_needs_the_setting_and_the_addon(tmp_path):
    cfg = Config()
    exe = tmp_path / "DictadoSpeakers.exe"
    assert not diarize.available(cfg, exe)
    exe.write_bytes(b"x")
    assert diarize.available(cfg, exe)
    cfg.meetings.speakers = False
    assert not diarize.available(cfg, exe)
