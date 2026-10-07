"""Meeting names from the calendar (t0u.35): secret iCal feed, parsed and matched locally.
Every calendar here is made up: tests never read a real one."""
import json
from datetime import datetime, timedelta, timezone

from ecoscribe import calendar_ics as cal

UTC = timezone.utc
OWNER = "alex@example.com"


def ics(*events: str, owner: str = OWNER) -> str:
    body = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Google Inc//Google Calendar 70.9054//EN",
                        f"X-WR-CALNAME:{owner}", "X-WR-TIMEZONE:Europe/Stockholm",
                        *[e.strip().replace("\n", "\r\n") for e in events], "END:VCALENDAR"])
    return body + "\r\n"


RETRO = """BEGIN:VEVENT
DTSTART:20261006T080000Z
DTEND:20261006T083000Z
SUMMARY:Sprint retro\\, week 41
ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN=Ana Ruiz;X-NUM-GUESTS=0:mailto:ana@example.com
ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;CN=Johan
  Lindqvist;X-NUM-GUESTS=0:mailto:johan@example.com
ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN=alex@example.com:mailto:alex@example.com
ATTENDEE;CUTYPE=RESOURCE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN=Room 4:mailto:c_1@resource.calendar.google.com
ATTENDEE;CUTYPE=INDIVIDUAL;PARTSTAT=ACCEPTED:mailto:maria.k@example.com
DESCRIPTION:Join with Google Meet: https://meet.google.com/abc-defg-hij\\nAgenda
UID:retro@google.com
END:VEVENT"""


def at(h, m=0, day=6):
    return datetime(2026, 10, day, h, m, tzinfo=UTC)


def events(text, day=6):
    return cal.events_between(cal.parse(text), at(0, day=day), at(0, day=day) + timedelta(days=1))


def test_parses_title_times_and_people():
    [e] = events(ics(RETRO))
    assert e.title == "Sprint retro, week 41"
    assert (e.start, e.end) == (at(8), at(8, 30))
    # folded line joined; the owner and the room left out; no CN -> name from the address
    assert e.attendees == ["Ana Ruiz", "Johan Lindqvist", "Maria K"]
    assert "meet.google.com" in e.conference


def test_all_day_cancelled_and_declined_are_skipped():
    allday = "BEGIN:VEVENT\nDTSTART;VALUE=DATE:20261006\nDTEND;VALUE=DATE:20261007\nSUMMARY:Vacation\nEND:VEVENT"
    cancelled = "BEGIN:VEVENT\nDTSTART:20261006T090000Z\nDTEND:20261006T100000Z\nSUMMARY:Gone\nSTATUS:CANCELLED\nEND:VEVENT"
    declined = ("BEGIN:VEVENT\nDTSTART:20261006T090000Z\nDTEND:20261006T100000Z\nSUMMARY:Nope\n"
                "ATTENDEE;PARTSTAT=DECLINED;CN=Alex:mailto:alex@example.com\nEND:VEVENT")
    assert events(ics(allday, cancelled, declined)) == []


def test_weekly_recurrence_with_timezone_exdate_and_moved_instance():
    master = ("BEGIN:VEVENT\nDTSTART;TZID=Europe/Stockholm:20260901T093000\n"
              "DTEND;TZID=Europe/Stockholm:20260901T094500\nRRULE:FREQ=WEEKLY;BYDAY=TU\n"
              "EXDATE;TZID=Europe/Stockholm:20260929T093000\nSUMMARY:Standup\nUID:su@google.com\nEND:VEVENT")
    moved = ("BEGIN:VEVENT\nDTSTART;TZID=Europe/Stockholm:20261013T110000\n"
             "DTEND;TZID=Europe/Stockholm:20261013T111500\nRECURRENCE-ID;TZID=Europe/Stockholm:20261013T093000\n"
             "SUMMARY:Standup (moved)\nUID:su@google.com\nEND:VEVENT")
    text = ics(master, moved)
    [tue] = events(text, day=6)  # 2026-10-06 is a Tuesday; 09:30 Stockholm (CEST) = 07:30 UTC
    assert (tue.title, tue.start) == ("Standup", at(7, 30))
    sep29 = cal.events_between(cal.parse(text), datetime(2026, 9, 29, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC))
    assert sep29 == []  # EXDATE
    [oct13] = events(text, day=13)
    assert (oct13.title, oct13.start) == ("Standup (moved)", at(9, day=13))  # 11:00 CEST


