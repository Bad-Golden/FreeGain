"""
benchmark.py

Measures how much faster than real time the filter + gate run on this
machine. Anything comfortably above 1.0x works; below ~2x you may hear
dropouts under load -- reduce num_taps in audio_engine.py if so.

Run with: python benchmark.py
"""

import time

import numpy as np

from nlms_filter import NLMSFilter
from simple_gate import SimpleGate

SAMPLE_RATE = 48000
SECONDS = 2


def main():
    rng = np.random.default_rng(0)
    n = SAMPLE_RATE * SECONDS
    reference = rng.standard_normal(n) * 0.3
    mic = np.zeros(n)
    mic[5:] = reference[:-5] * 0.6
    mic += rng.standard_normal(n) * 0.02

    for taps in (128, 256, 512):
        nlms = NLMSFilter(num_taps=taps)
        gate = SimpleGate(sample_rate=SAMPLE_RATE)
        start = time.perf_counter()
        for i in range(0, n, 512):
            gate.process_block(nlms.process_block(reference[i:i + 512], mic[i:i + 512]))
        elapsed = time.perf_counter() - start
        print(f"{taps:4d} taps: {SECONDS / elapsed:5.1f}x real time at {SAMPLE_RATE} Hz")


if __name__ == "__main__":
    main()
