"""
nlms_filter.py

Normalized Least Mean Squares adaptive filter -- same algorithm as the
JUCE/C++ version this replaces. Models the acoustic path between a
reference signal (what's being sent to the speakers) and a microphone
signal, predicts the feedback/reverb component, and subtracts it.

Standard, textbook adaptive filtering technique (same family used in
acoustic echo cancellation). Independent implementation, not derived
from any commercial product.

Performance note: this uses a double-length circular buffer so the
per-sample window (dot product + tap update) is done with vectorized
numpy operations instead of a Python-level loop over taps. Verified at
~5.3x real-time at 256 taps / 44.1kHz on the machine this was tested on
(see README's stress-test notes) -- comfortable headroom, but re-check
on your actual machine since Python overhead varies with CPU/OS.
"""

import numpy as np


class NLMSFilter:
    def __init__(self, num_taps: int = 256, step_size: float = 0.5, epsilon: float = 1e-6):
        self.num_taps = num_taps
        self.mu = step_size
        self.eps = epsilon
        self.reset()

    def reset(self):
        self.taps = np.zeros(self.num_taps, dtype=np.float64)
        # Double-length buffer avoids an O(N) shift/copy every sample --
        # we only copy the tail back to the front when we hit the end.
        self.buf = np.zeros(self.num_taps * 2, dtype=np.float64)
        self.pos = self.num_taps
        self.energy = self.eps
        self.level_estimate = 0.0
        self.frozen = False

    def process_sample(self, reference: float, mic_input: float) -> float:
        # Defensive sanitization: a single non-finite sample (audio glitch,
        # buffer underrun, denormal from upstream) would otherwise poison
        # the filter taps permanently, since NaN propagates through every
        # multiply-add forever after. Caught via stress testing -- a real
        # single bad sample corrupted 150/200 subsequent output samples
        # before this fix.
        if not np.isfinite(reference):
            reference = 0.0
        if not np.isfinite(mic_input):
            mic_input = 0.0

        if self.pos == len(self.buf):
            self.buf[:self.num_taps] = self.buf[-self.num_taps:]
            self.pos = self.num_taps

        evicted_value = self.buf[self.pos - self.num_taps]
        self.buf[self.pos] = reference

        # Window newest-first, matching taps[0] = most recent convention.
        window = self.buf[self.pos - self.num_taps + 1: self.pos + 1][::-1]

        prediction = float(np.dot(self.taps, window))
        residual = mic_input - prediction

        # Double-talk guard: freeze *adaptation* if the residual looks like
        # genuine voice rather than an unmodeled feedback path. Energy
        # tracking below must NOT be gated by this -- the sliding window
        # keeps shifting every sample regardless of whether we adapt, so
        # energy has to be kept in sync every sample or it goes stale and
        # causes the step size to blow up once adaptation resumes. (This
        # was a real bug caught during testing -- see README.)
        self.level_estimate = 0.99 * self.level_estimate + 0.01 * abs(residual)
        self.frozen = abs(residual) > (6.0 * self.level_estimate + self.eps)

        self.energy = self.energy + reference * reference - evicted_value * evicted_value
        self.energy = max(self.energy, self.eps)

        if not self.frozen:
            normalized_step = self.mu / self.energy
            self.taps += normalized_step * residual * window
            # Belt-and-suspenders: if taps somehow go non-finite despite
            # input sanitization above (e.g. from an extreme/pathological
            # input sequence), reset rather than let corruption persist
            # silently forever.
            if not np.all(np.isfinite(self.taps)):
                self.taps.fill(0.0)
                self.energy = self.eps

        self.pos += 1
        return residual

    def process_block(self, reference: np.ndarray, mic_input: np.ndarray) -> np.ndarray:
        """Convenience wrapper for processing a block sample-by-sample."""
        out = np.empty_like(mic_input, dtype=np.float64)
        for i in range(len(mic_input)):
            out[i] = self.process_sample(reference[i], mic_input[i])
        return out

    def estimated_cancellation_depth_db(self, reference: float, residual: float) -> float:
        ref_level = abs(reference) + self.eps
        res_level = abs(residual) + self.eps
        ratio = max(ref_level / res_level, 1.0)
        return 20.0 * np.log10(ratio)
