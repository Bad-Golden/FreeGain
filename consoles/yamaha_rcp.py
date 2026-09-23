"""
consoles/yamaha_rcp.py

Yamaha "RCP" remote-control protocol: plain-text lines over TCP port 49280,
used by the TF, CL, QL, DM3, DM7 and Rivage PM series (the same protocol
third-party controllers like Companion and Bitfocus use).

  get MIXER:Current/InCh/Label/Name <ch-1> 0
    -> OK get MIXER:Current/InCh/Label/Name 0 0 "Vox"
  set MIXER:Current/InCh/Fader/On <ch-1> 0 <0|1>     (On=0 means muted)
  set MIXER:Current/MuteMaster/On <group-1> 0 <0|1>  (1 = mute group active)

EXPERIMENTAL: written from the published parameter names, not yet tested
against a real Yamaha console. Remote control must be enabled on the desk.
"""

import re

from .tcp import TCPDriver

_NAME_RE = re.compile(r'^(?:OK|NOTIFY) (?:get|set) MIXER:Current/InCh/Label/Name (\d+) \d+ "(.*)"')


class YamahaRCPDriver(TCPDriver):
    supports_names = True
    supports_mute_groups = True
    supports_channel_mute = True

    def __init__(self, profile: dict):
        super().__init__(profile)
        self._buffer = ""

    def _send_line(self, line: str) -> bool:
        return self.send_bytes((line + "\n").encode("utf-8"))

    def on_connected(self):
        self._buffer = ""
        self.request_all_channel_names()

    def keepalive(self):
        self._send_line("devinfo productname")

    def request_all_channel_names(self):
        for ch in range(self.max_channels):
            self._send_line(f"get MIXER:Current/InCh/Label/Name {ch} 0")

    def set_channel_mute(self, channel_one_indexed: int, muted: bool) -> bool:
        return self._send_line(
            f"set MIXER:Current/InCh/Fader/On {channel_one_indexed - 1} 0 {0 if muted else 1}")

    def set_mute_group(self, group_one_indexed: int, muted: bool) -> bool:
        return self._send_line(
            f"set MIXER:Current/MuteMaster/On {group_one_indexed - 1} 0 {1 if muted else 0}")

    def on_data(self, data: bytes):
        self._buffer += data.decode("utf-8", errors="replace")
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            self.handle_line(line.strip())

    def handle_line(self, line: str):
        match = _NAME_RE.match(line)
        if match:
            self._emit_name(int(match.group(1)) + 1, match.group(2))
