"""A throwaway text window for the Mac E2E: it comes to the front, and its text is dumped to a json file."""
import argparse
import json
import tkinter as tk
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = tk.Tk()
    root.title("DictadoTarget")
    root.geometry("520x200+200+200")
    text = tk.Text(root, font=("Helvetica", 13))
    text.pack(fill="both", expand=True)
    try:  # a Python process doesn't come to the front by itself on macOS
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass
    root.lift()
    root.focus_force()
    text.focus_set()

    def dump():
        Path(a.out).write_text(json.dumps({"text": text.get("1.0", "end-1c")}, ensure_ascii=False), encoding="utf-8")
        root.after(100, dump)
    dump()
    root.mainloop()


if __name__ == "__main__":
    main()
