import numpy as np

from audio_engine import AudioEngine


def run_block(engine, indata):
    outdata = np.zeros((len(indata), 1), dtype=np.float32)
    engine._callback(indata.astype(np.float32), outdata, len(indata), None, None)
    return outdata


def test_selected_channels_are_used():
    engine = AudioEngine(sample_rate=48000, num_taps=16)
    engine.configure(mic_channel=3, reference_channel=5)
    indata = np.zeros((256, 6))
    indata[:, 3] = 0.5  # mic
    indata[:, 5] = 0.25  # reference
    engine.set_engaged(False)
    out = run_block(engine, indata)
    assert np.allclose(out[:, 0], 0.5)
    assert engine.last_input_peak == 0.5
    assert engine.last_reference_peak == 0.25


def test_zero_length_block_is_ignored():
    engine = AudioEngine(sample_rate=48000)
    out = np.zeros((0, 1), dtype=np.float32)
    engine._callback(np.zeros((0, 2), dtype=np.float32), out, 0, None, None)


def test_relearn_resets_on_next_block():
    engine = AudioEngine(sample_rate=48000, num_taps=16)
    rng = np.random.default_rng(0)
    indata = rng.standard_normal((512, 2)) * 0.1
    run_block(engine, indata)
    assert engine.filter.taps.any()
    engine.trigger_relearn()
    assert engine.filter.taps.any()  # not touched from the UI thread
    run_block(engine, np.zeros((1, 2)))
    assert not engine.filter.taps.any()


def test_output_is_clipped_and_status_counted():
    engine = AudioEngine(sample_rate=48000, num_taps=16)
    engine.set_engaged(False)
    outdata = np.zeros((4, 1), dtype=np.float32)
    indata = np.full((4, 2), 3.0, dtype=np.float32)
    engine._callback(indata, outdata, 4, None, "input overflow")
    assert np.all(outdata <= 1.0)
    assert engine.xrun_count == 1
