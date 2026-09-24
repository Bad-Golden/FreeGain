import numpy as np

from pem_filter import PEMFDAF, _levinson
from roomsim import FS, depth_db, echo, music, room, singing


def test_levinson_recovers_an_ar_process():
    rng = np.random.default_rng(0)
    true = np.array([1.0, -1.2, 0.6])
    x = np.zeros(50000)
    w = rng.standard_normal(len(x))
    for n in range(2, len(x)):
        x[n] = w[n] - true[1] * x[n - 1] - true[2] * x[n - 2]
    r = np.array([np.dot(x[: len(x) - k], x[k:]) for k in range(3)])
    assert np.allclose(_levinson(r, 2), true, atol=0.02)


def test_whitening_finds_the_pitch():
    f = PEMFDAF(2048, sample_rate=FS)
    s = singing(2, seed=3)
    f._e_hist[:] = s[-len(f._e_hist):]
    f._whitening_filter()
    period_ms = 1000 * f.pitch_lag / FS
    assert f.pitch_gain > 0.2 and 2.5 <= period_ms <= 20


def test_whitened_output_is_flatter():
    f = PEMFDAF(2048, sample_rate=FS)
    # A real mic always adds some breath/room noise (here ~40 dB down).
    s = singing(2, seed=4) + np.random.default_rng(4).standard_normal(2 * FS) * 1e-3
    f._e_hist[:] = s[-len(f._e_hist):]
    a, lag, gain = f._whitening_filter()
    w = f._whiten(s, 8192, a, lag, gain)
    band = slice(int(100 / FS * 8192), int(8000 / FS * 8192))   # voice band
    raw = (np.abs(np.fft.rfft(s[-8192:])) ** 2)[band]
    white = (np.abs(np.fft.rfft(w)) ** 2)[band]
    flatness = lambda p: np.exp(np.mean(np.log(p + 1e-20))) / np.mean(p)  # noqa: E731
    assert flatness(white) > 5 * flatness(raw)


def test_open_loop_convergence():
    x = music(8, seed=2)
    d = echo(x, room(5, 40, seed=2))
    e = PEMFDAF(4096, sample_rate=FS).process(x, d)
    assert depth_db(d[-FS:], e[-FS:]) > 25


def test_output_never_louder_than_the_mic():
    """Safety net: whatever the filter does, blocks never exceed the mic."""
    rng = np.random.default_rng(3)
    f = PEMFDAF(2048, sample_rate=FS)
    x = music(4)[:256 * 700]          # whole blocks, so output lines up with input
    d = echo(x, room(4, 20)) + rng.standard_normal(len(x)) * 0.05
    cut = 256 * 180
    f.process(x[:cut], d[:cut])
    f.W *= -30          # sabotage the model
    out = f.process(x[cut:], d[cut:])
    assert not f._buffered and f.bypassed_blocks > 0
    mic = d[cut:]
    for i in range(0, len(out), 256):
        blk = slice(i, i + 256)
        # The join smoothing (a 32-sample ramp that removes the click where
        # the mic takes over) may add a sliver on the first bypassed block;
        # the sabotaged model on its own put out ~260x the mic's energy.
        assert np.sum(out[blk] ** 2) <= np.sum(mic[blk] ** 2) * 1.25 + 1e-3


def test_silence_after_music_keeps_the_model():
    """Regression (soak test): when the PA stops and only background noise is
    left, the leftover prediction can be a hair louder than the near-silent
    mic. That must not trigger the divergence reset and wipe the model."""
    from fdaf_filter import PartitionedFDAF
    rng = np.random.default_rng(7)
    h = room(10, 80, seed=5)
    for f in (PEMFDAF(16384, step_size=0.1, sample_rate=FS), PartitionedFDAF(16384)):
        x = music(12, seed=1) * 0.3
        d = echo(x, h)
        before = depth_db(d[-FS:], f.process(x, d)[-FS:])
        silence = np.concatenate([x[-FS // 2:], np.zeros(3 * FS)])   # music stops...
        tail = echo(silence, h)[FS // 2:] + rng.standard_normal(3 * FS) * 1e-4
        f.process(np.zeros(3 * FS), tail)                             # ...room goes quiet
        assert f.resets == 0
        x2 = music(2, seed=3) * 0.1
        d2 = echo(x2, h)
        e2 = f.process(x2, d2)
        # Nothing learned is lost over the break (feedback mode learns a
        # 340 ms tail slowly, so compare with where it was, not a fixed bar).
        assert depth_db(d2[FS // 2:], e2[FS // 2:]) > before - 3
