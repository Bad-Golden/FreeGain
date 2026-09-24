"""
stress_feedback_loop.py -- the real test: a closed acoustic feedback loop.

    singer -> mic -> FreeGain -> console gain G -> PA speaker
                ^                                      |
                +------------- room ------------------+

With FreeGain bypassed the loop howls once G passes the room's "maximum
stable gain" (MSG). The question is how many dB louder the PA can go with
FreeGain active before it howls -- the "added stable gain".

The simulation is sample-accurate and block-based like a real sound card:
the reference FreeGain receives is exactly what's sent to the speaker, and
the loop has the real I/O latency (the processed block is only heard one
block later, plus console/USB delay).

Usage:  python tests/stress_feedback_loop.py [--songs 2]
"""

import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from audio_engine import FEEDBACK_SHIFT_HZ, AudioEngine  # noqa: E402
from freq_shift import FrequencyShifter  # noqa: E402
from roomsim import FS, room, singing, voice  # noqa: E402

BLOCK = 512
LATENCY_BLOCKS = 2        # console + USB round trip on top of the block itself


def run_loop(gain: float, h: np.ndarray, seconds: float, engaged: bool,
             backing: np.ndarray = None, seed: int = 0, freq_shift_hz: float = 0.0,
             source: str = "singing", warmup_s: float = 0.0, warmup_gain: float = 0.0,
             step: float = None, automation=None):
    """
    Return (output, clean singer) for a loop with the given console gain.

    With warmup_s, the first warmup_s seconds run at warmup_gain -- a
    soundcheck at a safe level -- before the gain is pushed to `gain`,
    which is how an engineer actually rides a vocal up.
    """
    seconds = seconds + warmup_s
    n = int(seconds * FS) // BLOCK * BLOCK
    make = singing if source == "singing" else voice
    s = make(seconds + 1, seed=seed, level=0.1)[:n]
    engine = AudioEngine(sample_rate=FS)
    engine.set_engaged(engaged)
    engine.set_gate_threshold_db(-120)   # measure the canceller, not the gate
    if step is not None:
        engine.filter.mu = step
    if freq_shift_hz:
        engine.set_frequency_shift(freq_shift_hz)
    hist = np.zeros(len(h) + BLOCK - 1)   # speaker history for the room convolution
    nfft = 1 << int(np.ceil(np.log2(len(hist))))
    Hf = np.fft.rfft(h, nfft)
    out_queue = [np.zeros(BLOCK)] * LATENCY_BLOCKS
    out = np.zeros(n)
    speaker = np.zeros(n)
    for i in range(0, n, BLOCK):
        # What the PA plays now: FreeGain's output from LATENCY_BLOCKS ago x gain.
        g = warmup_gain if i < warmup_s * FS else gain
        if automation is not None:
            automation(engine, i / FS)     # e.g. ride the Output level slider
        spk = g * out_queue.pop(0)
        if backing is not None:
            spk = spk + backing[i:i + BLOCK]
        spk = np.clip(spk, -4, 4)                      # amplifier rails
        speaker[i:i + BLOCK] = spk
        hist = np.concatenate([hist[BLOCK:], spk])
        # Last BLOCK samples of the linear convolution (overlap-save).
        room_sound = np.fft.irfft(np.fft.rfft(hist, nfft) * Hf, nfft)[len(hist) - BLOCK:len(hist)]
        mic = np.clip(s[i:i + BLOCK] + room_sound, -1, 1)  # mic preamp clips
        indata = np.stack([mic, spk / 4], axis=1).astype(np.float32)  # ref at line level
        outdata = np.zeros((BLOCK, 1), dtype=np.float32)
        engine._callback(indata, outdata, BLOCK, None, None)
        out[i:i + BLOCK] = outdata[:, 0]
        out_queue.append(outdata[:, 0].astype(np.float64))
        if i % FS < BLOCK:
            engine.delay_estimator.estimate_once()
    return out, s


