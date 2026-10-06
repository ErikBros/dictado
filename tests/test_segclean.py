import numpy as np

from dictado import segclean

SR = 16000


def test_strip_tags():
    assert segclean.strip_tags("och så podden <i>Ardalan träffar</i>") == "och så podden Ardalan träffar"
    assert segclean.strip_tags('<font color="#fff">Hej</font> där') == "Hej där"
    assert segclean.strip_tags("&lt;i&gt;Hej&lt;/i&gt;") == "Hej"
    assert segclean.strip_tags("3 < 5 och 7 > 2") == "3 < 5 och 7 > 2"  # not a tag


def test_credit_lines():
    for s in ("Text: VSI OrdKedjan 2021 www.vsi-stockholm.se", "Undertexter av Amara.org", "Textning: SVT",
              "Svensktextning.nu", "Översättning: Anna", "Subtitles by the Amara.org community",
              "Undertexter från Amara.org-gemenskapen"):
        assert segclean.is_credit(s), s
    for s in ("Text är viktigt i det här projektet.", "Vi pratar om undertexter på YouTube.",
              "Ja, hallå där och välkommen till Simple Swedish Podcast", "Översätt det till engelska."):
        assert not segclean.is_credit(s), s


def test_clean_segments_drops_credits_and_tags():
    segs = [{"t0": 0, "t1": 2, "text": "Hej <i>alla</i>"}, {"t0": 2, "t1": 4, "text": "Text: VSI 2021"},
            {"t0": 4, "t1": 5, "text": "<i></i>"}]
    assert [s["text"] for s in segclean.clean_segments(segs)] == ["Hej alla"]


def test_drop_silent_keeps_speech_on_either_track():
    mic = np.zeros(SR * 9, np.float32)
    system = np.zeros(SR * 9, np.float32)
    mic[0:SR * 3] = 0.05  # 0-3 s: the user
    system[3 * SR:6 * SR] = 0.02  # 3-6 s: the others; 6-9 s digital silence on both
    segs = [{"t0": 0.0, "t1": 3.0, "text": "a"}, {"t0": 3.0, "t1": 6.0, "text": "b"},
            {"t0": 6.0, "t1": 9.0, "text": "Text: VSI"}, {"t0": 6.5, "t1": 8.0, "text": "c"}]
    assert [s["text"] for s in segclean.drop_silent(segs, mic, system)] == ["a", "b"]


def test_drop_silent_keeps_segments_past_the_audio():
    segs = [{"t0": 20.0, "t1": 21.0, "text": "x"}]  # no audio to judge it by: keep, never lose text
    assert segclean.drop_silent(segs, np.zeros(SR), np.zeros(SR)) == segs
