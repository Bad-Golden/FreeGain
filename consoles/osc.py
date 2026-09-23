"""
consoles/osc.py

OSC-over-UDP driver, driven entirely by the profile's address templates.
Covers Behringer X32 / XAir, Midas M32 / MR, Behringer Wing, and a
"Generic OSC" profile users can point at any OSC-capable console.

These consoles reply to whichever local port a request was SENT from, so
one UDP socket is used for both sending and receiving.

Profile keys used (templates use {ch} / {n}, with format specs allowed,
e.g. "/ch/{ch:02d}/config/name"):
  port                   UDP port on the console
  name_address           query/reply address for a channel's name
  mute_group_address     address to set a mute group (optional)
  mute_group_values      [unmuted_value, muted_value], default [0, 1]
  channel_mute_address   address to mute a channel (optional)
  channel_mute_values    [unmuted_value, muted_value], default [0, 1]
                         (X32 uses ".../mix/on", so it's [1, 0])
  keepalive              list of addresses sent every few seconds
  meter_request          [address, arg] to (re)subscribe meters (optional)
  meter_format           "int16_db" (XAir) or "float32" (X32)
"""

import re
import socket
import struct
import threading
from typing import Callable, Optional

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket, ParseError

from .base import KEEPALIVE_INTERVAL_S, ConsoleDriver, valid_ip


def template_to_regex(template: str) -> "re.Pattern":
    """'/ch/{ch:02d}/config/name' -> r'^/ch/(\\d+)/config/name$'"""
    parts = re.split(r"\{ch(?::[^}]*)?\}", template)
    return re.compile("^" + r"(\d+)".join(re.escape(p) for p in parts) + "$")


class OSCDriver(ConsoleDriver):
    def __init__(self, profile: dict):
        super().__init__(profile)
        self.meter_format = profile.get("meter_format", "float32")
        self.name_address = profile.get("name_address")
        self._name_re = template_to_regex(self.name_address) if self.name_address else None
        self.supports_names = bool(self.name_address)
        self.supports_mute_groups = bool(profile.get("mute_group_address"))
        self.supports_channel_mute = bool(profile.get("channel_mute_address"))

        self.sock: Optional[socket.socket] = None
        self.mixer_addr = None
        self.meters_enabled = False
        self._send_lock = threading.Lock()
        self._threads = []

        self.on_meter_block: Optional[Callable[[list], None]] = None
        self.on_parameter_changed: Optional[Callable[[str, object], None]] = None

    # ---------- lifecycle ----------

    def connect(self, host: str, local_port: int = 0, port: Optional[int] = None) -> bool:
        """
        Success only means the socket is open -- see is_responding().
        `port` overrides the profile's port (used for testing).
        """
        self.disconnect()
        if not valid_ip(host):
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", local_port))
            sock.settimeout(0.5)
        except OSError:
            return False

        self.sock = sock
        self.host = host
        self.mixer_addr = (host, port if port is not None else self.profile["port"])
        self.last_reply_time = 0.0
        self.connected = True
        self._stop_event = threading.Event()
        self._threads = [
            threading.Thread(target=self._recv_loop, args=(sock, self._stop_event), daemon=True),
            threading.Thread(target=self._keepalive_loop, args=(self._stop_event,), daemon=True),
        ]
        for t in self._threads:
            t.start()

        self.send_keepalive()
        # Probe: any reply flips is_responding(), so ask for channel 1's name.
        if self.name_address:
            self.request_channel_name(1)
        return True

    def disconnect(self):
        super().disconnect()
        self.meters_enabled = False
        sock, self.sock = self.sock, None
        if sock:
            sock.close()
        for t in self._threads:
            if t.is_alive() and t is not threading.current_thread():
                t.join(timeout=1.0)
        self._threads = []

    # ---------- commands ----------

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
            return False

    def send_keepalive(self):
        for address in self.profile.get("keepalive", []):
            self._send(address)
        if self.meters_enabled and self.profile.get("meter_request"):
            address, arg = self.profile["meter_request"]
            self._send(address, [arg])

    def request_channel_name(self, channel_one_indexed: int):
        if self.name_address:
            self._send(self.name_address.format(ch=channel_one_indexed))

    def request_all_channel_names(self):
        for ch in range(1, self.max_channels + 1):
            self.request_channel_name(ch)

    def subscribe_to_meters(self):
        if self.profile.get("meter_request"):
            self.meters_enabled = True
            self.send_keepalive()

    def set_mute_group(self, group_one_indexed: int, muted: bool) -> bool:
        template = self.profile.get("mute_group_address")
        if not template:
            return False
        values = self.profile.get("mute_group_values", [0, 1])
        return self._send(template.format(n=group_one_indexed), [values[1 if muted else 0]])

    def set_channel_mute(self, channel_one_indexed: int, muted: bool) -> bool:
        template = self.profile.get("channel_mute_address")
        if not template:
            return False
        values = self.profile.get("channel_mute_values", [0, 1])
        return self._send(template.format(ch=channel_one_indexed), [values[1 if muted else 0]])

    def set_channel_fader(self, channel_one_indexed: int, normalized_level: float) -> bool:
        template = self.profile.get("fader_address")
        if not template:
            return False
        level = max(0.0, min(1.0, float(normalized_level)))
        return self._send(template.format(ch=channel_one_indexed), [level])

    # ---------- background threads ----------

    def _keepalive_loop(self, stop_event):
        while not stop_event.wait(KEEPALIVE_INTERVAL_S):
            self.send_keepalive()

    def _recv_loop(self, sock, stop_event):
        # `sock` is passed in so a concurrent disconnect() (which sets
        # self.sock = None) can't make this loop call a method on None.
        while not stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                packet = OscPacket(data)
            except (ParseError, ValueError, struct.error, IndexError):
                continue
            self.mark_reply()
            for timed_msg in packet.messages:
                try:
                    self._handle_message(timed_msg.message)
                except Exception as exc:  # a bad callback must not kill the thread
                    print(f"[osc] error handling {timed_msg.message.address}: {exc}")

    def _handle_message(self, message):
        address = message.address
        params = list(message.params)

        if address.startswith("/meters/"):
            if params and isinstance(params[0], (bytes, bytearray)) and self.on_meter_block:
                self.on_meter_block(parse_meter_blob(params[0], self.meter_format))
            return

        if self._name_re:
            match = self._name_re.match(address)
            if match:
                name = next((p for p in params if isinstance(p, str)), None)
                if name is not None:
                    self._emit_name(int(match.group(1)), name)
                return

        if params and isinstance(params[0], (int, float)) and self.on_parameter_changed:
            self.on_parameter_changed(address, params[0])


def parse_meter_blob(blob: bytes, meter_format: str = "int16_db") -> list:
    """
    Meter blobs are an int32 value count followed by that many values, all
    little-endian. Returns linear 0..1 levels.

      int16_db (XAir): signed 16-bit, units of 1/256 dB (0 = 0 dBFS)
      float32  (X32):  32-bit float, already linear 0..1

    Crash-safe against truncated/over-claimed/negative counts.
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
