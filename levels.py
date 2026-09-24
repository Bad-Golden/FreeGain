"""
levels.py

Level controls for the audio path: smoothly-ramped gains and a soft
output limiter.

Gain changes are ramped across one block instead of jumping, so moving a
slider during a show never produces clicks or "zipper" noise.

The limiter is a stateless soft clipper: signals below -1 dBFS pass
untouched; above that they bend smoothly towards full scale instead of
hitting it hard. Stateless means no added latency and nothing to pump.
It's a safety net for when the output level is pushed up, not a mastering
limiter.
"""

import numpy as np

LIMIT_THRESHOLD = 10 ** (-1.0 / 20)   # -1 dBFS


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20.0))


class GainRamp:
    """A gain that moves to its new value over one block."""

    def __init__(self, db: float = 0.0):
        self.current = db_to_gain(db)
        self.target = self.current
        self.db = float(db)

    def set_db(self, db: float):
        self.db = float(db)
        self.target = db_to_gain(db)

    def apply(self, block: np.ndarray) -> np.ndarray:
        n = len(block)
        if n == 0:
            return block
        if self.current == self.target:
            return block if self.current == 1.0 else block * self.current
        ramp = np.linspace(self.current, self.target, n + 1)[1:]
        self.current = self.target
        return block * ramp


def soft_limit(block: np.ndarray, threshold: float = LIMIT_THRESHOLD):
    """Return (limited block, whether any sample was over the threshold)."""
    mag = np.abs(block)
    over = mag > threshold
    if not over.any():
        return block, False
    headroom = 1.0 - threshold
    out = block.copy()
    out[over] = np.sign(block[over]) * (
        threshold + headroom * np.tanh((mag[over] - threshold) / headroom))
    return out, True