def test_pick_the_event_happening_now():
    a = "BEGIN:VEVENT\nDTSTART:20261006T090000Z\nDTEND:20261006T100000Z\nSUMMARY:Planning\nEND:VEVENT"
    evs = events(ics(RETRO, a))
    assert cal.pick(evs, at(8, 10)).title == "Sprint retro, week 41"
    assert cal.pick(evs, at(7, 52)).title == "Sprint retro, week 41"  # joined 8 min early
    assert cal.pick(evs, at(8, 58)).title == "Planning"  # 2 min before Planning starts
    assert cal.pick(evs, at(11)) is None


def test_overlap_prefers_the_call_app_link():
    teams = ("BEGIN:VEVENT\nDTSTART:20261006T080000Z\nDTEND:20261006T090000Z\nSUMMARY:Client sync\n"
             "LOCATION:https://teams.microsoft.com/l/meetup-join/xyz\nEND:VEVENT")
    evs = events(ics(RETRO, teams))
    assert cal.pick(evs, at(8, 5), app="ms-teams").title == "Client sync"
    assert cal.pick(evs, at(8, 5), app="chrome").title == "Sprint retro, week 41"  # Meet in a browser


def test_feed_caches_and_survives_a_failed_fetch(tmp_path):
    clock = [at(8, 5).timestamp()]
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        if len(calls) > 1:
            raise OSError("offline")
        return ics(RETRO).encode()
    f = cal.CalendarFeed("https://calendar.google.com/calendar/ical/x/private-abc/basic.ics", tmp_path,
                         fetch=fetch, clock=lambda: clock[0])
    assert f.refresh() is True
    assert f.lookup(at(8, 5)).title == "Sprint retro, week 41"
    assert f.refresh() is False  # fresh enough: no second download within 10 min
    clock[0] += 3600
    assert f.refresh() is False and len(calls) == 2  # offline: keeps the cached copy
    again = cal.CalendarFeed(f.url, tmp_path, fetch=fetch, clock=lambda: clock[0])
    assert again.lookup(at(8, 5)).title == "Sprint retro, week 41"  # read from the cache file


def test_feed_without_url_does_nothing(tmp_path):
    f = cal.CalendarFeed("", tmp_path, fetch=lambda u, t: 1 / 0)
    assert f.refresh() is False and f.lookup(at(8)) is None


def test_meeting_info_for_meta():
    [e] = events(ics(RETRO))
    info = cal.meta_info(e)
    assert info == {"title": "Sprint retro, week 41", "attendees": ["Ana Ruiz", "Johan Lindqvist", "Maria K"],
                    "start": "2026-10-06T08:00:00+00:00", "end": "2026-10-06T08:30:00+00:00"}
    json.dumps(info)


def test_valid_url():
    assert cal.valid_url("https://calendar.google.com/calendar/ical/a%40b.com/private-123/basic.ics")
    assert cal.valid_url("webcal://calendar.google.com/x/basic.ics")
    assert not cal.valid_url("http://example.com/x.ics") and not cal.valid_url("hello")


# -- wiring: meeting start, prompt words, Copy for Claude, Settings ------------------------------
class FakeFeed:
    def __init__(self, ev):
        self.ev, self.asked = ev, []

    def lookup(self, now=None, app=None):
        self.asked.append(app)
        return self.ev


def _ctl(tmp_path, feed):
    from tests.test_meetings import make
    c, sp, ev, changes = make(tmp_path)
    c.calendar = feed
    return c


def test_meeting_named_from_the_calendar(tmp_path):
    from ecoscribe import sessions
    [e] = events(ics(RETRO))
    feed = FakeFeed(e)
    c = _ctl(tmp_path, feed)
    d = c.start_meeting("sv", app="chrome")
    meta = sessions.read_meta(d)
    assert meta["title"] == "Sprint retro, week 41" and feed.asked == ["chrome"]
    assert meta["calendar"]["attendees"] == ["Ana Ruiz", "Johan Lindqvist", "Maria K"]


