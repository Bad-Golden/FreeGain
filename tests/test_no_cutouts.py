"""The singer must never cut out. A tip reported cutting out; the stress
test found the gate (-34 dBFS threshold, no floor) chopping ~20% of a vocal
whose loudest phrases sat at -30 dBFS -- normal on a console's USB/Dante
send. Measured here directly: 10 ms frames where the singer is present
(within 30 dB of their peak) but the output is >10 dB quieter than the
voice, for 30 ms or longer."""

import numpy as np
import pytest

from audio_engine import AudioEngine
from roomsim import FS, echo, music, room, singing, voice

F = FS // 100


def _frames(x):
    n = len(x) // F
    return np.sqrt(np.mean(x[:n * F].reshape(n, F) ** 2, axis=1) + 1e-20)


def cutout_ms(v, out, skip_s=4):
    fv, fo = _frames(v), _frames(out)
    bad = (fv > fv.max() * 10 ** (-30 / 20)) & (fo < fv * 10 ** (-10 / 20))
    bad[:skip_s * 100] = False
    total, run = 0, 0
    for b in list(bad) + [False]:
        if b:
            run += 1
        else:
            total += run * 10 if run >= 3 else 0
            run = 0
    return total


def dynamic_vocal(seconds, peak_dbfs, kind, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(seconds * FS) / FS
    swells = 10 ** ((-12 * (1 + np.sin(2 * np.pi * t / 4.0)) - 6 * rng.random()) / 20)
    src = singing(seconds, level=1.0) if kind == "sung" else voice(seconds, level=1.0)
    return src / np.sqrt(np.mean(src ** 2)) * swells * 10 ** (peak_dbfs / 20)


@pytest.mark.parametrize("feedback", [True, False])
@pytest.mark.parametrize("kind", ["sung", "spoken"])
@pytest.mark.parametrize("peak_dbfs", [-18, -30, -40])
def test_quiet_and_dynamic_vocals_never_cut_out(feedback, kind, peak_dbfs):
    T = 14
    v = dynamic_vocal(T, peak_dbfs, kind)
    x = music(T) * 0.3
    mic = v + echo(x, room(12, 80, seed=3)) + 1e-4 * np.random.default_rng(0).standard_normal(len(v))
    engine = AudioEngine(sample_rate=FS, feedback_mode=feedback)
    out = np.zeros(len(v))
    for i in range(0, len(v) - 511, 512):
        od = np.zeros((512, 1), np.float32)
        engine._callback(np.stack([mic[i:i + 512], x[i:i + 512]], 1).astype(np.float32),
                         od, 512, None, None)
        out[i:i + 512] = od[:, 0]
    assert cutout_ms(v, out) == 0
