"""The Dictado window (its own process: Dictado.exe --ui).

pywebview + WebView2 renders dictado/web/. The Api below is what the page calls
(window.pywebview.api.*). It talks to the background app only through files
(config.toml, status.json, history.jsonl) and the reload event, so a crash here
can never affect dictation. Non-method attributes are _private on purpose:
pywebview exposes every public attribute of the API object to JavaScript.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from . import __version__, commands, config, diarize, hotkeys, export, ipc, meetings, paths, sessions, status, tomlw
from .routing import LANG_NAMES

log = logging.getLogger(__name__)
HOTKEYS = [("rctrl", "Right Ctrl (recommended)"), ("scrolllock", "Scroll Lock"), ("pause", "Pause")] + \
          [(f"f{n}", f"F{n}") for n in range(13, 25)]
LANGUAGES = [("en", "English"), ("sv", "Swedish"), ("es", "Spanish"), ("en,es", "English and Spanish")]
MEET_MODES = [("prompt", "Ask"), ("auto", "Start by itself"), ("off", "Don't detect")]
MEET_LANGS = [("sv", "Swedish"), ("en", "English"), ("es", "Spanish"), ("el", "Greek"), ("el,es", "Greek + Spanish"), ("auto", "Detect")]


def _voice_command_list() -> list[dict]:
    """Settings > Voice commands > See all commands (t0u.38): from the table the matcher uses."""
    from .text import VOICE_COMMANDS
    return [{"what": what, **{lang: ", ".join(f'"{p}"' for p in ps) for lang, ps in langs.items()}}
            for _, what, langs in VOICE_COMMANDS]


def parse_languages(value) -> list[str]:
    """'en,es' -> ['en', 'es']. Swedish only on its own: it runs on its own model (t0u.24)."""
    langs = [x for x in str(value).split(",") if x]
    if not langs or any(x not in ("en", "es", "sv") for x in langs) or ("sv" in langs and langs != ["sv"]):
        raise ValueError("languages")
    return langs


def save_dictation_languages(config_path: Path, value) -> list[str]:
    """The tray's "Dictation language >": save it; the caller then signals the reload."""
    c = config.load(Path(config_path))
    c.whisper.languages = parse_languages(value)
    tomlw.save(c, Path(config_path))
    return c.whisper.languages


def pretty_mic(name: str) -> str:
    """'Microphone (Anker PowerConf C20' -> 'Anker PowerConf C20' (MME cuts names at 31 chars)."""
    m = re.match(r"^[^(]*\((.+?)\)?$", name or "")
    return m.group(1).strip() if m else (name or "")


def _pid_alive(pid) -> bool:
    import ctypes
    if not pid:
        return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def _mme_input_names() -> list[str]:
    import sounddevice as sd
    names = []
    for d in sd.query_devices():
        host = sd.query_hostapis(d["hostapi"])["name"]
        if host == "MME" and d["max_input_channels"] > 0 and "Sound Mapper" not in d["name"]:
            if d["name"] not in names:
                names.append(d["name"])
    return names


def _copy(text: str) -> None:
    from .deliver import set_clipboard_text
    set_clipboard_text(text, private=False)


