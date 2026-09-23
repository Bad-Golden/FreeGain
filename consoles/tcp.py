"""
consoles/tcp.py

Shared plumbing for consoles controlled over a persistent TCP connection
(Yamaha RCP, Allen & Heath MIDI-over-TCP). Connecting happens on a
background thread so a console that isn't there can't freeze the UI, and
the connection is retried automatically if it drops.
"""

import socket
import threading
from typing import Optional

from .base import KEEPALIVE_INTERVAL_S, ConsoleDriver, valid_ip

CONNECT_TIMEOUT_S = 3.0
RETRY_DELAY_S = 3.0


class TCPDriver(ConsoleDriver):
    def __init__(self, profile: dict):
        super().__init__(profile)
        self.sock: Optional[socket.socket] = None
        self.port = profile["port"]
        self._send_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def connect(self, host: str, port: Optional[int] = None) -> bool:
        self.disconnect()
        if not valid_ip(host):
            return False
        self.host = host
        if port is not None:
            self.port = port
        self.connected = True
        self.last_reply_time = 0.0
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop_event,), daemon=True)
        self._thread.start()
        return True

    def disconnect(self):
        super().disconnect()
        self._close_socket()
        t, self._thread = self._thread, None
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=CONNECT_TIMEOUT_S + 1.0)

    def _close_socket(self):
        sock, self.sock = self.sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def is_responding(self) -> bool:
        # For TCP, an open connection is the real signal: some consoles
        # (e.g. Allen & Heath) only send data when something changes.
        return self.connected and self.sock is not None

    def send_bytes(self, data: bytes) -> bool:
        sock = self.sock
        if not sock:
            return False
        try:
            with self._send_lock:
                sock.sendall(data)
            return True
        except OSError:
            self._close_socket()  # the run loop will reconnect
            return False

    # ---------- hooks for subclasses ----------

    def on_connected(self):
        """Called on the background thread right after the TCP connect."""

    def on_data(self, data: bytes):
        """Called with every chunk received."""

    def keepalive(self):
        """Called every KEEPALIVE_INTERVAL_S while connected."""

    # ---------- background thread ----------

    def _run(self, stop_event: threading.Event):
        while not stop_event.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT_S)
            except OSError:
                stop_event.wait(RETRY_DELAY_S)
                continue
            sock.settimeout(0.5)
            if stop_event.is_set():
                sock.close()
                break
            self.sock = sock
            # A TCP connection that opened means something is listening.
            self.mark_reply()
            self.on_connected()
            self._read_until_closed(sock, stop_event)
            self._close_socket()
            if not stop_event.is_set():
                stop_event.wait(RETRY_DELAY_S)

    def _read_until_closed(self, sock, stop_event):
        waited = 0.0
        while not stop_event.is_set() and self.sock is sock:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                waited += 0.5
                if waited >= KEEPALIVE_INTERVAL_S:
                    waited = 0.0
                    self.keepalive()
                continue
            except OSError:
                return
            if not data:
                return  # console closed the connection
            self.mark_reply()
            try:
                self.on_data(data)
            except Exception as exc:  # a bad parse must not kill the thread
                print(f"[{type(self).__name__}] error handling data: {exc}")
