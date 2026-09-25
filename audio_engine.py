"""
audio_engine.py

Handles audio I/O via sounddevice (PortAudio) and runs each block through
the echo/feedback canceller and the gate.

Works with any audio interface PortAudio can open -- a console's built-in
USB interface, Dante Virtual Soundcard, an external interface fed from the
console's direct outs, etc. The mic and reference signals are picked by
input channel index (0-based), so you choose which input carries the vocal
mic and which carries the speaker feed. The stream is opened with just
enough input channels to cover both selections.

Signal chain per block:

  reference -> [bulk delay, from the delay estimator] -> PBFDAF filter
  mic -------------------------------------------------> (-) -> gate -> out

The delay estimator (delay_estimator.py) measures how late the speaker
sound reaches the mic and the reference is delayed by that much (minus a
safety margin), so the filter's taps cover the room's reverb rather than
the travel time.
"""

import os
import threading
import time
from collections import deque

import numpy as np

from delay_estimator import DelayEstimator
from fdaf_filter import PartitionedFDAF
from freq_shift import FrequencyShifter
from levels import GainRamp, soft_limit
from pem_filter import PEMFDAF
from nlms_filter import cancellation_depth_db
from simple_gate import SimpleGate

# Echo tail options offered in the UI (milliseconds of room modelled after
# the bulk delay). Longer = more cancellation in reverberant rooms, slower
# to converge, more CPU.
TAIL_OPTIONS_MS = (40, 85, 170, 340)
DEFAULT_TAIL_MS = 85
MAX_BULK_DELAY_MS = 500.0
DELAY_MARGIN_MS = 5.0        # start the filter this much before the direct sound
DELAY_CHANGE_MS = 2.0        # ignore estimate changes smaller than this
FILTER_BLOCK = 256


def filter_block_for(sample_rate: float) -> int:
    """
    Canceller block size. At 88.2/96 kHz twice as many samples arrive per
    second, so blocks twice as long keep the number of FFT rounds (and the
    CPU load) about the same as at 44.1/48 kHz -- measured: feedback mode
    at 96 kHz went from 2.1x to ~4x real time. The engine's 512-sample
    audio blocks are a multiple of both sizes, so no latency is added.
    """
    return FILTER_BLOCK * 2 if sample_rate > 64000 else FILTER_BLOCK

