"""
fdaf_filter.py

Partitioned-block frequency-domain adaptive filter (PBFDAF, the "MDF"
algorithm used by most software echo cancellers).

Why this replaced the sample-by-sample NLMS filter: a real room needs
tens of milliseconds of echo tail modelled (a speaker 3 m away is ~9 ms
late before any reverb even starts), i.e. thousands of taps. The
time-domain NLMS loop runs in Python once per sample and can only afford
~256 taps (5 ms at 48 kHz) in real time. Doing the same maths per block in
the frequency domain costs a handful of numpy FFTs per block instead, so
4096+ taps run many times faster than real time.

How it works, per block of N samples:
  * the reference is split into K partitions of N samples each, so the
    filter covers K*N taps without the latency of one huge FFT;
  * prediction = sum over partitions of X_k * W_k (overlap-save);
  * the error updates every partition, normalised per frequency bin by the
    reference power in that bin (the frequency-domain version of NLMS);
  * the gradient is constrained to N taps per partition, which keeps the
    result equal to true linear convolution.

Robustness (all of it exercised by tests/test_fdaf_filter.py):
  * non-finite input samples are treated as silence;
  * double-talk: adaptation slows sharply when the residual jumps above its
    recent level (someone singing into the mic), so the voice isn't learned;
  * divergence guard: if the filter makes the signal louder instead of
    quieter for several blocks, or its state goes non-finite, it resets;
  * any input length works. Lengths that are a multiple of N add no
    latency; other lengths switch to buffered mode, which adds N samples.
"""

import math

import numpy as np


