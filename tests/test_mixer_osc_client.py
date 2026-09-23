import socket
import struct
import threading
import time

import pytest
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket

from mixer_osc_client import MixerOSCClient


def osc(address, *args):
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


class FakeMixer:
    """Minimal UDP mixer: replies to the sender's port, like the real thing."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.received = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            for m in OscPacket(data).messages:
                msg = m.message
                self.received.append((msg.address, list(msg.params)))
                if msg.address == "/info":
                    self.sock.sendto(osc("/info", "V1.0", "fake", "XR18", "1.0"), addr)
                elif msg.address.endswith("/config/name"):
                    ch = int(msg.address.split("/")[2])
                    self.sock.sendto(osc(msg.address, f"Vox {ch}"), addr)

    def close(self):
        self._stop.set()
        self.sock.close()
        self._thread.join(1)


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def mixer():
    m = FakeMixer()
    yield m
    m.close()


def test_round_trip_against_fake_mixer(mixer):
    client = MixerOSCClient("xair")
    names = {}
    client.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    try:
        assert client.connect("127.0.0.1", port=mixer.port)
        assert wait_for(client.is_responding)
        client.request_all_channel_names()
        assert wait_for(lambda: len(names) == 18)
        assert names[1] == "Vox 1" and names[18] == "Vox 18"

        assert client.set_mute_group(1, True)
        client.subscribe_to_meters()
        client.send_keepalive()
        assert wait_for(lambda: ("/config/mute/1", [1]) in mixer.received)
        assert wait_for(lambda: ("/meters", ["/meters/1"]) in mixer.received)
        assert wait_for(lambda: ("/xremote", []) in mixer.received)
    finally:
        client.disconnect()
    assert not client.connected
    assert client.set_mute_group(1, False) is False  # no crash after disconnect


def test_not_responding_without_mixer():
    client = MixerOSCClient("x32")
    try:
        assert client.connect("127.0.0.1", port=9)  # nothing listening
        time.sleep(0.1)
        assert client.connected and not client.is_responding()
    finally:
        client.disconnect()


def test_invalid_ip_rejected():
    client = MixerOSCClient()
    assert client.connect("not-an-ip") is False
    assert client.connect("192.168.1.") is False
    assert not client.connected


def test_unknown_console_type():
    with pytest.raises(ValueError):
        MixerOSCClient("x99")


def test_fader_level_clamped(mixer):
    client = MixerOSCClient("xair")
    try:
        client.connect("127.0.0.1", port=mixer.port)
        client.set_channel_fader(3, 1.7)
        assert wait_for(lambda: any(a == "/ch/03/mix/fader" for a, _ in mixer.received))
        params = next(p for a, p in mixer.received if a == "/ch/03/mix/fader")
        assert params == [pytest.approx(1.0)]
    finally:
        client.disconnect()


@pytest.mark.parametrize("address,expected", [
    ("/ch/01/config/name", 1),
    ("/ch/32/config/name", 32),
    ("/bus/1/config/name", -1),
    ("/config/name", -1),
])
def test_extract_channel_number(address, expected):
    assert MixerOSCClient._extract_channel_number(address) == expected


def test_parse_int16_db_meters():
    blob = struct.pack("<i3h", 3, 0, -256 * 20, -256 * 128)
    levels = MixerOSCClient.parse_meter_blob(blob, "int16_db")
    assert levels[0] == pytest.approx(1.0)
    assert levels[1] == pytest.approx(0.1)
    assert levels[2] < 1e-6


def test_parse_float32_meters():
    blob = struct.pack("<i3f", 3, 0.5, 2.0, float("nan"))
    assert MixerOSCClient.parse_meter_blob(blob, "float32") == [0.5, 1.0, 0.0]


@pytest.mark.parametrize("blob", [
    b"",
    b"\x01\x00",
    struct.pack("<i", 100) + b"\x00\x00",  # over-claimed count
    struct.pack("<i", -5) + b"\x00" * 8,  # negative count
    struct.pack("<i", 2) + b"\x00",  # truncated value
])
@pytest.mark.parametrize("fmt", ["int16_db", "float32"])
def test_parse_meter_blob_malformed(blob, fmt):
    levels = MixerOSCClient.parse_meter_blob(blob, fmt)
    assert all(0.0 <= v <= 1.0 for v in levels)


def test_meter_messages_dispatched(mixer):
    client = MixerOSCClient("xair")
    got = []
    client.on_meter_block = got.append
    try:
        client.connect("127.0.0.1", port=mixer.port)
        blob = struct.pack("<i2h", 2, 0, -256 * 6)
        local_port = client.sock.getsockname()[1]
        mixer.sock.sendto(osc("/meters/1", blob), ("127.0.0.1", local_port))
        assert wait_for(lambda: got)
        assert len(got[0]) == 2
    finally:
        client.disconnect()


def test_garbage_datagram_does_not_kill_receiver(mixer):
    client = MixerOSCClient("xair")
    names = {}
    client.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    try:
        client.connect("127.0.0.1", port=mixer.port)
        local_port = client.sock.getsockname()[1]
        mixer.sock.sendto(b"\xff\xfe garbage", ("127.0.0.1", local_port))
        client.request_channel_name(2)
        assert wait_for(lambda: names.get(2) == "Vox 2")
    finally:
        client.disconnect()
