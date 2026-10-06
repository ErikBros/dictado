"""Write a Config back to TOML (tomllib only reads)."""
from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path

from .config import Config


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON string escapes are valid TOML basic-string escapes
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):  # inline table; keys quoted so "*" and "a/b" stay valid
        return "{" + ", ".join(f"{json.dumps(str(k), ensure_ascii=False)} = {_value(x)}" for k, x in v.items()) + "}"
    raise TypeError(f"can't write {type(v).__name__} to TOML")


def dumps(cfg: Config) -> str:
    out = ["# Dictado settings. Written by the Dictado window; safe to edit by hand.", ""]
    for section in fields(cfg):
        obj = getattr(cfg, section.name)
        out.append(f"[{section.name}]")
        for f in fields(obj):
            out.append(f"{f.name} = {_value(getattr(obj, f.name))}")
        out.append("")
    return "\n".join(out)


def save(cfg: Config, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(cfg), encoding="utf-8")
    os.replace(tmp, path)
