from PIL import Image

from ecoscribe.icon import TRAY, mic_image, save_ico, tray_image


def test_ico_has_every_size(tmp_path):
    p = tmp_path / "d.ico"
    save_ico(p)
    sizes = set(Image.open(p).info["sizes"])
    assert {(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)} <= sizes


def test_images_are_square_rgba():
    for n in (16, 24, 64, 256):
        im = mic_image(n)
        assert im.size == (n, n) and im.mode == "RGBA"
    for state in TRAY:
        assert tray_image(state).size == (64, 64)


def test_tray_states_differ():
    px = {s: tray_image(s).getpixel((10, 32)) for s in TRAY}
    assert len(set(px.values())) == 3
