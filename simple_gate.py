"""
simple_gate.py

Basic envelope-follower gate/expander. Mirrors the JUCE version's behavior:
attenuates the signal below a threshold, with separate attack/release
time constants.
"""

import math

import numpy as np


class SimpleGate:
    def __init__(self, threshold_db: float = -34.0, attack_ms: float = 3.0,
                 release_ms: float = 180.0, sample_rate: float = 44100.0):
        self.sample_rate = float(sample_rate)
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.set_threshold_db(threshold_db)
        self.set_timing(attack_ms, release_ms)
        self.envelope = 0.0

    def set_threshold_db(self, threshold_db: float):
        self.threshold_linear = 10.0 ** (threshold_db / 20.0)

    def set_timing(self, attack_ms: float, release_ms: float):
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.attack_coeff = self._coeff(attack_ms)
        self.release_coeff = self._coeff(release_ms)

    def set_sample_rate(self, sample_rate: float):
        """Recompute time constants when the audio device's rate is known."""
        self.sample_rate = float(sample_rate)
        self.set_timing(self.attack_ms, self.release_ms)

    def reset(self):
        self.envelope = 0.0

    def _coeff(self, time_ms: float) -> float:
        return 1.0 - math.exp(-1.0 / (max(time_ms, 0.01) * 0.001 * self.sample_rate))

    def process_sample(self, sample: float) -> float:
        if not math.isfinite(sample):
            sample = 0.0
        rectified = abs(sample)
        coeff = self.attack_coeff if rectified > self.envelope else self.release_coeff
        self.envelope += coeff * (rectified - self.envelope)
        if not math.isfinite(self.envelope):
            self.envelope = 0.0
        if self.envelope >= self.threshold_linear:
            return sample
        return sample * (self.envelope / self.threshold_linear)

    def process_block(self, block: np.ndarray) -> np.ndarray:
        # Read coefficients once per block so a UI thread changing them
        # mid-block can't produce a half-updated pair.
        attack, release = self.attack_coeff, self.release_coeff
        threshold = self.threshold_linear
        env = self.envelope
        samples = np.asarray(block, dtype=np.float64).tolist()
        out = np.empty(len(samples), dtype=np.float64)
        for i, sample in enumerate(samples):
            if not math.isfinite(sample):
                sample = 0.0
            rectified = abs(sample)
            env += (attack if rectified > env else release) * (rectified - env)
            if not math.isfinite(env):
                env = 0.0
            out[i] = sample if env >= threshold else sample * (env / threshold)
        self.envelope = env
        return out
