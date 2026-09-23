"""
simple_gate.py

Basic RMS-envelope gate/expander. Mirrors the JUCE version's behavior:
attenuates the signal below a threshold, with separate attack/release
time constants.
"""

import numpy as np


class SimpleGate:
    def __init__(self, threshold_db: float = -34.0, attack_ms: float = 3.0,
                 release_ms: float = 180.0, sample_rate: float = 44100.0):
        self.sample_rate = sample_rate
        self.set_threshold_db(threshold_db)
        self.set_timing(attack_ms, release_ms)
        self.envelope = 0.0

    def set_threshold_db(self, threshold_db: float):
        self.threshold_linear = 10.0 ** (threshold_db / 20.0)

    def set_timing(self, attack_ms: float, release_ms: float):
        self.attack_coeff = 1.0 - np.exp(-1.0 / (max(attack_ms, 0.01) * 0.001 * self.sample_rate))
        self.release_coeff = 1.0 - np.exp(-1.0 / (max(release_ms, 0.01) * 0.001 * self.sample_rate))

    def process_sample(self, sample: float) -> float:
        if not np.isfinite(sample):
            sample = 0.0
        rectified = abs(sample)
        coeff = self.attack_coeff if rectified > self.envelope else self.release_coeff
        self.envelope += coeff * (rectified - self.envelope)
        if not np.isfinite(self.envelope):
            self.envelope = 0.0
        gain = 1.0 if self.envelope > self.threshold_linear else (self.envelope / self.threshold_linear)
        return sample * gain

    def process_block(self, block: np.ndarray) -> np.ndarray:
        out = np.empty_like(block)
        for i in range(len(block)):
            out[i] = self.process_sample(block[i])
        return out
