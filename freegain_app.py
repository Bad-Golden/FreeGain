"""
freegain_app.py

Main window: bypass toggle, relearn room, panic mute, audio device and
mic/reference channel pickers (named live from the mixer over OSC), gate
threshold/attack/release sliders, input/output/cancellation-depth meters,
and a console picker (brand + model) for remote control of the mixer.

Settings (mixer IP, console model, devices, channels, gate) are saved to
local_config.json next to this file on exit. Per-console protocol tweaks
(e.g. a non-default MIDI channel, or OSC addresses for "Generic OSC") go
in that file's "console_options" section -- see README.md.

Run with: python freegain_app.py
"""

import json
import math
import os
import queue
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk, messagebox

import diagnostics
from audio_engine import DEFAULT_TAIL_MS, TAIL_OPTIONS_MS, AudioEngine
from version import __version__
from consoles import (CONSOLE_PROFILES, DEFAULT_PROFILE, AudioOnlyDriver, brands,
                      create_driver, models_for_brand)


def _config_path() -> Path:
    # The packaged .exe unpacks to a temporary folder on every launch, so
    # settings saved next to __file__ would be lost; keep them per-user.
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "FreeGain"
        else:
            base = Path(os.environ.get("APPDATA") or Path.home()) / "FreeGain"
        base.mkdir(parents=True, exist_ok=True)
        return base / "local_config.json"
    return Path(__file__).with_name("local_config.json")


CONFIG_PATH = _config_path()

BG = "#1c1b1a"
PANEL = "#26241f"
LINE = "#3a362e"
AMBER = "#e8a33d"
TEAL = "#4fa88a"
RED = "#d6543c"
PANIC_BG = "#3a2420"
TEXT_HI = "#f2ede4"
TEXT_LO = "#9c9689"
FONT = ("Segoe UI", 9)
FONT_BIG = ("Segoe UI", 10)

METER_FLOOR_DB = -60.0
ACTIVITY_THRESHOLD = 0.01  # ~ -40 dBFS
DEFAULT_DEVICE_LABEL = "System default"
MAX_USB_CHANNELS = 64

