"""Ecoscribe's mark: a mic glyph, drawn with Pillow at any size (app icon + tray states)."""
from __future__ import annotations

from PIL import Image, ImageDraw

from . import palette as P


def mic_image(size: int, bg: str = P.AEGEAN, fg: str = P.PAPER, shape: str = "square") -> Image.Image:
    """Rounded square (app icon) or circle (tray) with a mic. Drawn 4x and downsampled."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bgc = P.rgb(bg) + (255,)
    fgc = P.rgb(fg) + (255,)
    if shape == "circle":
        d.ellipse((0, 0, s - 1, s - 1), fill=bgc)
    else:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=bgc)
    w = s / 64  # design grid: 64 units
    if size <= 24:  # small: fewer, fatter strokes and a wider gap so the cradle never touches
        stroke = max(1, int(6.5 * w))
        d.rounded_rectangle((25 * w, 9 * w, 39 * w, 35 * w), radius=int(7 * w), fill=fgc)
        d.arc((13 * w, 15 * w, 51 * w, 45 * w), start=10, end=170, fill=fgc, width=stroke)
        d.line((32 * w, 44 * w, 32 * w, 54 * w), fill=fgc, width=stroke)
        d.rounded_rectangle((21 * w, 51 * w, 43 * w, 51 * w + stroke), radius=stroke // 2, fill=fgc)
    else:
        stroke = max(1, int(4.5 * w))
        d.rounded_rectangle((25 * w, 12 * w, 39 * w, 37 * w), radius=int(7 * w), fill=fgc)   # capsule
        d.arc((18 * w, 20 * w, 46 * w, 45 * w), start=0, end=180, fill=fgc, width=stroke)    # cradle
        d.line((32 * w, 45 * w, 32 * w, 52 * w), fill=fgc, width=stroke)                     # stem
        d.rounded_rectangle((24 * w, 50 * w, 40 * w, 50 * w + stroke), radius=stroke // 2, fill=fgc)
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path) -> None:
    """Every size drawn natively (Pillow would otherwise just downscale the 256 image)."""
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [mic_image(n) for n in sizes]
    imgs[-1].save(path, format="ICO", sizes=[(n, n) for n in sizes], append_images=imgs[:-1])


TRAY = {"idle": P.INK, "recording": P.TILE, "busy": P.AEGEAN}


def tray_image(state: str) -> Image.Image:
    """Windows shows tray icons at 16-24 px; use the small geometry, upscaled cleanly."""
    return mic_image(24, bg=TRAY.get(state, P.INK), shape="circle").resize((64, 64), Image.LANCZOS)
