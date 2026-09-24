"""
benchmark.py

Measures how much faster than real time the full processing chain (echo
canceller + gate) runs on this machine, for each "Room echo tail" setting.
Anything comfortably above 1x works; below ~2x you may hear dropouts under
load -- pick a shorter echo tail if so.

Run with: python benchmark.py
"""

import time

import numpy as np

from audio_engine import TAIL_OPTIONS_MS
from fdaf_filter import PartitionedFDAF
from simple_gate import SimpleGate

SAMPLE_RATE = 48000
SECONDS = 4
BLOCK = 512


def main():
    rng = np.random.default_rng(0)
    n = SAMPLE_RATE * SECONDS
    reference = np.convolve(rng.standard_normal(n), [1, 0.9, 0.5])[:n] * 0.1
    mic = np.zeros(n)
    mic[480:] = reference[:-480] * 0.5
    mic += rng.standard_normal(n) * 0.01

    print(f"Processing {SECONDS} s of audio at {SAMPLE_RATE} Hz in {BLOCK}-sample blocks")
    for tail_ms in TAIL_OPTIONS_MS:
        canceller = PartitionedFDAF(int(tail_ms / 1000 * SAMPLE_RATE))
        gate = SimpleGate(sample_rate=SAMPLE_RATE)
        worst = 0.0
        start = time.perf_counter()
        for i in range(0, n, BLOCK):
            t0 = time.perf_counter()
            gate.process_block(canceller.process(reference[i:i + BLOCK], mic[i:i + BLOCK]))
            worst = max(worst, (time.perf_counter() - t0) / (BLOCK / SAMPLE_RATE))
        speed = SECONDS / (time.perf_counter() - start)
        print(f"  echo tail {tail_ms:4d} ms ({canceller.filter_length:5d} taps): "
              f"{speed:5.1f}x real time, CPU {100 / speed:4.1f}%, worst block {100 * worst:4.0f}%")


if __name__ == "__main__":
    main()
