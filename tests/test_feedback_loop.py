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
