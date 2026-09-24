"""
pem_filter.py

Echo canceller for a *closed* feedback loop, using the prediction error
method (PEM) on top of the partitioned-block frequency-domain filter.

The problem: when FreeGain's output goes back out of the speakers, the
singer's voice is in both the mic and (a few tens of ms later) the
reference. A pitched, sustained note repeats itself, so an adaptive filter
can lower its error by "predicting" the live voice from its own echo --
i.e. by cancelling the singer. This is the closed-loop bias of acoustic
feedback cancellation.

The fix: model the voice as a source (short-term vowel resonances via LPC,
plus a long-term pitch predictor), and learn from *pre-whitened* versions
of the reference and the error, with that source model removed. After
whitening, the voice is close to white noise, which no longer correlates
with its own delayed echo, while the room's response is unchanged -- so
the filter learns the room, not the singer. The output is still computed
with the ordinary (unwhitened) filter.
"""

import numpy as np

from fdaf_filter import PartitionedFDAF

LPC_ORDER = 20
HISTORY = 2048            # samples of error history the source model is fit on
PITCH_MIN_MS, PITCH_MAX_MS = 2.5, 20.0


def _levinson(r: np.ndarray, order: int) -> np.ndarray:
    """LPC coefficients a (a[0] = 1) from autocorrelation r."""
    a = np.zeros(order + 1)
    a[0] = 1.0
    err = r[0]
    for i in range(1, order + 1):
        if err <= 1e-12:
            break
        k = -(r[i] + np.dot(a[1:i], r[i - 1:0:-1])) / err
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        err *= (1 - k * k)
    return a


class PEMFDAF(PartitionedFDAF):
    def __init__(self, filter_length: int = 2048, block_size: int = 256,
                 step_size: float = 0.5, regularization: float = 1e-6,
                 sample_rate: float = 48000.0):
        self.sample_rate = float(sample_rate)
        self.pitch_min = int(PITCH_MIN_MS / 1000 * sample_rate)
        self.pitch_max = int(PITCH_MAX_MS / 1000 * sample_rate)
        super().__init__(filter_length, block_size, step_size, regularization)

    def reset(self):
        super().reset()
        n_bins = self.N + 1
        self.Xw = np.zeros((self.K, n_bins), dtype=np.complex128)
        self.power_w = np.zeros(n_bins)
        keep = self.pitch_max + LPC_ORDER + self.N + 1
        self._x_hist = np.zeros(keep)
        self._e_hist = np.zeros(max(keep, HISTORY))
        self.xw_prev = np.zeros(self.N)
        self.pitch_lag = 0
        self.pitch_gain = 0.0
        self._window = np.hanning(HISTORY)
        self._model = None
        self._fit_count = 0

    def inherit(self, other):
        super().inherit(other)
        if isinstance(other, PEMFDAF):
            k = min(self.K, other.K)
            self.Xw[:k] = other.Xw[:k]
            self.power_w = other.power_w.copy()

    # ---------- source model ----------

    def _whitening_filter(self):
        """
        Fit the source model to the recent error. Returns (a, lag, gain):
        the whitening filter is A(z) * (1 - gain * z^-lag).
        """
        seg = self._e_hist[-HISTORY:] * self._window
        if float(np.dot(seg, seg)) < 1e-12:
            return np.array([1.0]), 0, 0.0
        spec = np.fft.rfft(seg, 2 * HISTORY)
        r = np.fft.irfft(np.abs(spec) ** 2)[: LPC_ORDER + 1]
        r[0] *= 1.0 + 1e-4                     # white-noise correction for stability
        a = _levinson(r, LPC_ORDER)
        # Long-term (pitch) predictor on the LPC residual.
        resid = np.convolve(self._e_hist[-HISTORY:], a)[LPC_ORDER:HISTORY]
        n = len(resid)
        spec = np.fft.rfft(resid, 2 * n)
        ac = np.fft.irfft(np.abs(spec) ** 2)[: self.pitch_max + 1]
        lags = ac[self.pitch_min:self.pitch_max + 1]
        lag = int(np.argmax(lags)) + self.pitch_min
        gain = float(ac[lag] / (ac[0] + 1e-20))
        if gain < 0.2:
            self.pitch_lag, self.pitch_gain = 0, 0.0
        else:
            self.pitch_lag, self.pitch_gain = lag, min(gain, 0.9)
        return a, self.pitch_lag, self.pitch_gain

    @staticmethod
    def _whiten(hist: np.ndarray, n: int, a: np.ndarray, lag: int, gain: float) -> np.ndarray:
        """Apply A(z) then (1 - gain z^-lag) to the last n samples of hist.
        Done as a short convolution plus one delayed subtraction, instead of
        convolving with a mostly-zero filter hundreds of taps long."""
        p = len(a) - 1
        u = np.convolve(hist[-(n + lag + p):], a, mode="valid")   # n + lag samples
        if lag == 0 or gain == 0.0:
            return u[-n:]
        return u[lag:] - gain * u[:n]

    # ---------- core ----------

    def _process_block(self, x: np.ndarray, d: np.ndarray) -> np.ndarray:
        N = self.N
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = np.fft.rfft(np.concatenate([self.x_prev, x]))
        self.x_prev = x.copy()
        self._x_hist = np.concatenate([self._x_hist[N:], x])

        Y = np.einsum("kb,kb->b", self.X, self.W)
        y = np.fft.irfft(Y, n=2 * N)[N:]
        e = d - y
        if not np.all(np.isfinite(e)):
            self._hard_reset()
            return d.copy()
        self._e_hist = np.concatenate([self._e_hist[N:], e])

        # Whiten the reference and the error with the current source model.
        # The voice changes slowly compared with a 5 ms block: re-fit the
        # source model every other block (halves the cost).
        self._fit_count += 1
        if self._model is None or self._fit_count % 2 == 0:
            self._model = self._whitening_filter()
        a, lag, gain = self._model
        xw = self._whiten(self._x_hist, N, a, lag, gain)
        ew = self._whiten(self._e_hist, N, a, lag, gain)
        self.Xw = np.roll(self.Xw, 1, axis=0)
        self.Xw[0] = np.fft.rfft(np.concatenate([self.xw_prev, xw]))
        self.xw_prev = xw

        inst_power = np.sum(self.Xw.real ** 2 + self.Xw.imag ** 2, axis=0)
        if not self.power_w.any():
            self.power_w = inst_power.copy()
        else:
            a = self.POWER_SMOOTHING
            self.power_w = a * self.power_w + (1 - a) * inst_power

        e_energy = float(np.dot(e, e)) / N
        d_energy = float(np.dot(d, d)) / N
        y_energy = float(np.dot(y, y)) / N
        step = self.mu * self._step_scale(e, y, e_energy, d_energy, y_energy)

        if float(np.dot(x, x)) > 1e-12:
            Ew = np.fft.rfft(np.concatenate([np.zeros(N), ew]))
            norm = step / (self.power_w + self.delta * 2 * N + 1e-12)
            G = np.conj(self.Xw) * (Ew * norm)
            g = np.fft.irfft(G, n=2 * N, axis=1)
            g[:, N:] = 0.0
            self.W += np.fft.rfft(g, axis=1)

        self._divergence_guard(e_energy, d_energy)
        return self._safe_output(e, d, e_energy, d_energy)

    def _hard_reset(self):
        super()._hard_reset()
        self.power_w[:] = 0
