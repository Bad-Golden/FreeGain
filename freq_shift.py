"""
freq_shift.py

Shifts every frequency in a signal up by a few hertz -- the classic trick
that lets a feedback canceller work inside a closed loop.

Why: in a live PA the singer's voice reaches the mic directly *and* comes
back out of the speakers a few tens of milliseconds later. To an adaptive
filter the two look alike, so it partly learns the voice instead of the
room (the "closed-loop bias" of acoustic feedback cancellation). Shifting
FreeGain's output by a few Hz means the voice that returns through the
speakers no longer lines up with the live voice at the mic, which breaks
that correlation. A small shift also spreads the energy of a ringing
frequency so feedback builds up more slowly.

How: a single-sideband shift needs the signal's analytic form (the signal
plus a copy phase-shifted by 90 degrees). An FIR Hilbert transformer would
add 5-10 ms of latency to reach down to voice fundamentals, so instead
this uses a pair of all-pass filter chains whose outputs stay 90 degrees
apart from ~20 Hz to ~20 kHz (Olli Niemitalo's well-known coefficient
set). All-pass filters add almost no latency. Their impulse responses are
computed once and applied per block with FFT convolution, so it's all
vectorised numpy -- no per-sample Python loop in the audio path.
"""

import math
from functools import lru_cache

import numpy as np

# Niemitalo's 90-degree all-pass pair; each coefficient is one
# second-order section y[n] = a^2 (x[n] + y[n-2]) - x[n-2].
_PATH_A = (0.6923878, 0.9360654322959, 0.9882295226860, 0.9987488452737)
_PATH_B = (0.4021921162426, 0.8561710882420, 0.9722909545651, 0.9952884791278)
IR_LENGTH = 4096   # tails beyond this are < -43 dB; image rejection stays >= 47 dB


def _allpass_ir(coefficients, length: int, extra_delay: int = 0) -> np.ndarray:
    x = np.zeros(length)
    x[extra_delay] = 1.0
    for a in coefficients:
        a2 = a * a
        y = np.zeros(length)
        for n in range(length):
            y[n] = a2 * (x[n] + (y[n - 2] if n >= 2 else 0.0)) - (x[n - 2] if n >= 2 else 0.0)
        x = y
    return x


@lru_cache(maxsize=4)
def _pair_spectra(nfft: int):
    """The all-pass pair's spectra, computed once per FFT size. Computing the
    impulse responses is a slow pure-Python loop (~20 ms), which must never
    happen on the audio thread."""
    h_i = _allpass_ir(_PATH_A, IR_LENGTH, extra_delay=1)
    h_q = _allpass_ir(_PATH_B, IR_LENGTH)
    HI, HQ = np.fft.rfft(h_i, nfft), np.fft.rfft(h_q, nfft)
    HI.flags.writeable = False
    HQ.flags.writeable = False
    return HI, HQ


class FrequencyShifter:
    def __init__(self, shift_hz: float, sample_rate: float, block_size: int = 512):
        self.sample_rate = float(sample_rate)
        self.shift_hz = float(shift_hz)
        self.block = block_size
        self._phase = 0.0
        # Path A carries the extra one-sample delay; the two outputs are then
        # 90 degrees apart (I and Q of the analytic signal).
        self._nfft = 1 << int(math.ceil(math.log2(IR_LENGTH + block_size)))
        self._HI, self._HQ = _pair_spectra(self._nfft)
        self._history = np.zeros(IR_LENGTH - 1)

    def set_shift(self, shift_hz: float):
        self.shift_hz = float(shift_hz)

    def reset(self):
        self._history[:] = 0.0
        self._phase = 0.0

    def process(self, block: np.ndarray) -> np.ndarray:
        n = len(block)
        if n == 0:
            return np.zeros(0)
        if n > self._nfft - (IR_LENGTH - 1):
            # Larger than planned for: process in pieces.
            return np.concatenate([self.process(block[i:i + self.block])
                                   for i in range(0, n, self.block)])
        buf = np.concatenate([self._history, block])
        self._history = buf[-(IR_LENGTH - 1):]
        spec = np.fft.rfft(buf, self._nfft)
        end = len(buf)
        i_part = np.fft.irfft(spec * self._HI, self._nfft)[end - n:end]
        q_part = np.fft.irfft(spec * self._HQ, self._nfft)[end - n:end]
        if self.shift_hz == 0.0:
            return i_part
        w = 2.0 * math.pi * self.shift_hz / self.sample_rate
        phase = self._phase + w * np.arange(n)
        self._phase = (self._phase + w * n) % (2.0 * math.pi)
        return i_part * np.cos(phase) + q_part * np.sin(phase)
