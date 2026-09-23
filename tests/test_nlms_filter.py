import numpy as np
import pytest

from nlms_filter import NLMSFilter, cancellation_depth_db


def make_feedback(n, delay=5, gain=0.6, voice=0.02, seed=0):
    rng = np.random.default_rng(seed)
    reference = rng.standard_normal(n) * 0.3
    mic = np.zeros(n)
    mic[delay:] = reference[:-delay] * gain
    mic += rng.standard_normal(n) * voice
    return reference, mic


def test_converges_on_synthetic_feedback():
    reference, mic = make_feedback(8000)
    out = NLMSFilter(num_taps=256, step_size=0.5).process_block(reference, mic)
    assert np.all(np.isfinite(out))
    early = np.mean(out[:200] ** 2)
    late = np.mean(out[-1000:] ** 2)
    assert late < early / 10


def test_running_energy_matches_window_across_wraps():
    f = NLMSFilter(num_taps=16)
    rng = np.random.default_rng(1)
    for x in rng.standard_normal(16 * 7 + 5):
        f.process_sample(float(x), 0.0)
    window = f.buf[f.pos - 16:f.pos]
    assert f.energy == pytest.approx(float(np.dot(window, window)), rel=1e-9)


def test_non_finite_input_does_not_poison_filter():
    reference, mic = make_feedback(4000)
    reference[1000] = np.nan
    mic[2000] = np.inf
    out = NLMSFilter(num_taps=64).process_block(reference, mic)
    assert np.all(np.isfinite(out))
    assert np.all(np.isfinite(out[2001:]))


def test_empty_and_mismatched_blocks():
    f = NLMSFilter(num_taps=32)
    assert len(f.process_block(np.array([]), np.array([]))) == 0
    assert len(f.process_block(np.zeros(10), np.zeros(7))) == 7


def test_reset_clears_state():
    reference, mic = make_feedback(2000)
    f = NLMSFilter(num_taps=32)
    f.process_block(reference, mic)
    f.reset()
    assert not f.taps.any()
    assert f.energy == f.eps


def test_rejects_zero_taps():
    with pytest.raises(ValueError):
        NLMSFilter(num_taps=0)


def test_cancellation_depth():
    mic = np.ones(100)
    assert cancellation_depth_db(mic, mic * 0.1) == pytest.approx(20.0, abs=1e-6)
    assert cancellation_depth_db(mic, mic) == pytest.approx(0.0, abs=1e-6)
    assert cancellation_depth_db(mic, mic * 2) == 0.0  # never negative
    assert cancellation_depth_db(np.array([]), np.array([])) == 0.0
