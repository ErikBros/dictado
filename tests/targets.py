"""A throwaway text window for tests: whatever lands in it is dumped to a json file.

Run as a script: python targets.py --title DictadoTargetA --out C:/tmp/a.json [--x 100 --y 100]
"""
import argparse
import json
import time
import tkinter as tk
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--x", type=int, default=200)
    ap.add_argument("--y", type=int, default=200)
    a = ap.parse_args()
    out = Path(a.out)
    root = tk.Tk()
    root.title(a.title)
    root.geometry(f"520x200+{a.x}+{a.y}")
    text = tk.Text(root, font=("Segoe UI", 11))
    text.pack(fill="both", expand=True)
    text.focus_set()
    last = [None]
    events = []  # every paste attempt and whether reading the clipboard worked

    def on_paste(_e):
        try:
            data = root.clipboard_get()
            events.append({"t": round(time.time(), 3), "ok": True, "data": data})
        except tk.TclError as err:
            events.append({"t": round(time.time(), 3), "ok": False, "err": str(err)})
            return "break"
        return None
    text.bind("<<Paste>>", on_paste, add="+")

    def dump():
        try:
            content = text.get("1.0", "end-1c")
            state = (content, len(events))
            if state != last[0]:
                tmp = out.with_suffix(".tmp")
                tmp.write_text(json.dumps({"text": content, "pastes": events}), encoding="utf-8")
                tmp.replace(out)  # can hit PermissionError while a reader has it open: retry next tick
                last[0] = state
        except OSError:
            pass
        finally:
            root.after(50, dump)

    root.after(50, dump)
    root.mainloop()


if __name__ == "__main__":
    main()
