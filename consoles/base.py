"""
consoles/base.py

Common interface every console driver implements, so the app doesn't care
which brand of mixer it's talking to.

A driver covers the *control* side only (channel names, mutes). Audio for
the feedback filter always comes in through whatever audio interface the
console exposes to the computer (USB, Dante Virtual Soundcard, an external
interface...), which works with any console regardless of driver.

Callbacks (`on_channel_name`) fire on a driver's background thread, never
the UI thread -- UI code must queue the data rather than touch widgets.
"""

import ipaddress
import threading
import time
from typing import Callable, Optional

# A console counts as "responding" if it sent something within this window.
RESPONSE_TIMEOUT_S = 12.0
KEEPALIVE_INTERVAL_S = 5.0


def valid_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class ConsoleDriver:
    """Base class. Subclasses override the capability flags and methods."""

    supports_names = False
    supports_mute_groups = False
    supports_channel_mute = False
    needs_network = True

    def __init__(self, profile: dict):
        self.profile = profile
        self.max_channels = profile.get("max_channels", 32)
        self.connected = False
        self.host: Optional[str] = None
        self.last_reply_time = 0.0
        self.on_channel_name: Optional[Callable[[int, str], None]] = None
        self._stop_event = threading.Event()

    # ---------- lifecycle ----------

    def connect(self, host: str) -> bool:
        raise NotImplementedError

    def disconnect(self):
        self._stop_event.set()
        self.connected = False

    def mark_reply(self):
        self.last_reply_time = time.monotonic()

    def is_responding(self) -> bool:
        return (self.connected and self.last_reply_time > 0
                and time.monotonic() - self.last_reply_time < RESPONSE_TIMEOUT_S)

    # ---------- commands (return True if sent) ----------

    def request_all_channel_names(self):
        pass

    def set_mute_group(self, group_one_indexed: int, muted: bool) -> bool:
        return False

    def set_channel_mute(self, channel_one_indexed: int, muted: bool) -> bool:
        return False

    # ---------- helpers ----------

    def _emit_name(self, channel: int, name: str):
        if self.on_channel_name and 1 <= channel <= self.max_channels:
            self.on_channel_name(channel, name)


class AudioOnlyDriver(ConsoleDriver):
    """No remote control -- for any console, via its audio interface only."""

    needs_network = False

    def connect(self, host: str) -> bool:
        return False
