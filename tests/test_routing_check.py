"""The mic and reference carrying the same signal (a routing mistake) must
not silence the singer: FreeGain passes the vocal through and says so."""

import numpy as np
import pytest

from audio_engine import AudioEngine
from roomsim import FS, depth_db, echo, music, room, singing, voice


def run(engine, mic, ref, block=512):
    out = np.zeros(len(mic))
    flags = []
    for i in range(0, len(mic), block):
        n = min(block, len(mic) - i)
        od = np.zeros((n, 1), np.float32)
        engine._callback(np.stack([mic[i:i + n], ref[i:i + n]], 1).astype(np.float32),
                         od, n, None, None)
        out[i:i + n] = od[:, 0]
        flags.append(engine.same_signal)
    return out, flags


def level_db(x):
    return 10 * np.log10(np.mean(x ** 2) + 1e-30)


@pytest.mark.parametrize("feedback", [True, False])
@pytest.mark.parametrize("source", ["speech", "singing"])
def test_same_channel_passes_the_vocal_through(feedback, source):
    v = voice(8) if source == "speech" else singing(8)
    mic = v + echo(music(8), room(10, 60))
    engine = AudioEngine(sample_rate=FS, feedback_mode=feedback)
    out, flags = run(engine, mic, mic)
    assert engine.same_signal
    assert engine.diagnostics()["mic_and_reference_same_signal"] is True
    last = slice(-3 * FS, None)
    assert abs(level_db(out[last]) - level_db(mic[last])) < 1.0
    # Detected quickly: within a second.
    assert flags.index(True) * 512 / FS < 1.0


def test_same_source_at_a_different_gain_is_detected():
    v = voice(5)
    engine = AudioEngine(sample_rate=FS)
    run(engine, v, 0.5 * v)
    assert engine.same_signal


def test_recovers_when_routing_is_fixed():
    x, v = music(20), voice(20)
    h = room(12, 80)
    mic = echo(x, h) + v
    engine = AudioEngine(sample_rate=FS, feedback_mode=False)
    run(engine, mic[:5 * FS], mic[:5 * FS])
    assert engine.same_signal
    out, _ = run(engine, echo(x, h)[5 * FS:], x[5 * FS:])      # reference fixed, no singer
    assert not engine.same_signal
    assert depth_db(echo(x, h)[-3 * FS:], out[-3 * FS:]) > 20


@pytest.mark.parametrize("feedback", [True, False])
def test_normal_show_never_triggers(feedback):
    x, v = music(15), voice(15)
    mic = echo(x, room(12, 80, seed=2)) + v
    engine = AudioEngine(sample_rate=FS, feedback_mode=feedback)
    _, flags = run(engine, mic, x)
    assert not any(flags)


def test_test_tones_through_the_room_never_trigger():
    t = np.arange(2 * FS) / FS
    for k, f in enumerate(np.geomspace(60, 8000, 60)):
        x = 0.3 * np.sin(2 * np.pi * f * t)
        engine = AudioEngine(sample_rate=FS)
        _, flags = run(engine, echo(x, room(3 + (k % 7) * 2, 40, seed=k)), x)
        assert not any(flags), f"{f:.0f} Hz tone"


def test_singer_in_the_mains_with_no_delay_does_not_trigger():
    # A digital loop with the raw vocal in the reference, plus the band.
    v = singing(8)
    ref = 0.8 * v + music(8, seed=4)
    engine = AudioEngine(sample_rate=FS)
    _, flags = run(engine, v, ref)
    assert not any(flags)
