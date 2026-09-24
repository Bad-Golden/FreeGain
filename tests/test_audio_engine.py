import threading

import numpy as np

from audio_engine import AudioEngine
from roomsim import FS, depth_db, echo, music, room


def run_block(engine, indata):
    outdata = np.zeros((len(indata), 1), dtype=np.float32)
    engine._callback(indata.astype(np.float32), outdata, len(indata), None, None)
    return outdata


def run_signal(engine, mic, ref, block=512, extra_channels=0):
    out = []
    for i in range(0, len(mic) - block + 1, block):
        indata = np.zeros((block, 2 + extra_channels))
        indata[:, engine.mic_channel] = mic[i:i + block]
        indata[:, engine.reference_channel] = ref[i:i + block]
        out.append(run_block(engine, indata)[:, 0])
    return np.concatenate(out)


def test_selected_channels_are_used():
    engine = AudioEngine(sample_rate=48000)
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
    engine = AudioEngine(sample_rate=48000)
    rng = np.random.default_rng(0)
    run_block(engine, rng.standard_normal((512, 2)) * 0.1)
    assert engine.filter.W.any()
    engine.trigger_relearn()
    assert engine.filter.W.any()  # not touched from the UI thread
    run_block(engine, np.zeros((512, 2)))
    assert not engine.filter.W.any()


def test_output_is_clipped_nan_safe_and_status_counted():
    engine = AudioEngine(sample_rate=48000)
    engine.set_engaged(False)
    outdata = np.zeros((4, 1), dtype=np.float32)
    indata = np.array([[3.0, 0.0], [np.nan, np.inf], [-np.inf, 1.0], [0.5, 0.5]], dtype=np.float32)
    engine._callback(indata, outdata, 4, None, "input overflow")
    assert np.all(np.isfinite(outdata)) and np.all(np.abs(outdata) <= 1.0)
    assert engine.xrun_count == 1


def test_cancels_a_realistic_room_with_auto_delay():
    """Speaker 3 m away (9 ms) plus 60 ms of reverb: the old 5 ms filter got 0 dB."""
    x = music(8)
    d = echo(x, room(delay_ms=9, tail_ms=60))
    engine = AudioEngine(sample_rate=FS, feedback_mode=False)
    half = len(x) // 2
    run_signal(engine, d[:half], x[:half])
    engine.delay_estimator.estimate_once()
    engine.delay_estimator.estimate_once()
    assert abs(engine.delay_estimator.delay_ms - 9) < 1.0
    out = run_signal(engine, d[half:], x[half:])
    assert abs(engine.bulk_delay_ms - 4) < 1.0  # 9 ms minus the 5 ms safety margin
    assert depth_db(d[-FS:], out[-FS:]) > 25


def test_long_speaker_delay_is_compensated():
    """A 120 ms delay (delay tower / long USB routing) is beyond the filter's
    own 85 ms window; the bulk delay has to bring it into range."""
    x = music(8, seed=4)
    d = echo(x, room(delay_ms=120, tail_ms=40, seed=4))
    engine = AudioEngine(sample_rate=FS, feedback_mode=False)
    half = len(x) // 2
    run_signal(engine, d[:half], x[:half])
    engine.delay_estimator.estimate_once()
    engine.delay_estimator.estimate_once()
    out = run_signal(engine, d[half:], x[half:])
    assert depth_db(d[-FS:], out[-FS:]) > 25

    manual = AudioEngine(sample_rate=FS, feedback_mode=False)
    manual.set_auto_delay(False)
    out = run_signal(manual, d, x)
    assert depth_db(d[-FS:], out[-FS:]) < 3  # without it: nothing


def test_tail_change_takes_effect_on_audio_thread():
    engine = AudioEngine(sample_rate=FS, tail_ms=40)
    assert engine.filter.filter_length == 2048
    engine.set_tail_ms(170)
    assert engine.filter.filter_length == 2048
    run_block(engine, np.zeros((512, 2)))
    assert engine.filter.filter_length >= 8160


def test_irregular_block_sizes():
    x = music(3, seed=2)
    d = echo(x, room(2, 20, seed=2))
    engine = AudioEngine(sample_rate=FS)
    rng = np.random.default_rng(5)
    pos, outs = 0, []
    while pos < len(x):
        n = int(rng.choice([1, 37, 256, 441, 512, 1000, 2048]))
        n = min(n, len(x) - pos)
        indata = np.stack([d[pos:pos + n], x[pos:pos + n]], axis=1)
        outs.append(run_block(engine, indata)[:, 0])
        pos += n
    out = np.concatenate(outs)
    assert len(out) == len(x) and np.all(np.isfinite(out))
    assert depth_db(d[-FS // 2:], out[-FS // 2:]) > 15


def test_diagnostics_snapshot_is_json_ready():
    import json
    engine = AudioEngine(sample_rate=FS)
    run_signal(engine, music(1), music(1, seed=3))
    info = engine.diagnostics()
    json.dumps(info)
    assert info["filter_taps"] >= 4000 and info["blocks_processed"] > 0
    assert 0 <= info["cpu_load_percent"]


def test_ui_thread_changes_while_audio_runs():
    """Hammer relearn / tail / gate / bypass from another thread during processing."""
    engine = AudioEngine(sample_rate=FS)
    x, stop, errors = music(4), threading.Event(), []

    def poke():
        i = 0
        while not stop.is_set():
            try:
                engine.trigger_relearn()
                engine.set_tail_ms([40, 85, 170][i % 3])
                engine.set_gate_threshold_db(-60 + i % 50)
                engine.set_gate_timing(1 + i % 20, 50 + i % 500)
                engine.set_engaged(i % 7 != 0)
                engine.set_mic_gain_db(-24 + i % 48)
                engine.set_output_gain_db(-40 + i % 52)
                i += 1
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

    t = threading.Thread(target=poke)
    t.start()
    try:
        out = run_signal(engine, echo(x, room(5, 30)), x)
    finally:
        stop.set()
        t.join()
    assert not errors
    assert np.all(np.isfinite(out)) and np.max(np.abs(out)) <= 1.0


def test_feedback_mode_is_default_and_toggles_without_losing_learning():
    from fdaf_filter import PartitionedFDAF
    from pem_filter import PEMFDAF
    engine = AudioEngine(sample_rate=FS)
    assert engine.feedback_mode and isinstance(engine.filter, PEMFDAF)
    run_block(engine, np.zeros((512, 2)))
    assert engine.shifter is not None and engine.shift_hz == 5.0
    x = music(4)
    run_signal(engine, echo(x, room(3, 20)), x)
    learned = engine.filter.W.copy()
    engine.set_feedback_mode(False)
    run_block(engine, np.zeros((512, 2)))
    assert type(engine.filter) is PartitionedFDAF and engine.shifter is None
    assert np.allclose(engine.filter.W, learned)
    engine.set_feedback_mode(True)
    run_block(engine, np.zeros((512, 2)))
    assert isinstance(engine.filter, PEMFDAF) and engine.shifter is not None


def test_feedback_mode_still_cancels_spill():
    """Feedback mode learns more carefully, but plain echo still goes."""
    x = music(10, seed=6)
    d = echo(x, room(3, 30, seed=6))
    engine = AudioEngine(sample_rate=FS)
    engine.set_gate_threshold_db(-120)
    out = run_signal(engine, d, x)
    assert depth_db(d[-FS:], out[-FS:]) > 20
