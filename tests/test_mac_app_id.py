"""dictado-uee: on the Mac, Coach me's people / AI split goes by bundle id, so a translated app name still counts."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS bundle ids")


def test_bundle_ids_map_to_the_names_coach_knows():
    from ecoscribe.coach import audience
    from ecoscribe.platform.macos.context import app_key
    assert app_key("com.apple.MobileSMS") == "messages" and audience(app_key("com.apple.MobileSMS")) == "people"
    assert audience(app_key("com.apple.mail")) == "people"
    assert audience(app_key("com.anthropic.claudefordesktop")) == "ai"
    assert audience(app_key("com.tinyspeck.slackmacgap")) == "people"  # from detect.BUNDLES
    assert app_key("com.google.Chrome") == "chrome" and audience("chrome", "Invented - Inbox - Gmail") == "people"


def test_an_unknown_bundle_falls_back_to_the_name():
    from ecoscribe.platform.macos.context import app_key
    assert app_key("com.example.notes") == "" and app_key("") == ""


def test_foreground_app_reads_the_frontmost_bundle():
    from ecoscribe.platform.macos.context import foreground_app
    assert isinstance(foreground_app(), str)  # whatever is in front; never raises
