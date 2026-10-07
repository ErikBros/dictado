"""'Add a language' checked on the Mac (dictado-tjn): the real Settings page in a hidden pywebview window
(WKWebView, the engine the real window uses) on the real Api and a throwaway data folder. Nothing appears
on screen, no keys, no permission needed.

Adds German and Finnish from the picker, saves, then checks the saved config, the Meetings language list,
the menu bar's Dictation language list (the real Tray.entries) and the model each language routes to.
Then removes Finnish with its x and saves again. The dictation model: English + German stays on turbo,
Finnish in the set moves dictation to large-v3.

    .venv/bin/python tools/mac_lang_check.py      -> prints JSON, exit 0 = all good; screenshots in --shots
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(APP / "spike" / "shots"))
    a = ap.parse_args()
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ecoscribe-lang-"))
    cfg_path = tmp / "config.toml"
    cfg_path.write_text('[whisper]\nlanguages = ["en"]\n', encoding="utf-8")
    (tmp / "welcome_done").write_text("x")  # a fresh data dir opens the Welcome card over the page

    import webview
    from dictado import config, window
    from dictado.platform.macos.shell import Tray
    from dictado.engine import dictation_model
    from dictado import meetui

    api = window.Api(data_dir=tmp, config_path=cfg_path, signal_reload=lambda *x: None, list_mic_names=lambda: [])
    url = (window.web_dir() / "index.html").as_uri() + "?page=ajustes"
    win = webview.create_window("lang-check", url, js_api=api, width=980, height=900, hidden=True)
    res: dict = {}

    def js(code):
        return win.evaluate_js(code)

    def wait(cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if js(cond):
                return True
            time.sleep(0.1)
        return False

    def snap(name):
        from PyObjCTools import AppHelper
        from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep
        from WebKit import WKSnapshotConfiguration
        from webview.platforms.cocoa import BrowserView
        done = threading.Event()

        def handler(img, err):
            if img is not None:
                rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
                rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(
                    str(shots / f"lang-{name}.png"), True)
            done.set()
        wv = BrowserView.instances[win.uid].webview
        AppHelper.callAfter(lambda: wv.takeSnapshotWithConfiguration_completionHandler_(
            WKSnapshotConfiguration.alloc().init(), handler))
        done.wait(10)

    def checks_now():
        return js("JSON.stringify([...document.querySelectorAll('#f-languages label')].map(l => ({code: l.querySelector('input').value, "
                  "on: l.querySelector('input').checked, removable: !!l.querySelector('.lang-x')})))")

    def menu_and_meetings():
        c = config.load(cfg_path)
        meetui.set_langs(c.whisper.extra_languages)
        from dictado.languages import name
        t = Tray.__new__(Tray)  # entries() only reads self.a: the real menu as data, no status item on screen
        t.a = dict(open_window=lambda: None, app_ref=None, log_path=None, on_quit=None, meeting_label=None,
                   on_meeting=None, open_meetings=None, meeting_state=None, last_lang=None, start_meeting=None,
                   dict_langs=[("", "Auto")] + [(x, name(x)) for x in c.whisper.languages] if len(c.whisper.languages) > 1 else None,
                   dict_lang=lambda: "", set_dict_lang=lambda x: None)
        menu = next((e[3] for e in t.entries() if e and e[0] == "Dictation language"), None)
        return {"config": {"extra": c.whisper.extra_languages, "languages": c.whisper.languages,
                           "meet_default": c.meetings.default_lang},
                "menu_dictation_language": [e[0] for e in menu] if menu else None,
                "meeting_prompt_langs": [n for _, n in meetui.LANGS],
                "dictation_model": dictation_model(c.whisper)[0]}

    def run():
        try:
            ok = wait("!!document.querySelector('#lang-add option[value=\"de\"]') && "
                      "!document.querySelector('#page-ajustes').hidden", 20)
            js("const s=document.createElement('style');s.textContent='*{animation:none!important;transition:none!important}';document.head.appendChild(s)")
            res["page_loaded"] = ok
            res["before"] = json.loads(checks_now())
            res["picker_count_before"] = js("document.querySelectorAll('#lang-add option').length - 1")
            for code in ("de", "fi"):
                js(f"(() => {{ const s=document.querySelector('#lang-add'); s.value='{code}'; s.dispatchEvent(new Event('change')); }})()")
                time.sleep(0.2)
            res["after_add"] = json.loads(checks_now())
            res["picker_has_de_after_add"] = js("!!document.querySelector('#lang-add option[value=\"de\"]')")
            res["savebar_shown"] = js("!document.querySelector('#savebar').hidden")
            js("document.querySelector('#lang-add').scrollIntoView({block: 'center'})")
            time.sleep(0.3)
            snap("added")
            js("document.querySelector('#save').click()")
            wait("document.querySelector('#savebar').hidden")
            res["toast_after_save"] = js("document.querySelector('#toast').textContent")
            res["saved_1"] = menu_and_meetings()
            # a fresh load: what the real window shows after a restart
            win.load_url(url.replace("?page=ajustes", "?page=reuniones"))
            wait("document.querySelectorAll('#r-lang option').length > 4", 15)
            res["meetings_page_langs"] = json.loads(js("JSON.stringify([...document.querySelectorAll('#r-lang option')].map(o => o.textContent))"))
            win.load_url(url)
            wait("document.querySelectorAll('#f-languages label').length >= 4", 15)
            js("const s=document.createElement('style');s.textContent='*{animation:none!important;transition:none!important}';document.head.appendChild(s)")
            res["reloaded"] = json.loads(checks_now())
            res["meet_lang_options"] = json.loads(js("JSON.stringify([...document.querySelectorAll('#f-meet-lang option')].map(o => o.textContent))"))
            js("[...document.querySelectorAll('#f-languages label')].find(l => l.querySelector('input').value === 'fi').querySelector('.lang-x').click()")
            time.sleep(0.2)
            res["after_remove"] = json.loads(checks_now())
            js("document.querySelector('#save').click()")
            wait("document.querySelector('#savebar').hidden")
            res["saved_2"] = menu_and_meetings()
            js("document.querySelector('#lang-add').scrollIntoView({block: 'center'})")
            time.sleep(0.3)
            snap("removed")
        except Exception as e:  # noqa: BLE001 (report, don't hang the window)
            res["error"] = repr(e)
        finally:
            win.destroy()

    webview.start(run)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    s1, s2 = res.get("saved_1", {}), res.get("saved_2", {})
    ok = (res.get("page_loaded") and not res.get("error")
          and [c["code"] for c in res["before"]] == ["en", "sv"]
          and [(c["code"], c["on"], c["removable"]) for c in res["after_add"]][2:] == [("de", True, True), ("fi", True, True)]
          and s1["config"]["extra"] == ["de", "fi"] and s1["config"]["languages"] == ["en", "de", "fi"]
          and s1["menu_dictation_language"] == ["Auto", "English", "German", "Finnish"]
          and "German" in s1["meeting_prompt_langs"] and "Finnish" in s1["meeting_prompt_langs"]
          and "German" in res["meetings_page_langs"] and "Finnish" in res["meetings_page_langs"]
          and "turbo" not in s1["dictation_model"] and "turbo" in s2["dictation_model"]
          and [c["code"] for c in res["reloaded"]] == ["en", "sv", "de", "fi"]
          and s2["config"]["extra"] == ["de"] and s2["config"]["languages"] == ["en", "de"]
          and s2["menu_dictation_language"] == ["Auto", "English", "German"]
          and "Finnish" not in s2["meeting_prompt_langs"])
    print("OK" if ok else "FAILED", tmp)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
