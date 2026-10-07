"""Start at login: the HKCU Run key on Windows, a LaunchAgent on macOS (ecoscribe/platform/*/startup.py)."""
import sys

if sys.platform == "darwin":
    from .platform.macos.startup import OLD_NAME, NAME, app_command, disable, enable, get, is_enabled  # noqa: F401
else:
    from .platform.windows.startup import OLD_NAME, NAME, app_command, disable, enable, get, is_enabled  # noqa: F401