DEFAULT_CONFIG = {
    "console_type": DEFAULT_PROFILE,
    "console_options": {},
    "mixer_ip": "192.168.1.10",
    "input_device": None,
    "output_device": None,
    "mic_channel": 0,
    "reference_channel": 1,
    "gate_threshold_db": -34.0,
    "gate_attack_ms": 3.0,
    "gate_release_ms": 180.0,
    "tail_ms": DEFAULT_TAIL_MS,
    "auto_delay": True,
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            config.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
    except (OSError, ValueError):
        pass
    # Key used by earlier versions, before per-model profiles existed.
    config["console_type"] = {"xair": "xr18"}.get(config["console_type"],
                                                  config["console_type"])
    if config["console_type"] not in CONSOLE_PROFILES:
        config["console_type"] = DEFAULT_PROFILE
    if not isinstance(config["console_options"], dict):
        config["console_options"] = {}
    return config


def save_config(config: dict):
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError:
        pass  # read-only folder etc. -- not worth interrupting shutdown


def level_to_meter(level: float) -> float:
    """Linear 0..1 amplitude -> 0..1 meter position on a dB scale."""
    if level <= 0.0:
        return 0.0
    db = 20.0 * math.log10(level)
    return max(0.0, min(1.0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB))


class Meter(tk.Canvas):
    def __init__(self, parent, colour=AMBER, **kwargs):
        super().__init__(parent, height=14, bg=PANEL, highlightthickness=1,
                         highlightbackground=LINE, **kwargs)
        self.colour = colour
        self.level = 0.0
        self.bind("<Configure>", lambda _e: self._redraw())

    def set_level(self, level01: float):
        level01 = max(0.0, min(1.0, level01))
        if abs(level01 - self.level) > 0.002:
            self.level = level01
            self._redraw()

    def _redraw(self):
        self.delete("fill")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 4:
            return
        self.create_rectangle(2, 2, 2 + (w - 4) * self.level, h - 2,
                              fill=self.colour, outline="", tags="fill")


class ActiveDot(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=14, height=14, bg=PANEL, highlightthickness=0, **kwargs)
        self.active = False
        self._redraw()

    def set_active(self, active: bool):
        if active != self.active:
            self.active = active
            self._redraw()

    def _redraw(self):
        self.delete("all")
        self.create_oval(2, 2, 12, 12, fill=TEAL if self.active else LINE, outline="")


class FreeGainApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"FreeGain {__version__}")
        self._set_window_icon()
        self.root.configure(bg=BG)
        self.root.geometry("840x600")
        self.root.minsize(780, 540)

        self.config = load_config()
        if self.config["tail_ms"] not in TAIL_OPTIONS_MS:
            self.config["tail_ms"] = DEFAULT_TAIL_MS
        self.engine = AudioEngine(tail_ms=self.config["tail_ms"])
        self.engine.set_auto_delay(bool(self.config["auto_delay"]))
        self.messages = []   # (time, text) of status messages, for diagnostics
        self.devices = []
        self.console = AudioOnlyDriver(CONSOLE_PROFILES["audio_only"])
        self.engaged = True
        self.panic_active = False
        self.panic_target = None  # ("group", n) or ("channel", n) while muted

        # Console callbacks run on the driver's thread; tkinter isn't
        # thread-safe, so they only enqueue and the UI loop drains this.
        self.console_events: "queue.Queue[tuple]" = queue.Queue()
        self.channel_names: dict = {}
        # [(device_index_or_None, label)], parallel to the device comboboxes.
        self._input_choices = [(None, DEFAULT_DEVICE_LABEL)]
        self._output_choices = [(None, DEFAULT_DEVICE_LABEL)]

        self._build_ui()
        self._refresh_devices()
        self._start_audio(show_errors=False)
        self._schedule_ui_refresh()

    def _set_window_icon(self):
        if sys.platform != "win32":
            return
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent / "packaging"))
        try:
            self.root.iconbitmap(default=str(base / "freegain.ico"))
        except (tk.TclError, OSError):
            pass  # cosmetic only

    # ---------- UI construction ----------

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale", background=BG, troughcolor=PANEL)
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                        foreground=TEXT_HI, arrowcolor=TEXT_HI, bordercolor=LINE)
        # clam's readonly state otherwise renders grey-on-grey.
        style.map("TCombobox",
                  fieldbackground=[("readonly", PANEL)],
                  foreground=[("readonly", TEXT_HI)],
                  selectbackground=[("readonly", PANEL)],
                  selectforeground=[("readonly", TEXT_HI)],
                  background=[("readonly", PANEL)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_HI)
        self.root.option_add("*TCombobox*Listbox.selectBackground", LINE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT_HI)

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=16, pady=(16, 4))

        tk.Label(top, text="Console", bg=BG, fg=TEXT_LO, font=FONT).pack(side="left")
        self.brand_box = ttk.Combobox(top, values=brands(), state="readonly", width=22)
        self.brand_box.pack(side="left", padx=(6, 6))
        self.brand_box.bind("<<ComboboxSelected>>", lambda _e: self._on_brand_changed())
        self.model_box = ttk.Combobox(top, state="readonly", width=34)
        self.model_box.pack(side="left", padx=(0, 6))
        self.model_box.bind("<<ComboboxSelected>>", lambda _e: self._on_model_changed())
        self.console_note = tk.Label(top, text="", bg=BG, fg=TEXT_LO, font=FONT)
        self.console_note.pack(side="left")

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(top, text="Mixer IP", bg=BG, fg=TEXT_LO, font=FONT).pack(side="left")
        self.ip_entry = tk.Entry(top, bg=PANEL, fg=TEXT_HI, insertbackground=TEXT_HI,
                                 relief="flat", width=16)
        self.ip_entry.insert(0, self.config["mixer_ip"])
        self.ip_entry.pack(side="left", padx=(6, 6), ipady=3)
        self.ip_entry.bind("<Return>", lambda _e: self._on_connect())

        self.connect_btn = self._button(top, "Connect", self._on_connect)
        self.connect_btn.pack(side="left")

        self.connection_label = tk.Label(top, text="Not connected", bg=BG, fg=TEXT_LO,
                                         font=FONT_BIG)
        self.connection_label.pack(side="left", padx=(12, 0))
        self._select_console(self.config["console_type"])

        self._build_audio_row()

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=8)

        sidebar = tk.Frame(body, bg=PANEL, width=220)
        sidebar.pack(side="left", fill="y", padx=(0, 16))
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_main(main)

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=16, pady=(0, 8))
        self._button(bottom, "Save diagnostics…", self._on_save_diagnostics).pack(
            side="right")
        self.status_label = tk.Label(bottom, text="", bg=BG, fg=TEXT_LO, font=FONT,
                                     anchor="w", justify="left", wraplength=620)
        self.status_label.pack(side="left", fill="x", expand=True)

    def _build_audio_row(self):
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=16, pady=(4, 0))

        tk.Label(row, text="Audio in", bg=BG, fg=TEXT_LO, font=FONT).pack(side="left")
        self.input_box = ttk.Combobox(row, state="readonly", width=30)
        self.input_box.pack(side="left", padx=(6, 12))

        tk.Label(row, text="out", bg=BG, fg=TEXT_LO, font=FONT).pack(side="left")
        self.output_box = ttk.Combobox(row, state="readonly", width=30)
        self.output_box.pack(side="left", padx=(6, 6))

        self._button(row, "Apply", lambda: self._start_audio(show_errors=True)).pack(side="left")
        self._button(row, "↻", self._refresh_devices).pack(side="left", padx=(6, 0))

    def _build_sidebar(self, parent):
        pad = {"padx": 12, "pady": (10, 2)}

        tk.Label(parent, text="Vocal mic input", bg=PANEL, fg=TEXT_LO,
                 font=FONT).pack(anchor="w", **pad)
        row1 = tk.Frame(parent, bg=PANEL)
        row1.pack(fill="x", padx=12)
        self.vocal_box = ttk.Combobox(row1, state="readonly")
        self.vocal_box.pack(side="left", fill="x", expand=True)
        self.vocal_dot = ActiveDot(row1)
        self.vocal_dot.pack(side="left", padx=(6, 0))

        tk.Label(parent, text="Reference (speaker feed) input", bg=PANEL, fg=TEXT_LO,
                 font=FONT).pack(anchor="w", **pad)
        row2 = tk.Frame(parent, bg=PANEL)
        row2.pack(fill="x", padx=12)
        self.reference_box = ttk.Combobox(row2, state="readonly")
        self.reference_box.pack(side="left", fill="x", expand=True)
        self.reference_dot = ActiveDot(row2)
        self.reference_dot.pack(side="left", padx=(6, 0))

        self._populate_channel_lists(MAX_USB_CHANNELS)
        self.vocal_box.current(min(self.config["mic_channel"], MAX_USB_CHANNELS - 1))
        self.reference_box.current(min(self.config["reference_channel"], MAX_USB_CHANNELS - 1))
        self.vocal_box.bind("<<ComboboxSelected>>", lambda _e: self._on_channels_changed())
        self.reference_box.bind("<<ComboboxSelected>>", lambda _e: self._on_channels_changed())

        tk.Label(parent, text="Room echo tail", bg=PANEL, fg=TEXT_LO,
                 font=FONT).pack(anchor="w", **pad)
        self.tail_box = ttk.Combobox(
            parent, state="readonly",
            values=[f"{ms} ms" + {40: " (small room)", 85: " (typical)", 170: " (large hall)",
                                   340: " (very live)"}[ms] for ms in TAIL_OPTIONS_MS])
        self.tail_box.current(TAIL_OPTIONS_MS.index(self.config["tail_ms"]))
        self.tail_box.pack(fill="x", padx=12)
        self.tail_box.bind("<<ComboboxSelected>>", lambda _e: self._on_tail_changed())

        self.auto_delay_var = tk.BooleanVar(value=bool(self.config["auto_delay"]))
        tk.Checkbutton(parent, text="Find speaker delay automatically",
                       variable=self.auto_delay_var, command=self._on_auto_delay_changed,
                       bg=PANEL, fg=TEXT_HI, selectcolor=BG, activebackground=PANEL,
                       activeforeground=TEXT_HI, font=FONT, anchor="w",
                       wraplength=190, justify="left").pack(fill="x", padx=8, pady=(6, 0))
        self.delay_label = tk.Label(parent, text="Speaker delay: measuring…", bg=PANEL,
                                    fg=TEXT_LO, font=FONT, anchor="w", justify="left",
                                    wraplength=190)
        self.delay_label.pack(fill="x", padx=12)

        tk.Button(parent, text="Relearn room", command=self._on_relearn, bg=BG, fg=TEXT_HI,
                  relief="flat", activebackground=LINE).pack(fill="x", padx=12, pady=(14, 6))

        self.panic_btn = tk.Button(parent, text="Panic mute",
                                   command=self._on_panic, bg=PANIC_BG, fg=RED,
                                   relief="flat", activebackground=RED, wraplength=180)
        self.panic_btn.pack(fill="x", padx=12, pady=6)

    def _build_main(self, parent):
        top_row = tk.Frame(parent, bg=BG)
        top_row.pack(fill="x", pady=(0, 12))

        self.bypass_btn = tk.Button(top_row, text="Active", command=self._on_bypass_toggle,
                                    bg=BG, fg=TEAL, relief="solid", bd=2,
                                    highlightbackground=TEAL, width=10, height=4)
        self.bypass_btn.pack(side="left", padx=(0, 16))

        meter_col = tk.Frame(top_row, bg=BG)
        meter_col.pack(side="left", fill="x", expand=True, anchor="s")
        tk.Label(meter_col, text="Input", bg=BG, fg=TEXT_LO, font=FONT).pack(anchor="w")
        self.input_meter = Meter(meter_col, colour=TEAL)
        self.input_meter.pack(fill="x")

        self.depth_label = tk.Label(parent, text="Cancellation depth: -- dB", bg=BG, fg=TEXT_HI,
                                    font=FONT_BIG, anchor="w")
        self.depth_label.pack(fill="x", pady=(4, 2))
        self.depth_meter = Meter(parent, colour=AMBER)
        self.depth_meter.pack(fill="x", pady=(0, 16))

        gate_row = tk.Frame(parent, bg=BG)
        gate_row.pack(fill="x", pady=(0, 16))

        self.threshold_var = tk.DoubleVar(value=self.config["gate_threshold_db"])
        self.attack_var = tk.DoubleVar(value=self.config["gate_attack_ms"])
        self.release_var = tk.DoubleVar(value=self.config["gate_release_ms"])

        self._build_slider(gate_row, "Threshold", "dB", self.threshold_var, -60, 0)
        self._build_slider(gate_row, "Attack", "ms", self.attack_var, 0.5, 50)
        self._build_slider(gate_row, "Release", "ms", self.release_var, 10, 1000)

        tk.Label(parent, text="Output", bg=BG, fg=TEXT_LO, font=FONT).pack(anchor="w")
        self.output_meter = Meter(parent, colour=AMBER)
        self.output_meter.pack(fill="x")

    def _build_slider(self, parent, label, unit, var, lo, hi):
        col = tk.Frame(parent, bg=BG)
        col.pack(side="left", fill="x", expand=True, padx=6)
        value_label = tk.Label(col, bg=BG, fg=TEXT_LO, font=FONT)
        value_label.pack(anchor="w")

        def on_change(_=None):
            value_label.config(text=f"{label}: {var.get():.1f} {unit}")
            self._on_gate_change()

        ttk.Scale(col, from_=lo, to=hi, variable=var, orient="horizontal",
                  command=on_change).pack(fill="x")
        on_change()

    @staticmethod
    def _button(parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=PANEL, fg=TEXT_HI,
                         relief="flat", activebackground=LINE, padx=8)

    # ---------- Audio ----------

    def _refresh_devices(self):
        try:
            devices = AudioEngine.list_devices()
        except Exception as exc:  # PortAudio missing, driver error, ...
            self._input_choices = [(None, DEFAULT_DEVICE_LABEL)]
            self._output_choices = [(None, DEFAULT_DEVICE_LABEL)]
            self.input_box.configure(values=[DEFAULT_DEVICE_LABEL])
            self.output_box.configure(values=[DEFAULT_DEVICE_LABEL])
            self.input_box.current(0)
            self.output_box.current(0)
            self._set_status(f"Audio devices unavailable: {exc}")
            return

        inputs = [(None, DEFAULT_DEVICE_LABEL)] + [
            (i, f"{name} [{api}] ({ins} in)") for i, name, api, ins, _outs in devices if ins > 0]
        outputs = [(None, DEFAULT_DEVICE_LABEL)] + [
            (i, f"{name} [{api}] ({outs} out)") for i, name, api, _ins, outs in devices if outs > 0]
        self._input_choices, self._output_choices = inputs, outputs
        self.devices = devices
        self.input_box.configure(values=[label for _i, label in inputs])
        self.output_box.configure(values=[label for _i, label in outputs])
        self.input_box.current(self._choice_index(inputs, self.config["input_device"]))
        self.output_box.current(self._choice_index(outputs, self.config["output_device"]))

    @staticmethod
    def _choice_index(choices, device_index) -> int:
        for pos, (idx, _label) in enumerate(choices):
            if idx == device_index:
                return pos
        return 0

    @staticmethod
    def _selected_device(box, choices):
        pos = box.current()
        return choices[pos][0] if 0 <= pos < len(choices) else None

    def _start_audio(self, show_errors: bool):
        input_device = self._selected_device(self.input_box, self._input_choices)
        output_device = self._selected_device(self.output_box, self._output_choices)
        mic = max(self.vocal_box.current(), 0)
        ref = max(self.reference_box.current(), 0)

        self.config.update(input_device=input_device, output_device=output_device,
                           mic_channel=mic, reference_channel=ref)
        try:
            self.engine.configure(input_device, output_device, mic, ref)
            self.engine.start()
            if mic == ref:
                self._set_status("Vocal mic and reference are the same input -- "
                                 "pick different channels for the filter to work.")
            else:
                self._set_status(f"Audio running at {self.engine.sample_rate:.0f} Hz, "
                                 f"mic = input {mic + 1}, reference = input {ref + 1}")
        except Exception as exc:  # sounddevice raises PortAudioError/ValueError/...
            self.engine.stop()
            self._set_status(f"Audio not running: {exc}")
            if show_errors:
                messagebox.showwarning(
                    "Audio device",
                    f"Couldn't start audio:\n{exc}\n\n"
                    "Pick your console's audio interface in the 'Audio in' box "
                    "and make sure the selected channels exist on it.")

    def _on_channels_changed(self):
        self._start_audio(show_errors=True)

    # ---------- Console (remote control) ----------

    def _selected_console_key(self) -> str:
        keys = models_for_brand(self.brand_box.get())
        pos = self.model_box.current()
        return keys[pos] if 0 <= pos < len(keys) else "audio_only"

    def _select_console(self, key: str):
        brand = CONSOLE_PROFILES[key]["brand"]
        self.brand_box.current(brands().index(brand))
        self._fill_models(brand)
        self.model_box.current(models_for_brand(brand).index(key))
        self._on_model_changed()

    def _fill_models(self, brand: str):
        self.model_box.configure(
            values=[CONSOLE_PROFILES[k]["label"] for k in models_for_brand(brand)])

    def _on_brand_changed(self):
        self._fill_models(self.brand_box.get())
        self.model_box.current(0)
        self._on_model_changed()

    def _on_model_changed(self):
        profile = CONSOLE_PROFILES[self._selected_console_key()]
        needs_network = profile["driver"] != "none"
        state = "normal" if needs_network else "disabled"
        self.ip_entry.config(state=state)
        self.connect_btn.config(state=state)
        self.console_note.config(
            text="experimental" if profile["status"] == "experimental" else "",
            fg=AMBER)

    def _on_connect(self):
        ip = self.ip_entry.get().strip()
        console_key = self._selected_console_key()

        self.console.disconnect()
        options = self.config["console_options"].get(console_key, {})
        self.console = create_driver(console_key, options)
        self.console.on_channel_name = (
            lambda ch, name: self.console_events.put(("name", ch, name)))
        self.channel_names.clear()
        self._populate_channel_lists(MAX_USB_CHANNELS)

        # New connection = the mixer's actual mute state is unknown to us;
        # don't show a stale "muted" indicator from a previous session.
        self._set_panic_state(None)

        if not self.console.connect(ip):
            self.connection_label.config(
                text="Invalid IP, network error or missing package (see console)", fg=RED)
            return

        self.config.update(console_type=console_key, mixer_ip=ip)
        self.connection_label.config(text=f"Waiting for {ip}\u2026", fg=TEXT_LO)
        self.console.request_all_channel_names()

    def _drain_console_events(self):
        changed = False
        try:
            while True:
                kind, *payload = self.console_events.get_nowait()
                if kind == "name":
                    channel, name = payload
                    self.channel_names[channel] = name
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self._populate_channel_lists(MAX_USB_CHANNELS)

    def _populate_channel_lists(self, count: int):
        # Assumes the console's default routing (console channel N -> USB /
        # interface input N), so live channel names are shown against inputs.
        values = []
        for ch in range(1, count + 1):
            name = self.channel_names.get(ch)
            values.append(f"Input {ch} \u2013 {name}" if name else f"Input {ch}")
        for box in (self.vocal_box, self.reference_box):
            current = box.current()
            box.configure(values=values)
            if 0 <= current < len(values):
                box.current(current)

    def _update_connection_label(self):
        console = self.console
        if not console.connected:
            return
        if console.is_responding():
            self.connection_label.config(text=f"Connected to {console.host}", fg=TEAL)
        elif console.last_reply_time:
            self.connection_label.config(text=f"{console.host} stopped responding", fg=RED)

    # ---------- Actions ----------

    def _on_bypass_toggle(self):
        self.engaged = not self.engaged
        self.engine.set_engaged(self.engaged)
        self.bypass_btn.config(
            text="Active" if self.engaged else "Bypassed",
            fg=TEAL if self.engaged else TEXT_LO,
            highlightbackground=TEAL if self.engaged else LINE,
        )

    def _on_relearn(self):
        self.engine.trigger_relearn()

    def _panic_target(self):
        """Mute group 1 where the console has them, else the vocal channel."""
        if self.console.supports_mute_groups:
            return ("group", 1)
        if self.console.supports_channel_mute:
            return ("channel", max(self.vocal_box.current(), 0) + 1)
        return None

    def _on_panic(self):
        # Persistent toggle: stays lit while the mute is active, and unmutes
        # exactly what it muted even if the vocal channel changed meanwhile.
        if not self.console.connected:
            messagebox.showinfo("Panic mute", "Connect to the mixer first -- "
                                "panic mute works through the console's remote control.")
            return
        target = self.panic_target or self._panic_target()
        if target is None:
            messagebox.showinfo("Panic mute", "This console's driver can't mute remotely.")
            return
        mute = self.panic_target is None
        kind, number = target
        if kind == "group":
            sent = self.console.set_mute_group(number, mute)
        else:
            sent = self.console.set_channel_mute(number, mute)
        if sent:
            self._set_panic_state(target if mute else None)
        else:
            self._set_status("Panic mute: couldn't send to the console (not connected yet?)")

    def _set_panic_state(self, target):
        self.panic_target = target
        self.panic_active = target is not None
        if target:
            what = "mute group" if target[0] == "group" else "channel"
            self.panic_btn.config(bg=RED, fg=BG, text=f"MUTED {what} {target[1]} (click to unmute)")
        else:
            self.panic_btn.config(bg=PANIC_BG, fg=RED, text="Panic mute")

    def _on_tail_changed(self):
        tail = TAIL_OPTIONS_MS[self.tail_box.current()]
        self.config["tail_ms"] = tail
        self.engine.set_tail_ms(tail)

    def _on_auto_delay_changed(self):
        enabled = bool(self.auto_delay_var.get())
        self.config["auto_delay"] = enabled
        self.engine.set_auto_delay(enabled)

    def _on_save_diagnostics(self):
        report = diagnostics.build_report(
            self.engine, self.console, self.config, self.devices, self.messages)
        path = filedialog.asksaveasfilename(
            title="Save FreeGain diagnostics",
            initialdir=str(diagnostics.default_folder()),
            initialfile=diagnostics.default_filename(),
            defaultextension=".json",
            filetypes=[("Diagnostics report", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            saved = diagnostics.write_report(report, path)
        except OSError as exc:
            messagebox.showerror("Save diagnostics", f"Couldn't save the report:\n{exc}")
            return
        self._set_status(f"Diagnostics saved to {saved}")

    def _on_gate_change(self):
        self.engine.set_gate_threshold_db(self.threshold_var.get())
        self.engine.set_gate_timing(self.attack_var.get(), self.release_var.get())

    def _set_status(self, text: str):
        self.status_label.config(text=text)
        self.messages.append((time.strftime("%H:%M:%S"), text))
        del self.messages[:-200]

    # ---------- Periodic updates ----------

    def _schedule_ui_refresh(self):
        self._drain_console_events()
        self._update_connection_label()

        engine = self.engine
        self.input_meter.set_level(level_to_meter(engine.last_input_peak))
        self.output_meter.set_level(level_to_meter(engine.last_output_peak))
        depth = engine.last_cancellation_depth_db if self.engaged else 0.0
        self.depth_meter.set_level(depth / 30.0)
        extra = f"   •   CPU {100 * engine.cpu_load:.0f}%" if engine.running else ""
        if engine.xrun_count:
            extra += f"   •   dropouts: {engine.xrun_count}"
        self.depth_label.config(text=f"Cancellation depth: {depth:.1f} dB{extra}")
        self._update_delay_label()
        self.vocal_dot.set_active(engine.last_input_peak > ACTIVITY_THRESHOLD)
        self.reference_dot.set_active(engine.last_reference_peak > ACTIVITY_THRESHOLD)
        self.root.after(33, self._schedule_ui_refresh)  # ~30fps

    def _update_delay_label(self):
        engine = self.engine
        measured = engine.delay_estimator.delay_ms
        if not engine.auto_delay:
            text = "Speaker delay: off"
        elif measured is None:
            text = "Speaker delay: measuring… (needs music)"
        else:
            text = f"Speaker delay: {measured:.1f} ms"
        if self.delay_label.cget("text") != text:
            self.delay_label.config(text=text)

    def on_close(self):
        self.config.update(
            gate_threshold_db=round(self.threshold_var.get(), 1),
            gate_attack_ms=round(self.attack_var.get(), 1),
            gate_release_ms=round(self.release_var.get(), 1),
        )
        save_config(self.config)
        self.engine.stop()
        self.console.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = FreeGainApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
