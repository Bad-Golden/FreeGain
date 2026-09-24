"""Synthetic rooms and signals shared by the DSP tests."""

import numpy as np

FS = 48000


def room(delay_ms: float, tail_ms: float, seed: int = 0, gain: float = 0.5,
         fs: int = FS) -> np.ndarray:
    """Impulse response: direct sound after `delay_ms`, then decaying reverb."""
    rng = np.random.default_rng(seed)
    d0 = int(delay_ms / 1000 * fs)
    n = d0 + max(1, int(tail_ms / 1000 * fs))
    h = np.zeros(n)
    t = np.arange(n - d0)
    h[d0:] = rng.standard_normal(n - d0) * np.exp(-t / (tail_ms / 1000 * fs / 6.9))
    h[d0] += 1.0
    return h / np.sqrt(np.sum(h ** 2)) * gain


def music(seconds: float, seed: int = 0, fs: int = FS) -> np.ndarray:
    """Coloured noise standing in for a PA mix (bass-heavy, never silent)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * fs)
    return np.convolve(rng.standard_normal(n), [1, 0.9, 0.5, 0.2])[:n] * 0.1


def voice(seconds: float, seed: int = 1, fs: int = FS, level: float = 0.3) -> np.ndarray:
    """Speech-like signal: band-limited noise gated at ~3 syllables/second."""
    rng = np.random.default_rng(seed)
    n = int(seconds * fs)
    carrier = np.convolve(rng.standard_normal(n), np.ones(6) / 6)[:n]
    envelope = np.clip(np.sin(np.arange(n) / fs * 2 * np.pi * 3), 0, None) ** 0.5
    return level * carrier * envelope


def echo(reference: np.ndarray, h: np.ndarray) -> np.ndarray:
    return np.convolve(reference, h)[: len(reference)]


def depth_db(before: np.ndarray, after: np.ndarray) -> float:
    return 10 * np.log10((np.mean(before ** 2) + 1e-20) / (np.mean(after ** 2) + 1e-20))


def singing(seconds: float, seed: int = 1, fs: int = FS, level: float = 0.1) -> np.ndarray:
    """A sung melody: pitched harmonics with vibrato, note changes, vowel-like
    resonances and phrasing. Much harder for a feedback canceller than noisy
    speech, because a pitched voice repeats itself every period."""
    rng = np.random.default_rng(seed)
    n = int(seconds * fs)
    t = np.arange(n) / fs
    # A new note every ~0.5 s, somewhere in a comfortable singing range.
    note_len = int(0.5 * fs)
    notes = 150 * 2 ** (rng.integers(0, 12, n // note_len + 1) / 12)
    f0 = np.repeat(notes, note_len)[:n]
    f0 = np.convolve(f0, np.ones(2000) / 2000, mode="same")          # glide between notes
    f0 *= 1 + 0.01 * np.sin(2 * np.pi * 5.5 * t)                      # vibrato
    phase = 2 * np.pi * np.cumsum(f0) / fs
    voice = sum((0.7 ** k) * np.sin(k * phase) for k in range(1, 16))
    # Vowel resonances: a couple of fixed formant-ish peaks.
    spectrum = np.fft.rfft(voice)
    freqs = np.fft.rfftfreq(n, 1 / fs)
    shape = 1 + 3 * np.exp(-((freqs - 700) / 250) ** 2) + 2 * np.exp(-((freqs - 1200) / 300) ** 2)
    voice = np.fft.irfft(spectrum * shape, n)
    # Phrasing: sing for ~3 s, breathe for ~0.7 s.
    envelope = (np.sin(2 * np.pi * t / 3.7) > -0.6).astype(float)
    envelope = np.convolve(envelope, np.ones(1500) / 1500, mode="same")
    voice *= envelope
    return level * voice / (np.sqrt(np.mean(voice ** 2)) + 1e-12)
