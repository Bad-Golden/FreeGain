import time

import numpy as np
import pytest

from fdaf_filter import PartitionedFDAF
from roomsim import FS, depth_db, echo, music, room, voice


@pytest.mark.parametrize("delay_ms,tail_ms,taps,min_db", [
    (1, 3, 2048, 60),       # mic right next to the speaker
    (9, 30, 4096, 60),      # wedge 3 m away, dry room
    (9, 60, 4096, 60),      # wedge 3 m away, normal room
    (20, 150, 8192, 30),    # 7 m away, reverberant hall
])
def test_converges_in_realistic_rooms(delay_ms, tail_ms, taps, min_db):
    x = music(8, seed=delay_ms)
    d = echo(x, room(delay_ms, tail_ms, seed=delay_ms))
    f = PartitionedFDAF(taps)
    e = f.process(x, d)
    assert depth_db(d[-FS:], e[-FS:]) > min_db
    assert f.resets == 0


def test_realistic_noise_floor():
    """With 60 dB SNR background noise it should cancel down to the noise."""
    rng = np.random.default_rng(0)
    x = music(8)
    noise = rng.standard_normal(len(x)) * 1e-3
    d = echo(x, room(9, 60)) + noise
    e = PartitionedFDAF(4096).process(x, d)
    residual_echo = e[-FS:] - noise[-FS:]
    assert depth_db(d[-FS:], e[-FS:]) > 30
    assert np.mean(residual_echo ** 2) < 4 * np.mean(noise[-FS:] ** 2)


def test_double_talk_keeps_the_voice_and_the_model():
    x = music(12, seed=7)
    h = room(9, 60, seed=7)
    s = voice(12, seed=8)
    f = PartitionedFDAF(4096)
    # Learn the room with music only, then someone starts singing.
    f.process(x[:6 * FS], echo(x, h)[:6 * FS])
    d = echo(x, h)[6 * FS:] + s[6 * FS:]
    e = f.process(x[6 * FS:], d)
    # The voice comes through: what's left besides the voice is small.
    voice_error_db = depth_db(s[6 * FS:], e - s[6 * FS:])
    assert voice_error_db > 15, voice_error_db
    # The voice itself is not attenuated (level within 1 dB).
    assert abs(10 * np.log10(np.mean(e ** 2) / np.mean(s[6 * FS:] ** 2))) < 1.0
    # And the room model survived: echo-only cancellation still works.
    tail = f.process(x[:2 * FS], echo(x, h)[:2 * FS])
    assert depth_db(echo(x, h)[FS:2 * FS], tail[FS:]) > 20
    assert f.resets == 0


def test_reconverges_after_the_room_changes():
    x = music(12, seed=3)
    d1 = echo(x, room(9, 60, seed=1))
    d2 = echo(x, room(14, 60, seed=2))  # a mic got moved
    d = np.concatenate([d1[:6 * FS], d2[6 * FS:]])
    e = PartitionedFDAF(4096).process(x, d)
    assert depth_db(d[5 * FS:6 * FS], e[5 * FS:6 * FS]) > 30
    assert depth_db(d[-FS:], e[-FS:]) > 30


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_input_is_harmless(bad):
    x = music(4)
    d = echo(x, room(5, 30))
    x2, d2 = x.copy(), d.copy()
    x2[FS:FS + 50] = bad
    d2[2 * FS:2 * FS + 50] = bad
    e = PartitionedFDAF(2048).process(x2, d2)
    assert np.all(np.isfinite(e))
    assert depth_db(d[-FS:], e[-FS:]) > 30


def test_silent_reference_passes_mic_through():
    s = voice(2)
    e = PartitionedFDAF(2048).process(np.zeros(len(s)), s)
    assert np.allclose(e, s)


def test_silence_everywhere():
    e = PartitionedFDAF(2048).process(np.zeros(FS), np.zeros(FS))
    assert not e.any()


def test_full_scale_clipped_and_dc_input():
    x = np.clip(music(3) * 30, -1, 1) + 0.2       # hard clipped, DC offset
    d = np.clip(echo(x, room(5, 30)) * 3, -1, 1)
    f = PartitionedFDAF(2048)
    e = f.process(x, d)
    assert np.all(np.isfinite(e))
    assert np.max(np.abs(e)) < 10
    assert depth_db(d[-FS:], e[-FS:]) > 3


