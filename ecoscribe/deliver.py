"""Put the transcript into whatever window has focus right now: clipboard + paste, the previous
clipboard text restored afterwards (per platform: ecoscribe/platform/windows/deliver.py,
ecoscribe/platform/macos/deliver.py)."""
import sys

if sys.platform == "darwin":  # NSPasteboard + Cmd+V
    from .platform.macos.deliver import (ClipboardBusy, DeliveryResult, deliver, foreground_exe,  # noqa: F401
                                         get_clipboard_text, set_clipboard_text)
else:  # clipboard + Ctrl+V, kept out of clipboard history
    from .platform.windows.deliver import (ClipboardBusy, DeliveryResult, deliver, foreground_exe,  # noqa: F401
                                           get_clipboard_text, set_clipboard_text)
