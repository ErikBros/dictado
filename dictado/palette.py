"""The Dictado palette. Every Dictado surface uses only these."""
PAPER = "#fbfaf6"
INK = "#232a33"
AEGEAN = "#2e6187"
TILE = "#b3541e"
# derived tints
INK_SOFT = "#5b6470"
LINE = "#e4e1d8"
AEGEAN_SOFT = "#dbe6ef"
TILE_SOFT = "#f3e0d4"
PILL_OFF = "#4a525c"   # unlit level bar on the ink pill


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