def test_divergence_guard_resets_a_broken_filter():
    x = music(2)
    d = echo(x, room(2, 10))
    f = PartitionedFDAF(2048)
    f.process(x[:FS], d[:FS])
    f.W[:] = 1e3  # simulate a corrupted model
    e = f.process(x[FS:], d[FS:])
    assert f.resets >= 1
    assert np.all(np.isfinite(e))
    assert np.mean(e[-FS // 4:] ** 2) <= 1.5 * np.mean(d[-FS // 4:] ** 2)


def test_buffered_mode_equals_aligned_mode_delayed():
    x = music(1)[:187 * 256]  # a whole number of blocks, so no buffering
    d = echo(x, room(2, 10))
    f_aligned = PartitionedFDAF(1024)
    aligned = f_aligned.process(x, d)
    assert not f_aligned._buffered
    f = PartitionedFDAF(1024)
    rng = np.random.default_rng(1)
    pos, parts = 0, []
    while pos < len(x):
        n = min(int(rng.integers(1, 700)), len(x) - pos)
        parts.append(f.process(x[pos:pos + n], d[pos:pos + n]))
        pos += n
    buffered = np.concatenate(parts)
    assert len(buffered) == len(x)
    assert np.allclose(buffered[256:], aligned[:-256])


def test_empty_and_mismatched_lengths():
    f = PartitionedFDAF(1024)
    assert len(f.process(np.zeros(0), np.zeros(0))) == 0
    assert len(f.process(np.zeros(512), np.zeros(256))) == 256


def test_bad_arguments():
    with pytest.raises(ValueError):
        PartitionedFDAF(2048, block_size=300)
    with pytest.raises(ValueError):
        PartitionedFDAF(0)


def test_long_run_is_stable():
    """Two minutes of changing material: stays finite and bounded."""
    f = PartitionedFDAF(4096)
    h = room(9, 60)
    for minute_part in range(12):
        x = music(10, seed=100 + minute_part) * (0.1 + minute_part % 4)
        d = echo(x, h) + voice(10, seed=200 + minute_part) * (minute_part % 3 == 0)
        e = f.process(x, d)
        assert np.all(np.isfinite(e))
    assert np.all(np.isfinite(f.W))
    assert np.max(np.abs(f.impulse_response())) < 10


@pytest.mark.parametrize("tail_ms,min_speed", [(40, 8), (85, 5), (170, 3), (340, 1.5)])
def test_runs_faster_than_real_time(tail_ms, min_speed):
    x = music(3)
    d = echo(x, room(5, 30))
    # Best of three runs: measures the code, not a stall of a shared CI
    # machine (a single run once came in at 4.6x on a macOS runner).
    best = float("inf")
    for _ in range(3):
        f = PartitionedFDAF(int(tail_ms / 1000 * FS))
        start = time.perf_counter()
        for i in range(0, len(x), 512):
            f.process(x[i:i + 512], d[i:i + 512])
        best = min(best, time.perf_counter() - start)
    speed = 3.0 / best
    assert speed > min_speed, f"{tail_ms} ms tail only {speed:.1f}x real time"


@pytest.mark.parametrize("comeback_gain", [1.0, 10.0])
def test_music_returning_after_a_silent_break(comeback_gain):
    """Band stops, someone speaks, band comes back (possibly louder): the
    learned room must survive, not get scrambled by the first loud blocks."""
    h = room(9, 60, seed=11)
    f = PartitionedFDAF(4096)
    x1 = music(6, seed=12)
    f.process(x1, echo(x1, h))
    speech = voice(4, seed=13)
    f.process(np.zeros(len(speech)), speech)          # PA silent, talking
    x2 = music(3, seed=14) * comeback_gain
    d2 = echo(x2, h)
    e2 = f.process(x2, d2)
    # Within the first half second the old model is already cancelling.
    assert depth_db(d2[FS // 10:FS // 2], e2[FS // 10:FS // 2]) > 25
    assert depth_db(d2[-FS:], e2[-FS:]) > 40


def test_long_echo_tail_keeps_converging():
    """Regression: with the 340 ms tail, double-talk protection used to
    decide 'learned' at ~20 dB and then nearly stop learning. Found by the
    soak test. It must keep improving in echo-only conditions."""
    h = room(12, 80, seed=2)
    f = PartitionedFDAF(16384)
    x = music(8, seed=12) * 0.3
    d = echo(x, h)
    e = f.process(x, d)
    assert depth_db(d[-FS:], e[-FS:]) > 40
    # And after a sung break with the PA silent, it picks straight back up.
    f.process(np.zeros(5 * FS), voice(5, seed=13, level=0.5))
    x2 = music(3, seed=14) * 0.3
    d2 = echo(x2, h)
    e2 = f.process(x2, d2)
    assert depth_db(d2[FS // 2:FS], e2[FS // 2:FS]) > 45
