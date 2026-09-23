"""
mixer_osc_client.py

OSC client for Behringer/Midas XAir and X32/M32 mixers.

Both mixer families reply to whichever local port your OUTGOING request
was sent from -- not to a separately configured "listen port". So this
client binds ONE UDP socket and uses it for both sending and receiving.

Subscriptions on both families expire after ~10 seconds: `/xremote`
(push notifications for parameter changes) and `/meters/...` (meter
streaming) both have to be renewed periodically. The keepalive thread
here renews both.

UDP has no handshake, so "connected" here only means the socket is open.
`is_responding()` tells you whether the mixer has actually replied
recently -- use that for any "connected" indicator shown to the user.

Callbacks (`on_channel_name`, `on_meter_block`, `on_parameter_changed`)
are invoked from the client's background receive thread, NOT the UI
thread. UI code must hand the data over to its own thread (e.g. via a
queue) rather than touching widgets directly from inside a callback.

Supports both XAir and X32 via console_profiles.py -- the address scheme
is identical between the two families; only the port, channel count and
meter encoding differ.
"""

import ipaddress
import re
import socket
import struct
import threading
import time
from typing import Callable, Optional

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket, ParseError

from console_profiles import CONSOLE_PROFILES, DEFAULT_PROFILE

# Subscriptions expire after ~10s on the mixer; renew comfortably inside that.
KEEPALIVE_INTERVAL_S = 5.0
# Mixer counts as "responding" if it replied within this window.
RESPONSE_TIMEOUT_S = 12.0

_CHANNEL_RE = re.compile(r"^/ch/(\d+)/")


