"""Meeting names from the calendar (t0u.35).

The user pastes their calendar's secret iCal address (Google Calendar > Settings > Integrate
calendar > Secret address in iCal format) into Settings. The background app downloads it
every 10 min and when a call is detected, keeps a copy in the data folder, and at a
meeting's start picks the event happening now: its title names the session and its
attendees go into that call's Whisper prompt and Copy for Claude.

Read-only and local: the link is a secret (anyone with it can read the calendar), so it
is only kept in config.toml and never written to a log. Small RFC 5545 reader, no
dependency beyond python-dateutil for repeating events.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)
UTC = timezone.utc
CACHE = "calendar.ics"
MAX_AGE_S = 600     # download at most every 10 min (a detected call forces one)
EARLY_S = 600       # a call that starts up to 10 min before the event belongs to it
MAX_BYTES = 30_000_000

# call app (detect.py names) -> what its link looks like in the event
APP_LINKS = {"teams": "teams.microsoft", "msteams": "teams.microsoft", "ms-teams": "teams.microsoft",
             "zoom": "zoom.us", "webex": "webex.com", "ciscocollabhost": "webex.com", "slack": "slack.com",
             "chrome": "meet.google", "msedge": "meet.google", "firefox": "meet.google", "brave": "meet.google",
             "opera": "meet.google"}


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    attendees: list[str] = field(default_factory=list)
    conference: str = ""
    uid: str = ""


@dataclass
class _Raw:
    props: list[tuple[str, dict, str]]

    def get(self, name: str):
        for n, p, v in self.props:
            if n == name:
                return p, v
        return None, None

    def all(self, name: str):
        return [(p, v) for n, p, v in self.props if n == name]


@dataclass
class Calendar:
    owner: str | None
    tz: str | None
    events: list[_Raw]


# -- parsing ------------------------------------------------------------------------------------
def _split_params(head: str) -> tuple[str, dict]:
    parts, cur, q = [], "", False
    for ch in head:
        if ch == '"':
            q = not q
        elif ch == ";" and not q:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params


def _line(line: str):
    q = False
    for i, ch in enumerate(line):
        if ch == '"':
            q = not q
        elif ch == ":" and not q:
            name, params = _split_params(line[:i])
            return name, params, line[i + 1:]
    return None


def _text(v: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v).strip()


def parse(text: str | bytes) -> Calendar:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold
    owner = tz = None
    events: list[_Raw] = []
    cur: list | None = None
    depth = 0  # VALARM etc. inside an event
    for raw in text.splitlines():
        got = _line(raw)
        if not got:
            continue
        name, params, value = got
        if name == "BEGIN":
            if value.upper() == "VEVENT" and cur is None:
                cur, depth = [], 0
            elif cur is not None:
                depth += 1
            continue
        if name == "END":
            if cur is not None and depth:
                depth -= 1
            elif cur is not None and value.upper() == "VEVENT":
                events.append(_Raw(cur))
                cur = None
            continue
        if cur is not None:
            if not depth:
                cur.append((name, params, value))
        elif name == "X-WR-CALNAME" and "@" in value:
            owner = value.strip().lower()
        elif name == "X-WR-TIMEZONE":
            tz = value.strip()
    return Calendar(owner, tz, events)


def _zone(name: str | None):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def _when(params: dict, value: str, default_tz) -> datetime | date | None:
    v = value.strip().split(",")[0]
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
            return datetime.strptime(v, "%Y%m%d").date()
        dt = datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if v.endswith("Z"):
        return dt.replace(tzinfo=UTC)
    tz = _zone(params.get("TZID")) or default_tz
    return dt.replace(tzinfo=tz) if tz else dt.astimezone()  # floating: this PC's time


def _name_of(email: str) -> str:
    local = email.split("@")[0]
    return " ".join(w.capitalize() for w in re.split(r"[._\-+]+", local) if w)


def _people(ev: _Raw, owner: str | None) -> tuple[list[str], bool]:
    """(attendee names without the owner and rooms, declined by the owner)."""
    names, declined = [], False
    for p, v in ev.all("ATTENDEE"):
        email = re.sub(r"(?i)^mailto:", "", v).strip().lower()
        if owner and email == owner:
            declined = p.get("PARTSTAT", "").upper() == "DECLINED"
            continue
        if p.get("CUTYPE", "INDIVIDUAL").upper() in ("RESOURCE", "ROOM") or email.endswith("resource.calendar.google.com"):
            continue
        cn = p.get("CN", "").strip()
        name = cn if cn and "@" not in cn else _name_of(email)
        if name and name not in names:
            names.append(name)
    return names, declined


def _conference(ev: _Raw) -> str:
    return " ".join(v for n, _, v in ev.props
                    if n in ("LOCATION", "DESCRIPTION", "URL", "X-GOOGLE-CONFERENCE")).lower()


def _base(ev: _Raw, cal: Calendar):
    """Event for one VEVENT at its own time, or None if it can't name a meeting."""
    default_tz = _zone(cal.tz)
    p, v = ev.get("DTSTART")
    if v is None:
        return None
    start = _when(p, v, default_tz)
    if not isinstance(start, datetime):
        return None  # all-day: not a call
    p2, v2 = ev.get("DTEND")
    end = _when(p2, v2, default_tz) if v2 else None
    if not isinstance(end, datetime):
        dur = ev.get("DURATION")[1]
        m = re.fullmatch(r"P?T?(?:(\d+)H)?(?:(\d+)M)?", dur or "")
        end = start + (timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0)) if m and dur else timedelta(hours=1))
    _, status = ev.get("STATUS")
    if (status or "").upper() == "CANCELLED":
        return None
    people, declined = _people(ev, cal.owner)
    if declined:
        return None
    title = _text(ev.get("SUMMARY")[1] or "").strip()
    return Event(title=title, start=start, end=end, attendees=people, conference=_conference(ev),
                 uid=(ev.get("UID")[1] or "").strip())


