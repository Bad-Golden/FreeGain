"""Hostile-network stress tests for the console drivers."""

import socket
import threading
import time

import numpy as np

from consoles import create_driver
from consoles.soundcraft_ui import SoundcraftUiDriver
from consoles.profiles import CONSOLE_PROFILES
from fakes import FakeOSCMixer, FakeTCPConsole, osc


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def garbage(rng, n):
    kind = rng.integers(0, 5)
    if kind == 0:
        return bytes(rng.integers(0, 256, n, dtype=np.uint8))
    if kind == 1:
        return osc("/ch/01/config/name", "x")[: int(rng.integers(0, 20))]  # truncated
    if kind == 2:
        return osc("/meters/1", bytes(rng.integers(0, 256, n, dtype=np.uint8)))
    if kind == 3:
        return osc("/ch/99999/config/name", "overflow")
    return b"#bundle\x00" + bytes(rng.integers(0, 256, n, dtype=np.uint8))


def test_osc_driver_survives_a_garbage_flood():
    mixer = FakeOSCMixer()
    driver = create_driver("x32")
    names, meters = {}, []
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    driver.on_meter_block = meters.append
    rng = np.random.default_rng(0)
    try:
        assert driver.connect("127.0.0.1", port=mixer.port)
        target = ("127.0.0.1", driver.sock.getsockname()[1])
        blaster = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for _ in range(3000):
            blaster.sendto(garbage(rng, int(rng.integers(1, 1500))), target)
        blaster.close()
        # Still alive and still understanding real replies. UDP is lossy: if
        # the flood filled the OS receive buffer the first reply can be
        # dropped by the kernel, so ask again until it gets through.
        deadline = time.monotonic() + 15
        while names.get(7) != "Vox 7" and time.monotonic() < deadline:
            driver.request_channel_name(7)
            wait_for(lambda: names.get(7) == "Vox 7", timeout=0.5)
        assert names.get(7) == "Vox 7"
        assert 7 in names and all(1 <= ch <= 32 for ch in names)
    finally:
        driver.disconnect()
        mixer.close()


def test_yamaha_driver_survives_garbage_lines():
    rng = np.random.default_rng(1)

    def responder(line):
        if line.startswith("get MIXER:Current/InCh/Label/Name 3 "):
            junk = [
                "\x00\xff" * 200,
                "OK get MIXER:Current/InCh/Label/Name",          # truncated
                'OK get MIXER:Current/InCh/Label/Name x 0 "bad"',
                "NOTIFY " + "A" * 100000,                        # huge line
                'OK get MIXER:Current/InCh/Label/Name 999999 0 "far"',
            ]
            return "\n".join(junk) + '\nOK get MIXER:Current/InCh/Label/Name 3 0 "Lead"'
        return "".join(chr(int(c)) for c in rng.integers(32, 127, 40))

    console = FakeTCPConsole(responder)
    driver = create_driver("tf5")
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    try:
        assert driver.connect("127.0.0.1", port=console.port)
        assert wait_for(lambda: names.get(4) == "Lead", timeout=10)
        assert all(1 <= ch <= 48 for ch in names)
        assert driver.set_channel_mute(1, True)
    finally:
        driver.disconnect()
        console.close()


def test_tcp_driver_reconnects_after_the_console_drops():
    console = FakeTCPConsole()
    driver = create_driver("qu16")
    try:
        assert driver.connect("127.0.0.1", port=console.port)
        assert wait_for(driver.is_responding)
        port = console.port
        console.close()                 # console reboots
        assert wait_for(lambda: not driver.set_channel_mute(1, True), timeout=10)
        # Bring a console back on the same port.
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        srv.settimeout(10)
        conn, _ = srv.accept()
        assert wait_for(driver.is_responding)
        assert driver.set_channel_mute(2, True)
        conn.settimeout(5)
        assert bytes([0x90, 0x01, 0x7F]) in conn.recv(64)
        conn.close()
        srv.close()
    finally:
        driver.disconnect()


def test_rapid_connect_disconnect_leaks_no_threads():
    mixer = FakeOSCMixer()
    console = FakeTCPConsole()
    before = threading.active_count()
    try:
        for i in range(40):
            osc_driver = create_driver("xr18")
            osc_driver.connect("127.0.0.1", port=mixer.port)
            tcp_driver = create_driver("sq6")
            tcp_driver.connect("127.0.0.1", port=console.port)
            if i % 2:
                osc_driver.set_mute_group(1, True)
                tcp_driver.set_channel_mute(1, True)
            osc_driver.disconnect()
            tcp_driver.disconnect()
        assert wait_for(lambda: threading.active_count() <= before + 1, timeout=10)
    finally:
        mixer.close()
        console.close()


def test_soundcraft_parser_fuzz():
    driver = SoundcraftUiDriver(dict(CONSOLE_PROFILES["ui24r"]))
    names = {}
    driver.on_channel_name = lambda ch, name: names.__setitem__(ch, name)
    rng = np.random.default_rng(2)
    alphabet = list("3:^.SETDi0123456789namemute\n\x00é")
    for _ in range(5000):
        driver.handle_message("".join(rng.choice(alphabet, int(rng.integers(0, 80)))))
    driver.handle_message("3:::SETS^i.5.name^Pastor")
    assert names.get(6) == "Pastor"
    assert all(1 <= ch <= 24 for ch in names)


def test_every_driver_handles_calls_while_disconnected():
    for key in CONSOLE_PROFILES:
        driver = create_driver(key)
        driver.request_all_channel_names()
        assert driver.set_mute_group(1, True) is False
        assert driver.set_channel_mute(1, True) is False
        driver.disconnect()
        driver.disconnect()
