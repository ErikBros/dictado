"""Screenshot the window pages in headless Edge (demo API) for design review.

    python shoot.py [out_dir]   -> <page>@<scale>x.png for every page at 100% and 150%
Headless Edge opens no visible window.
"""
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else APP / "packaging" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
index = (APP / "dictado" / "web" / "index.html").as_uri()
SHOTS = {
    "inicio": "page=inicio", "historial": "page=historial", "ajustes": "page=ajustes",
    "bienvenida": "page=bienvenida&welcome=1", "detenido": "page=inicio&state=stopped",
    "cargando": "page=inicio&state=loading",
    "ajustes-cambios": "page=ajustes&dirty=1",
    "reuniones": "page=reuniones", "reuniones-vacia": "page=reuniones&rec=0",
    "reunion-directo": "page=reuniones/2026-10-05_1400_retro",
    "reunion-lista": "page=reuniones/2026-10-05_0915_planering",
    "reunion-cola": "page=reuniones/2026-10-05_1130_podcast",
}
TALL = {"ajustes-largo": "page=ajustes&dirty=1"}
for scale in (1, 1.5):
    for name, q in SHOTS.items():
        out = OUT / f"{name}@{scale}x.png"
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--force-device-scale-factor={scale}", "--window-size=980,690",
                        "--virtual-time-budget=2500", f"--screenshot={out}", f"{index}?demo=1&{q}"],
                       check=True, capture_output=True, timeout=60)
        print(out.name)
for name, q in TALL.items():
    out = OUT / f"{name}@1x.png"
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--window-size=980,1180", "--virtual-time-budget=2500", f"--screenshot={out}", f"{index}?demo=1&{q}"],
                   check=True, capture_output=True, timeout=60)
    print(out.name)
