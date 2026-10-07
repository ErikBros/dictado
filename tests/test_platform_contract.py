"""The platform contract (dictado-8tf): every OS-specific capability exists on every platform,
or has an open ticket, or is explicitly not needed; and FEATURES.md says so. Reads the source
files, so it runs the same on Windows, macOS and CI without importing platform code."""
import ast
import re
from pathlib import Path

import pytest

from ecoscribe.platform.base import CAPABILITIES, PLATFORMS

ROOT = Path(__file__).resolve().parent.parent
FEATURES = (ROOT / "FEATURES.md").read_text(encoding="utf-8")


def _defined(module: str) -> set[str]:
    path = ROOT / (module.replace(".", "/") + ".py")
    assert path.exists(), f"{module}: no file {path.relative_to(ROOT)}"
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _row(label: str) -> list[str]:
    for line in FEATURES.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == label:
            return cells
    raise AssertionError(f"FEATURES.md has no row for '{label}'")


@pytest.mark.parametrize("label", list(CAPABILITIES))
@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_capability_is_provided_ticketed_or_not_needed(label, platform):
    entry = CAPABILITIES[label].get(platform)
    assert entry is not None, f"'{label}' has nothing for {platform}: add the code, a ticket or a not_needed reason"
    col = _row(label)[1 + PLATFORMS.index(platform)]
    if isinstance(entry, tuple):
        kind, value = entry
        assert kind in ("ticket", "not_needed"), entry
        if kind == "ticket":
            assert re.fullmatch(r"dictado-[a-z0-9]+", value), value
            assert value in col, f"FEATURES.md '{label}' / {platform} must mention {value}"
        else:
            assert value and "not needed" in col.lower(), f"FEATURES.md '{label}' / {platform} must say not needed"
        return
    if entry.startswith("file:"):
        assert (ROOT / entry[5:]).exists(), entry
    else:
        module, names = entry.split(":")
        missing = set(names.split(",")) - _defined(module)
        assert not missing, f"{module} lacks {missing}"
    assert col.lower().startswith("done"), f"FEATURES.md '{label}' / {platform} should say done"


def test_features_md_lists_only_known_platform_rows():
    """Every OS-specific row in FEATURES.md's platform table is backed by the contract."""
    section = FEATURES.split("## Platform-specific", 1)[1].split("\n## ", 1)[0]
    labels = [c.strip().strip("|").split("|")[0].strip() for c in section.splitlines()
              if c.startswith("|") and not c.startswith("|--") and not c.startswith("| Capability")]
    assert set(labels) == set(CAPABILITIES), set(labels) ^ set(CAPABILITIES)
