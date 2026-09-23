"""
consoles/soundcraft_ui.py

Soundcraft Ui12 / Ui16 / Ui24R. These are controlled from a browser over a
WebSocket at ws://<ip>/socket.io, using text messages prefixed "3:::":

  3:::SETD^i.<ch-1>.mute^<0|1>    set a channel's mute
  3:::SETS^i.<ch-1>.name^<name>   (sent by the console) channel name
  3:::ALIVE                       keepalive, sent every couple of seconds

The console sends its full state, including names, right after connecting.

Requires the optional `websocket-client` package (pip install
websocket-client).

EXPERIMENTAL: follows the community-documented Ui protocol (as used by
the open-source soundcraft-ui-connection library), not yet tested against
a real Ui mixer.
"""

import re
import threading
import time
from typing import Optional

from .base import ConsoleDriver, valid_ip

_NAME_RE = re.compile(r"^SETS\^i\.(\d+)\.name\^(.*)$")
KEEPALIVE_S = 2.0


class SoundcraftUiDriver(ConsoleDriver):
    supports_names = True
    supports_channel_mute = True

    def __init__(self, profile: dict):
        super().__init__(profile)
        self.ws = None
        self._thread: Optional[threading.Thread] = None
        self._send_lock = threading.Lock()

    def connect(self, host: str) -> bool:
        self.disconnect()
        if not valid_ip(host):
            return False
        try:
            import websocket  # websocket-client
        except ImportError:
            print("[soundcraft] install websocket-client: pip install websocket-client")
            return False
        self.host = host
        self.connected = True
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(websocket, self._stop_event),
                                        daemon=True)
        self._thread.start()
        return True

    def disconnect(self):
        super().disconnect()
        ws, self.ws = self.ws, None
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        t, self._thread = self._thread, None
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=4.0)

    def _send(self, message: str) -> bool:
        ws = self.ws
        if not ws:
            return False
        try:
            with self._send_lock:
                ws.send("3:::" + message)
            return True
        except Exception:
            return False

    def set_channel_mute(self, channel_one_indexed: int, muted: bool) -> bool:
        return self._send(f"SETD^i.{channel_one_indexed - 1}.mute^{1 if muted else 0}")

    def request_all_channel_names(self):
        pass  # the console pushes names itself on connect

    def handle_message(self, raw: str):
        for message in raw.split("\n"):
            message = message.strip()
            if message.startswith("3:::"):
                message = message[4:]
            match = _NAME_RE.match(message)
            if match:
                self._emit_name(int(match.group(1)) + 1, match.group(2))

    def _run(self, websocket, stop_event):
        while not stop_event.is_set():
            try:
                ws = websocket.create_connection(f"ws://{self.host}/socket.io", timeout=3)
            except Exception:
                stop_event.wait(3.0)
                continue
            ws.settimeout(KEEPALIVE_S)
            self.ws = ws
            self.mark_reply()
            last_alive = time.monotonic()
            while not stop_event.is_set():
                # Time-based rather than on-timeout: the console streams
                # meter data constantly, so recv() rarely times out.
                if time.monotonic() - last_alive >= KEEPALIVE_S:
                    self._send("ALIVE")
                    last_alive = time.monotonic()
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    break
                if not raw:
                    break
                self.mark_reply()
                self.handle_message(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
            self.ws = None
            try:
                ws.close()
            except Exception:
                pass
            if not stop_event.is_set():
                stop_event.wait(3.0)

    def is_responding(self) -> bool:
        return self.connected and self.ws is not None
