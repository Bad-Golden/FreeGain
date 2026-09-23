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
numpy operations instead of a Python-level loop over taps. Scalar checks
in the per-sample path use the `math` module rather than numpy, since
numpy's scalar functions carry ~1us of overhead each -- which adds up at
44-48k calls per second. Run `python benchmark.py` to check headroom on
your own machine.
"""

import math

import numpy as np


class NLMSFilter:
    # Double-talk detector: adaptation freezes when the residual jumps above
    # this multiple of its own recent average level.
    DOUBLE_TALK_RATIO = 6.0
    LEVEL_SMOOTHING = 0.01

    def __init__(self, num_taps: int = 256, step_size: float = 0.5, epsilon: float = 1e-6):
        if num_taps < 1:
            raise ValueError("num_taps must be >= 1")
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
        # buffer underrun) would otherwise poison the filter taps
        # permanently, since NaN propagates through every multiply-add
        # forever after.
        if not math.isfinite(reference):
            reference = 0.0
        if not math.isfinite(mic_input):
            mic_input = 0.0

        n = self.num_taps
        if self.pos == len(self.buf):
            self.buf[:n] = self.buf[-n:]
            self.pos = n
            # The running energy sum accumulates floating-point drift over
            # millions of add/subtract steps; resync it exactly once per
            # wrap (every num_taps samples), which is cheap.
            self.energy = max(float(np.dot(self.buf[:n], self.buf[:n])), self.eps)

        evicted_value = self.buf.item(self.pos - n)
        self.buf[self.pos] = reference

        # Window newest-first, matching taps[0] = most recent convention.
        window = self.buf[self.pos - n + 1: self.pos + 1][::-1]

        prediction = float(np.dot(self.taps, window))
        if not math.isfinite(prediction):
            # Safety net: taps went non-finite despite input sanitization
            # (pathological input). Reset rather than let corruption persist.
            self.taps.fill(0.0)
            prediction = 0.0
        residual = mic_input - prediction

        # Double-talk guard: freeze *adaptation* if the residual looks like
        # genuine voice rather than an unmodeled feedback path. Energy
        # tracking below must NOT be gated by this -- the sliding window
        # keeps shifting every sample regardless of whether we adapt, so
        # energy has to be kept in sync every sample or it goes stale and
        # causes the step size to blow up once adaptation resumes.
        abs_residual = abs(residual)
        self.level_estimate += self.LEVEL_SMOOTHING * (abs_residual - self.level_estimate)
        self.frozen = abs_residual > (self.DOUBLE_TALK_RATIO * self.level_estimate + self.eps)

        energy = self.energy + reference * reference - evicted_value * evicted_value
        self.energy = energy if energy > self.eps else self.eps

        if not self.frozen:
            self.taps += (self.mu * residual / self.energy) * window

        self.pos += 1
        return residual

    def process_block(self, reference: np.ndarray, mic_input: np.ndarray) -> np.ndarray:
        """Process a block sample-by-sample, returning the residual."""
        count = min(len(reference), len(mic_input))
        out = np.empty(count, dtype=np.float64)
        # tolist() gives plain Python floats, which are much cheaper to
        # handle per-sample than numpy scalars.
        refs = np.asarray(reference[:count], dtype=np.float64).tolist()
        mics = np.asarray(mic_input[:count], dtype=np.float64).tolist()
        process = self.process_sample
        for i in range(count):
            out[i] = process(refs[i], mics[i])
        return out


def cancellation_depth_db(mic_block: np.ndarray, residual_block: np.ndarray,
                          eps: float = 1e-12) -> float:
    """
    How much the filter reduced the mic signal over a block, in dB
    (a block-level ERLE estimate). 0 dB means nothing was removed.

    Comparing whole-block power is far more meaningful than comparing
    two individual samples, which just produces a jittery number.
    """
    if len(mic_block) == 0 or len(residual_block) == 0:
        return 0.0
    mic_power = float(np.mean(np.square(mic_block))) + eps
    res_power = float(np.mean(np.square(residual_block))) + eps
    return max(0.0, 10.0 * math.log10(mic_power / res_power))
