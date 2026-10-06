from dictado.detect import Detector, MicUse, app_from_nonpackaged, app_from_packaged, uses_from_entries


def use(app, on=True):
    return MicUse(app=app, in_use=on, start=1, stop=0 if on else 2)


def run(det, frames, step=2.0, t0=0.0):
    """frames: list of (uses, titles); returns events with their times."""
    out = []
    for i, (uses, titles) in enumerate(frames):
        ev = det.update(uses, titles, t0 + i * step)
        if ev:
            out.append(ev)
    return out


def test_call_app_starts_meeting():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome", False)], [], 0.0) is None
    ev = d.update([use("msteams")], [], 2.0)
    assert ev.kind == "start" and ev.app == "msteams" and ev.at == 2.0


def test_browser_without_second_signal_ignored():
    d = Detector(debounce_polls=1)
    frames = [([use("chrome")], ["Inbox - Gmail", "Dictado"])] * 900  # 30 min at 2 s
    assert run(d, frames) == []


def test_browser_with_meet_title_starts():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome")], ["Inbox - Gmail"], 0.0) is None
    ev = d.update([use("chrome")], ["Meet - abc-defg-hij - Google Chrome"], 2.0)
    assert ev.kind == "start" and ev.app == "chrome"


def test_own_process_excluded():
    d = Detector(debounce_polls=1)
    frames = [([use("dictado"), use("pythonw")], ["Microsoft Teams"])] * 50
    assert run(d, frames) == []


def test_short_release_within_grace_keeps_meeting():
    d = Detector(debounce_polls=1)
    frames = ([([use("msteams")], [])] * 5 + [([use("msteams", False)], [])] * 5
              + [([use("msteams")], [])] * 20 + [([use("msteams", False)], [])] * 9)
    evs = run(d, frames)
    assert [e.kind for e in evs] == ["start"]


def test_release_past_grace_ends():
    d = Detector(debounce_polls=1)
    assert d.update([use("msteams")], [], 0.0).kind == "start"
    assert d.update([use("msteams", False)], [], 100.0) is None  # released, seen at 100
    assert d.update([use("msteams", False)], [], 118.0) is None
    ev = d.update([use("msteams", False)], [], 120.0)
    assert ev.kind == "end" and ev.app == "msteams" and ev.at == 120.0
    assert d.update([use("msteams", False)], [], 122.0) is None


def test_one_meeting_at_a_time():
    d = Detector(debounce_polls=1)
    assert d.update([use("msteams")], [], 0.0).kind == "start"
    assert d.update([use("msteams"), use("slack")], [], 2.0) is None
    d.update([use("msteams", False), use("slack")], [], 4.0)
    ev = d.update([use("msteams", False), use("slack")], [], 30.0)
    assert ev.kind == "end" and ev.app == "msteams"
    ev = d.update([use("msteams", False), use("slack")], [], 32.0)
    assert ev.kind == "start" and ev.app == "slack"


def test_browser_meeting_ends_when_title_goes_even_if_tab_keeps_mic():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome")], ["Meet - x"], 0.0).kind == "start"
    d.update([use("chrome")], ["Inbox - Gmail"], 2.0)
    ev = d.update([use("chrome")], ["Inbox - Gmail"], 22.0)
    assert ev.kind == "end" and ev.app == "chrome"


def test_any_version_in_use_counts():
    # slack keeps one ConsentStore entry per app version: in use if ANY is
    uses = uses_from_entries([("C:#Users#E#AppData#Local#slack#app-4.51.191#slack.exe", 5, 9, True),
                              ("C:#Users#E#AppData#Local#slack#app-4.52.162#slack.exe", 7, 0, True)])
    assert [u.app for u in uses if u.in_use] == ["slack"]
    assert Detector(debounce_polls=1).update(uses, [], 0.0).app == "slack"


def test_parse_nonpackaged_path():
    assert app_from_nonpackaged("C:#Program Files#Slack#slack.exe") == "slack"
    assert app_from_nonpackaged("C:#Users#alex#AppData#Local#WisprFlow#app-1.5.433#Wispr Flow.exe") == "wispr flow"


def test_parse_packaged_name():
    assert app_from_packaged("MSTeams_8wekyb3d8bbwe") == "msteams"
    assert app_from_packaged("5319275A.WhatsAppDesktop_cv1g1gvanyjgm") == "whatsappdesktop"
    assert app_from_packaged("com.notion.app.desktop.notion_87smfmv0eebam") == "notion"


def test_whatsapp_desktop_counts_as_call_app():
    assert Detector(debounce_polls=1).update([use("whatsappdesktop")], [], 0.0).app == "whatsappdesktop"


def test_in_use_rule():
    uses = uses_from_entries([("MSTeams_8wekyb3d8bbwe", 5, 0, False), ("Claude_pzs8sxrjxfjjc", 0, 0, False),
                              ("C:#x#zoom.exe", 5, 6, True)])
    by = {u.app: u.in_use for u in uses}
    assert by == {"msteams": True, "claude": False, "zoom": False}


def test_start_needs_two_polls_by_default():
    d = Detector()
    assert d.update([use("telegram")], [], 0.0) is None  # a voice-note blip
    assert d.update([use("telegram", False)], [], 2.0) is None
    assert d.update([use("msteams")], [], 4.0) is None
    ev = d.update([use("msteams")], [], 6.0)
    assert ev.kind == "start" and ev.app == "msteams" and ev.at == 6.0


def test_meeting_title_only_counts_in_a_browser_window():
    d = Detector(debounce_polls=1)
    assert d.update([use("chrome")], [("Notes: Zoom with Anna", "notepad")], 0.0) is None
    ev = d.update([use("chrome")], [("Meet - abc - Google Chrome", "chrome")], 2.0)
    assert ev.kind == "start" and ev.app == "chrome"


def test_stale_desktop_entry_ignored_when_app_not_running():
    stale = MicUse(app="slack", in_use=True, start=1, stop=0, nonpackaged=True)
    d = Detector(debounce_polls=1)
    assert d.update([stale], [], 0.0, running={"chrome", "explorer"}) is None
    assert d.update([stale], [], 2.0, running={"slack"}).app == "slack"


def test_packaged_entries_not_checked_against_processes():
    # MSTeams' package family name is not its exe name (ms-teams.exe): never drop it
    d = Detector(debounce_polls=1)
    assert d.update([use("msteams")], [], 0.0, running={"explorer"}).app == "msteams"


def test_uses_from_entries_marks_nonpackaged():
    uses = {u.app: u for u in uses_from_entries([("MSTeams_8wekyb3d8bbwe", 5, 0, False), ("C:#x#zoom.exe", 5, 0, True)])}
    assert uses["zoom"].nonpackaged and not uses["msteams"].nonpackaged
