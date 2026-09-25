"""How quickly FreeGain locks onto a room -- kept fast without learning the
singer (closed-loop voice quality is guarded in test_feedback_loop.py)."""

import numpy as np
import pytest

from audio_engine import AudioEngine
from roomsim import FS, depth_db, echo, music, room


def per_second_depth(engine, d, x):
    out = np.zeros(len(d))
    for i in range(0, len(d) - 511, 512):
        od = np.zeros((512, 1), np.float32)
        engine._callback(np.stack([d[i:i + 512], x[i:i + 512]], 1).astype(np.float32),
                         od, 512, None, None)
        out[i:i + 512] = od[:, 0]
        if i % FS < 512:
            engine.delay_estimator.estimate_once()
    return [depth_db(d[k * FS:(k + 1) * FS], out[k * FS:(k + 1) * FS])
            for k in range(len(d) // FS)]


@pytest.mark.parametrize("feedback", [True, False])
def test_locks_on_within_seconds(feedback):
    x = music(6, seed=3)
    d = echo(x, room(12, 80, seed=4))
    engine = AudioEngine(sample_rate=FS, feedback_mode=feedback)
    engine.set_gate_threshold_db(-120)
    engine.set_auto_delay(False)
    engine.bulk_delay = int(0.007 * FS)
    depths = per_second_depth(engine, d, x)
    # Before the fast start, feedback mode managed ~8 dB after 2 s.
    assert depths[1] > 15 and depths[2] > 25, depths


def test_finding_the_delay_keeps_what_was_learned():
    """At startup the filter learns at zero delay, then the delay finder
    reports the real one. The learned room is shifted, not thrown away:
    no drop in cancellation when that happens."""
    x = music(8, seed=1)
    d = echo(x, room(12, 60, seed=2))
    engine = AudioEngine(sample_rate=FS)
    engine.set_gate_threshold_db(-120)
    depths = per_second_depth(engine, d, x)
    assert len(engine.delay_changes) == 1
    assert all(b > a - 1 for a, b in zip(depths[1:], depths[2:])), depths
    assert depths[-1] > 30, depths
