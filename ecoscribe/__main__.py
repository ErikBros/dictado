"""Entry point: pythonw -m ecoscribe [--test ...]"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

from . import __version__, hotkeys, paths, winutil
from .engine import dictation_model


def parse(argv):
    ap = argparse.ArgumentParser(prog="ecoscribe")
    ap.add_argument("--test", action="store_true", help="accept injected keys, separate instance")
    ap.add_argument("--test-audio", help="wav file or folder with next_clip.txt instead of the mic")
    ap.add_argument("--log", help="log file path")
    ap.add_argument("--config", help="config.toml path")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--no-sounds", action="store_true")
    ap.add_argument("--ui", action="store_true", help="open the Ecoscribe window")
    ap.add_argument("--page", default=None, help="window page: inicio, historial, ajustes, bienvenida")
    ap.add_argument("--restarted", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--selftest", metavar="WAV", help="load the engine, transcribe WAV, write a JSON result, exit")
    ap.add_argument("--out", help="where --selftest writes its JSON result")
    ap.add_argument("--transcribe", metavar="DIR", help="transcribe one session folder, then exit")
    ap.add_argument("--meeting", metavar="DIR", help="record + live-transcribe a meeting into DIR until stopped")
    ap.add_argument("--speakers", metavar="DIR", help="tell the remote speakers apart in a finished session (needs the add-on)")
    ap.add_argument("--engine-worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--mcp", action="store_true", help="read-only MCP server over stdio, for the Claude app")
    ap.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)  # the watchdog (t0u.37)
    ap.add_argument("--after-crash", metavar="REPORT", help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def _migrate_from_script(log) -> None:
    """The installed app replaces the 1.0 script deploy: its Startup shortcut would
    otherwise start a second engine at login (double paste)."""
    lnk = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Dictado.lnk"
    try:
        if lnk.exists():
            lnk.unlink()
            log.info("removed old script Startup shortcut %s", lnk)
    except OSError:
        log.exception("could not remove %s", lnk)


def _migrate_run_key(log) -> None:
    """Start with Windows was the "Dictado" Run value before the rename (dictado-c9u)."""
    if sys.platform == "darwin":
        return
    from . import startup
    try:
        old = startup.get(startup.OLD_NAME)
        cur = startup.get()
        if old is not None or (cur and "dictado.exe" in cur.lower()):  # Ecoscribe 1.6.0 pointed at Dictado.exe
            startup.enable(startup.app_command())
            startup.disable(startup.OLD_NAME)
            log.info("Run key %s / %s -> %s", old, cur, startup.app_command())
    except Exception:
        log.exception("could not move the Run key")


def decide_launch(have_mutex: bool, restarted: bool, test: bool) -> str:
    """run | wait | open_ui | exit. A second launch must never start a second engine
    (two hooks would paste everything twice)."""
    if have_mutex:
        return "run"
    if restarted:
        return "wait"
    return "exit" if test else "open_ui"


def _loaded_nvidia_dlls() -> list[str]:
    try:
        import win32api
        import win32process
        mods = win32process.EnumProcessModules(win32api.GetCurrentProcess())
        names = [win32process.GetModuleFileNameEx(win32api.GetCurrentProcess(), m) for m in mods]
        return sorted({Path(n).name for n in names if "nvidia" in n.lower() or "ctranslate2" in n.lower()})
    except Exception as e:
        return [f"error: {e}"]


_KEEP: list = []


def selftest(wav: str, out: str | None) -> int:
    """Proves a (frozen) build can load CUDA + VAD + model and transcribe."""
    import json
    import os as _os
    winutil.add_cuda_dll_dirs()
    from .audio import read_wav
    from .config import TextCfg, WhisperCfg
    from .engine import Engine
    res = {"ok": False}
    try:
        e = Engine(WhisperCfg(), TextCfg())
        _KEEP.append(e)  # never destroyed: see Engine._retired
        t0 = time.monotonic()
        e.load()
        res["load_s"] = round(time.monotonic() - t0, 2)
        audio = read_wav(Path(wav))
        e.transcribe(audio)
        r = e.transcribe(audio)
        res.update(ok=e.device in ("cuda", "mlx") and bool(r.text), device=e.device, fallback=e.fallback_reason,
                   ms=r.ms, text=r.text, lang=r.lang, frozen=bool(getattr(sys, "frozen", False)),
                   exe=sys.executable, pid=_os.getpid(), nvidia_dlls=_loaded_nvidia_dlls())
    except Exception as ex:  # report, don't crash silently in a windowed exe
        res["error"] = f"{type(ex).__name__}: {ex}"
    data = json.dumps(res, ensure_ascii=False)
    if out:
        Path(out).write_text(data, encoding="utf-8")
    elif sys.stdout:
        print(data)
    return 0 if res["ok"] else 1


MANUAL = "_manual"  # meeting_langs.json key: language of the last meeting started by hand


def _calendar_feed(cfg, data, ctl, log):
    """t0u.35: the secret iCal link, if set: names meetings. Downloads in the background
    (at most every 10 min), never blocks a call."""
    from .calendar_ics import CalendarFeed
    if not cfg.meetings.calendar_url:
        return None
    feed = CalendarFeed(cfg.meetings.calendar_url, data)
    if not feed.url:
        log.warning("calendar link in config.toml isn't a calendar link; meetings keep their default name")
        return None
    ctl.calendar = feed

    def loop():
        while True:
            try:
                feed.refresh()
            except Exception:
                log.exception("calendar refresh failed")
            time.sleep(60)
    threading.Thread(target=loop, name="ecoscribe-calendar", daemon=True).start()
    log.info("calendar on")
    return feed


def _start_meetings(cfg, data, ui, root, log):
    """Controller (one worker at a time), detector thread, prompt box, 1 s poll on the tk thread."""
    from . import ipc, meetui
    from .meetings import Controller
    from .meetwatch import MeetWatch
    if sys.platform == "darwin":
        from .platform.macos.shell import PromptWindow
    else:
        from .ui import PromptWindow
    try:
        ctl = Controller(data, cfg)
    except Exception:
        log.exception("meetings controller failed; meetings are off")
        return None, None
    feed = _calendar_feed(cfg, data, ctl, log)

    def ui_prompt(kind, app=None, lang=None):
        if kind == "start" and feed is not None:  # a call: fetch the calendar now, for its name
            threading.Thread(target=feed.refresh, kwargs={"force": True}, name="ecoscribe-calendar", daemon=True).start()
        ui.prompt(kind, app, lang)
    watch = MeetWatch(ctl, cfg, ui_prompt=ui_prompt, data_dir=data)

    def on_answer(prompt, choice, lang):
        if choice == "abrir":
            ipc.open_ui("reuniones/" + Path(prompt.app).name)
        else:
            watch.answer(choice, lang)
    ui.prompts = PromptWindow(root, on_answer)
    if cfg.meetings.mode != "off":
        watch.start()
    from . import commands
    commands.Watcher(data, commands.handler_for(ctl, watch, MANUAL)).start()  # the window's buttons
    tracker = meetui.Tracker()

    def poll():
        try:
            ctl.poll()
            st = ctl.state()
            line = meetui.last_live_line(st["meeting"]["dir"]) if st["meeting"] else None
            ui.set_meeting(st, meetui.meeting_view(st, time.time(), line))
            for kind, d in tracker.update(st):
                ui.prompt(kind, d, None)
        except Exception:
            log.exception("meetings poll failed")
        root.after(1000, poll)
    root.after(1000, poll)
    log.info("meetings on: mode=%s", cfg.meetings.mode)
    return ctl, watch


def main(argv=None) -> int:
    argv_in = argv
    try:  # dictado-c9u: the Dictado folders become the Ecoscribe ones, before anything opens a file there
        renamed = paths.migrate_all()
    except Exception as e:
        renamed = [("dictado folders", "", f"error: {e}")]
    raw = sys.argv[1:] if argv is None else argv
    if raw[:1] == ["--hook"]:  # the hooks' own small process (t0u.37): nothing else loads
        from .hook import hook_process_main
        winutil.hard_exit(hook_process_main(raw[1:]))
    args = parse(sys.argv[1:] if argv is None else argv)
    if args.transcribe:  # worker process: no mutex, no hook/tray/tk
        from .transcribe import main as transcribe_main
        winutil.hard_exit(transcribe_main(args.transcribe))
    if args.supervise:  # the watchdog: restarts the background app after a crash (t0u.37)
        from .supervise import main as supervise_main
        winutil.hard_exit(supervise_main())
    if args.mcp:  # the Claude app's child process: stdio only, no mutex, no UI
        from .mcp_server import main as mcp_main
        winutil.hard_exit(mcp_main(args.config))
    if args.engine_worker:  # on-demand dictation model, serves the background app over pipes
        from .engine_proc import worker_main
        winutil.hard_exit(worker_main(args.config))
    if args.meeting:
        from .meeting import main as meeting_main
        winutil.hard_exit(meeting_main(args.meeting))
    if args.speakers:
        from .diarize import main as speakers_main
        winutil.hard_exit(speakers_main(args.speakers))
    if args.selftest:
        winutil.hard_exit(selftest(args.selftest, args.out))
    if args.ui:
        winutil.set_dpi_aware()
        from .window import main as window_main
        return window_main(args.page)
    winutil.set_dpi_aware()
    data = paths.data_dir()
    log_path = Path(args.log) if args.log else data / ("ecoscribe-test.log" if args.test else "ecoscribe.log")
    winutil.setup_logging(log_path, logging.DEBUG if args.test else logging.INFO)
    log = logging.getLogger("ecoscribe")
    for noisy in ("faster_whisper", "httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    from . import ipc, status
    for old, new, what in renamed:
        if what != "none":
            log.info("rename: %s -> %s: %s", old, new, what)
    if getattr(sys, "frozen", False) and not args.test:
        _migrate_from_script(log)
        _migrate_run_key(log)
        try:
            from . import claude_link
            for f in claude_link.relink_old(claude_link.config_files(), claude_link.server_entry()):
                log.info("Claude app link renamed dictado -> ecoscribe in %s", f)
        except Exception:
            log.exception("could not rename the Claude app link")
    mutex = "Local\\EcoscribeTest" if args.test else "Local\\EcoscribeSingleInstance"
    action = decide_launch(winutil.single_instance(mutex), args.restarted, args.test)
    if action == "wait":
        for _ in range(150):  # old copy is cleaning up; it released the mutex just before spawning us
            time.sleep(0.1)
            if winutil.single_instance(mutex):
                action = "run"
                break
    if action != "run":
        if action == "open_ui":
            log.info("already running: opening the window")
            ipc.open_ui(args.page)
        else:
            log.info("already running, exiting")
        return 0
    status_path = data / ("status-test.json" if args.test else "status.json")
    if sys.platform == "darwin":  # logout, Activity Monitor > Quit: a quit, not a crash (the watchdog leaves)
        import signal

        def _on_term(*_):
            status.write(status_path, state="stopped")
            log.info("SIGTERM: quitting")
            winutil.hard_exit(0)
        signal.signal(signal.SIGTERM, _on_term)
    status.write(status_path, state="loading", error=None, version=__version__, test=args.test)
    (data / ("ecoscribe-test.pid" if args.test else "ecoscribe.pid")).write_text(str(os.getpid()))
    log.info("ecoscribe %s starting pid=%d test=%s", __version__, os.getpid(), args.test)
    try:  # t0u.37: a native crash leaves every thread's Python stack in crashes/live/fault-<pid>.log
        from . import crash
        crash.enable(data, os.getpid())
    except Exception:
        log.exception("crash logging not enabled")
    winutil.add_cuda_dll_dirs()

    from . import config as config_mod
    from .app import App
    from .audio import FileSource, Recorder
    from .deliver import deliver
    from .engine import Engine
    from .micgate import MicGate
    from .ui import Ui
    if sys.platform == "darwin":  # one AppKit main loop owns the menu bar item and the panels (uat.5)
        from .platform.macos.keyhook import HookThread
        from .platform.macos.shell import Overlay, Root, Sounds, Tray
    else:
        import tkinter as tk

        from .hook import HookThread
        from .ui import Overlay, Sounds, Tray

    try:
        cfg = config_mod.load(Path(args.config) if args.config else paths.config_path())
    except Exception:
        log.exception("bad config, using defaults")
        cfg = config_mod.Config()
    from . import meetui
    meetui.set_langs(cfg.whisper.extra_languages)  # dictado-ehs: English + Swedish + the added languages
    if cfg.ui.debug_log:  # Settings > Troubleshooting > Detailed logging (t0u.37)
        logging.getLogger().setLevel(logging.DEBUG)
        log.info("detailed logging on")

    root = Root() if sys.platform == "darwin" else tk.Tk()
    root.withdraw()
    hint = hotkeys.cancel_hint(cfg.hotkey.key)
    if sys.platform == "darwin":  # the Mac pill says how to finish and cancel (ecoscribe/platform/macos/shell.py)
        from .platform.macos.shell import cancel_hint as mac_hint
        hint = mac_hint(cfg.hotkey)
    overlay = Overlay(root, hint=hint) if cfg.ui.overlay else None
    sounds = Sounds(data / "sounds", enabled=cfg.ui.sounds and not args.no_sounds)
    ui = Ui(root, overlay, sounds)

    if args.test_audio:
        recorder, gate = FileSource(args.test_audio), None
    else:
        recorder = Recorder(cfg.audio, on_warning=lambda m: (log.warning(m), ui.flash(m)))
        gate = MicGate(cfg.audio.device, cfg.audio.unmute_volume, enabled=cfg.audio.unmute_while_recording)
    recorder.open()
    if overlay:
        overlay.level_fn = recorder.level

    if cfg.whisper.on_demand:  # the model lives in a worker started at the tap, gone after idle
        from .engine_proc import EngineProxy, spawn_worker
        engine = EngineProxy(cfg.whisper, cfg.text,
                             spawn=lambda: spawn_worker(args.config))  # the worker reads the same config
    else:
        engine = Engine(cfg.whisper, cfg.text)
    from .spool import Spool
    app = App(cfg, recorder, engine, deliver, ui, gate=gate, history_path=data / ("history-test.jsonl" if args.test else "history.jsonl"),
              spool=Spool(data / ("spool-test" if args.test else "spool")))
    app.ready = False
    app.start()

    meet_ctl, watch = _start_meetings(cfg, data, ui, root, log) if not args.test else (None, None)

    def quit_app():
        log.info("quit requested")
        status.write(status_path, state="stopped")  # the watchdog reads this: a quit, not a crash
        if meet_ctl:
            meet_ctl.stop_meeting()  # the worker finalizes on its own; a queued job waits for the next start
        if watch:
            watch.stop()
        app.shutdown()
        getattr(engine, "close", lambda: None)()
        recorder.close()
        if ui.tray:
            ui.tray.stop()
        root.after(0, root.destroy)

    if not (args.no_tray or os.environ.get("ECOSCRIBE_NO_TRAY")):  # env: survives a watchdog restart (checks)
        meet_kw = {}
        if meet_ctl:
            from . import meetui

            def toggle_meeting():
                if meet_ctl.state()["meeting"]:
                    meet_ctl.stop_meeting()
                else:
                    meet_ctl.start_meeting(watch.lang_for(MANUAL), app=watch.call_app_now())
            def start_in(lang):
                watch.remember(MANUAL, lang)
                meet_ctl.start_meeting(lang, app=watch.call_app_now())
            meet_kw = dict(meeting_label=lambda: meetui.tray_meeting_label(meet_ctl.state()),
                           on_meeting=toggle_meeting, open_meetings=lambda: ipc.open_ui("reuniones"),
                           meeting_state=meet_ctl.state, last_lang=lambda: watch.lang_for(MANUAL), start_meeting=start_in)
        from .languages import name as lang_name
        from .window import save_dictation_languages

        def set_dict_lang(code):
            """Tray > Dictation language: save, then the same restart as a Settings save."""
            try:
                save_dictation_languages(Path(args.config) if args.config else paths.config_path(), code)
            except Exception:
                log.exception("dictation language %s not saved", code)
                return
            log.info("dictation language -> %s from the tray", code)
            ipc.signal_reload(ipc.RELOAD_EVENT + ("-test" if args.test else ""))
        ui.tray = Tray(lambda: app, log_path, quit_app, open_window=lambda: ipc.open_ui(),
                       dict_langs=[("", "Auto")] + [(c, lang_name(c)) for c in cfg.whisper.languages]
                       if len(cfg.whisper.languages) > 1 else None,
                       dict_lang=lambda: app.next_lang or "", set_dict_lang=lambda c: app.set_next_language(c),
                       **meet_kw)

    def restart():
        """Settings were saved: come back with the new config (a clean re-exec)."""
        from .restart import do_restart
        log.info("reload requested: restarting")
        status.write(status_path, state="restarting")
        argv = [a for a in (sys.argv[1:] if argv_in is None else argv_in) if a != "--restarted"]
        do_restart(
            spawn=lambda: ipc.spawn(argv + ["--restarted"]),
            cleanup_steps=[("app", app.shutdown), ("engine", getattr(engine, "close", lambda: None)), ("hook", hook.stop),
                           ("gate", lambda: gate and gate.restore()), ("mic", recorder.close),
                           ("tray", lambda: ui.tray and ui.tray.stop())],
            release=winutil.release_instance,
            exit_fn=winutil.hard_exit,
            on_spawn_fail=lambda: (status.write(status_path, state="ready" if app.ready else "loading"),
                                   ui.flash("Couldn't restart: settings apply the next time Ecoscribe starts")))

    from .hotkeys import ComboMatcher, combo_vks
    # macOS: the event tap stays in-process (macOS times out a slow tap instead of lagging the keyboard)
    use_proc = cfg.limits.hook_process and sys.platform != "darwin"  # test instances too: run_e2e exercises the real path
    hook_cls, hook_kw = HookThread, {}
    if use_proc:
        from .hook import HookClient, spawn_hook_process
        hook_cls, hook_kw = HookClient, {"spawn": spawn_hook_process}
    hook = hook_cls(app.on_action, cfg.hotkey.vk, cfg.hotkey.max_tap_s, **hook_kw,
                      combo=ComboMatcher(cfg.hotkey.key) if combo_vks(cfg.hotkey.key) else None,
                      accept_injected=args.test, reinstall_s=cfg.limits.hook_reinstall_s,
                      swallow_cancel=lambda: app.state == "recording",
                      hold=cfg.hotkey.hold_to_talk and not combo_vks(cfg.hotkey.key), hold_s=cfg.hotkey.hold_s)
    hook.start()
    if sys.platform == "darwin":  # say which permission is missing instead of a dead hotkey (pre-mortem #3)
        def _permissions():
            hook.ready.wait(5)
            from .platform.macos import permissions

            def changed(st, before):  # first check, then each grant while running (dictado-6qp)
                status.write(status_path, permissions=st, key_tap=bool(hook.ok))
                missing = permissions.missing(st=st)
                if before is None:
                    if missing:
                        log.warning("missing macOS permissions: %s (key tap ok=%s)", ", ".join(missing), hook.ok)
                        ui.flash("Ecoscribe needs " + " + ".join(missing) + ": see Settings", )
                    return
                got = [permissions.PANES[k][0] for k, on in st.items() if on and not before.get(k)]
                log.info("macOS permission granted: %s (still missing: %s)", ", ".join(got) or "-",
                         ", ".join(missing) or "none")
                if not hook.ok and st.get("accessibility") and st.get("input"):
                    ui.flash("Permissions on: quit and reopen Ecoscribe to use the key")  # a key tap starts only at launch
            permissions.watch(changed)
        threading.Thread(target=_permissions, name="ecoscribe-permissions", daemon=True).start()

    # only now: restart() needs the hook to exist
    watcher = ipc.ReloadWatcher(lambda: root.after(0, restart),
                                ipc.RELOAD_EVENT + ("-test" if args.test else ""))
    watcher.start()
    if not args.test and not (data / "welcome_done").exists():
        ipc.open_ui("bienvenida")

    def load_model():
        if cfg.whisper.on_demand:
            app.ready = True
            status.write(status_path, state="ready", error=None, device=engine.device, fallback=None,
                         model=dictation_model(cfg.whisper)[0], on_demand=True, mic=recorder.device_name,
                         fell_back=recorder.fell_back, languages=cfg.whisper.languages, hotkey=cfg.hotkey.key)
            log.info("ready on_demand model=%s idle_exit_s=%.0f mic=%s", dictation_model(cfg.whisper)[0],
                     cfg.whisper.idle_exit_s, recorder.device_name)
            after_ready()
            return
        t0 = time.monotonic()
        ui.flash("Loading the model…")
        try:
            engine.load()
        except Exception:
            log.exception("model load failed")
            status.write(status_path, state="error", error="model load failed")
            ui.flash("Error loading the model, see the log")
            return
        app.ready = True
        status.write(status_path, state="ready", error=None, device=engine.device, fallback=engine.fallback_reason,
                     model=dictation_model(cfg.whisper)[0] if engine.device == cfg.whisper.device else "small",
                     mic=recorder.device_name, fell_back=recorder.fell_back, languages=cfg.whisper.languages,
                     hotkey=cfg.hotkey.key)
        log.info("ready model=%s device=%s load_s=%.1f mic=%s fell_back=%s",
                 dictation_model(cfg.whisper)[0] if engine.device == cfg.whisper.device else "small", engine.device,
                 time.monotonic() - t0, recorder.device_name, recorder.fell_back)
        if engine.fallback_reason:
            ui.flash("No GPU: slow mode")
        else:
            after_ready()

    def recover_spool():  # t0u.37: a dictation a crash cut off goes to History
        threading.Thread(target=app.recover, name="ecoscribe-recover", daemon=True).start()

    def after_ready():
        if args.after_crash:  # t0u.37: never a silent restart
            log.warning("restarted after a crash: %s", args.after_crash)
            ui.flash("Ecoscribe crashed and restarted. Report saved.", 8.0)
        else:
            ui.flash(f"Ecoscribe ready: {hotkeys.how(cfg.hotkey.key)}")
        recover_spool()

    threading.Thread(target=load_model, name="ecoscribe-load", daemon=True).start()
    if not args.test and (sys.platform == "darwin" or getattr(sys, "frozen", False)
                          or os.environ.get("ECOSCRIBE_SUPERVISE")):
        from . import supervise

        def keep_watchdog():  # started now, and again if it ever goes missing
            threading.Thread(target=supervise.ensure, args=(log,), daemon=True).start()
            root.after(60_000, keep_watchdog)
        root.after(2000, keep_watchdog)
    try:  # t0u.37: a frozen main thread leaves every thread's stack in crashes/live/
        from .crash import FreezeWatch
        freeze = FreezeWatch(data, os.getpid()).start()

        def beat():
            freeze.beat()
            root.after(500, beat)
        root.after(500, beat)
    except Exception:
        log.exception("freeze watch not started")
    try:
        root.mainloop()
    finally:
        hook.stop()
        if gate:
            gate.restore()
        log.info("ecoscribe stopped")
    winutil.hard_exit(0)


if __name__ == "__main__":
    sys.exit(main())