class MixerOSCClient:
    def __init__(self, console_type: str = DEFAULT_PROFILE):
        if console_type not in CONSOLE_PROFILES:
            raise ValueError(f"Unknown console_type '{console_type}', "
                             f"expected one of {list(CONSOLE_PROFILES)}")
        self.console_type = console_type
        self.profile = CONSOLE_PROFILES[console_type]
        self.max_channels = self.profile["max_channels"]
        self.meter_format = self.profile["meter_format"]

        self.sock: Optional[socket.socket] = None
        self.mixer_addr = None
        self.connected = False
        self.last_reply_time = 0.0
        self.meters_enabled = False

        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None

        # Callbacks, set these from the UI layer. Called on the receive
        # thread -- see module docstring.
        self.on_channel_name: Optional[Callable[[int, str], None]] = None
        self.on_meter_block: Optional[Callable[[list], None]] = None
        self.on_parameter_changed: Optional[Callable[[str, object], None]] = None

    # ---------- Connection lifecycle ----------

    def connect(self, mixer_ip: str, local_port: int = 0, port: Optional[int] = None) -> bool:
        """
        Open the socket and start background threads. Returns False if the
        IP is invalid or the socket can't be opened. Note that success does
        NOT mean a mixer is there -- see is_responding().

        local_port=0 lets the OS pick an ephemeral port. That's fine: we use
        the SAME socket for sending and receiving, so whichever port the OS
        picks is exactly the port the mixer replies to. `port` overrides the
        profile's mixer port (useful for testing against a local fake).
        """
        self.disconnect()
        try:
            ipaddress.ip_address(mixer_ip)
        except ValueError:
            return False

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", local_port))
            sock.settimeout(0.5)
        except OSError:
            return False

        self.sock = sock
        self.mixer_addr = (mixer_ip, port if port is not None else self.profile["port"])
        self.last_reply_time = 0.0
        self.connected = True
        self._stop_event = threading.Event()

        self._recv_thread = threading.Thread(
            target=self._recv_loop, args=(sock, self._stop_event), daemon=True)
        self._recv_thread.start()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, args=(self._stop_event,), daemon=True)
        self._keepalive_thread.start()

        # Probe so is_responding() flips quickly if a mixer is there.
        self._send("/info")
        return True

    def disconnect(self):
        self._stop_event.set()
        self.connected = False
        self.meters_enabled = False
        sock, self.sock = self.sock, None
        if sock:
            sock.close()
        for thread in (self._recv_thread, self._keepalive_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self._recv_thread = None
        self._keepalive_thread = None

    def is_responding(self) -> bool:
        return (self.connected and self.last_reply_time > 0
                and time.monotonic() - self.last_reply_time < RESPONSE_TIMEOUT_S)

    # ---------- Commands ----------

    def _send(self, address: str, args=None) -> bool:
        sock, addr = self.sock, self.mixer_addr
        if not sock or not addr:
            return False
        builder = OscMessageBuilder(address=address)
        for arg in (args or []):
            builder.add_arg(arg)
        try:
            with self._send_lock:
                sock.sendto(builder.build().dgram, addr)
            return True
        except OSError:
            # Network unreachable, socket closed mid-disconnect, etc.
            # Never let a send failure crash a UI callback or thread.
            return False

    def send_keepalive(self):
        self._send("/xremote")
        if self.meters_enabled:
            self._send("/meters", ["/meters/1"])

    def request_channel_name(self, channel_one_indexed: int):
        self._send(f"/ch/{channel_one_indexed:02d}/config/name")

    def request_all_channel_names(self):
        for ch in range(1, self.max_channels + 1):
            self.request_channel_name(ch)

    def subscribe_to_meters(self):
        self.meters_enabled = True
        self._send("/meters", ["/meters/1"])

    def set_mute_group(self, group_one_indexed: int, muted: bool) -> bool:
        return self._send(f"/config/mute/{group_one_indexed}", [1 if muted else 0])

    def set_channel_fader(self, channel_one_indexed: int, normalized_level: float) -> bool:
        level = max(0.0, min(1.0, float(normalized_level)))
        return self._send(f"/ch/{channel_one_indexed:02d}/mix/fader", [level])

    # ---------- Background threads ----------

    def _keepalive_loop(self, stop_event: threading.Event):
        while not stop_event.wait(KEEPALIVE_INTERVAL_S):
            self.send_keepalive()

    def _recv_loop(self, sock: socket.socket, stop_event: threading.Event):
        # `sock` is passed in rather than read from self.sock so that a
        # concurrent disconnect() (which sets self.sock = None) can't make
        # this loop call a method on None.
        while not stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed during disconnect()

            try:
                packet = OscPacket(data)
            except (ParseError, ValueError, struct.error, IndexError):
                continue  # malformed/non-OSC datagram -- ignore, don't crash

            self.last_reply_time = time.monotonic()
            for timed_msg in packet.messages:
                try:
                    self._handle_message(timed_msg.message)
                except Exception as exc:  # a bad callback must not kill the thread
                    print(f"[osc] error handling {timed_msg.message.address}: {exc}")

    def _handle_message(self, message):
        address = message.address
        params = list(message.params)

        if address.startswith("/meters/"):
            if params and isinstance(params[0], (bytes, bytearray)):
                levels = self.parse_meter_blob(params[0], self.meter_format)
                if self.on_meter_block:
                    self.on_meter_block(levels)
            return

        if address.endswith("/config/name") and params and isinstance(params[0], str):
            chan = self._extract_channel_number(address)
            if self.on_channel_name and chan > 0:
                self.on_channel_name(chan, params[0])
            return

        if params and isinstance(params[0], (int, float)) and self.on_parameter_changed:
            self.on_parameter_changed(address, params[0])

    # ---------- Parsing helpers ----------

    @staticmethod
    def _extract_channel_number(address: str) -> int:
        match = _CHANNEL_RE.match(address)
        return int(match.group(1)) if match else -1

    @staticmethod
    def parse_meter_blob(blob: bytes, meter_format: str = "int16_db") -> list:
        """
        Meter blobs are an int32 value count followed by that many values,
        all little-endian. Returns linear 0..1 levels.

          int16_db (XAir): signed 16-bit, units of 1/256 dB (0 = 0 dBFS)
          float32  (X32):  32-bit float, already linear 0..1

        Crash-safe against truncated/over-claimed/negative counts. The
        encodings follow the community-documented XAir/X32 protocol, but
        haven't been checked against captured traffic from real hardware
        yet -- if meter values look wrong, capture packets with Wireshark.
        """
        if len(blob) < 4:
            return []
        count = struct.unpack_from("<i", blob, 0)[0]
        if count <= 0:
            return []

        if meter_format == "float32":
            count = min(count, (len(blob) - 4) // 4)
            raw = struct.unpack_from(f"<{count}f", blob, 4)
            return [max(0.0, min(1.0, v)) if v == v else 0.0 for v in raw]

        count = min(count, (len(blob) - 4) // 2)
        raw = struct.unpack_from(f"<{count}h", blob, 4)
        return [min(1.0, 10.0 ** ((v / 256.0) / 20.0)) for v in raw]
