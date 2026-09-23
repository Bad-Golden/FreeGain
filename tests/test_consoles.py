import re
import struct
import time

import pytest

from consoles import CONSOLE_PROFILES, brands, create_driver, models_for_brand
from consoles.allen_heath import AllenHeathDriver
from consoles.osc import parse_meter_blob, template_to_regex
from consoles.soundcraft_ui import SoundcraftUiDriver
from fakes import FakeOSCMixer, FakeTCPConsole, osc


def wait_for(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------- registry ----------

@pytest.mark.parametrize("key", list(CONSOLE_PROFILES))
def test_every_profile_builds_a_driver(key):
    driver = create_driver(key)
    assert driver.max_channels >= 1
    assert CONSOLE_PROFILES[key]["status"] in ("documented", "experimental")
    assert driver.connect("not-an-ip") is False


def test_brands_cover_all_models():
    assert sum(len(models_for_brand(b)) for b in brands()) == len(CONSOLE_PROFILES)
    for expected in ("Behringer", "Midas", "Yamaha", "Allen & Heath", "Soundcraft"):
        assert expected in brands()


def test_overrides_only_allowed_keys():
    driver = create_driver("generic_osc", {"port": 9000, "driver": "evil", "max_channels": 8})
    assert driver.profile["port"] == 9000
    assert driver.profile["driver"] == "osc"
    assert driver.max_channels == 8


def test_unknown_console():
    with pytest.raises(ValueError):
        create_driver("x99")


def test_audio_only_never_connects():
    driver = create_driver("audio_only")
    assert driver.connect("127.0.0.1") is False
    assert not driver.supports_channel_mute and not driver.supports_mute_groups


# ---------- OSC family ----------

@pytest.mark.parametrize("template,address,channel", [
    ("/ch/{ch:02d}/config/name", "/ch/07/config/name", 7),
    ("/ch/{ch}/name", "/ch/40/name", 40),
])
def test_template_to_regex(template, address, channel):
    assert int(template_to_regex(template).match(address).group(1)) == channel
    assert template_to_regex(template).match("/bus/1/name") is None


@pytest.fixture
def mixer():
    m = FakeOSCMixer()
    yield m
    m.close()


@pytest.mark.parametrize("key,mute_addr,mute_val,group_addr", [
    ("xr18", "/ch/03/mix/on", 0, "/config/mute/1"),
    ("x32", "/ch/03/mix/on", 0, "/config/mute/1"),
    ("wing", "/ch/3/mute", 1, "/mgrp/1/mute"),
])
def test_osc_round_trip(mixer, key, mute_addr, mute_val, group_addr):
    driver = create_driver(key)
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    try:
        assert driver.connect("127.0.0.1", port=mixer.port)
        assert wait_for(driver.is_responding)
        driver.request_all_channel_names()
        assert wait_for(lambda: len(names) == driver.max_channels)
        assert names[1] == "Vox 1"
        assert driver.set_channel_mute(3, True)
        assert driver.set_mute_group(1, True)
        assert wait_for(lambda: (mute_addr, [mute_val]) in mixer.received)
        assert wait_for(lambda: (group_addr, [1]) in mixer.received)
    finally:
        driver.disconnect()
    assert driver.set_mute_group(1, False) is False  # no crash after disconnect


def test_osc_keepalive_and_meters(mixer):
    driver = create_driver("xr18")
    try:
        driver.connect("127.0.0.1", port=mixer.port)
        driver.subscribe_to_meters()
        assert wait_for(lambda: ("/xremote", []) in mixer.received)
        assert wait_for(lambda: ("/meters", ["/meters/1"]) in mixer.received)
    finally:
        driver.disconnect()


def test_osc_meter_and_garbage_handling(mixer):
    driver = create_driver("xr18")
    got = []
    driver.on_meter_block = got.append
    try:
        driver.connect("127.0.0.1", port=mixer.port)
        local = ("127.0.0.1", driver.sock.getsockname()[1])
        mixer.sock.sendto(b"\xff garbage", local)
        mixer.sock.sendto(osc("/meters/1", struct.pack("<i2h", 2, 0, -256 * 6)), local)
        assert wait_for(lambda: got)
        assert len(got[0]) == 2
    finally:
        driver.disconnect()


def test_osc_not_responding_without_console():
    driver = create_driver("x32")
    try:
        assert driver.connect("127.0.0.1", port=9)
        time.sleep(0.1)
        assert driver.connected and not driver.is_responding()
    finally:
        driver.disconnect()


def test_generic_osc_custom_addresses(mixer):
    driver = create_driver("generic_osc", {
        "name_address": "/input/{ch}/label/name",
        "channel_mute_address": "/input/{ch}/mute",
        "channel_mute_values": [0, 1],
        "keepalive": [],
    })
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    try:
        driver.connect("127.0.0.1", port=mixer.port)
        driver.request_channel_name(5)
        driver.set_channel_mute(5, True)
        assert wait_for(lambda: names.get(5) == "Vox 5")
        assert wait_for(lambda: ("/input/5/mute", [1]) in mixer.received)
    finally:
        driver.disconnect()


def test_parse_meter_blobs():
    levels = parse_meter_blob(struct.pack("<i3h", 3, 0, -256 * 20, -256 * 128), "int16_db")
    assert levels[0] == pytest.approx(1.0) and levels[1] == pytest.approx(0.1)
    assert parse_meter_blob(struct.pack("<i3f", 3, 0.5, 2.0, float("nan")), "float32") == [0.5, 1.0, 0.0]


@pytest.mark.parametrize("blob", [
    b"", b"\x01\x00", struct.pack("<i", 100) + b"\x00\x00",
    struct.pack("<i", -5) + b"\x00" * 8, struct.pack("<i", 2) + b"\x00",
])
@pytest.mark.parametrize("fmt", ["int16_db", "float32"])
def test_parse_meter_blob_malformed(blob, fmt):
    assert all(0.0 <= v <= 1.0 for v in parse_meter_blob(blob, fmt))


# ---------- Yamaha RCP ----------

def yamaha_responder(line):
    match = re.match(r"get MIXER:Current/InCh/Label/Name (\d+) 0", line)
    if match:
        return f'OK get MIXER:Current/InCh/Label/Name {match.group(1)} 0 "Ch{match.group(1)}"'
    if line == "devinfo productname":
        return 'OK devinfo productname "TF5"'
    return None


def test_yamaha_round_trip():
    console = FakeTCPConsole(yamaha_responder)
    driver = create_driver("tf5")
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    try:
        assert driver.connect("127.0.0.1", port=console.port)
        assert wait_for(driver.is_responding)
        assert wait_for(lambda: len(names) == 48)
        assert names[1] == "Ch0" and names[48] == "Ch47"
        assert driver.set_channel_mute(2, True)
        assert driver.set_mute_group(1, True)
        assert wait_for(lambda: b"set MIXER:Current/InCh/Fader/On 1 0 0\n" in console.data)
        assert wait_for(lambda: b"set MIXER:Current/MuteMaster/On 0 0 1\n" in console.data)
    finally:
        driver.disconnect()
        console.close()


def test_yamaha_ignores_unrelated_lines():
    driver = create_driver("cl5")
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    driver.on_data(b'ERROR get MIXER:Current/Bogus\nNOTIFY set MIXER:Current/InCh/Label/Name 4 0 "Pastor"\npartial')
    assert names == {5: "Pastor"}


# ---------- Allen & Heath ----------

def test_allen_heath_note_mute_bytes():
    qu = AllenHeathDriver(dict(CONSOLE_PROFILES["qu16"]))
    assert qu.mute_message(1, True) == bytes([0x90, 0x00, 0x7F, 0x90, 0x00, 0x00])
    assert qu.mute_message(16, False) == bytes([0x90, 0x0F, 0x3F, 0x90, 0x0F, 0x00])
    dlive = AllenHeathDriver(dict(CONSOLE_PROFILES["dlive"]))
    assert dlive.mute_message(1, True)[0] == 0x9B  # MIDI channel 12


def test_allen_heath_nrpn_mute_bytes():
    sq = AllenHeathDriver(dict(CONSOLE_PROFILES["sq6"]))
    assert sq.mute_message(3, True) == bytes(
        [0xB0, 0x63, 0x00, 0xB0, 0x62, 0x02, 0xB0, 0x06, 0x00, 0xB0, 0x26, 0x01])


def test_allen_heath_midi_channel_override():
    driver = create_driver("qu24", {"midi_channel": 5})
    assert driver.mute_message(1, True)[0] == 0x94


def test_allen_heath_over_tcp():
    console = FakeTCPConsole()
    driver = create_driver("avantis")
    try:
        assert driver.connect("127.0.0.1", port=console.port)
        assert wait_for(driver.is_responding)
        assert driver.set_channel_mute(10, True)
        assert driver.set_channel_mute(999, True) is False  # out of range
        assert wait_for(lambda: bytes([0x90, 0x09, 0x7F, 0x90, 0x09, 0x00]) in console.data)
    finally:
        driver.disconnect()
        console.close()


def test_tcp_driver_waits_when_console_absent():
    driver = create_driver("sq5")
    try:
        assert driver.connect("127.0.0.1", port=9)
        time.sleep(0.2)
        assert not driver.is_responding()
        assert driver.set_channel_mute(1, True) is False
    finally:
        driver.disconnect()


# ---------- Soundcraft Ui ----------

class FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def test_soundcraft_messages():
    driver = SoundcraftUiDriver(dict(CONSOLE_PROFILES["ui24r"]))
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    driver.handle_message("3:::SETS^i.0.name^Lead Vox\n3:::SETD^i.0.mix^0.5\nSETS^i.99.name^too far")
    assert names == {1: "Lead Vox"}

    assert driver.set_channel_mute(1, True) is False  # not connected
    driver.ws = FakeWS()
    assert driver.set_channel_mute(4, True)
    assert driver.ws.sent == ["3:::SETD^i.3.mute^1"]