# Feedback mode: the processed vocal goes back out of the PA, so the loop is
# closed. Uses the prediction-error-method filter (learns the room, not the
# singer), a small frequency shift on the output to decorrelate the loop,
# and slower learning. Measured in tests/stress_feedback_loop.py: about
# +6 dB of extra usable gain before feedback with pitched singing, with the
# voice as clean as bypass at normal gain.
FEEDBACK_SHIFT_HZ = 5.0
# Careful long-term step. The filter starts faster (see pem_filter.WARM_STEP)
# and eases down to this.
FEEDBACK_STEP = 0.1
# Spill mode (feedback mode off): the reference never contains the vocal,
# e.g. a band or playback bleeding into a mic. The plain filter learns fast.
SPILL_STEP = 0.5


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
    def __init__(self, sample_rate=None, block_size: int = 512,
                 tail_ms: float = DEFAULT_TAIL_MS, feedback_mode: bool = True):
        # sample_rate=None means "use the device's native rate" -- console
        # interfaces usually run at 48 kHz, and forcing a different rate
        # either fails to open or makes the OS resample behind our back.
        self.requested_sample_rate = sample_rate
        self.sample_rate = float(sample_rate or 48000)
        self.base_block_size = block_size
        self.block_size = self._block_for(self.sample_rate)
        self.tail_ms = float(tail_ms)
        self.feedback_mode = bool(feedback_mode)
        self.filter = self._make_filter()
        self.gate = SimpleGate(sample_rate=self.sample_rate)
        self.delay_estimator = DelayEstimator(self.sample_rate, MAX_BULK_DELAY_MS)
        self.stream = None
        self.engaged = True
        self.auto_delay = True
        # Output frequency shift (Hz) against closed-loop feedback; 0 = off.
        self.shift_hz = 0.0
        self.shifter = None
        self._pending_shift = None
        if self.feedback_mode:
            self.shift_hz = FEEDBACK_SHIFT_HZ
            self.shifter = FrequencyShifter(FEEDBACK_SHIFT_HZ, self.sample_rate, self.block_size)

        self.mic_channel = 0
        self.reference_channel = 1
        self.input_device = None
        self.output_device = None

        # Applied bulk delay of the reference, in samples.
        self.bulk_delay = 0
        self._max_delay = int(MAX_BULK_DELAY_MS / 1000 * self.sample_rate)
        self._ref_history = np.zeros(self._max_delay)
        self.delay_changes = deque(maxlen=100)   # (time, old_ms, new_ms)

        # Requests from the UI thread, acted on at the start of the next audio
        # block -- so the filter is never swapped or reset mid-processing.
        self._reset_requested = threading.Event()
        self._pending_filter = None

        # Latest metering info, read by the UI refresh loop.
        self.last_input_peak = 0.0
        self.last_output_peak = 0.0
        self.last_reference_peak = 0.0
        self.last_cancellation_depth_db = 0.0
        self.xrun_count = 0

        # Level controls. Mic gain is applied *after* the echo canceller (so
        # changing it never forces a relearn) and before the gate; output
        # level is the final fader, followed by a soft limiter.
        self.mic_gain = GainRamp(0.0)
        self.output_gain = GainRamp(0.0)
        self.limiting = False          # limiter touched the last block
        self.limited_blocks = 0
        self.blocks_processed = 0

        # Routing check: if the mic and reference carry the same signal
        # (same channel picked twice, or the same source patched to both),
        # cancelling would silence the singer. Pass the vocal through instead
        # and tell the operator.
        self.same_signal = False
        self._same_run = 0.0          # seconds the two have matched
        self._differ_run = 0.0        # seconds they've differed since then

        # Diagnostics: CPU load of the audio callback and per-second history.
        self.cpu_load = 0.0          # smoothed: processing time / block duration
        self.cpu_load_peak = 0.0
        self.history = deque(maxlen=600)   # (time, depth_dB, in_peak, ref_peak, delay_ms)
        self._acc = [0.0, 0, 0.0, 0.0]     # depth sum, blocks, in peak, ref peak
        self._acc_start = time.monotonic()

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
        self.set_sample_rate(float(rate))

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
        self.delay_estimator.start()

    def stop(self):
        self.delay_estimator.stop()
        stream, self.stream = self.stream, None
        if stream:
            stream.stop()
            stream.close()

    def _block_for(self, rate: float) -> int:
        # Keep the audio block ~10.7 ms long at any rate: 512 samples at
        # 44.1/48 kHz, 1024 at 88.2/96 kHz. Same latency, half the per-block
        # overhead at high rates (5.3 ms blocks were occasionally overrun).
        return self.base_block_size * (2 if rate > 64000 else 1)

    def set_sample_rate(self, rate: float):
        """Rebuild everything that depends on the sample rate (stream stopped)."""
        self.sample_rate = float(rate)
        self.block_size = self._block_for(self.sample_rate)
        self.gate.set_sample_rate(self.sample_rate)
        self.gate.reset()
        self.filter = self._make_filter()
        self.delay_estimator.stop()
        self.delay_estimator = DelayEstimator(self.sample_rate, MAX_BULK_DELAY_MS)
        self._max_delay = int(MAX_BULK_DELAY_MS / 1000 * self.sample_rate)
        self._ref_history = np.zeros(self._max_delay)
        self.bulk_delay = 0
        if self.shift_hz:
            self.shifter = FrequencyShifter(self.shift_hz, self.sample_rate, self.block_size)

    # ---------- Controls (called from the UI thread) ----------

    def trigger_relearn(self):
        """Forget the room: reset the filter and re-measure the delay."""
        self.delay_estimator.reset()
        self._reset_requested.set()

    def set_engaged(self, engaged: bool):
        self.engaged = engaged

    def set_auto_delay(self, enabled: bool):
        self.auto_delay = enabled
        if not enabled:
            self._pending_delay = 0

    def set_tail_ms(self, tail_ms: float):
        """Change how much room reverb the filter models. Applied next block."""
        self.tail_ms = float(tail_ms)
        self._pending_filter = self._make_filter()

    def set_feedback_mode(self, enabled: bool):
        """Switch between feedback mode (closed loop) and spill mode. Keeps
        what the filter has learned; applied next block."""
        self.feedback_mode = bool(enabled)
        self._pending_filter = self._make_filter()
        self._queue_shift(FEEDBACK_SHIFT_HZ if enabled else 0.0)

    def set_frequency_shift(self, hz: float):
        """Shift FreeGain's output up by `hz` (0 = off). Applied next block."""
        self._queue_shift(max(0.0, float(hz)))

    def _queue_shift(self, hz: float):
        # Build the shifter here, on the caller's (UI) thread; the audio
        # thread only swaps it in, so it never stalls a block.
        shifter = FrequencyShifter(hz, self.sample_rate, self.block_size) if hz else None
        self._pending_shift = (hz, shifter)

    def set_mic_gain_db(self, db: float):
        self.mic_gain.set_db(db)

    def set_output_gain_db(self, db: float):
        self.output_gain.set_db(db)

    def set_gate_threshold_db(self, threshold_db: float):
        self.gate.set_threshold_db(threshold_db)

    def set_gate_timing(self, attack_ms: float, release_ms: float):
        self.gate.set_timing(attack_ms, release_ms)

    @property
    def bulk_delay_ms(self) -> float:
        return 1000.0 * self.bulk_delay / self.sample_rate

    def _make_filter(self) -> PartitionedFDAF:
        taps = int(self.tail_ms / 1000.0 * self.sample_rate)
        if self.feedback_mode:
            return PEMFDAF(filter_length=taps, block_size=filter_block_for(self.sample_rate),
                           step_size=FEEDBACK_STEP, sample_rate=self.sample_rate)
        return PartitionedFDAF(filter_length=taps, block_size=filter_block_for(self.sample_rate),
                               step_size=SPILL_STEP)

    # ---------- Audio thread ----------

    _pending_delay = None

    def _callback(self, indata, outdata, frames, time_info, status):
        started = time.perf_counter()
        # Don't print from the audio thread -- console I/O can block long
        # enough to cause the very dropouts being reported. Just count them.
        if status:
            self.xrun_count += 1

        # Some drivers send zero-length blocks transiently (device
        # reconfiguration, stream start/stop).
        if frames == 0:
            return

        channels = indata.shape[1]
        mic = indata[:, min(self.mic_channel, channels - 1)].astype(np.float64)
        reference = indata[:, min(self.reference_channel, channels - 1)].astype(np.float64)
        if not np.all(np.isfinite(mic)):
            mic = np.nan_to_num(mic, nan=0.0, posinf=0.0, neginf=0.0)
        if not np.all(np.isfinite(reference)):
            reference = np.nan_to_num(reference, nan=0.0, posinf=0.0, neginf=0.0)

        self._apply_pending_changes()
        self.delay_estimator.push(reference, mic)
        delayed_ref = self._delay_reference(reference)

        self._check_routing(mic, reference)

        mic_gain = self.mic_gain.current
        if self.engaged and self.same_signal:
            out = self.mic_gain.apply(mic)
            depth = 0.0
        elif self.engaged:
            residual = self.filter.process(delayed_ref, mic)
            out = self.gate.process_block(self.mic_gain.apply(residual))
            if self.shifter is not None:
                out = self.shifter.process(out)
            depth = cancellation_depth_db(mic, residual)
        else:
            # Bypass keeps the same level controls, so A/B comparisons are fair.
            out = self.mic_gain.apply(mic)
            depth = 0.0
        out, self.limiting = soft_limit(self.output_gain.apply(out))
        if self.limiting:
            self.limited_blocks += 1

        outdata[:, 0] = np.clip(out, -1.0, 1.0).astype(np.float32)
        if outdata.shape[1] > 1:
            outdata[:, 1:] = outdata[:, :1]

        # Input meter shows the mic after the mic gain, like a channel meter.
        self.last_input_peak = _peak(mic) * max(mic_gain, self.mic_gain.current)
        self.last_output_peak = _peak(out)
        self.last_reference_peak = _peak(reference)
        self.last_cancellation_depth_db = depth
        self.blocks_processed += 1
        self._update_stats(depth, frames, time.perf_counter() - started)

    def _apply_pending_changes(self):
        if self._pending_filter is not None:
            new, self._pending_filter = self._pending_filter, None
            new.inherit(self.filter)
            self.filter = new
        if self._reset_requested.is_set():
            self._reset_requested.clear()
            self.filter.reset()
            self.gate.reset()
        if self._pending_shift is not None:
            (hz, shifter), self._pending_shift = self._pending_shift, None
            self.shift_hz = hz
            if shifter is None:
                self.shifter = None
            elif self.shifter is None:
                self.shifter = shifter
            else:
                self.shifter.set_shift(hz)   # keep its history: no click

        if self.auto_delay:
            measured = self.delay_estimator.delay_samples
            if measured is not None:
                margin = int(DELAY_MARGIN_MS / 1000 * self.sample_rate)
                self._pending_delay = max(0, min(self._max_delay, measured - margin))
        if self._pending_delay is not None:
            change = abs(self._pending_delay - self.bulk_delay)
            if change > DELAY_CHANGE_MS / 1000 * self.sample_rate:
                old_ms = self.bulk_delay_ms
                delta = self._pending_delay - self.bulk_delay
                self.bulk_delay = self._pending_delay
                self.delay_changes.append((time.time(), old_ms, self.bulk_delay_ms))
                if abs(delta) < self.filter.filter_length // 2:
                    # Same room, re-aligned (e.g. the delay was just found at
                    # startup): keep what was learned, shifted to match.
                    end = len(self._ref_history) - self.bulk_delay
                    self.filter.shift_taps(delta, self._ref_history[:max(0, end)])
                else:
                    # A big jump (moved mic, delay tower): start over.
                    self.filter.reset()
            self._pending_delay = None

    SAME_CORRELATION = 0.999      # zero-lag correlation that means "same signal"
    SAME_AFTER_S = 0.5            # ...for this long before we step in
    DIFFER_AFTER_S = 1.0          # and this long below 0.9 before we step out

    def _check_routing(self, mic: np.ndarray, reference: np.ndarray):
        mm = float(np.dot(mic, mic))
        rr = float(np.dot(reference, reference))
        n = len(mic)
        if mm < 1e-8 * n or rr < 1e-8 * n:
            return                        # silence proves nothing either way
        corr = float(np.dot(mic, reference)) / np.sqrt(mm * rr)
        dt = n / self.sample_rate
        if corr > self.SAME_CORRELATION:
            # A pure tone (a sound-check oscillator) through the room can line
            # up with the reference by chance; only broadband audio proves the
            # two are the same signal. Tonal blocks are neutral evidence.
            spec = np.abs(np.fft.rfft(mic)) ** 2
            if np.sort(spec)[-4:].sum() > 0.9 * spec.sum():
                return
            self._same_run += dt
            self._differ_run = 0.0
            if self._same_run >= self.SAME_AFTER_S:
                self.same_signal = True
        else:
            self._same_run = 0.0
            if corr < 0.9:
                self._differ_run += dt
                if self._differ_run >= self.DIFFER_AFTER_S:
                    self.same_signal = False

    def _delay_reference(self, reference: np.ndarray) -> np.ndarray:
        n = len(reference)
        buf = np.concatenate([self._ref_history, reference])
        self._ref_history = buf[-self._max_delay:] if self._max_delay else np.zeros(0)
        end = len(buf) - self.bulk_delay
        return buf[end - n:end]

    def _update_stats(self, depth: float, frames: int, elapsed: float):
        load = elapsed / (frames / self.sample_rate)
        self.cpu_load = 0.95 * self.cpu_load + 0.05 * load
        self.cpu_load_peak = max(self.cpu_load_peak, load)
        acc = self._acc
        acc[0] += depth
        acc[1] += 1
        acc[2] = max(acc[2], self.last_input_peak)
        acc[3] = max(acc[3], self.last_reference_peak)
        now = time.monotonic()
        if now - self._acc_start >= 1.0:
            self.history.append((time.time(), acc[0] / acc[1], acc[2], acc[3], self.bulk_delay_ms))
            self._acc = [0.0, 0, 0.0, 0.0]
            self._acc_start = now

    # ---------- Diagnostics ----------

    def diagnostics(self) -> dict:
        est = self.delay_estimator
        return {
            "running": self.running,
            "sample_rate": self.sample_rate,
            "block_size": self.block_size,
            "input_device": self.input_device,
            "output_device": self.output_device,
            "mic_channel": self.mic_channel + 1,
            "reference_channel": self.reference_channel + 1,
            "engaged": self.engaged,
            "tail_ms": self.tail_ms,
            "feedback_mode": self.feedback_mode,
            "frequency_shift_hz": self.shift_hz,
            "safety_bypassed_blocks": self.filter.bypassed_blocks,
            "filter_taps": self.filter.filter_length,
            "filter_resets": self.filter.resets,
            "auto_delay": self.auto_delay,
            "bulk_delay_ms": round(self.bulk_delay_ms, 2),
            "measured_delay_ms": None if est.delay_ms is None else round(est.delay_ms, 2),
            "delay_peak_ratio": round(est.last_ratio, 1),
            "delay_changes": [(round(t, 1), round(a, 2), round(b, 2))
                              for t, a, b in self.delay_changes],
            "delay_history": [(round(t, 1), None if ms is None else round(ms, 2), round(r, 1), ok)
                              for t, ms, r, ok in est.history],
            "cpu_load_percent": round(100 * self.cpu_load, 1),
            "cpu_load_peak_percent": round(100 * self.cpu_load_peak, 1),
            "xruns": self.xrun_count,
            "blocks_processed": self.blocks_processed,
            "mic_gain_db": round(self.mic_gain.db, 1),
            "output_gain_db": round(self.output_gain.db, 1),
            "limited_blocks": self.limited_blocks,
            "mic_and_reference_same_signal": self.same_signal,
            "gate": {"threshold_linear": self.gate.threshold_linear,
                     "attack_ms": self.gate.attack_ms, "release_ms": self.gate.release_ms},
            "history_per_second": [
                {"t": round(t, 1), "depth_db": round(d, 1), "input_peak": round(i, 4),
                 "reference_peak": round(r, 4), "delay_ms": round(ms, 2)}
                for t, d, i, r, ms in self.history],
        }


def _peak(block: np.ndarray) -> float:
    if len(block) == 0:
        return 0.0
    peak = float(np.max(np.abs(block)))
    return peak if np.isfinite(peak) else 0.0
