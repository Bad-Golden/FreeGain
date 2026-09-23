"""
consoles/allen_heath.py

Allen & Heath consoles accept MIDI messages over a TCP connection:
  Qu series        port 51325   channel mute via Note On
  dLive MixRack    port 51328   channel mute via Note On
  Avantis          port 51325   channel mute via Note On
  SQ series        port 51325   channel mute via NRPN

Note On mute (Qu / dLive / Avantis), N = MIDI channel - 1, CH = input - 1:
  9N CH 7F  9N CH 00   -> mute on
  9N CH 3F  9N CH 00   -> mute off

NRPN mute (SQ), inputs are parameter MSB 0x00, LSB = input - 1:
  BN 63 00  BN 62 CH  BN 06 00  BN 26 <01 on | 00 off>

The MIDI channel must match the one set on the console (defaults to 1 on
Qu/SQ/Avantis, 12 on dLive). Override it with "midi_channel" in
local_config.json's "console_options" if yours differs.

Channel names use SysEx that differs per family, so names aren't fetched.

EXPERIMENTAL: follows Allen & Heath's published MIDI protocol documents
but hasn't been tested against a real console yet.
"""

from .tcp import TCPDriver


class AllenHeathDriver(TCPDriver):
    supports_channel_mute = True

    def __init__(self, profile: dict):
        super().__init__(profile)
        self.midi_channel = int(profile.get("midi_channel", 1))
        self.mute_style = profile.get("mute_style", "note")  # "note" or "nrpn"

    def mute_message(self, channel_one_indexed: int, muted: bool) -> bytes:
        n = (self.midi_channel - 1) & 0x0F
        ch = (channel_one_indexed - 1) & 0x7F
        if self.mute_style == "nrpn":
            status = 0xB0 | n
            return bytes([status, 0x63, 0x00, status, 0x62, ch,
                          status, 0x06, 0x00, status, 0x26, 0x01 if muted else 0x00])
        status = 0x90 | n
        return bytes([status, ch, 0x7F if muted else 0x3F, status, ch, 0x00])

    def set_channel_mute(self, channel_one_indexed: int, muted: bool) -> bool:
        if not 1 <= channel_one_indexed <= self.max_channels:
            return False
        return self.send_bytes(self.mute_message(channel_one_indexed, muted))
