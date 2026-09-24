"""
delay_estimator.py

Finds how late the speaker sound arrives at the vocal mic, relative to the
reference signal, so the adaptive filter's taps can be spent on the room's
reverb instead of on dead time.

Method: GCC-PHAT (generalised cross-correlation with phase transform) over
the last ~2.7 seconds of audio. PHAT whitens both signals so the peak stays
sharp even for music with a strong bass or a coloured PA. Only positive
lags (mic later than reference) are searched: in a closed feedback loop
the reference also contains the vocal, but *later* than the mic, which
shows up at negative lags and is ignored.

The audio thread only copies blocks into a ring buffer (cheap). The FFTs
run on a background thread about once a second. They run on a 4x
decimated copy of the audio (~12 kHz, 0.08 ms resolution -- far finer than
needed) so each estimate takes a few milliseconds: Python threads share one
interpreter lock, and a long computation here could delay the audio thread.
An estimate is only accepted when the correlation peak clearly stands out
and two estimates in a row agree, so music pauses, silence or double-talk
don't make the delay jump around.
"""

import threading
import time
from typing import Optional

import numpy as np

WINDOW = 1 << 17            # ~2.7 s at 48 kHz
MIN_PEAK_RATIO = 12.0        # peak vs. mean |correlation| to count as a match
AGREE_MS = 1.0               # consecutive estimates must agree within this
MIN_RMS = 1e-4               # below this the reference is treated as silent


def gcc_phat(reference: np.ndarray, mic: np.ndarray, max_lag: int):
    """Return (lag_in_samples, peak_ratio) for mic relative to reference."""
    n = 1 << int(np.ceil(np.log2(len(reference) + len(mic))))
    R = np.fft.rfft(reference, n)
    M = np.fft.rfft(mic, n)
    cross = M * np.conj(R)
    cross /= np.abs(cross) + 1e-12
    corr = np.fft.irfft(cross, n)[: max_lag + 1]
    mag = np.abs(corr)
    peak = int(np.argmax(mag))
    ratio = float(mag[peak] / (np.mean(mag) + 1e-12))
    # The strongest peak can be a reflection that happens to be louder than
    # the direct sound. The direct path is the *earliest* strong peak, so
    # take the first lag that reaches half the maximum.
    lag = int(np.argmax(mag[: peak + 1] >= 0.5 * mag[peak]))
    return lag, ratio


class DelayEstimator:
    def __init__(self, sample_rate: float, max_delay_ms: float = 500.0,
                 interval_s: float = 1.0):
        self.sample_rate = float(sample_rate)
        self.max_lag = int(max_delay_ms / 1000.0 * sample_rate)
        # Analyse at ~12 kHz: plenty for a delay estimate, 4x less work.
        self.decimation = max(1, int(round(self.sample_rate / 12000.0)))
        self.interval_s = interval_s
        self._ref = np.zeros(WINDOW)
        self._mic = np.zeros(WINDOW)
        self._filled = 0
        self._pos = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.delay_samples: Optional[int] = None   # accepted estimate
        self.last_lag: Optional[int] = None         # most recent raw estimate
        self.last_ratio = 0.0
        self.history = []                           # (time, lag_ms, ratio, accepted)
        self._candidate: Optional[int] = None

    # ---------- audio thread ----------

    def push(self, reference: np.ndarray, mic: np.ndarray):
        n = min(len(reference), len(mic), WINDOW)
        if n == 0:
            return
        with self._lock:
            end = self._pos + n
            if end <= WINDOW:
                self._ref[self._pos:end] = reference[-n:]
                self._mic[self._pos:end] = mic[-n:]
            else:
                first = WINDOW - self._pos
                self._ref[self._pos:] = reference[-n:][:first]
                self._mic[self._pos:] = mic[-n:][:first]
                self._ref[: n - first] = reference[-n:][first:]
                self._mic[: n - first] = mic[-n:][first:]
            self._pos = end % WINDOW
            self._filled = min(WINDOW, self._filled + n)

    # ---------- background thread ----------

    def start(self):
        self.stop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def reset(self):
        with self._lock:
            self._filled = 0
            self._pos = 0
        self.delay_samples = None
        self._candidate = None

    def _run(self, stop: threading.Event):
        while not stop.wait(self.interval_s):
            try:
                self.estimate_once()
            except Exception as exc:  # never let the worker die silently
                self.history.append((time.time(), None, 0.0, f"error: {exc}"))

    def estimate_once(self) -> Optional[int]:
        """Run one estimate on the buffered audio. Returns the accepted delay."""
        with self._lock:
            if self._filled < min(WINDOW, self.max_lag * 4):
                return self.delay_samples
            ref = np.roll(self._ref, -self._pos)[-self._filled:]
            mic = np.roll(self._mic, -self._pos)[-self._filled:]
        if np.sqrt(np.mean(ref ** 2)) < MIN_RMS or np.sqrt(np.mean(mic ** 2)) < MIN_RMS:
            return self.delay_samples
        q = self.decimation
        if q > 1:
            usable = len(ref) // q * q
            # Averaging q samples is a crude but adequate anti-alias filter.
            ref = ref[-usable:].reshape(-1, q).mean(axis=1)
            mic = mic[-usable:].reshape(-1, q).mean(axis=1)
        lag, ratio = gcc_phat(ref, mic, self.max_lag // q)
        lag *= q
        self.last_lag, self.last_ratio = lag, ratio
        accepted = False
        if ratio >= MIN_PEAK_RATIO:
            agree = int(AGREE_MS / 1000.0 * self.sample_rate)
            if self._candidate is not None and abs(lag - self._candidate) <= agree:
                self.delay_samples = lag
                accepted = True
            self._candidate = lag
        else:
            self._candidate = None
        self.history.append((time.time(), 1000.0 * lag / self.sample_rate, ratio, accepted))
        del self.history[:-50]
        return self.delay_samples

    @property
    def delay_ms(self) -> Optional[float]:
        if self.delay_samples is None:
            return None
        return 1000.0 * self.delay_samples / self.sample_rate
