"""
audio_engine.py

Handles audio I/O via sounddevice (PortAudio) and runs each block
through the NLMS filter + gate.

Works with any audio interface PortAudio can open -- a console's built-in
USB interface, Dante Virtual Soundcard, an external interface fed from the
console's direct outs, etc. The mic and reference signals are picked by
input channel index (0-based), so you choose which input carries the vocal
mic and which carries the speaker feed. The stream is opened with just
enough input channels to cover both selections.
"""

import os
import threading

import numpy as np

from nlms_filter import NLMSFilter, cancellation_depth_db
from simple_gate import SimpleGate


def _sd():
    # Imported lazily so the rest of the app (and the test suite) can load
    # on machines where the PortAudio library isn't installed.
    #
    # On Windows, sounddevice ships a second PortAudio build with ASIO
    # support and only loads it when this variable is set. Most console USB
    # drivers (XAir, X32, Wing, Qu, SQ...) and Dante Virtual Soundcard are
    # ASIO, so turn it on unless the user has explicitly set it otherwise.
    os.environ.setdefault("SD_ENABLE_ASIO", "1")
    import sounddevice
    return sounddevice


class AudioEngine:
    def __init__(self, sample_rate=None, block_size: int = 512, num_taps: int = 256):
        # sample_rate=None means "use the device's native rate" -- console
        # interfaces usually run at 48 kHz, and forcing a different rate
        # either fails to open or makes the OS resample behind our back.
        self.requested_sample_rate = sample_rate
        self.sample_rate = float(sample_rate or 48000)
        self.block_size = block_size
        self.filter = NLMSFilter(num_taps=num_taps, step_size=0.5)
        self.gate = SimpleGate(sample_rate=self.sample_rate)
        self.stream = None
        self.engaged = True

        self.mic_channel = 0
        self.reference_channel = 1
        self.input_device = None
        self.output_device = None

        # Set from the UI thread, acted on at the start of the next audio
        # block -- so the filter is never reset halfway through processing.
        self._reset_requested = threading.Event()

        # Latest metering info, read by the UI refresh loop.
        self.last_input_peak = 0.0
        self.last_output_peak = 0.0
        self.last_reference_peak = 0.0
        self.last_cancellation_depth_db = 0.0
        self.xrun_count = 0

    # ---------- Device handling ----------

    @staticmethod
    def list_devices():
        """
        Return [(index, name, host_api, max_input_channels, max_output_channels)].

        The host API (ASIO, WASAPI, MME, Core Audio...) matters on Windows:
        multichannel console interfaces usually only expose all their
        channels through ASIO or WASAPI, while MME often shows just two.
        """
        sd = _sd()
        apis = [api["name"] for api in sd.query_hostapis()]
        return [(i, d["name"], apis[d["hostapi"]] if d["hostapi"] < len(apis) else "?",
                 d["max_input_channels"], d["max_output_channels"])
                for i, d in enumerate(sd.query_devices())]

    def configure(self, input_device=None, output_device=None,
                  mic_channel: int = 0, reference_channel: int = 1):
        """Set routing. Takes effect on the next start()."""
        if mic_channel < 0 or reference_channel < 0:
            raise ValueError("channel indices must be >= 0")
        self.input_device = input_device
        self.output_device = output_device
        self.mic_channel = mic_channel
        self.reference_channel = reference_channel

    @property
    def running(self) -> bool:
        return self.stream is not None

    def start(self):
        sd = _sd()
        self.stop()

        in_channels = max(self.mic_channel, self.reference_channel) + 1
        in_info = sd.query_devices(self.input_device, "input")
        if in_info["max_input_channels"] < in_channels:
            raise RuntimeError(
                f"'{in_info['name']}' has {in_info['max_input_channels']} input "
                f"channel(s), but channel {in_channels} was selected.")

        rate = self.requested_sample_rate or in_info["default_samplerate"]
        self.sample_rate = float(rate)
        self.gate.set_sample_rate(self.sample_rate)
        self.gate.reset()
        self._reset_requested.set()  # new device = new room/latency, relearn

        stream = sd.Stream(
            device=(self.input_device, self.output_device),
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=(in_channels, 1),
            dtype="float32",
            callback=self._callback,
        )
        stream.start()
        self.stream = stream

    def stop(self):
        stream, self.stream = self.stream, None
        if stream:
            stream.stop()
            stream.close()

    # ---------- Controls (called from the UI thread) ----------

    def trigger_relearn(self):
        self._reset_requested.set()

    def set_engaged(self, engaged: bool):
        self.engaged = engaged

    def set_gate_threshold_db(self, threshold_db: float):
        self.gate.set_threshold_db(threshold_db)

    def set_gate_timing(self, attack_ms: float, release_ms: float):
        self.gate.set_timing(attack_ms, release_ms)

    # ---------- Audio thread ----------

    def _callback(self, indata, outdata, frames, time_info, status):
        # Don't print from the audio thread -- console I/O can block long
        # enough to cause the very dropouts being reported. Just count them.
        if status:
            self.xrun_count += 1

        # Some drivers send zero-length blocks transiently (device
        # reconfiguration, stream start/stop).
        if frames == 0:
            return

        if self._reset_requested.is_set():
            self._reset_requested.clear()
            self.filter.reset()

        channels = indata.shape[1]
        mic = indata[:, min(self.mic_channel, channels - 1)].astype(np.float64)
        reference = indata[:, min(self.reference_channel, channels - 1)].astype(np.float64)

        if self.engaged:
            residual = self.filter.process_block(reference, mic)
            out = self.gate.process_block(residual)
            depth = cancellation_depth_db(mic, residual)
        else:
            out = np.nan_to_num(mic, nan=0.0, posinf=0.0, neginf=0.0)
            depth = 0.0

        outdata[:, 0] = np.clip(out, -1.0, 1.0).astype(np.float32)
        if outdata.shape[1] > 1:
            outdata[:, 1:] = outdata[:, :1]

        self.last_input_peak = _peak(mic)
        self.last_output_peak = _peak(out)
        self.last_reference_peak = _peak(reference)
        self.last_cancellation_depth_db = depth


def _peak(block: np.ndarray) -> float:
    if len(block) == 0:
        return 0.0
    peak = float(np.max(np.abs(block)))
    return peak if np.isfinite(peak) else 0.0
