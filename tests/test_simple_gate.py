import numpy as np
import pytest

from simple_gate import SimpleGate


def test_loud_signal_passes_quiet_signal_attenuated():
    gate = SimpleGate(threshold_db=-30.0, sample_rate=48000)
    t = np.arange(48000) / 48000
    loud = 0.5 * np.sin(2 * np.pi * 440 * t)
    out = gate.process_block(loud)
    assert np.allclose(out[-1000:], loud[-1000:])

    quiet = 0.001 * np.sin(2 * np.pi * 440 * t)
    gate.reset()
    out = gate.process_block(quiet)
    assert np.max(np.abs(out[-1000:])) < 0.1 * np.max(np.abs(quiet))


@pytest.mark.parametrize("block", [512, 441, 37])
@pytest.mark.parametrize("fs", [44100, 48000, 96000])
def test_block_behaves_like_per_sample(block, fs):
    """The vectorised block gate steps its envelope every 16 samples instead
    of every sample; level over time must match the per-sample gate."""
    rng = np.random.default_rng(0)
    n = fs
    t = np.arange(n) / fs
    bursts = (np.sin(2 * np.pi * 3 * t) > 0.3).astype(float)       # on/off like syllables
    x = rng.standard_normal(n) * 0.05 * (bursts + 0.02)
    a, b = SimpleGate(sample_rate=fs), SimpleGate(sample_rate=fs)
    fast = np.concatenate([a.process_block(x[i:i + block]) for i in range(0, n, block)])
    slow = np.array([b.process_sample(float(v)) for v in x])
    win = int(0.005 * fs)
    diffs = []
    for i in range(0, n - win, win):
        rs = np.sqrt(np.mean(slow[i:i + win] ** 2))
        rf = np.sqrt(np.mean(fast[i:i + win] ** 2))
        if rs > 1e-4:
            diffs.append(abs(20 * np.log10((rf + 1e-12) / rs)))
    assert np.median(diffs) < 0.5
    assert np.percentile(diffs, 95) < 3.0


def test_block_gain_is_smooth():
    gate = SimpleGate(threshold_db=-30.0, sample_rate=48000)
    x = np.ones(4800) * 0.001          # well below threshold, then a step up
    x[2400:] = 0.5
    out = np.concatenate([gate.process_block(x[i:i + 512]) for i in range(0, len(x), 512)])
    assert np.max(np.abs(np.diff(out[2400:]))) < 0.05      # no hard gain jumps


def test_non_finite_samples_become_silence():
    gate = SimpleGate()
    out = gate.process_block(np.array([np.nan, np.inf, -np.inf, 0.5]))
    assert np.all(np.isfinite(out))
    assert out[:3].tolist() == [0.0, 0.0, 0.0]


def test_sample_rate_change_recomputes_coefficients():
    gate = SimpleGate(sample_rate=44100)
    before = gate.attack_coeff
    gate.set_sample_rate(96000)
    assert gate.attack_coeff < before
