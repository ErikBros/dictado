"""Real mouse-wheel scroll of the live meeting transcript in headless Chrome over CDP (t0u.19).
Setting scrollTop from code works even on an overflow: hidden list, so only a real wheel
event proves the user can scroll. Run with Windows Python (needs `websockets`):

    python tools/scroll_check.py      exit 0 = the wheel scrolls up and a new live line doesn't yank it back
"""
import asyncio, json, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
import websockets
C = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
TMP = Path(tempfile.mkdtemp(prefix="dictado-scroll-"))
shutil.copytree(Path(__file__).resolve().parent.parent / "dictado" / "web", TMP / "web")  # Chrome can't read \\wsl paths reliably
URL = (TMP / "web" / "index.html").as_uri() + "?demo=1&page=reuniones/2026-10-05_1400_retro"
p = subprocess.Popen([C, "--headless=new", "--disable-gpu", "--remote-debugging-port=9333", f"--user-data-dir={TMP / 'prof'}",
                      "--window-size=980,690", URL])
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json")); break
        except Exception: time.sleep(0.2)
    ws_url = [t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"]
    async def main():
        async with websockets.connect(ws_url, max_size=None) as ws:
            n = 0
            async def call(m, **pa):
                nonlocal n; n += 1; await ws.send(json.dumps({"id": n, "method": m, "params": pa}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == n: return r.get("result", {})
            ev = lambda js: call("Runtime.evaluate", expression=js, returnByValue=True)
            await asyncio.sleep(12)  # live lines pile up past the list height
            r = await ev("(()=>{const l=document.querySelector('#r-segs');const b=l.getBoundingClientRect();return {ov:getComputedStyle(l).overflowY,sh:l.scrollHeight,ch:l.clientHeight,st:l.scrollTop,x:b.x+b.width/2,y:b.y+b.height/2}})()")
            before = r["result"]["value"]; print("before", before)
            for _ in range(5):
                await call("Input.dispatchMouseEvent", type="mouseWheel", x=before["x"], y=before["y"], deltaX=0, deltaY=-300)
                await asyncio.sleep(0.15)
            await asyncio.sleep(1.5)  # a live line arrives meanwhile: must not yank back
            r = await ev("document.querySelector('#r-segs').scrollTop")
            after = r["result"]["value"]; print("after wheel up", after)
            sys.exit(0 if before["ov"] == "auto" and after < before["st"] else 1)
    asyncio.run(main())
finally:
    p.kill()
    time.sleep(1)
    shutil.rmtree(TMP, ignore_errors=True)