def _key(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%S")


def events_between(cal: Calendar, lo: datetime, hi: datetime) -> list[Event]:
    """Timed, not cancelled, not declined events overlapping [lo, hi), repeats expanded."""
    out: list[Event] = []
    moved: set[tuple[str, str]] = set()
    default_tz = _zone(cal.tz)
    for ev in cal.events:  # moved/changed single instances of a repeat
        p, v = ev.get("RECURRENCE-ID")
        if v is not None:
            rid = _when(p, v, default_tz)
            uid = (ev.get("UID")[1] or "").strip()
            if isinstance(rid, datetime):
                moved.add((uid, _key(rid)))
    for ev in cal.events:
        _, rrule = ev.get("RRULE")
        e = _base(ev, cal)
        if e is None:
            continue
        if rrule is None:
            if e.start < hi and e.end > lo and e.title:
                out.append(e)
            continue
        if ev.get("RECURRENCE-ID")[1] is not None:
            continue
        out += _expand(ev, e, rrule, lo, hi, moved, default_tz)
    out.sort(key=lambda x: x.start)
    return out


def _expand(ev: _Raw, e: Event, rrule: str, lo, hi, moved, default_tz) -> list[Event]:
    from dateutil.rrule import rrulestr
    dur = e.end - e.start
    try:
        rule = rrulestr(rrule, dtstart=e.start)
        starts = rule.between(lo - dur, hi, inc=True)
    except Exception:
        try:  # UNTIL without Z next to a zoned start: dateutil wants them to agree
            rule = rrulestr(re.sub(r"UNTIL=(\d{8}T\d{6})(?!Z)", r"UNTIL=\1Z", rrule), dtstart=e.start)
            starts = rule.between(lo - dur, hi, inc=True)
        except Exception:
            log.warning("repeat rule not understood for one event; skipped")
            return []
    skip = set()
    for p, v in ev.all("EXDATE"):
        for part in v.split(","):
            x = _when(p, part, default_tz)
            if isinstance(x, datetime):
                skip.add(_key(x))
    out = []
    for s in starts:
        k = _key(s)
        if k in skip or (e.uid, k) in moved or not e.title:
            continue
        out.append(Event(e.title, s, s + dur, list(e.attendees), e.conference, e.uid))
    return out


# -- matching ------------------------------------------------------------------------------------
def pick(events: list[Event], now: datetime, app: str | None = None, early_s: float = EARLY_S) -> Event | None:
    """The event this call belongs to: running now (or starting within early_s), its link
    matching the call app first, then the closest start."""
    early = timedelta(seconds=early_s)
    cands = [e for e in events if e.start - early <= now < e.end]
    if not cands:
        return None
    link = APP_LINKS.get((app or "").lower())

    def score(e):
        return (bool(link and link in e.conference), -abs((now - e.start).total_seconds()))
    return max(cands, key=score)


def meta_info(e: Event) -> dict:
    return {"title": e.title, "attendees": list(e.attendees),
            "start": e.start.astimezone(UTC).isoformat(), "end": e.end.astimezone(UTC).isoformat()}


def session_words(d: Path, vocabulary) -> list[str]:
    """Your words plus this meeting's attendees (from meta), for its Whisper prompt."""
    words = list(vocabulary or [])
    try:
        from . import sessions
        people = (sessions.read_meta(Path(d)).get("calendar") or {}).get("attendees") or []
    except Exception:
        people = []
    return words + [p for p in people if p not in words]


def valid_url(url: str) -> bool:
    return bool(re.match(r"(?i)^(https|webcal)://[^\s/]+/\S+$", (url or "").strip()))


# -- the feed ------------------------------------------------------------------------------------
def _fetch(url: str, timeout: float) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Dictado"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https only, see valid_url)
        return r.read(MAX_BYTES)


class CalendarFeed:
    """The secret iCal link, downloaded now and then and cached in `data_dir`."""

    def __init__(self, url: str, data_dir: Path, fetch=_fetch, clock=time.time, max_age_s: float = MAX_AGE_S):
        url = (url or "").strip()
        self.url = re.sub(r"(?i)^webcal://", "https://", url) if valid_url(url) else ""
        self.path = Path(data_dir) / CACHE
        self.fetch, self.clock, self.max_age = fetch, clock, max_age_s
        self.last_try: float | None = None
        self._parsed: tuple[float, Calendar] | None = None

    def refresh(self, force: bool = False) -> bool:
        """Download if the copy is older than max_age (or `force`). True = a new copy."""
        if not self.url:
            return False
        now = self.clock()
        if not force and self.last_try is not None and now - self.last_try < self.max_age:
            return False
        self.last_try = now
        try:
            data = self.fetch(self.url, 15)
            if b"BEGIN:VCALENDAR" not in data[:2000]:
                raise ValueError("not an iCal file (wrong link?)")
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            os.replace(tmp, self.path)
            self._parsed = None
            log.info("calendar downloaded (%d KB)", len(data) // 1024)  # never the link: it's a secret
            return True
        except Exception as e:
            log.warning("calendar not downloaded (%s); using the last copy", type(e).__name__)
            return False

    def calendar(self) -> Calendar | None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        if self._parsed is None or self._parsed[0] != mtime:
            self._parsed = (mtime, parse(self.path.read_bytes()))
        return self._parsed[1]

    def lookup(self, now: datetime | None = None, app: str | None = None) -> Event | None:
        if not self.url:
            return None
        c = self.calendar()
        if c is None:
            return None
        now = now or datetime.now(UTC)
        return pick(events_between(c, now - timedelta(days=1), now + timedelta(days=1)), now, app)

    def today(self, now: datetime | None = None) -> list[Event]:
        """For the Settings test button: today's timed events."""
        c = self.calendar()
        if c is None:
            return []
        now = (now or datetime.now(UTC)).astimezone()
        lo = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return events_between(c, lo, lo + timedelta(days=1))