def test_given_title_and_no_event_keep_their_names(tmp_path):
    from ecoscribe import sessions
    [e] = events(ics(RETRO))
    c = _ctl(tmp_path, FakeFeed(e))
    assert sessions.read_meta(c.start_meeting("sv", title="Mine"))["title"] == "Mine"
    c2 = _ctl(tmp_path / "b", FakeFeed(None))
    assert sessions.read_meta(c2.start_meeting("sv"))["title"] == "Meeting"


def test_broken_calendar_never_stops_a_meeting(tmp_path):
    from ecoscribe import sessions

    class Boom:
        def lookup(self, now=None, app=None):
            raise RuntimeError("bad file")
    c = _ctl(tmp_path, Boom())
    assert sessions.read_meta(c.start_meeting("sv"))["title"] == "Meeting"


def test_attendees_join_the_prompt_words(tmp_path):
    from ecoscribe import sessions
    d = sessions.create("x", "sv", "meeting", tmp_path / "t")
    sessions.write_meta(d, calendar={"title": "x", "attendees": ["Ana Ruiz", "Göran"]})
    assert cal.session_words(d, ["Göteborg", "Ana Ruiz"]) == ["Göteborg", "Ana Ruiz", "Göran"]
    d2 = sessions.create("y", "sv", "meeting", tmp_path / "t")
    assert cal.session_words(d2, ["Göteborg"]) == ["Göteborg"]


def test_copy_for_claude_lists_attendees():
    from ecoscribe import export
    meta = {"title": "Retro", "created": "2026-10-06T10:00:00", "calendar": {"attendees": ["Ana Ruiz", "Johan"]}}
    assert "Attendees: Ana Ruiz, Johan" in export.for_claude(meta, [])
    assert "Attendees" not in export.for_claude({"title": "x"}, [])


def _api(tmp_path, fetch=None):
    from ecoscribe.window import Api
    a = Api(data_dir=tmp_path / "data", config_path=tmp_path / "cfg" / "config.toml", signal_reload=lambda: True)
    if fetch:
        a._calendar_fetch = fetch
    return a


URL = "https://calendar.google.com/calendar/ical/x%40example.com/private-abc/basic.ics"


def test_settings_saves_and_checks_the_link(tmp_path):
    from ecoscribe import config
    a = _api(tmp_path)
    assert a.get_settings()["values"]["calendar_url"] == ""
    assert a.save_settings({"calendar_url": "  " + URL + " "})["ok"]
    assert config.load(tmp_path / "cfg" / "config.toml").meetings.calendar_url == URL
    bad = a.save_settings({"calendar_url": "my calendar"})
    assert not bad["ok"] and "link" in bad["error"]
    assert a.save_settings({"calendar_url": ""})["ok"]  # clearing turns it off


def test_settings_test_button_downloads_and_says_what_it_found(tmp_path):
    a = _api(tmp_path, fetch=lambda u, t: ics(RETRO).encode())
    out = a.test_calendar(URL, now=at(8, 5).isoformat())
    assert out["ok"] and out["today"] == 1 and out["now"] == "Sprint retro, week 41"
    assert (tmp_path / "data" / "calendar.ics").exists()
    assert not a.test_calendar("nope")["ok"]
    fail = _api(tmp_path / "b", fetch=lambda u, t: b"<html>sign in</html>").test_calendar(URL)
    assert not fail["ok"] and "calendar" in fail["error"].lower()


def test_background_app_sets_the_feed_only_with_a_link(tmp_path):
    import logging
    from ecoscribe.__main__ import _calendar_feed
    from ecoscribe.config import Config
    c, ctl = Config(), type("C", (), {"calendar": None})()
    assert _calendar_feed(c, tmp_path, ctl, logging.getLogger()) is None and ctl.calendar is None
    c.meetings.calendar_url = "not a link"
    assert _calendar_feed(c, tmp_path, ctl, logging.getLogger()) is None
    c.meetings.calendar_url = URL
    feed = _calendar_feed(c, tmp_path, ctl, logging.getLogger())
    assert feed is not None and ctl.calendar is feed
