"""Write packaging/ecoscribe.ico (+ a preview PNG) from ecoscribe/icon.py."""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from ecoscribe.icon import mic_image, save_ico, tray_image  # noqa: E402

save_ico(APP / "packaging" / "ecoscribe.ico")
sheet = mic_image(256)
from PIL import Image  # noqa: E402
canvas = Image.new("RGBA", (256 + 3 * 80 + 40, 256), (251, 250, 246, 255))
canvas.paste(sheet, (0, 0), sheet)
for i, st in enumerate(("idle", "recording", "busy")):
    t = tray_image(st).resize((64, 64))
    canvas.paste(t, (276 + i * 80, 96), t)
canvas.save(APP / "packaging" / "icon-preview.png")
print("ok")
