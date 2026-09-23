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


def test_block_matches_per_sample():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(2000) * 0.05
    a, b = SimpleGate(), SimpleGate()
    block = a.process_block(x)
    single = np.array([b.process_sample(float(s)) for s in x])
    assert np.allclose(block, single)
    assert a.envelope == pytest.approx(b.envelope)


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
