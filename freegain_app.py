"""
freegain_app.py

Main window. Same feature set as before, now with a console-type picker
(XAir vs X32) since they use different OSC ports/channel counts: bypass
toggle, relearn room, panic mute, vocal/reference channel pickers with
live-signal indicator dots, gate threshold/attack/release sliders,
input/output/cancellation-depth meters, and an OSC connect field.

Run with: python freegain_app.py
"""

import tkinter as tk
from tkinter import ttk, messagebox

from audio_engine import AudioEngine
from mixer_osc_client import MixerOSCClient
from console_profiles import CONSOLE_PROFILES, DEFAULT_PROFILE

BG = "#1c1b1a"
PANEL = "#26241f"
LINE = "#3a362e"
AMBER = "#e8a33d"
TEAL = "#4fa88a"
RED = "#d6543c"
TEXT_HI = "#f2ede4"
TEXT_LO = "#9c9689"


class Meter(tk.Canvas):
    def __init__(self, parent, colour=AMBER, **kwargs):
        super().__init__(parent, height=14, bg=PANEL, highlightthickness=1,
                          highlightbackground=LINE, **kwargs)
        self.colour = colour
        self.level = 0.0

    def set_level(self, level01: float):
        self.level = max(0.0, min(1.0, level01))
        self._redraw()

    def _redraw(self):
        self.delete("fill")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
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
        colour = TEAL if self.active else LINE
        self.create_oval(2, 2, 12, 12, fill=colour, outline="")


class FreeGainApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("FreeGain")
        self.root.configure(bg=BG)
        self.root.geometry("720x560")

        self.engine = AudioEngine()
        self.osc = MixerOSCClient(console_type=DEFAULT_PROFILE)
        self.engaged = True

        self._build_ui()
        self._start_audio()
        self._schedule_ui_refresh()
        self._schedule_keepalive()

    # ---------- UI construction ----------

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale", background=BG, troughcolor=PANEL)
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT_HI)

        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=16, pady=(16, 8))

        self.connection_label = tk.Label(top, text="OSC: not connected", bg=BG, fg=TEXT_LO,
                                          font=("Segoe UI", 10))
        self.connection_label.pack(side="left")

        self.console_box = ttk.Combobox(
            top, values=[CONSOLE_PROFILES[k]["label"] for k in CONSOLE_PROFILES],
            state="readonly", width=28)
        self.console_box.current(list(CONSOLE_PROFILES).index(DEFAULT_PROFILE))
        self.console_box.pack(side="left", padx=(12, 6))

        self.ip_entry = tk.Entry(top, bg=PANEL, fg=TEXT_HI, insertbackground=TEXT_HI,
                                  relief="flat", width=20)
        self.ip_entry.insert(0, "192.168.1.10")
        self.ip_entry.pack(side="left", padx=(0, 6))

        tk.Button(top, text="Connect", command=self._on_connect, bg=PANEL, fg=TEXT_HI,
                  relief="flat", activebackground=LINE).pack(side="left")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=8)

        sidebar = tk.Frame(body, bg=PANEL, width=200)
        sidebar.pack(side="left", fill="y", padx=(0, 16))
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_main(main)

    def _build_sidebar(self, parent):
        pad = {"padx": 12, "pady": (10, 2)}

        tk.Label(parent, text="Vocal channel", bg=PANEL, fg=TEXT_LO,
                  font=("Segoe UI", 9)).pack(anchor="w", **pad)
        row1 = tk.Frame(parent, bg=PANEL)
        row1.pack(fill="x", padx=12)
        self.vocal_box = ttk.Combobox(row1, values=["Ch 1", "Ch 2", "Ch 3", "Ch 4"], state="readonly")
        self.vocal_box.current(0)
        self.vocal_box.pack(side="left", fill="x", expand=True)
        self.vocal_dot = ActiveDot(row1)
        self.vocal_dot.pack(side="left", padx=(6, 0))

        tk.Label(parent, text="Reference bus", bg=PANEL, fg=TEXT_LO,
                  font=("Segoe UI", 9)).pack(anchor="w", **pad)
        row2 = tk.Frame(parent, bg=PANEL)
        row2.pack(fill="x", padx=12)
        self.reference_box = ttk.Combobox(row2, values=["Main LR", "Bus 1"], state="readonly")
        self.reference_box.current(0)
        self.reference_box.pack(side="left", fill="x", expand=True)
        self.reference_dot = ActiveDot(row2)
        self.reference_dot.pack(side="left", padx=(6, 0))

        tk.Button(parent, text="Relearn room", command=self._on_relearn, bg=BG, fg=TEXT_HI,
                  relief="flat", activebackground=LINE).pack(fill="x", padx=12, pady=(20, 6))

        self.panic_btn = tk.Button(parent, text="Panic mute", command=self._on_panic,
                                    bg="#3a2420", fg=RED, relief="flat", activebackground=RED)
        self.panic_btn.pack(fill="x", padx=12, pady=6)
        self.panic_active = False

    def _build_main(self, parent):
        top_row = tk.Frame(parent, bg=BG)
        top_row.pack(fill="x", pady=(0, 12))

        self.bypass_btn = tk.Button(top_row, text="Active", command=self._on_bypass_toggle,
                                     bg=BG, fg=TEAL, relief="solid", bd=2,
                                     highlightbackground=TEAL, width=10, height=4)
        self.bypass_btn.pack(side="left", padx=(0, 16))

        meter_col = tk.Frame(top_row, bg=BG)
        meter_col.pack(side="left", fill="x", expand=True, anchor="s")
        tk.Label(meter_col, text="Input", bg=BG, fg=TEXT_LO, font=("Segoe UI", 9)).pack(anchor="w")
        self.input_meter = Meter(meter_col, colour=TEAL)
        self.input_meter.pack(fill="x")

        tk.Label(parent, text="Cancellation depth: -- dB", bg=BG, fg=TEXT_HI,
                  font=("Segoe UI", 10), anchor="w", name="depthlabel").pack(fill="x", pady=(4, 2))
        self.depth_label = parent.nametowidget("depthlabel")
        self.depth_meter = Meter(parent, colour=AMBER)
        self.depth_meter.pack(fill="x", pady=(0, 16))

        gate_row = tk.Frame(parent, bg=BG)
        gate_row.pack(fill="x", pady=(0, 16))

        self.threshold_var = tk.DoubleVar(value=-34.0)
        self.attack_var = tk.DoubleVar(value=3.0)
        self.release_var = tk.DoubleVar(value=180.0)

        self._build_slider(gate_row, "Threshold (dB)", self.threshold_var, -60, 0,
                            self._on_gate_change)
        self._build_slider(gate_row, "Attack (ms)", self.attack_var, 0.5, 50,
                            self._on_gate_change)
        self._build_slider(gate_row, "Release (ms)", self.release_var, 10, 1000,
                            self._on_gate_change)

        tk.Label(parent, text="Output", bg=BG, fg=TEXT_LO, font=("Segoe UI", 9)).pack(anchor="w")
        self.output_meter = Meter(parent, colour=AMBER)
        self.output_meter.pack(fill="x")

    def _build_slider(self, parent, label, var, lo, hi, command):
        col = tk.Frame(parent, bg=BG)
        col.pack(side="left", fill="x", expand=True, padx=6)
        tk.Label(col, text=label, bg=BG, fg=TEXT_LO, font=("Segoe UI", 9)).pack(anchor="w")
        scale = ttk.Scale(col, from_=lo, to=hi, variable=var, orient="horizontal",
                           command=lambda _=None: command())
        scale.pack(fill="x")

    # ---------- Actions ----------

    def _start_audio(self):
        try:
            self.engine.start()
        except Exception as exc:  # sounddevice raises plain Exception/PortAudioError
            messagebox.showwarning(
                "Audio device",
                f"Couldn't open the default audio device automatically:\n{exc}\n\n"
                "You may need to select your XAir's USB audio device manually -- "
                "see README.md for how to list and pick a specific device.",
            )

    def _on_connect(self):
        ip = self.ip_entry.get().strip()
        console_key = list(CONSOLE_PROFILES.keys())[self.console_box.current()]

        # Reconnecting to a different console type needs a fresh client,
        # since port/channel-count are set at construction time.
        self.osc.disconnect()
        self.osc = MixerOSCClient(console_type=console_key)

        ok = self.osc.connect(ip)
        if ok:
            self.connection_label.config(text=f"OSC: connecting to {ip}")
            self.osc.on_channel_name = self._on_channel_name
            self.osc.subscribe_to_meters()
            self._populate_channel_list(self.osc.max_channels)
            # Fresh client = mixer's actual mute state is unknown to us;
            # don't show a stale "muted" indicator from a previous session.
            self.panic_active = False
            self.panic_btn.config(bg="#3a2420", fg=RED, text="Panic mute")
        else:
            self.connection_label.config(text="OSC: connection failed")

    def _populate_channel_list(self, max_channels: int):
        values = [f"Ch {i}" for i in range(1, max_channels + 1)]
        self.vocal_box.configure(values=values)
        self.vocal_box.current(0)

    def _on_channel_name(self, channel: int, name: str):
        # Update the vocal channel dropdown label if it corresponds to an entry.
        idx = channel - 1
        values = list(self.vocal_box["values"])
        if 0 <= idx < len(values):
            values[idx] = f"Ch {channel} - {name}"
            self.root.after(0, lambda: self.vocal_box.configure(values=values))

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
        # Real persistent toggle: pressed = muted (stays lit red until
        # pressed again), not just a momentary flash. Previously this only
        # ever sent "mute on" and reverted the button color after 400ms
        # regardless of actual mixer state -- misleading, since the mute
        # was still engaged on the mixer after the button looked normal
        # again.
        self.panic_active = not self.panic_active
        self.osc.set_mute_group(1, self.panic_active)
        if self.panic_active:
            self.panic_btn.config(bg=RED, fg=BG, text="Muted (click to unmute)")
        else:
            self.panic_btn.config(bg="#3a2420", fg=RED, text="Panic mute")

    def _on_gate_change(self):
        self.engine.set_gate_threshold_db(self.threshold_var.get())
        self.engine.set_gate_timing(self.attack_var.get(), self.release_var.get())

    # ---------- Periodic updates ----------

    def _schedule_ui_refresh(self):
        activity_threshold = 0.01  # ~ -40 dBFS
        self.input_meter.set_level(self.engine.last_input_peak)
        self.output_meter.set_level(self.engine.last_output_peak)
        depth = self.engine.last_cancellation_depth_db
        self.depth_meter.set_level(max(0.0, min(1.0, depth / 30.0)))
        self.depth_label.config(text=f"Cancellation depth: {depth:.1f} dB")
        self.vocal_dot.set_active(self.engine.last_input_peak > activity_threshold)
        self.reference_dot.set_active(self.engine.last_reference_peak > activity_threshold)
        self.root.after(33, self._schedule_ui_refresh)  # ~30fps

    def _schedule_keepalive(self):
        if self.osc.connected:
            self.osc.send_keepalive()
        self.root.after(8000, self._schedule_keepalive)

    def on_close(self):
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
