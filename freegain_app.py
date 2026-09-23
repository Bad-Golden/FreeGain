"""
freegain_app.py

Main window: bypass toggle, relearn room, panic mute, audio device and
mic/reference channel pickers (named live from the mixer over OSC), gate
threshold/attack/release sliders, input/output/cancellation-depth meters,
and an OSC connect field with XAir/X32 console picker.

Settings (mixer IP, console type, devices, channels, gate) are saved to
local_config.json next to this file on exit.

Run with: python freegain_app.py
"""

import json
import math
import queue
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from audio_engine import AudioEngine
from console_profiles import CONSOLE_PROFILES, DEFAULT_PROFILE
from mixer_osc_client import MixerOSCClient

CONFIG_PATH = Path(__file__).with_name("local_config.json")

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
MAX_USB_CHANNELS = 32

DEFAULT_CONFIG = {
    "console_type": DEFAULT_PROFILE,
    "mixer_ip": "192.168.1.10",
    "input_device": None,
    "output_device": None,
    "mic_channel": 0,
    "reference_channel": 1,
    "gate_threshold_db": -34.0,
    "gate_attack_ms": 3.0,
    "gate_release_ms": 180.0,
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            config.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
    except (OSError, ValueError):
        pass
    if config["console_type"] not in CONSOLE_PROFILES:
        config["console_type"] = DEFAULT_PROFILE
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
        self.root.title("FreeGain")
        self.root.configure(bg=BG)
        self.root.geometry("840x600")
        self.root.minsize(780, 540)

        self.config = load_config()
        self.engine = AudioEngine()
        self.osc = MixerOSCClient(console_type=self.config["console_type"])
        self.engaged = True
        self.panic_active = False

        # OSC callbacks run on the OSC receive thread; tkinter isn't
        # thread-safe, so they only enqueue and the UI loop drains this.
        self.osc_events: "queue.Queue[tuple]" = queue.Queue()
        self.channel_names: dict = {}
        # [(device_index_or_None, label)], parallel to the device comboboxes.
        self._input_choices = [(None, DEFAULT_DEVICE_LABEL)]
        self._output_choices = [(None, DEFAULT_DEVICE_LABEL)]

        self._build_ui()
        self._refresh_devices()
        self._start_audio(show_errors=False)
        self._schedule_ui_refresh()

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

        keys = list(CONSOLE_PROFILES)
        self.console_box = ttk.Combobox(
            top, values=[CONSOLE_PROFILES[k]["label"] for k in keys],
            state="readonly", width=30)
        self.console_box.current(keys.index(self.config["console_type"]))
        self.console_box.pack(side="left", padx=(0, 6))

        self.ip_entry = tk.Entry(top, bg=PANEL, fg=TEXT_HI, insertbackground=TEXT_HI,
                                 relief="flat", width=16)
        self.ip_entry.insert(0, self.config["mixer_ip"])
        self.ip_entry.pack(side="left", padx=(0, 6), ipady=3)
        self.ip_entry.bind("<Return>", lambda _e: self._on_connect())

        self._button(top, "Connect", self._on_connect).pack(side="left")

        self.connection_label = tk.Label(top, text="OSC: not connected", bg=BG, fg=TEXT_LO,
                                         font=FONT_BIG)
        self.connection_label.pack(side="left", padx=(12, 0))

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

        self.status_label = tk.Label(self.root, text="", bg=BG, fg=TEXT_LO, font=FONT, anchor="w")
        self.status_label.pack(fill="x", padx=16, pady=(0, 8))

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

        tk.Button(parent, text="Relearn room", command=self._on_relearn, bg=BG, fg=TEXT_HI,
                  relief="flat", activebackground=LINE).pack(fill="x", padx=12, pady=(20, 6))

        self.panic_btn = tk.Button(parent, text="Panic mute (mute group 1)",
                                   command=self._on_panic, bg=PANIC_BG, fg=RED,
                                   relief="flat", activebackground=RED)
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
            (i, f"{i}: {name} ({ins} in)") for i, name, ins, _outs in devices if ins > 0]
        outputs = [(None, DEFAULT_DEVICE_LABEL)] + [
            (i, f"{i}: {name} ({outs} out)") for i, name, _ins, outs in devices if outs > 0]
        self._input_choices, self._output_choices = inputs, outputs
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
                                 f"mic = USB {mic + 1}, reference = USB {ref + 1}")
        except Exception as exc:  # sounddevice raises PortAudioError/ValueError/...
            self.engine.stop()
            self._set_status(f"Audio not running: {exc}")
            if show_errors:
                messagebox.showwarning(
                    "Audio device",
                    f"Couldn't start audio:\n{exc}\n\n"
                    "Pick your mixer's USB audio device in the 'Audio in' box "
                    "and make sure the selected channels exist on it.")

    def _on_channels_changed(self):
        self._start_audio(show_errors=True)

    # ---------- OSC ----------

    def _on_connect(self):
        ip = self.ip_entry.get().strip()
        console_key = list(CONSOLE_PROFILES)[self.console_box.current()]

        # Console type sets port/channel count, so reconnect with a fresh client.
        self.osc.disconnect()
        self.osc = MixerOSCClient(console_type=console_key)
        self.osc.on_channel_name = lambda ch, name: self.osc_events.put(("name", ch, name))
        self.channel_names.clear()
        self._populate_channel_lists(MAX_USB_CHANNELS)

        # Fresh client = mixer's actual mute state is unknown to us;
        # don't show a stale "muted" indicator from a previous session.
        self._set_panic_state(False)

        if not self.osc.connect(ip):
            self.connection_label.config(text="OSC: invalid IP or network error", fg=RED)
            return

        self.config.update(console_type=console_key, mixer_ip=ip)
        self.connection_label.config(text=f"OSC: waiting for {ip}…", fg=TEXT_LO)
        self.osc.request_all_channel_names()

    def _drain_osc_events(self):
        changed = False
        try:
            while True:
                kind, *payload = self.osc_events.get_nowait()
                if kind == "name":
                    channel, name = payload
                    self.channel_names[channel] = name
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self._populate_channel_lists(MAX_USB_CHANNELS)

    def _populate_channel_lists(self, count: int):
        # Assumes the mixer's default USB routing (mixer channel N -> USB
        # input N), so live channel names are shown against USB inputs.
        values = []
        for ch in range(1, count + 1):
            name = self.channel_names.get(ch)
            values.append(f"USB {ch} – {name}" if name else f"USB {ch}")
        for box in (self.vocal_box, self.reference_box):
            current = box.current()
            box.configure(values=values)
            if 0 <= current < len(values):
                box.current(current)

    def _update_connection_label(self):
        if not self.osc.connected:
            return
        ip = self.osc.mixer_addr[0]
        if self.osc.is_responding():
            self.connection_label.config(text=f"OSC: connected to {ip}", fg=TEAL)
        elif self.osc.last_reply_time:
            self.connection_label.config(text=f"OSC: {ip} stopped responding", fg=RED)

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

    def _on_panic(self):
        # Persistent toggle: stays lit while the mute is active.
        if not self.osc.connected:
            messagebox.showinfo("Panic mute", "Connect to the mixer first -- "
                                "panic mute works through OSC mute group 1.")
            return
        target = not self.panic_active
        if self.osc.set_mute_group(1, target):
            self._set_panic_state(target)
        else:
            self._set_status("Panic mute: couldn't send to mixer (network error)")

    def _set_panic_state(self, active: bool):
        self.panic_active = active
        if active:
            self.panic_btn.config(bg=RED, fg=BG, text="MUTED (click to unmute)")
        else:
            self.panic_btn.config(bg=PANIC_BG, fg=RED, text="Panic mute (mute group 1)")

    def _on_gate_change(self):
        self.engine.set_gate_threshold_db(self.threshold_var.get())
        self.engine.set_gate_timing(self.attack_var.get(), self.release_var.get())

    def _set_status(self, text: str):
        self.status_label.config(text=text)

    # ---------- Periodic updates ----------

    def _schedule_ui_refresh(self):
        self._drain_osc_events()
        self._update_connection_label()

        engine = self.engine
        self.input_meter.set_level(level_to_meter(engine.last_input_peak))
        self.output_meter.set_level(level_to_meter(engine.last_output_peak))
        depth = engine.last_cancellation_depth_db if self.engaged else 0.0
        self.depth_meter.set_level(depth / 30.0)
        self.depth_label.config(text=f"Cancellation depth: {depth:.1f} dB"
                                     + (f"   •   dropouts: {engine.xrun_count}"
                                        if engine.xrun_count else ""))
        self.vocal_dot.set_active(engine.last_input_peak > ACTIVITY_THRESHOLD)
        self.reference_dot.set_active(engine.last_reference_peak > ACTIVITY_THRESHOLD)
        self.root.after(33, self._schedule_ui_refresh)  # ~30fps

    def on_close(self):
        self.config.update(
            gate_threshold_db=round(self.threshold_var.get(), 1),
            gate_attack_ms=round(self.attack_var.get(), 1),
            gate_release_ms=round(self.release_var.get(), 1),
        )
        save_config(self.config)
        self.engine.stop()
        self.osc.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = FreeGainApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
