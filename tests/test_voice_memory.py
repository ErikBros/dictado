"""Local voice memory (t0u.32): a person named once is recognised in later calls.

The speaker add-on (1.1.0) writes one embedding per voice next to its turns. Ecoscribe keeps
them per session (voices.json) and, when the user names a speaker, learns that voice under the
name in %LOCALAPPDATA%\\ecoscribe\\voices.json. The next call's voices are compared by cosine;
a match names the speaker by itself. Nothing leaves the PC; [meetings] voice_memory = false
stores nothing. Threshold from real podcasts (spike/voice_memory, 2026-10-05): the same
person across recordings 0.75-0.99, different people at most 0.28 -> 0.55, and only voices
with at least 8 s of speech.
"""
import json
from pathlib import Path

from ecoscribe import diarize, sessions, voices
from tests.test_diarize import seg

ANA, TOM, NEW = [1.0, 0.1, 0.0, 0.0], [0.0, 1.0, 0.1, 0.0], [0.0, 0.0, 0.2, 1.0]


def near(v, k=0.15):
    return [x + (k if i == 3 else 0) for i, x in enumerate(v)]


def test_match_names_known_voices_once():
    mem = {"Ana": {"emb": ANA, "n": 1}, "Tom": {"emb": TOM, "n": 1}}
    got = voices.match({"Speaker 1": near(ANA), "Speaker 2": NEW}, mem)
    assert list(got) == ["Speaker 1"] and got["Speaker 1"][0] == "Ana" and got["Speaker 1"][1] > 0.9
    two = voices.match({"Speaker 1": near(ANA, 0.3), "Speaker 2": near(ANA, 0.05)}, mem)
    assert two == {"Speaker 2": ("Ana", two["Speaker 2"][1])}  # one name, the closest voice


def test_learn_averages_and_forget(tmp_path):
    p = tmp_path / "voices.json"
    voices.learn(p, "Ana", ANA)
    voices.learn(p, "Ana", near(ANA, 0.4))
    mem = voices.load(p)
    assert mem["Ana"]["n"] == 2 and voices.cosine(mem["Ana"]["emb"], ANA) > 0.95
    assert voices.names(p) == ["Ana"]
    voices.forget(p)
    assert voices.load(p) == {}


def call(tmp_path, turns, segs, emb):
    d = sessions.create("Call", "sv", "meeting", tmp_path / "t")
    (d / "audio" / "system.flac").write_bytes(b"x")
    (d / "transcript.json").write_text(json.dumps({"segments": segs}), encoding="utf-8")
    sessions.write_meta(d, status="done", duration_s=60.0, speakers="pending")

    def addon(audio, out):
        Path(out).write_text(json.dumps(turns), encoding="utf-8")
        if emb is not None:
            Path(str(Path(out).with_suffix("")) + ".voices.json").write_text(json.dumps(emb), encoding="utf-8")
        return 0
    return d, addon


TURNS = [[0.0, 10.0, "SPEAKER_00"], [10.0, 22.0, "SPEAKER_01"], [22.0, 24.0, "SPEAKER_02"]]
SEGS = [seg(1, 9, "Others"), seg(11, 21, "Others"), seg(22.5, 23.5, "Others"), seg(30, 31, "Me")]


def test_a_known_voice_is_named_in_the_next_call(tmp_path):
    mem = tmp_path / "voices.json"
    voices.learn(mem, "Ana", ANA)
    d, addon = call(tmp_path, TURNS, SEGS, {"SPEAKER_00": NEW, "SPEAKER_01": near(ANA), "SPEAKER_02": ANA})
    assert diarize.run(d, run_addon=addon, memory=mem) == 0
    meta = sessions.read_meta(d)
    assert meta["speaker_names"] == {"Speaker 2": "Ana"}  # SPEAKER_02 sounds like Ana too, but 2 s is too short
    assert set(json.loads((d / "voices.json").read_text())) == {"Speaker 1", "Speaker 2"}
    assert "Ana" in (d / "transcript.md").read_text(encoding="utf-8")


def test_one_to_one_call_names_others(tmp_path):
    mem = tmp_path / "voices.json"
    voices.learn(mem, "Ana", ANA)
    d, addon = call(tmp_path, [[0.0, 20.0, "SPEAKER_00"]], [seg(1, 19, "Others"), seg(20, 21, "Me")], {"SPEAKER_00": ANA})
    diarize.run(d, run_addon=addon, memory=mem)
    assert sessions.read_meta(d)["speaker_names"] == {"Others": "Ana"}


def test_off_or_old_addon_stores_nothing(tmp_path):
    mem = tmp_path / "voices.json"
    d, addon = call(tmp_path, TURNS, SEGS, {"SPEAKER_00": NEW, "SPEAKER_01": ANA})
    assert diarize.run(d, run_addon=addon, memory=None) == 0
    assert not (d / "voices.json").exists() and not mem.exists()
    d2, old = call(tmp_path, TURNS, SEGS, None)
    assert diarize.run(d2, run_addon=old, memory=mem) == 0 and sessions.read_meta(d2)["speakers"] == "done"


def test_naming_a_speaker_teaches_the_memory(tmp_path):
    from ecoscribe.window import Api
    root = tmp_path / "t"
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[transcribe]\nroot = "{root.as_posix()}"\n', encoding="utf-8")
    d, addon = call(tmp_path, TURNS, SEGS, {"SPEAKER_00": NEW, "SPEAKER_01": ANA})
    diarize.run(d, run_addon=addon, memory=tmp_path / "data" / "voices.json")
    api = Api(data_dir=tmp_path / "data", config_path=cfg, signal_reload=lambda: True)
    assert api.rename_speaker(d.name, "Speaker 2", "Ana")["ok"]
    assert voices.names(tmp_path / "data" / "voices.json") == ["Ana"]
    assert api.voices_info() == {"count": 1, "names": ["Ana"], "on": True}
    assert api.forget_voices()["ok"] and api.voices_info()["count"] == 0
