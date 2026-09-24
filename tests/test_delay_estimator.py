import numpy as np
import pytest

from delay_estimator import WINDOW, DelayEstimator, gcc_phat
from roomsim import FS, echo, music, room, voice


def feed(est, x, d, block=512):
    for i in range(0, len(x), block):
        est.push(x[i:i + block], d[i:i + block])


@pytest.mark.parametrize("delay_ms", [0, 3, 9.5, 20, 60, 150, 400])
@pytest.mark.parametrize("noise,talk", [(0.0, False), (0.01, False), (0.01, True)])
def test_finds_the_delay(delay_ms, noise, talk):
    rng = np.random.default_rng(int(delay_ms * 10))
    x = music(6, seed=int(delay_ms))
    d = echo(x, room(delay_ms, 80, seed=int(delay_ms))) + rng.standard_normal(len(x)) * noise
    if talk:
        d += voice(6)
    est = DelayEstimator(FS)
    feed(est, x, d)
    est.estimate_once()
    assert est.estimate_once() is not None
    assert abs(est.delay_ms - delay_ms) < 1.0


def test_needs_two_agreeing_estimates():
    x = music(6)
    d = echo(x, room(20, 50))
    est = DelayEstimator(FS)
    feed(est, x, d)
    assert est.estimate_once() is None
    assert est.estimate_once() is not None


def test_silence_and_unrelated_audio_give_no_estimate():
    est = DelayEstimator(FS)
    feed(est, np.zeros(4 * FS), np.zeros(4 * FS))
    est.estimate_once()
    assert est.estimate_once() is None

    est = DelayEstimator(FS)
    feed(est, music(4, seed=1), music(4, seed=2))  # mic hears something else
    est.estimate_once()
    assert est.estimate_once() is None


def test_ignores_the_vocal_inside_a_closed_loop():
    """In a feedback loop the reference contains the vocal *later* than the
    mic. Only the speaker->mic path (mic later) may be reported."""
    s = voice(6, level=0.5)
    x = music(6) * 0.3 + np.concatenate([np.zeros(240), s[:-240]])  # vocal 5 ms later in ref
    d = s + echo(x, room(12, 40))
    est = DelayEstimator(FS)
    feed(est, x, d)
    est.estimate_once()
    r = est.estimate_once()
    assert r is not None and abs(est.delay_ms - 12) < 1.0


def test_ring_buffer_wraps_correctly():
    x = music(10)
    d = echo(x, room(30, 40))
    est = DelayEstimator(FS)
    feed(est, x, d, block=700)          # 10 s through a 2.7 s ring, odd block size
    ref = np.roll(est._ref, -est._pos)
    assert np.allclose(ref, x[-WINDOW:])
    est.estimate_once()
    est.estimate_once()
    assert abs(est.delay_ms - 30) < 1.0


def test_changes_are_tracked():
    x = music(12, seed=9)
    est = DelayEstimator(FS)
    feed(est, x[:6 * FS], echo(x, room(10, 40))[:6 * FS])
    est.estimate_once(); est.estimate_once()
    assert abs(est.delay_ms - 10) < 1
    feed(est, x[6 * FS:], echo(x, room(40, 40))[6 * FS:])
    est.estimate_once(); est.estimate_once()
    assert abs(est.delay_ms - 40) < 1


def test_background_thread_runs_and_stops():
    x = music(4)
    d = echo(x, room(15, 30))
    est = DelayEstimator(FS, interval_s=0.05)
    feed(est, x, d)
    est.start()
    import time
    deadline = time.monotonic() + 5
    while est.delay_samples is None and time.monotonic() < deadline:
        time.sleep(0.02)
    est.stop()
    assert est.delay_samples is not None and abs(est.delay_ms - 15) < 1


def test_gcc_phat_on_pure_shift():
    x = np.random.default_rng(0).standard_normal(FS)
    d = np.concatenate([np.zeros(480), x[:-480]])
    lag, ratio = gcc_phat(x, d, 2000)
    assert lag == 480 and ratio > 100
