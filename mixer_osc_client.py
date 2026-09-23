"""
mixer_osc_client.py (replaces xair_osc_client.py)

OSC client for Behringer/Midas XAir and X32/M32 mixers.

IMPORTANT PROTOCOL CORRECTION from the earlier version of this file:
Both mixer families reply to whichever local port your OUTGOING request
was sent from -- not to a separately configured "listen port". This is
documented in Behringer's own X32-OSC protocol PDF ("replies are sent
back to the requester's IP/port"), and confirmed by community reports of
exactly this mistake (binding a different receive port and never getting
replies). The earlier version of this client bound two different sockets
(one to send, a separate one to listen) and would never have actually
received anything back from a real mixer. This version binds ONE socket
and uses it for both sending and receiving, which is the pattern the
protocol actually requires.

Status: written against python-osc's documented API (OscMessageBuilder /
OscPacket) but NOT executed against the real library or real hardware in
the environment this was built in -- no network access to install
python-osc, no XAir/X32 unit to test against. Test this against a real
mixer (or at least a real python-osc install + a UDP echo test) before
trusting it. See README.md.

Supports both XAir and X32 via console_profiles.py -- the address scheme
is identical between the two families, only the port and channel-count
ceiling differ.
"""

import re
import socket
import struct
import threading
import time
from typing import Callable, Optional

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket

from console_profiles import CONSOLE_PROFILES, DEFAULT_PROFILE


class MixerOSCClient:
    def __init__(self, console_type: str = DEFAULT_PROFILE):
        if console_type not in CONSOLE_PROFILES:
            raise ValueError(f"Unknown console_type '{console_type}', "
                              f"expected one of {list(CONSOLE_PROFILES)}")
        self.console_type = console_type
        self.profile = CONSOLE_PROFILES[console_type]
        self.max_channels = self.profile["max_channels"]

        self.sock: Optional[socket.socket] = None
        self.mixer_addr = None
        self.connected = False

        self._recv_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None

        # Callbacks, set these from the UI layer.
        self.on_channel_name: Optional[Callable[[int, str], None]] = None
        self.on_meter_block: Optional[Callable[[list], None]] = None
        self.on_parameter_changed: Optional[Callable[[str, float], None]] = None

    def connect(self, mixer_ip: str, local_port: int = 0) -> bool:
        """
        local_port=0 lets the OS pick an ephemeral port. That's fine --
        we use the SAME socket for sending and receiving, so whichever
        port the OS picks is exactly the port the mixer will reply to.
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("0.0.0.0", local_port))
            self.sock.settimeout(1.0)
            self.mixer_addr = (mixer_ip, self.profile["port"])
            self.connected = True

            self._stop_event.clear()
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()

            self._start_keepalive()
            return True
        except OSError:
            self.connected = False
            return False

    def disconnect(self):
        self._stop_event.set()
        self.connected = False
        if self.sock:
            self.sock.close()
            self.sock = None

    def _send(self, address: str, args=None):
        if not self.sock or not self.mixer_addr:
            return
        builder = OscMessageBuilder(address=address)
        for arg in (args or []):
            builder.add_arg(arg)
        msg = builder.build()
        self.sock.sendto(msg.dgram, self.mixer_addr)

    def send_keepalive(self):
        self._send("/xremote")

    def request_channel_name(self, channel_one_indexed: int):
        self._send(f"/ch/{channel_one_indexed:02d}/config/name")

    def subscribe_to_meters(self):
        self._send("/meters", ["/meters/1"])

    def set_mute_group(self, group_one_indexed: int, muted: bool):
        self._send(f"/config/mute/{group_one_indexed}", [1 if muted else 0])

    def set_channel_fader(self, channel_one_indexed: int, normalized_level: float):
        self._send(f"/ch/{channel_one_indexed:02d}/mix/fader", [normalized_level])

    def _start_keepalive(self):
        def loop():
            while not self._stop_event.is_set():
                self.send_keepalive()
                self._stop_event.wait(8.0)

        self._keepalive_thread = threading.Thread(target=loop, daemon=True)
        self._keepalive_thread.start()

    def _recv_loop(self):
        while not self._stop_event.is_set():
            try:
                data, _addr = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed during disconnect()

            try:
                packet = OscPacket(data)
            except Exception:
                continue  # malformed/non-OSC datagram -- ignore, don't crash

            for timed_msg in packet.messages:
                self._handle_message(timed_msg.message)

    def _handle_message(self, message):
        address = message.address
        params = list(message.params)

        if address.startswith("/meters/"):
            if params and isinstance(params[0], bytes):
                levels = self._parse_meter_blob(params[0])
                if self.on_meter_block:
                    self.on_meter_block(levels)
            return

        if "/config/name" in address and params and isinstance(params[0], str):
            chan = self._extract_channel_number(address)
            if self.on_channel_name and chan > 0:
                self.on_channel_name(chan, params[0])
            return

        if params and isinstance(params[0], float):
            if self.on_parameter_changed:
                self.on_parameter_changed(address, params[0])

    @staticmethod
    def _extract_channel_number(address: str) -> int:
        match = re.search(r"/(\d+)/", address)
        return int(match.group(1)) if match else -1

    @staticmethod
    def _parse_meter_blob(blob: bytes) -> list:
        """
        Meter blobs are a count (int32) followed by that many 16-bit
        fixed point values. Exact scaling is mixer/firmware-specific;
        this returns normalized 0..1 estimates. Verified crash-safe
        against malformed/truncated/adversarial input via stress testing,
        but the actual byte-layout interpretation is still a best guess
        not confirmed against real mixer traffic -- capture real OSC
        packets (e.g. with Wireshark) and adjust if values look wrong.
        """
        if len(blob) < 4:
            return []
        count = struct.unpack_from("<i", blob, 0)[0]
        available = (len(blob) - 4) // 2
        count = min(count, available)
        levels = []
        for i in range(max(count, 0)):
            sample = struct.unpack_from("<h", blob, 4 + i * 2)[0]
            levels.append(max(0.0, min(1.0, (sample + 32768.0) / 65536.0)))
        return levels
