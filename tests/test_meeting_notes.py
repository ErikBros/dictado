"""Notes during a call (t0u.30): typed next to the live transcript, saved as notes.md in the
session, and part of Copy for Claude, the summary prompt and the .md export (Granola's idea:
your notes steer the summary)."""
from dictado import export
from tests.test_window_sessions import env, make  # noqa: F401  (fixture)

SEGS = [{"t0": 0.0, "t1": 2.0, "text": "Vi flyttar releasen till fredag.", "speaker": "Others"}]


def test_save_and_read_notes(env):
    api, root, *_ = env
    d = make(root, "Retro", 1, segs=SEGS)
    assert api.get_session(d.name)["notes"] == ""
    assert api.save_notes(d.name, "- release moved?\n- ask Tom about budget")["ok"]
    assert (d / "notes.md").read_text(encoding="utf-8") == "- release moved?\n- ask Tom about budget"
    assert api.get_session(d.name)["notes"].startswith("- release moved?")
    assert api.save_notes(d.name, "   ")["ok"] and not (d / "notes.md").exists()  # emptied = gone


def test_notes_while_recording(env):
    api, root, *_ = env
    d = make(root, "Live", 2, status="recording")
    assert api.save_notes(d.name, "decide on Friday")["ok"]
    assert api.get_live(d.name)["notes"] == "decide on Friday"


def test_copy_for_claude_and_summary_carry_the_notes(env):
    api, root, sent, copied, _ = env
    d = make(root, "Retro", 3, segs=SEGS)
    api.save_notes(d.name, "- ask Tom about budget")
    api.copy_transcript(d.name, "claude")
    assert "My notes:\n- ask Tom about budget" in copied[-1] and "Vi flyttar releasen" in copied[-1]
    api.copy_transcript(d.name, "summary")
    assert "my notes" in copied[-1].lower().split("transcript:")[0]  # the ask points at the notes
    assert "- ask Tom about budget" in copied[-1]


def test_without_notes_the_texts_are_unchanged():
    meta = {"title": "Retro", "created": "2026-10-05T14:00:00", "lang": "sv", "duration_s": 60}
    assert export.for_claude(meta, SEGS, "") == export.for_claude(meta, SEGS)
    assert "My notes" not in export.for_claude(meta, SEGS)
    assert "My notes" not in export.summary_prompt(meta, SEGS)


def test_md_export_has_the_notes(env):
    api, root, *_ = env
    api._downloads = root.parent / "Downloads"
    d = make(root, "Retro", 4, segs=SEGS)
    api.save_notes(d.name, "- ask Tom")
    api.save_export(d.name, "md")
    md = (d / "transcript.md").read_text(encoding="utf-8")
    assert "## My notes\n\n- ask Tom" in md and md.index("My notes") < md.index("Vi flyttar")
