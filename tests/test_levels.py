import numpy as np
import pytest

from audio_engine import AudioEngine
from levels import LIMIT_THRESHOLD, GainRamp, db_to_gain, soft_limit
from roomsim import FS, depth_db, echo, music, room


def run(engine, mic, ref, block=512):
    out = []
    for i in range(0, len(mic) - block + 1, block):
        indata = np.stack([mic[i:i + block], ref[i:i + block]], axis=1).astype(np.float32)
        outdata = np.zeros((block, 1), dtype=np.float32)
        engine._callback(indata, outdata, block, None, None)
        out.append(outdata[:, 0].astype(np.float64))
    return np.concatenate(out)


def test_gain_ramp_reaches_target_without_jumps():
    g = GainRamp(0.0)
    g.set_db(-6.0)
    block = np.ones(512)
    first = g.apply(block)
    assert first[-1] == pytest.approx(db_to_gain(-6.0))
    assert np.max(np.abs(np.diff(first))) < 0.01          # smooth, no step
    assert np.allclose(g.apply(block), db_to_gain(-6.0))  # then steady


def test_soft_limiter():
    x = np.linspace(-3, 3, 10001)
    y, touched = soft_limit(x)
    assert touched and np.max(np.abs(y)) <= 1.0          # never beyond full scale
    assert np.all(np.diff(y) >= 0)                          # still monotonic
    quiet = np.linspace(-0.5, 0.5, 101)
    y, touched = soft_limit(quiet)
    assert not touched and np.array_equal(y, quiet)         # untouched below -1 dBFS
    assert soft_limit(np.array([LIMIT_THRESHOLD]))[0][0] == pytest.approx(LIMIT_THRESHOLD)


@pytest.mark.parametrize("engaged", [True, False])
def test_mic_and_output_gain_set_the_level(engaged):
    rng = np.random.default_rng(0)
    mic = rng.standard_normal(FS) * 0.05
    engine = AudioEngine(sample_rate=FS, feedback_mode=False)
    engine.set_gate_threshold_db(-120)
    engine.set_engaged(engaged)
    base = run(engine, mic, np.zeros(FS))
    engine2 = AudioEngine(sample_rate=FS, feedback_mode=False)
    engine2.set_gate_threshold_db(-120)
    engine2.set_engaged(engaged)
    engine2.set_mic_gain_db(6.0)
    engine2.set_output_gain_db(-12.0)
    louder = run(engine2, mic, np.zeros(FS))
    change = 20 * np.log10(np.std(louder[FS // 4:]) / np.std(base[FS // 4:]))
    assert change == pytest.approx(-6.0, abs=0.1)


def test_output_is_limited_when_pushed():
    rng = np.random.default_rng(1)
    mic = rng.standard_normal(FS) * 0.3
    engine = AudioEngine(sample_rate=FS, feedback_mode=False)
    engine.set_gate_threshold_db(-120)
    engine.set_output_gain_db(12.0)
    out = run(engine, mic, np.zeros(FS))
    assert np.max(np.abs(out)) <= 1.0 and engine.limited_blocks > 0


def test_changing_mic_gain_does_not_disturb_cancellation():
    """Mic gain sits after the canceller, so it never forces a relearn."""
    x = music(8, seed=3)
    d = echo(x, room(4, 30, seed=3))
    engine = AudioEngine(sample_rate=FS, feedback_mode=False)
    engine.set_gate_threshold_db(-120)
    run(engine, d[:6 * FS], x[:6 * FS])
    engine.set_mic_gain_db(12.0)
    out = run(engine, d[6 * FS:], x[6 * FS:])
    # 12 dB of make-up gain: depth relative to the boosted mic stays high.
    assert depth_db(d[-FS:] * db_to_gain(12.0), out[-FS:]) > 30


def test_input_meter_follows_mic_gain():
    engine = AudioEngine(sample_rate=FS)
    engine.set_mic_gain_db(6.0)
    mic = np.full(1024, 0.1)
    run(engine, mic, np.zeros(1024))
    assert engine.last_input_peak == pytest.approx(0.1 * db_to_gain(6.0), rel=0.01)