class Api:
    def __init__(self, data_dir: Path | None = None, config_path: Path | None = None, startup_mod=None,
                 signal_reload=None, list_mic_names=None, copy=None, send_command=None, downloads=None):
        from . import startup as _startup
        self._data_dir = Path(data_dir) if data_dir else paths.data_dir()
        self._config_path = Path(config_path) if config_path else paths.config_path()
        self._startup = startup_mod or _startup
        self._signal = signal_reload or ipc.signal_reload
        self._list_mic_names = list_mic_names or _mme_input_names
        self._copy = copy or _copy
        self._commands = send_command or commands.send
        self._downloads = Path(downloads) if downloads else Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"
        self._mic = None  # (recorder, gate) during the mic check
        import threading
        self._mic_lock = threading.Lock()

    # ---------------- status ----------------
    def get_status(self) -> dict:
        s = status.read(self._data_dir / "status.json") or {}
        alive = _pid_alive(s.get("pid"))
        if not alive:
            s = {"state": "stopped"}
        s["alive"] = alive
        s["version"] = __version__
        return s

    def start_app(self) -> dict:
        if self.get_status()["alive"]:
            return {"ok": True}
        ipc.spawn([])
        return {"ok": True}

    def restart_app(self) -> dict:
        return {"ok": bool(self._signal())}

    # ---------------- settings ----------------
    def _load(self) -> config.Config:
        try:
            return config.load(self._config_path)
        except Exception:
            log.exception("bad config, showing defaults")
            return config.Config()

    def get_settings(self) -> dict:
        c = self._load()
        try:
            labels = self._list_mic_names()
        except Exception:
            log.exception("could not list mics")
            labels = []
        mics = [{"value": "", "label": "Windows default"}] + [{"value": n, "label": pretty_mic(n)} for n in labels]
        cur = c.audio.device
        if cur and cur not in [m["value"] for m in mics]:
            match = next((m for m in mics[1:] if cur.lower() in m["value"].lower()), None)
            if match:
                match["value"] = cur  # keep the saved substring so nothing changes on save
            else:
                mics.append({"value": cur, "label": f"{cur} (not connected)"})
        return {
            "values": {
                "hotkey": c.hotkey.key, "hotkey_label": hotkeys.label(c.hotkey.key), "mic": cur, "languages": ",".join(c.whisper.languages),
                "sounds": c.ui.sounds, "overlay": c.ui.overlay, "unmute": c.audio.unmute_while_recording,
                "startup": self._startup.is_enabled(),
                "meet_mode": c.meetings.mode, "meet_lang": c.meetings.default_lang, "on_demand": c.whisper.on_demand,
                "speakers": c.meetings.speakers, "vocabulary": "\n".join(c.text.vocabulary),
                "voice_commands": c.text.voice_commands,
                "screen_names": c.text.screen_names,
                "hold_to_talk": c.hotkey.hold_to_talk, "voice_memory": c.meetings.voice_memory,
                "calendar_url": c.meetings.calendar_url, "debug_log": c.ui.debug_log,
                "snippets": [{"trigger": k, "text": v} for k, v in c.text.snippets.items()],
            },
            "speakers_addon": diarize.addon_exe().is_file(),
            "voice_command_list": _voice_command_list(),
            "options": {
                "hotkeys": [{"value": v, "label": l} for v, l in HOTKEYS],
                "mics": mics,
                "languages": [{"value": v, "label": l} for v, l in LANGUAGES],
                "meet_modes": [{"value": v, "label": l} for v, l in MEET_MODES],
                "meet_langs": [{"value": v, "label": l} for v, l in MEET_LANGS],
            },
            "can_startup": self._startup.app_command() is not None,
        }

    def check_hotkey(self, value: str) -> dict:
        """The Settings recorder asks before saving: is this shortcut allowed, and how to show it."""
        try:
            k = hotkeys.normalize(value)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "value": k, "label": hotkeys.label(k)}

    def save_settings(self, values: dict) -> dict:
        c = self._load()
        try:
            if "hotkey" in values:
                try:
                    c.hotkey.key = hotkeys.normalize(values["hotkey"])
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
            if "mic" in values:
                c.audio.device = str(values["mic"])
            if "vocabulary" in values:  # one word or name per line; blanks and repeats dropped
                seen, words = set(), []
                for line in str(values["vocabulary"]).splitlines():
                    w = " ".join(line.split())[:60]
                    if w and w.lower() not in seen:
                        seen.add(w.lower())
                        words.append(w)
                c.text.vocabulary = words[:100]
            if "snippets" in values:  # [{trigger, text}]; trigger lower-cased, blanks and repeats dropped
                table = {}
                for row in values["snippets"] or []:
                    k = " ".join(str(row.get("trigger", "")).lower().split())[:60]
                    if k and k not in table and str(row.get("text", "")).strip():
                        table[k] = str(row["text"])[:2000]
                c.text.snippets = dict(list(table.items())[:50])
            if "languages" in values:
                c.whisper.languages = parse_languages(values["languages"])
            if "meet_mode" in values:
                if values["meet_mode"] not in dict(MEET_MODES):
                    raise ValueError("meet_mode")
                c.meetings.mode = values["meet_mode"]
            if "calendar_url" in values:
                from .calendar_ics import valid_url
                url = str(values["calendar_url"] or "").strip()
                if url and not valid_url(url):
                    return {"ok": False, "error": "That isn't a calendar link: paste the secret address in iCal format "
                                                  "(it starts with https://)."}
                c.meetings.calendar_url = url
            if "meet_lang" in values:
                if values["meet_lang"] not in dict(MEET_LANGS):
                    raise ValueError("meet_lang")
                c.meetings.default_lang = values["meet_lang"]
            for key, (section, name) in {"sounds": ("ui", "sounds"), "overlay": ("ui", "overlay"),
                                         "unmute": ("audio", "unmute_while_recording"),
                                         "on_demand": ("whisper", "on_demand"),
                                         "speakers": ("meetings", "speakers"),
                                         "voice_commands": ("text", "voice_commands"),
                                         "screen_names": ("text", "screen_names"),
                                         "hold_to_talk": ("hotkey", "hold_to_talk"),
                                         "voice_memory": ("meetings", "voice_memory"),
                                         "debug_log": ("ui", "debug_log")}.items():
                if key in values:
                    setattr(getattr(c, section), name, bool(values[key]))
        except ValueError as e:
            return {"ok": False, "error": f"invalid value: {e}"}
        tomlw.save(c, self._config_path)
        if "startup" in values:
            cmd = self._startup.app_command()
            if values["startup"] and cmd:
                self._startup.enable(cmd)
            elif not values["startup"]:
                self._startup.disable()
        restarting = bool(self._signal())
        return {"ok": True, "restarting": restarting}

    # ---------------- mic check ----------------
    def mic_test_start(self, device: str | None = None) -> dict:
        # pywebview calls each API method on its own thread: serialize, never leak a gate
        with self._mic_lock:
            self._mic_stop_locked()
            from .audio import Recorder
            from .micgate import MicGate
            c = self._load()
            if device is not None:
                c.audio.device = device
            gate = MicGate(c.audio.device, c.audio.unmute_volume, enabled=c.audio.unmute_while_recording)
            rec = Recorder(c.audio)
            try:
                gate.open()
                rec.open()
                rec.begin()
            except Exception as e:
                log.exception("mic test could not start")
                for undo in (rec.abort, rec.close, gate.restore):
                    try:
                        undo()
                    except Exception:
                        pass
                return {"device": "", "fell_back": False, "error": str(e)}
            self._mic = (rec, gate)
            return {"device": rec.device_name, "fell_back": rec.fell_back}

    def mic_test_level(self) -> float:
        m = self._mic
        return m[0].level() if m else 0.0

    def mic_test_stop(self) -> dict:
        with self._mic_lock:
            self._mic_stop_locked()
        return {"ok": True}

    def _mic_stop_locked(self) -> None:
        if self._mic:
            rec, gate = self._mic
            self._mic = None
            try:
                rec.abort()
                rec.close()
            finally:
                gate.restore()

    # ---------------- history ----------------
    def get_history(self, limit: int = 200, query: str = "") -> dict:
        rows = []
        try:
            with open(self._data_dir / "history.jsonl", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get("text"):
                        rows.append(r)
        except FileNotFoundError:
            pass
        today = time.strftime("%Y-%m-%d")
        words = lambda r: len(re.findall(r"\w+", r["text"]))  # noqa: E731
        stats = {"total": len(rows), "total_words": sum(map(words, rows)),
                 "today_words": sum(words(r) for r in rows if str(r.get("ts", "")).startswith(today))}
        q = query.strip().lower()
        items = [r for r in reversed(rows) if not q or q in r["text"].lower()][:limit]
        return {"items": items, "stats": stats}

    def copy_text(self, text: str) -> dict:
        self._copy(text)
        return {"ok": True}

    def clear_history(self) -> dict:
        p = self._data_dir / "history.jsonl"
        if p.exists():
            p.replace(self._data_dir / f"history-{time.strftime('%Y%m%d-%H%M%S')}.bak")
        return {"ok": True}

    # ---------------- reuniones ----------------
    def _root(self) -> Path:
        return sessions.root_dir(self._load().transcribe.root)

    def _session(self, name: str) -> Path:
        d = self._root() / Path(str(name)).name  # a bare folder name: never a path out of the root
        if not (d / sessions.META).is_file():
            raise FileNotFoundError(name)
        return d

    @staticmethod
    def _row(m: dict) -> dict:
        d = Path(m["dir"])
        prog = {}
        try:
            prog = json.loads((d / "progress.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {"name": d.name, "title": m.get("title", ""), "lang": m.get("lang"),
                "lang_name": LANG_NAMES.get(m.get("lang_used") or m.get("lang"), m.get("lang") or ""),
                "duration_s": m.get("duration_s") or m.get("recorded_s"), "status": m.get("status"),
                "source": m.get("source"), "created": m.get("created"), "error": m.get("error"),
                "pct": prog.get("pct"), "slow": m.get("slow", False),
                "speakers": m.get("speakers"), "speaker_names": m.get("speaker_names") or {},
                "recognised": [(m.get("speaker_names") or {}).get(x, x) for x in m.get("speakers_recognised") or []]}

    def list_sessions(self, query: str = "") -> dict:
        q = str(query or "").strip().lower()
        rows = [self._row(m) for m in sessions.list_sessions(self._root())]
        return {"items": [r for r in rows if not q or q in r["title"].lower()], "state": self.meetings_state()}

    def get_session(self, name: str) -> dict:
        d = self._session(name)
        m = sessions.read_meta(d)
        m["dir"] = str(d)
        segs = []
        try:
            segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
        except (OSError, ValueError, KeyError):
            pass
        return {"session": self._row(m), "segments": export.turns(segs),  # read in turns, like the .md
                "notes": export.read_notes(d),
                "exports": [p.name for p in d.glob("transcript.*") if p.suffix in (".txt", ".md", ".srt")]}

    def get_live(self, name: str, since: int = 0) -> dict:
        """live.jsonl lines after the first `since`: a 2-hour meeting is never re-sent whole."""
        d = self._session(name)
        lines = []
        try:
            with open(d / "live.jsonl", encoding="utf-8") as f:
                for i, raw in enumerate(f):
                    if i < since:
                        continue
                    try:
                        lines.append(json.loads(raw))
                    except ValueError:
                        break  # the worker is writing this line right now
        except FileNotFoundError:
            pass
        m = sessions.read_meta(d)
        m["dir"] = str(d)
        return {"lines": lines, "next": int(since) + len(lines), "session": self._row(m),
                "notes": export.read_notes(d)}

    def claude_app(self) -> dict:
        from . import claude_link
        return {"connected": claude_link.is_connected(claude_link.config_files()),
                "frozen": bool(getattr(sys, "frozen", False))}

    def connect_claude_app(self) -> dict:
        """Settings > Meetings > Claude app: add Dictado's read-only MCP server to Claude desktop."""
        from . import claude_link
        if not getattr(sys, "frozen", False):
            return {"ok": False, "error": "Only from the installed Dictado"}
        try:
            done = claude_link.connect(claude_link.config_files(), claude_link.server_entry())
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Couldn't update Claude's settings: {e}"}
        return {"ok": True, "files": [str(f) for f in done]}

    _calendar_fetch = None  # tests swap in a fake download

    def test_calendar(self, url: str, now: str | None = None) -> dict:
        """Settings > Meetings > Calendar > Test: download the link now, say what it found."""
        from datetime import datetime

        from . import calendar_ics as cal
        if not cal.valid_url(url):
            return {"ok": False, "error": "Paste the secret address in iCal format first."}
        kw = {"fetch": self._calendar_fetch} if self._calendar_fetch else {}
        feed = cal.CalendarFeed(url, self._data_dir, **kw)
        if not feed.refresh(force=True):
            return {"ok": False, "error": "Couldn't read a calendar from that link. Check you copied the secret "
                                          "address in iCal format, and that you're online."}
        when = datetime.fromisoformat(now) if now else None
        ev = feed.lookup(when)
        return {"ok": True, "today": len(feed.today(when)), "now": ev.title if ev else None}

    def save_notes(self, name: str, text: str) -> dict:
        """Notes typed in the session view (t0u.30); empty removes the file."""
        d = self._session(name)
        text = str(text or "")[:50000]
        p = d / export.NOTES
        if text.strip():
            tmp = p.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, p)
        elif p.exists():
            p.unlink()
        return {"ok": True}

    def meetings_state(self) -> dict:
        st = meetings.read_state(self._data_dir)
        out = {"meeting": None, "job": None, "queue": [Path(q).name for q in st.get("queue", [])]}
        if st.get("meeting"):
            out["meeting"] = {**st["meeting"], "name": Path(st["meeting"]["dir"]).name}
        if st.get("job"):
            out["job"] = {**st["job"], "name": Path(st["job"]["dir"]).name}
        return out

    def start_meeting(self, lang: str = "") -> dict:
        return self._send("start_meeting", {"lang": lang} if lang else {})

    def set_meeting_lang(self, lang: str) -> dict:
        return self._send("set_meeting_lang", {"lang": lang})

    def stop_meeting(self) -> dict:
        return self._send("stop_meeting")

    def import_files(self, paths: list, lang: str = "auto") -> dict:
        paths = [str(p) for p in (paths or []) if str(p).strip()]
        if not paths:
            return {"ok": False, "error": "No files"}
        return self._send("import_files", {"paths": paths, "lang": lang or "auto"})

    def pick_files(self) -> dict:
        import webview
        kinds = ("Audio and video (*.mp3;*.m4a;*.wav;*.ogg;*.opus;*.flac;*.mp4;*.webm;*.mkv;*.mov)", "All files (*.*)")
        got = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True, file_types=kinds)
        return {"paths": list(got or [])}

    def rename_session(self, name: str, title: str) -> dict:
        title = str(title or "").strip()
        if not title:
            return {"ok": False, "error": "The title can't be empty"}
        sessions.rename(self._session(name), title)
        return {"ok": True}

    def delete_session(self, name: str) -> dict:
        d = self._session(name)
        st = meetings.read_state(self._data_dir)
        busy = {Path(x["dir"]).name for x in (st.get(k) for k in ("meeting", "job", "next_meeting")) if x}
        busy |= {Path(q).name for q in st.get("queue", [])}
        if d.name in busy or sessions.read_meta(d).get("status") in meetings.ACTIVE:
            return {"ok": False, "error": "It's running: stop it before deleting it"}
        sessions.delete(d)
        return {"ok": True}

    def open_folder(self, name: str) -> dict:
        os.startfile(str(self._session(name)))
        return {"ok": True}

    def rename_speaker(self, name: str, label: str, new: str) -> dict:
        """Name a speaker of one session ("Speaker 2" -> "Mamá"); empty = back to the label."""
        d = self._session(name)
        try:
            segs = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["segments"]
        except (OSError, ValueError, KeyError):
            segs = []
        label = str(label)
        if label not in {s.get("speaker") for s in segs} or label in ("", "None"):
            return {"ok": False, "error": "No such speaker in this session"}
        names = dict(sessions.read_meta(d).get("speaker_names") or {})
        new = " ".join(str(new or "").split())[:40]
        if new and new != label:
            names[label] = new
        else:
            names.pop(label, None)
        sessions.write_meta(d, speaker_names=names)
        export.write_all(d)
        if new and new != label and self._load().meetings.voice_memory:
            try:  # t0u.32: this voice is `new` from now on, in later calls too
                emb = json.loads((d / "voices.json").read_text(encoding="utf-8")).get(label)
                if emb:
                    from . import voices
                    voices.learn(self._data_dir / "voices.json", new, emb)
            except (OSError, ValueError):
                pass
        return {"ok": True, "names": names}

    def voices_info(self) -> dict:
        from . import voices
        n = voices.names(self._data_dir / "voices.json")
        return {"count": len(n), "names": n, "on": self._load().meetings.voice_memory}

    def forget_voices(self) -> dict:
        from . import voices
        voices.forget(self._data_dir / "voices.json")
        return {"ok": True}

    def copy_transcript(self, name: str, kind: str = "text") -> dict:
        s = self.get_session(name)
        meta = sessions.read_meta(self._session(name))
        text = export.for_claude(meta, s["segments"], s["notes"]) if kind == "claude" \
            else export.summary_prompt(meta, s["segments"], s["notes"]) if kind == "summary" else export.to_txt(s["segments"])
        self._copy(text)
        return {"ok": True, "chars": len(text)}

    def save_export(self, name: str, fmt: str) -> dict:
        if fmt not in ("txt", "md", "srt"):
            return {"ok": False, "error": "formato"}
        d = self._session(name)
        src = d / f"transcript.{fmt}"
        if (d / "transcript.json").exists():
            export.write_all(d)  # fresh every time: a rename since the meeting must show in the file
        import shutil
        title = sessions.read_meta(d).get("title") or "transcript"
        self._downloads.mkdir(parents=True, exist_ok=True)  # one click, no dialog (the user, 2026-10-05)
        base = f"{d.name[:16]}_{sessions.slug(title)}"
        dest, n = self._downloads / f"{base}.{fmt}", 2
        while dest.exists():
            dest, n = self._downloads / f"{base}-{n}.{fmt}", n + 1
        shutil.copyfile(src, dest)
        return {"ok": True, "path": str(dest), "name": dest.name}

    def _send(self, cmd: str, args: dict | None = None) -> dict:
        return self._commands(self._data_dir, cmd, args)

    # ---------------- misc ----------------
    # ---------- troubleshooting (t0u.37) ----------
    def crashes(self) -> dict:
        """Home: crashes the user hasn't dismissed, newest first; gave_up when the watchdog stopped."""
        from . import crash
        out = []
        for d in crash.unseen(self._data_dir, "user")[:5]:
            rep = (d / "report.md").read_text(encoding="utf-8", errors="replace")
            m = re.search(r"- Exit: (.*)", rep)
            out.append({"name": d.name, "when": d.name[:15].replace("_", " "), "exit": m.group(1) if m else "",
                        "gave_up": "stopped restarting" in rep})
        st = status.read(self._data_dir / "status.json") or {}
        return {"items": out, "gave_up": st.get("state") == "crashed"}

    def copy_crash_report(self, name: str) -> dict:
        from . import crash
        d = self._crash_dir(name)
        if d is None:
            return {"ok": False, "error": "Report not found"}
        self._copy(crash.for_claude(d))
        crash.mark_seen(d, "user")
        return {"ok": True}

    def dismiss_crash(self, name: str) -> dict:
        from . import crash
        d = self._crash_dir(name)
        if d is not None:
            crash.mark_seen(d, "user")
        return {"ok": True}

    def _crash_dir(self, name: str):
        from . import crash
        d = crash.crashes_dir(self._data_dir) / Path(str(name)).name
        return d if (d / "report.md").exists() else None

    def debug_info(self) -> str:
        """Settings > Troubleshooting > Copy debug info for Claude: everything to start debugging."""
        from . import __version__, crash
        d = self._data_dir

        def tail(name, n):
            p = d / name
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
            except OSError:
                return f"(no {name})"
            return "\n".join(lines)
        cfg = ""
        try:
            cfg = re.sub(r'(?m)^(calendar_url\s*=\s*).*$', r'\1"<removed>"',
                         self._config_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
        reps = crash.reports(d)[:5]
        live = sorted((crash.crashes_dir(d) / "live").glob("freeze-*.log")) if (crash.crashes_dir(d) / "live").exists() else []
        parts = [f"Dictado debug info. Please find what's wrong. Data folder: {d}", "",
                 f"Version: {__version__}", f"Status: {json.dumps(status.read(d / 'status.json') or {}, ensure_ascii=False)}", "",
                 "Recent crashes: " + (", ".join(p.name for p in reps) or "none"),
                 "Freezes recorded: " + (", ".join(p.name for p in live[-5:]) or "none"), "",
                 "## config.toml (calendar link removed)", "```", cfg.strip(), "```", ""]
        for name, n in (("dictado.log", 200), ("engine-worker.log", 40), ("supervisor.log", 30), ("detect.log", 20)):
            parts += [f"## {name} (last {n} lines)", "```", tail(name, n), "```", ""]
        for p in live[-2:]:
            parts += [f"## {p.name}", "```", p.read_text(encoding="utf-8", errors="replace")[:5000], "```", ""]
        return "\n".join(parts)

    def copy_debug_info(self) -> dict:
        self._copy(self.debug_info())
        return {"ok": True}

    def open_logs_folder(self) -> dict:
        os.startfile(str(self._data_dir))
        return {"ok": True}

    def open_log(self) -> dict:
        os.startfile(str(self._data_dir / "dictado.log"))
        return {"ok": True}

    def get_welcome(self) -> dict:
        return {"done": (self._data_dir / "welcome_done").exists()}

    def finish_welcome(self) -> dict:
        (self._data_dir / "welcome_done").write_text(time.strftime("%Y-%m-%d"), encoding="utf-8")
        return {"ok": True}


def web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def main(page: str | None = None) -> int:
    from . import palette as P
    from . import winutil
    winutil.setup_logging(paths.data_dir() / "window.log")
    if not winutil.single_instance(ipc.UI_MUTEX):
        ipc.focus_ui()
        return 0
    import webview
    api = Api()
    url = (web_dir() / "index.html").as_uri() + (f"?page={page}" if page else "")
    win = webview.create_window(ipc.UI_TITLE, url, js_api=api, width=980, height=720, min_size=(820, 560),
                                background_color=P.PAPER, text_select=True)
    win.events.closed += lambda: api.mic_test_stop()

    def on_drop(e):  # pywebview fills pywebviewFullPath only for drops handled from Python
        paths = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer") or {}).get("files", [])]
        win.evaluate_js(f"window.__dictado.dropped({json.dumps([p for p in paths if p])})")

    def on_loaded():
        from webview.dom import DOMEventHandler
        win.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True, stop_propagation=True)
    win.events.loaded += on_loaded
    webview.start(gui="edgechromium", private_mode=False,
                  storage_path=str(paths.data_dir() / "webview"), debug=bool(os.environ.get("DICTADO_DEVTOOLS")))
    api.mic_test_stop()
    return 0
