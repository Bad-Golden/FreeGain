"""FreeGain at 44.1, 48, 88.2 and 96 kHz (earlier testing was all at 48 kHz)."""

import numpy as np
import pytest

import audio_engine
import roomsim
from audio_engine import AudioEngine, filter_block_for
from pem_filter import PEMFDAF


def run(engine, d, x):
    B = engine.block_size
    out = np.zeros(len(x))
    for i in range(0, len(x) - B + 1, B):
        indata = np.stack([d[i:i + B], x[i:i + B]], 1).astype(np.float32)
        outdata = np.zeros((B, 1), dtype=np.float32)
        engine._callback(indata, outdata, B, None, None)
        out[i:i + B] = outdata[:, 0]
        if i % int(engine.sample_rate) < B:
            engine.delay_estimator.estimate_once()
    return out


@pytest.mark.parametrize("fs", [44100, 48000, 88200, 96000])
@pytest.mark.parametrize("feedback", [False, True])
def test_every_rate_finds_the_delay_and_cancels(fs, feedback):
    x = roomsim.music(8, seed=1, fs=fs)
    d = roomsim.echo(x, roomsim.room(12, 60, seed=2, fs=fs))
    engine = AudioEngine(sample_rate=fs, feedback_mode=feedback)
    engine.set_gate_threshold_db(-120)
    out = run(engine, d, x)
    assert abs(engine.delay_estimator.delay_ms - 12) < 1.0
    B = engine.block_size
    # Feedback mode learns deliberately slowly; 8 s is enough to prove it works.
    assert roomsim.depth_db(d[-2 * fs:-B], out[-2 * fs:-B]) > (15 if feedback else 40)


def test_block_sizes_keep_the_same_duration():
    assert AudioEngine(sample_rate=48000).block_size == 512
    assert AudioEngine(sample_rate=44100).block_size == 512
    assert AudioEngine(sample_rate=96000).block_size == 1024
    assert filter_block_for(48000) == 256 and filter_block_for(96000) == 512
    engine = AudioEngine(sample_rate=48000)
    engine.set_sample_rate(96000)
    assert engine.block_size == 1024 and engine.filter.N == 512


def test_voice_model_window():
    """Regression: 2048 samples at 48 kHz (4096 made the closed loop worse)."""
    assert PEMFDAF(4096, sample_rate=48000).history == 2048
    assert PEMFDAF(4096, sample_rate=44100).history == 2048
    assert PEMFDAF(8192, sample_rate=96000).history == 4096


def test_nothing_heavy_is_built_on_the_audio_thread(monkeypatch):
    """Regression: creating the frequency shifter took ~20 ms (two audio
    blocks) and used to happen inside the audio callback."""
    engine = AudioEngine(sample_rate=48000, feedback_mode=False)
    built_in_callback = []
    real = audio_engine.FrequencyShifter
    in_callback = {"now": False}

    def spy(*args, **kwargs):
        built_in_callback.append(in_callback["now"])
        return real(*args, **kwargs)

    monkeypatch.setattr(audio_engine, "FrequencyShifter", spy)
    original = engine._callback

    def wrapped(*args):
        in_callback["now"] = True
        try:
            return original(*args)
        finally:
            in_callback["now"] = False

    engine.set_feedback_mode(True)
    for _ in range(3):
        wrapped(np.zeros((512, 2), np.float32), np.zeros((512, 1), np.float32), 512, None, None)
    engine.set_feedback_mode(False)
    engine.set_frequency_shift(7.0)
    wrapped(np.zeros((512, 2), np.float32), np.zeros((512, 1), np.float32), 512, None, None)
    assert built_in_callback and not any(built_in_callback)
    assert engine.shifter is not None and engine.shift_hz == 7.0
