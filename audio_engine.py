"""
audio_engine.py

Handles USB audio I/O via sounddevice (PortAudio) and runs each block
through the NLMS filter + gate. Assumes input channel 0 = mic, channel 1
= reference (speaker feed) -- same assumption as the JUCE version, and
the same known gap: the UI's channel dropdowns don't yet reroute which
physical channel is used here. See README.md.
"""

import threading

import numpy as np
import sounddevice as sd

from nlms_filter import NLMSFilter
from simple_gate import SimpleGate


class AudioEngine:
    def __init__(self, sample_rate: int = 44100, block_size: int = 512, num_taps: int = 256):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.filter = NLMSFilter(num_taps=num_taps, step_size=0.5)
        self.gate = SimpleGate(sample_rate=sample_rate)
        self.stream = None
        self.engaged = True
        self._lock = threading.Lock()

        # Latest metering info, read by the UI refresh loop.
        self.last_input_peak = 0.0
        self.last_output_peak = 0.0
        self.last_reference_peak = 0.0
        self.last_cancellation_depth_db = 0.0

    def list_devices(self):
        return sd.query_devices()

    def start(self, device=None):
        self.stream = sd.Stream(
            device=device,
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=(2, 1),  # 2 in (mic, reference), 1 out
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def trigger_relearn(self):
        with self._lock:
            self.filter.reset()

    def set_engaged(self, engaged: bool):
        with self._lock:
            self.engaged = engaged

    def set_gate_threshold_db(self, threshold_db: float):
        self.gate.set_threshold_db(threshold_db)

    def set_gate_timing(self, attack_ms: float, release_ms: float):
        self.gate.set_timing(attack_ms, release_ms)

    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            # Overflow/underflow warnings land here -- surfacing them to
            # the UI (rather than just printing) is a reasonable next step.
            print(f"[audio] {status}")

        # Guard against a zero-length block, which some drivers can send
        # transiently (device reconfiguration, stream start/stop). Caught
        # via stress testing -- indexing [-1] below on an empty array
        # crashed the whole callback before this check.
        if frames == 0:
            return

        mic = indata[:, 0].astype(np.float64)
        reference = indata[:, 1].astype(np.float64) if indata.shape[1] > 1 else mic

        with self._lock:
            engaged = self.engaged

        if engaged:
            residual = self.filter.process_block(reference, mic)
            out = self.gate.process_block(residual)
            depth = self.filter.estimated_cancellation_depth_db(reference[-1], out[-1])
        else:
            out = mic.copy()
            depth = 0.0

        outdata[:, 0] = out.astype(np.float32)

        self.last_input_peak = float(np.max(np.abs(mic))) if len(mic) else 0.0
        self.last_output_peak = float(np.max(np.abs(out))) if len(out) else 0.0
        self.last_reference_peak = float(np.max(np.abs(reference))) if len(reference) else 0.0
        self.last_cancellation_depth_db = depth
