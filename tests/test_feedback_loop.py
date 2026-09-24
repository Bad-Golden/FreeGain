"""Closed-loop regression tests (see stress_feedback_loop.py for the full run)."""

from roomsim import room
from stress_feedback_loop import (FEEDBACK_SHIFT_HZ, howled, msg_linear, run_loop,
                                  voice_quality_db)


def _run(rel_db, engaged):
    h = room(9, 60, seed=12)
    m = msg_linear(h)
    out, s = run_loop(m * 10 ** (rel_db / 20), h, 12, engaged, seed=2,
                      warmup_s=10, warmup_gain=m * 10 ** (-12 / 20))
    return out, s


def test_bypass_howls_above_the_rooms_limit():
    out, s = _run(+6, engaged=False)
    assert howled(out, s)


def test_freegain_holds_six_db_above_the_limit_with_a_clean_voice():
    out, s = _run(+6, engaged=True)
    assert not howled(out, s)
    assert voice_quality_db(out, s, FEEDBACK_SHIFT_HZ) > 6


def test_freegain_does_not_harm_the_voice_at_normal_level():
    """At a safe level FreeGain must be at least as clean as bypass --
    before pre-whitening it partly cancelled pitched singing (3 dB)."""
    out, s = _run(-12, engaged=False)
    bypass_q = voice_quality_db(out, s, 0.0)
    out, s = _run(-12, engaged=True)
    assert voice_quality_db(out, s, FEEDBACK_SHIFT_HZ) > bypass_q - 2


def _howl_level_while_riding(engaged):
    """Ride the Output level slider (inside the loop) up at 1.5 dB/s after a
    10 s soundcheck; return the level at which the loop starts to howl."""
    import numpy as np
    from stress_feedback_loop import FS

    def ride(engine, t):
        engine.set_output_gain_db(-12 + max(0.0, t - 10) * 1.5)

    h = room(9, 60, seed=12)
    out, s = run_loop(msg_linear(h), h, 32, engaged, seed=2, automation=ride)
    for k in range(10, 30):
        sl = slice(k * FS, (k + 1) * FS)
        if np.mean(out[sl] ** 2) > 10 * np.mean(s[sl] ** 2) + 1e-12:
            return -12 + (k - 10) * 1.5
    return 999.0


def test_riding_the_output_level_up():
    """Output level sits inside the feedback loop: pushing it up is how
    howling starts. FreeGain must allow clearly more before it does."""
    assert _howl_level_while_riding(True) >= _howl_level_while_riding(False) + 5
