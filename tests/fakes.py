"""Fake consoles for driver tests: they speak just enough protocol."""

import re
import socket
import threading

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_packet import OscPacket


def osc(address, *args):
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


class FakeOSCMixer:
    """Replies to name queries (any address ending in 'name') from the sender's port."""

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
                params = list(msg.params)
                self.received.append((msg.address, params))
                if msg.address.endswith("name") and not params:
                    ch = int(re.search(r"/(\d+)/", msg.address).group(1))
                    self.sock.sendto(osc(msg.address, f"Vox {ch}"), addr)

    def close(self):
        self._stop.set()
        self.sock.close()
        self._thread.join(1)


class FakeTCPConsole:
    """Accepts one client at a time; records bytes; optional line responder."""

    def __init__(self, responder=None):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.server.settimeout(0.2)
        self.port = self.server.getsockname()[1]
        self.responder = responder
        self.data = b""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.settimeout(0.2)
            pending = b""
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self.data += chunk
                if self.responder:
                    pending += chunk
                    *lines, pending = pending.split(b"\n")
                    for line in lines:
                        reply = self.responder(line.decode())
                        if reply:
                            conn.sendall(reply.encode() + b"\n")
            conn.close()

    def close(self):
        self._stop.set()
        self.server.close()
        self._thread.join(1)