def howled(out: np.ndarray, s: np.ndarray) -> bool:
    """Howling = the output in the last 3 s is far louder than the singer."""
    tail = slice(-3 * FS, None)
    ratio = np.mean(out[tail] ** 2) / (np.mean(s[tail] ** 2) + 1e-20)
    return ratio > 10 ** (10 / 10) or np.mean(np.abs(out[tail]) > 0.99) > 0.01


def voice_quality_db(out: np.ndarray, s: np.ndarray, shift_hz: float) -> float:
    """How clean the singer comes through: singer power vs everything else
    (feedback, ringing, artefacts) over the last 8 s. The output is compared
    with the singer shifted the same way FreeGain shifts its output."""
    ref = s
    if shift_hz:
        sh = FrequencyShifter(shift_hz, FS, BLOCK)
        ref = np.concatenate([sh.process(s[i:i + BLOCK]) for i in range(0, len(s), BLOCK)])
    t = slice(-8 * FS, None)
    return float(10 * np.log10(np.mean(ref[t] ** 2) / (np.mean((out[t] - ref[t]) ** 2) + 1e-20)))


def msg_linear(h: np.ndarray) -> float:
    """Room's maximum stable gain: 1 / peak of |H(f)|."""
    return 1.0 / np.max(np.abs(np.fft.rfft(h, 1 << 16)))


def usable_gain(h, engaged, seconds=12, seed=1, source="singing", min_quality_db=6.0):
    """
    Soundcheck at a safe level (-12 dB) for 10 s, then push the gain up in
    3 dB steps. Returns (highest gain in dB relative to the room's MSG that
    neither howls nor drops voice quality below min_quality_db, voice
    quality at the safe level).
    """
    m = msg_linear(h)
    shift = FEEDBACK_SHIFT_HZ if engaged else 0.0
    best, safe_quality = None, None
    for rel_db in (-12, -3, 0, 3, 6, 9, 12, 15):
        out, s = run_loop(m * 10 ** (rel_db / 20), h, seconds, engaged, seed=seed,
                          source=source, warmup_s=10, warmup_gain=m * 10 ** (-12 / 20))
        q = voice_quality_db(out, s, shift)
        if rel_db == -12:
            safe_quality = q
        if howled(out, s) or q < min_quality_db:
            break
        best = rel_db
    return best, safe_quality


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=2, help="different melodies per room")
    args = ap.parse_args()

    rooms = {"wedge 1.5 m, dry": (4.5, 30), "wedge 3 m, normal room": (9, 60),
             "mains 7 m, hall": (20, 150)}
    print("Closed feedback loop: singer -> mic -> FreeGain -> PA -> room -> mic")
    print("Usable gain = highest level (vs. the room's howl point) with no howling and")
    print("voice quality >= 6 dB, after a 10 s soundcheck at -12 dB.\n")
    print(f"{'room':24} {'song':>4} {'bypassed':>9} {'FreeGain':>9} {'added':>7}   "
          f"{'quality at normal level (bypass / FreeGain)':>44}")
    added_all = []
    for name, (delay_ms, tail_ms) in rooms.items():
        for song in range(1, args.songs + 1):
            h = room(delay_ms, tail_ms, seed=song + 10)
            off, q_off = usable_gain(h, False, seed=song)
            on, q_on = usable_gain(h, True, seed=song)
            fmt = lambda v: "howls" if v is None else f"{v:+d} dB"  # noqa: E731
            added = None if off is None or on is None else on - off
            added_all.append(added)
            print(f"{name:24} {song:>4} {fmt(off):>9} {fmt(on):>9} "
                  f"{'-' if added is None else f'{added:+d} dB':>7}   "
                  f"{q_off:18.1f} dB / {q_on:.1f} dB", flush=True)
    ok = [a for a in added_all if a is not None]
    print(f"\nAdded usable gain: min {min(ok):+d} dB, max {max(ok):+d} dB "
          f"(3 dB steps, so the true figure is up to 3 dB higher)")


if __name__ == "__main__":
    main()