class PartitionedFDAF:
    # Double-talk detector: slow adaptation right down when the residual's
    # block energy jumps this far above its recent average.
    DOUBLE_TALK_RATIO = 4.0
    # Smoothing of the per-bin reference power used for normalisation.
    POWER_SMOOTHING = 0.9
    # Blocks in a row where the output is louder than the mic before the
    # divergence guard resets the filter.
    DIVERGENCE_BLOCKS = 8
    # ...and the leftover must exceed this fraction of the mic's typical
    # (slowly averaged, ~2 s) energy, so near-silence can't trigger it.
    DIVERGENCE_FLOOR = 0.01
    D_LONG_SMOOTHING = 0.0027
    # Smoothing of the block energies used for step-size control.
    ENERGY_SMOOTHING = 0.7
    # The filter counts as "adapted" once it removes this much (10 dB).
    ADAPTED_ERLE = 10.0
    # Leak estimator (see _step_scale).
    SPECTRUM_SMOOTHING = 0.35
    LEAK_SMOOTHING = 0.05
    MIN_LEAK = 0.005
    # How fast the ERLE estimate may fall per block (~3 s time constant at
    # 256-sample blocks, 48 kHz): slow enough that a sung phrase doesn't
    # look like a room change.
    ERLE_FALL = 0.0018
    # Output safety net: fall back to the raw mic when the filtered signal
    # would be louder than it.
    SAFE_RATIO = 1.0
    JOIN_SAMPLES = 32

    def __init__(self, filter_length: int = 2048, block_size: int = 256,
                 step_size: float = 0.5, regularization: float = 1e-6):
        if block_size < 8 or block_size & (block_size - 1):
            raise ValueError("block_size must be a power of two >= 8")
        if filter_length < 1:
            raise ValueError("filter_length must be >= 1")
        self.N = block_size
        self.K = max(1, math.ceil(filter_length / block_size))
        self.mu = step_size
        self.delta = regularization
        self.reset()

    @property
    def filter_length(self) -> int:
        return self.K * self.N

    def reset(self):
        n_bins = self.N + 1
        self.W = np.zeros((self.K, n_bins), dtype=np.complex128)
        self.X = np.zeros((self.K, n_bins), dtype=np.complex128)
        self.power = np.zeros(n_bins)
        self.x_prev = np.zeros(self.N)
        self.residual_level = 0.0
        self.e_smooth = self.d_smooth = 0.0
        self.Eh = self.Yh = None
        self.Pey = self.Pyy = 0.0
        self.leak = 1.0
        self.erle = 1.0
        self.adapted = False
        self.diverging_blocks = 0
        self.d_long = 0.0
        self.frozen = False
        self.resets = 0
        self._mix = 1.0            # 1 = outputting filtered signal, 0 = raw mic
        self._last_out = 0.0
        self.bypassed_blocks = 0
        self._in_ref = np.zeros(0)
        self._in_mic = np.zeros(0)
        self._out = np.zeros(0)
        self._buffered = False

    # ---------- public API ----------

    def process(self, reference: np.ndarray, mic: np.ndarray) -> np.ndarray:
        """Return the residual (mic with the predicted echo removed)."""
        count = min(len(reference), len(mic))
        if count == 0:
            return np.zeros(0)
        ref = _sanitize(reference[:count])
        mic = _sanitize(mic[:count])

        if not self._buffered and count % self.N == 0:
            out = np.empty(count)
            for start in range(0, count, self.N):
                out[start:start + self.N] = self._process_block(
                    ref[start:start + self.N], mic[start:start + self.N])
            return out

        # Irregular block sizes: queue input, emit with N samples of latency.
        if not self._buffered:
            self._buffered = True
            self._out = np.zeros(self.N)
        self._in_ref = np.concatenate([self._in_ref, ref])
        self._in_mic = np.concatenate([self._in_mic, mic])
        produced = []
        while len(self._in_ref) >= self.N:
            produced.append(self._process_block(self._in_ref[:self.N], self._in_mic[:self.N]))
            self._in_ref = self._in_ref[self.N:]
            self._in_mic = self._in_mic[self.N:]
        if produced:
            self._out = np.concatenate([self._out] + produced)
        out, self._out = self._out[:count], self._out[count:]
        return out

    def inherit(self, other: "PartitionedFDAF"):
        """
        Take over what another filter has learned, e.g. when the echo tail
        setting changes. Partitions both filters share are copied, so a
        longer tail keeps the learned room and just adds room to grow; a
        shorter one keeps the start of it. Needs the same block size.
        """
        if other.N != self.N:
            return
        k = min(self.K, other.K)
        self.W[:k] = other.W[:k]
        self.X[:k] = other.X[:k]
        self.x_prev = other.x_prev.copy()
        self.power = other.power.copy()

    # Same name as the old NLMSFilter so callers can swap filters.
    process_block = process

    def impulse_response(self) -> np.ndarray:
        """The time-domain filter the model has learned (for diagnostics)."""
        taps = np.fft.irfft(self.W, n=2 * self.N, axis=1)[:, :self.N]
        return taps.reshape(-1)

    # ---------- core ----------

    def _process_block(self, x: np.ndarray, d: np.ndarray) -> np.ndarray:
        N = self.N
        # Newest reference spectrum goes in front; oldest partition drops off.
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = np.fft.rfft(np.concatenate([self.x_prev, x]))
        self.x_prev = x.copy()

        Y = np.einsum("kb,kb->b", self.X, self.W)
        y = np.fft.irfft(Y, n=2 * N)[N:]
        e = d - y

        if not np.all(np.isfinite(e)):
            self._hard_reset()
            return d.copy()

        # Per-bin reference power across all partitions (the NLMS normaliser).
        inst_power = np.sum(self.X.real ** 2 + self.X.imag ** 2, axis=0)
        if not self.power.any():
            # First block after a reset: seed the estimate instead of
            # smoothing up from zero, which would make the first few steps
            # ~10x too large and overshoot.
            self.power = inst_power.copy()
        else:
            a = self.POWER_SMOOTHING
            self.power = a * self.power + (1 - a) * inst_power

        e_energy = float(np.dot(e, e)) / N
        d_energy = float(np.dot(d, d)) / N
        y_energy = float(np.dot(y, y)) / N
        step = self.mu * self._step_scale(e, y, e_energy, d_energy, y_energy)

        if float(np.dot(x, x)) > 1e-12:
            E = np.fft.rfft(np.concatenate([np.zeros(N), e]))
            norm = step / (self.power + self.delta * 2 * N + 1e-12)
            G = np.conj(self.X) * (E * norm)
            # Gradient constraint: keep only the first N taps of each partition.
            g = np.fft.irfft(G, n=2 * N, axis=1)
            g[:, N:] = 0.0
            self.W += np.fft.rfft(g, axis=1)

        self._divergence_guard(e_energy, d_energy)
        return self._safe_output(e, d, e_energy, d_energy)

    def _divergence_guard(self, e_energy: float, d_energy: float):
        """
        Reset the model if it makes the signal clearly louder for several
        blocks in a row -- it has diverged.

        The excess must also be significant against the mic's *typical*
        level. When the music stops and the room falls silent, a leftover
        prediction of 0.0003 over background noise of 0.0001 is 'louder'
        but harmless; resetting there threw away everything learned (found
        by the soak test: ~15 s of poor cancellation after every break).
        """
        self.d_long += self.D_LONG_SMOOTHING * (d_energy - self.d_long)
        if d_energy > 1e-10 and e_energy > 4.0 * d_energy \
                and e_energy > self.DIVERGENCE_FLOOR * self.d_long:
            self.diverging_blocks += 1
            if self.diverging_blocks >= self.DIVERGENCE_BLOCKS:
                self._hard_reset()
        else:
            self.diverging_blocks = 0

    def _safe_output(self, e, d, e_energy, d_energy):
        """
        Safety net: never output more than the raw mic. Removing echo can
        only make the signal quieter; if the leftover is louder than the
        mic, the model is wrong right now (still learning, or confused by a
        closed feedback loop), so pass the mic through instead.

        Switching to the mic happens at once -- none of the bad block gets
        through -- and only the small step at the joining sample is smoothed
        away over ~0.7 ms so it doesn't click. Switching back to the filtered
        signal crossfades over the block.
        """
        safe = e_energy <= d_energy * self.SAFE_RATIO
        was_filtered = self._mix == 1.0
        if safe and was_filtered:
            out = e
        elif not safe:
            self.bypassed_blocks += 1
            out = d.copy()
            if was_filtered:
                n = min(self.JOIN_SAMPLES, len(out))
                out[:n] += (self._last_out - d[0]) * np.linspace(1.0, 0.0, n)
        else:  # recovering: fade from the mic back to the filtered signal
            w = np.linspace(0.0, 1.0, len(e))
            out = w * e + (1.0 - w) * d
        self._mix = 1.0 if safe else 0.0
        self._last_out = float(out[-1])
        return out

    def _step_scale(self, e, y, e_energy: float, d_energy: float,
                    y_energy: float) -> float:
        """
        How fast to learn this block (0..1) -- the double-talk protection.

        Before the filter has learned the room it learns at full speed. After
        that, the step is the estimated fraction of the leftover signal that is
        still *residual echo* (the "optimal step size" of MDF echo
        cancellers such as Speex). Residual echo rises and falls together with
        the predicted echo, a voice doesn't, so the "leak" is estimated from
        how the leftover's spectrum co-varies with the prediction's:

            leak ~ cov(|E|^2, |Y|^2) / var(|Y|^2)
            residual echo ~ leak * |y|^2
            step ~ residual echo / |e|^2

        While someone sings, the leftover is mostly voice, the covariance
        collapses and learning nearly stops, so the voice isn't learned as
        feedback. When the room changes, the leftover is echo that tracks the
        prediction, the leak rises, and the filter re-learns.

        A sudden jump of the leftover above its recent level (a voice starting)
        additionally slows learning at once, before the estimates catch up.
        """
        s = self.ENERGY_SMOOTHING
        self.e_smooth = s * self.e_smooth + (1 - s) * e_energy
        self.d_smooth = s * self.d_smooth + (1 - s) * d_energy

        level = self.residual_level
        self.frozen = level > 0 and e_energy > self.DOUBLE_TALK_RATIO ** 2 * level
        self.residual_level = e_energy if level == 0 else 0.95 * level + 0.05 * e_energy

        # Leak estimate from spectral co-variation (see docstring).
        Ef = np.abs(np.fft.rfft(e)) ** 2
        Yf = np.abs(np.fft.rfft(y)) ** 2
        if self.Eh is None:
            self.Eh, self.Yh = Ef, Yf
        a = self.SPECTRUM_SMOOTHING
        self.Eh = (1 - a) * self.Eh + a * Ef
        self.Yh = (1 - a) * self.Yh + a * Yf
        dE, dY = Ef - self.Eh, Yf - self.Yh
        b = self.LEAK_SMOOTHING
        self.Pey = (1 - b) * self.Pey + b * float(np.dot(dE, dY))
        self.Pyy = (1 - b) * self.Pyy + b * float(np.dot(dY, dY))
        self.leak = min(1.0, max(self.MIN_LEAK, self.Pey / (self.Pyy + 1e-30)))

        if not self.adapted and self.d_smooth > 1e-12 and \
                self.d_smooth > self.ADAPTED_ERLE * self.e_smooth:
            self.adapted = True

        # Second residual-echo estimate: the echo the filter predicts, divided
        # by how much it has recently been removing (ERLE). Rises fast when
        # cancellation improves, falls slowly (seconds) when the leftover
        # grows -- so a sung phrase barely moves it, while a real room change
        # or a filter that is still converging (long echo tails) pulls it
        # down and keeps learning going. The leak estimate alone can
        # collapse to its minimum while a long filter is still far from
        # converged, stalling it at ~20 dB.
        if d_energy > 1e-12 and e_energy > 0:
            ratio = d_energy / e_energy
            if ratio > self.erle:
                self.erle += 0.3 * (ratio - self.erle)
            else:
                self.erle += self.ERLE_FALL * (ratio - self.erle)
            self.erle = max(1.0, self.erle)

        scale = 1.0
        if self.adapted:
            residual = max(self.leak * y_energy, y_energy / self.erle)
            scale = min(1.0, residual / (e_energy + 1e-20))
        if self.frozen:
            scale *= 0.05
        return scale

    def _hard_reset(self):
        self.W[:] = 0
        self.power[:] = 0
        self.residual_level = 0.0
        self.e_smooth = self.d_smooth = 0.0
        self.Eh = self.Yh = None
        self.Pey = self.Pyy = 0.0
        self.leak = 1.0
        self.erle = 1.0
        self.adapted = False
        self.diverging_blocks = 0
        self.resets += 1


def _sanitize(block: np.ndarray) -> np.ndarray:
    arr = np.asarray(block, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr
