import numpy as np
import pytest

from freq_shift import FrequencyShifter

FS = 48000


def shifted(x, hz, block=512):
    sh = FrequencyShifter(hz, FS, block)
    return np.concatenate([sh.process(x[i:i + block]) for i in range(0, len(x), block)])


@pytest.mark.parametrize("tone", [40.0, 110.0, 440.0, 3000.0, 12000.0])
@pytest.mark.parametrize("hz", [2.0, 5.0, 10.0])
def test_tone_moves_up_by_exactly_the_shift(tone, hz):
    t = np.arange(3 * FS) / FS
    y = shifted(np.sin(2 * np.pi * tone * t), hz)[FS:]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / FS)
    assert abs(freqs[np.argmax(spec)] - (tone + hz)) < 0.6
    image = spec[np.argmin(abs(freqs - (tone - hz)))]
    wanted = spec[np.argmin(abs(freqs - (tone + hz)))]
    assert 20 * np.log10(image / wanted) < -40         # mirror image suppressed
    assert abs(20 * np.log10(np.std(y) / np.std(np.sin(2 * np.pi * tone * t[FS:])))) < 0.2


def test_level_and_silence():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(2 * FS) * 0.1
    y = shifted(x, 5.0)
    assert abs(10 * np.log10(np.mean(y[FS:] ** 2) / np.mean(x[FS:] ** 2))) < 0.5
    assert not shifted(np.zeros(FS), 5.0).any()


def test_block_size_does_not_matter():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(FS)
    a = shifted(x, 5.0, block=512)
    sh = FrequencyShifter(5.0, FS, 512)
    pos, parts = 0, []
    for n in (37, 512, 1, 2000, 300) * 40:
        if pos >= len(x):
            break
        parts.append(sh.process(x[pos:pos + n]))
        pos += n
    b = np.concatenate(parts)
    assert np.allclose(a[:len(b)], b[:len(a)])


def test_zero_shift_is_allpass_and_empty_block():
    sh = FrequencyShifter(0.0, FS)
    assert len(sh.process(np.zeros(0))) == 0
    x = np.random.default_rng(2).standard_normal(FS)
    y = np.concatenate([sh.process(x[i:i + 512]) for i in range(0, FS, 512)])
    assert abs(np.std(y) / np.std(x) - 1) < 0.05
