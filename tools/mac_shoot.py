"""Screenshots of the Ecoscribe window pages on the Mac, rendered offscreen by WKWebView (the engine the real
window uses). Nothing appears on screen, no permission needed. Demo data (?demo=1), Mac wording (?mac=1).

    .venv/bin/python tools/mac_shoot.py [page ...]     -> spike/shots/win-<page>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from AppKit import NSApplication, NSBackingStoreBuffered, NSBitmapImageFileTypePNG, NSBitmapImageRep, NSMakeRect, NSWindow
from Foundation import NSURL, NSDate, NSRunLoop
from WebKit import WKSnapshotConfiguration, WKWebView, WKWebViewConfiguration

APP = Path(__file__).resolve().parent.parent
OUT = APP / "spike" / "shots"


def spin(seconds: float) -> None:
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def shoot(page: str, extra: str = "") -> Path:
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(-5000, -5000, 980, 720), 0,
                                                                        NSBackingStoreBuffered, False)
    web = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 980, 720), WKWebViewConfiguration.alloc().init())
    win.setContentView_(web)
    index = APP / "dictado" / "web" / "index.html"
    url = NSURL.URLWithString_(f"{index.as_uri()}?demo=1&mac=1&page={page}{extra}")
    web.loadFileURL_allowingReadAccessToURL_(url, NSURL.fileURLWithPath_(str(index.parent)))
    spin(2.5)
    # offscreen WebKit never runs CSS animations: the pages' fade-in would stay at opacity 0
    web.evaluateJavaScript_completionHandler_(
        "const s=document.createElement('style');s.textContent='*{animation:none!important;transition:none!important}';"
        "document.head.appendChild(s);", None)
    spin(0.5)
    done = {}
    web.takeSnapshotWithConfiguration_completionHandler_(WKSnapshotConfiguration.alloc().init(),
                                                         lambda img, err: done.update(img=img, err=err))
    for _ in range(50):
        if done:
            break
        spin(0.1)
    img = done.get("img")
    if img is None:
        raise SystemExit(f"no snapshot for {page}: {done.get('err')}")
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    out = OUT / f"win-{page}.png"
    rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(str(out), True)
    return out


if __name__ == "__main__":
    NSApplication.sharedApplication()
    OUT.mkdir(parents=True, exist_ok=True)
    for p in sys.argv[1:] or ["inicio", "ajustes", "bienvenida"]:
        print(shoot(p))
