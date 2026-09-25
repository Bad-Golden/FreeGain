"""
stress_soak.py -- simulate a long gig through the real audio engine.

Runs the same AudioEngine._callback the sound card calls, with a scripted
"show" on top of a simulated room:

  * music through the PA the whole time, changing level every few seconds
  * a singer who comes and goes (double-talk), sometimes louder than the PA
  * the mic gets moved (room change) twice
  * a delay tower / long USB routing (speaker delay jumps from 12 to 70 ms)
  * silence gaps, clipping bursts, NaN/Inf glitches from a bad driver
  * irregular block sizes, as some drivers deliver
  * the operator poking controls: relearn and echo tail changes, and gate
    settings from the UI thread concurrently with the audio thread
  * the automatic delay finder running on its own background thread

It fails (exit code 1) if the output ever goes non-finite or clips wildly,
if cancellation falls below target once settled, if the singer's voice gets
damaged, or if processing is too slow for real time.

Usage:  python tests/stress_soak.py [--minutes 10] [--seed 0] [--mode feedback|spill]
"""

import argparse
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from audio_engine import AudioEngine  # noqa: E402
from roomsim import FS, room  # noqa: E402

SEG = 5  # seconds per scripted segment


def make_show(minutes: float, seed: int):
    """Yield (segment_index, reference, mic, clean_voice, echo_only_flag, events)."""
    rng = np.random.default_rng(seed)
    rooms = [room(12, 80, seed=seed + 1), room(15, 90, seed=seed + 2),
             room(70, 60, seed=seed + 3)]
    room_idx = 0
    tail_x = np.zeros(0)
    segments = int(minutes * 60 / SEG)
    for k in range(segments):
        events = []
        if k == segments // 3:
            room_idx = 1
            events.append("mic moved")
        if k == 2 * segments // 3:
            room_idx = 2
            events.append("speaker delay now 70 ms")
        n = SEG * FS
        level = float(rng.choice([0.03, 0.1, 0.3]))
        x = np.convolve(rng.standard_normal(n), [1, 0.9, 0.5, 0.2])[:n] * level
        silent = rng.random() < 0.08
        if silent:
            x[:] = 0
            events.append("PA silent")
        h = rooms[room_idx]
        full = np.concatenate([tail_x, x])
        echo = np.convolve(full, h)[len(tail_x):len(tail_x) + n]
        tail_x = x[-len(h):]
        singing = rng.random() < 0.4
        voice = np.zeros(n)
        if singing:
            vl = float(rng.choice([0.05, 0.2, 0.5]))
            carrier = np.convolve(rng.standard_normal(n), np.ones(6) / 6)[:n]
            env = np.clip(np.sin(np.arange(n) / FS * 2 * np.pi * rng.uniform(2, 4)), 0, None) ** 0.5
            voice = vl * carrier * env
            events.append(f"singing (level {vl})")
        mic = echo + voice + rng.standard_normal(n) * 1e-4
        if rng.random() < 0.1:
            i = int(rng.integers(0, n - 2000))
            mic[i:i + 2000] = np.clip(mic[i:i + 2000] * 50, -1, 1)
            events.append("clipping burst")
        if rng.random() < 0.1:
            i = int(rng.integers(0, n - 64))
            bad = [np.nan, np.inf, -np.inf][int(rng.integers(0, 3))]
            (mic if rng.random() < 0.5 else x)[i:i + 64] = bad
            events.append("driver glitch (non-finite samples)")
        yield k, x, mic, voice, (not singing and not silent), events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", choices=["feedback", "spill"], default="feedback",
                    help="engine mode (default: feedback, the app's default)")
    args = ap.parse_args()

    engine = AudioEngine(sample_rate=FS, feedback_mode=(args.mode == "feedback"))
    engine.delay_estimator.interval_s = 0.2
    engine.delay_estimator.start()
    rng = np.random.default_rng(args.seed + 99)

    stop = threading.Event()
    ui_errors = []

    def operator():
        # Someone fiddling with the gate, bypass and echo tail throughout.
        r = np.random.default_rng(args.seed + 7)
        while not stop.wait(0.05):
            try:
                engine.set_gate_threshold_db(float(r.uniform(-60, -40)))
                engine.set_gate_timing(float(r.uniform(1, 20)), float(r.uniform(50, 500)))
            except Exception as exc:  # reported at the end
                ui_errors.append(repr(exc))

    ui = threading.Thread(target=operator, daemon=True)
    ui.start()

    failures = []
    worst_load = 0.0
    loads = []           # (block size, processing time / real-time budget)
    spikes = []          # blocks >= 256 samples that took longer than real time
    processed = 0.0
    wall_start = time.perf_counter()
    rows = []
    seen_changes = 0
    # Feedback mode learns deliberately slowly (a faster start measurably
    # damages the voice in a closed loop), so allow it longer to re-learn.
    relearn_segs = 6 if args.mode == "feedback" else 3
    for k, x, mic, voice, echo_only, events in make_show(args.minutes, args.seed):
        if "mic moved" in events or "speaker delay now 70 ms" in events:
            settled_after = k + relearn_segs + 1
        elif k == 0:
            settled_after = 4
        if rng.random() < 0.03:
            engine.trigger_relearn()
            events.append("operator pressed Relearn")
            settled_after = k + relearn_segs
        if rng.random() < 0.05:
            tail = float(rng.choice([40, 85, 170, 340]))
            engine.set_tail_ms(tail)
            events.append(f"echo tail -> {tail:.0f} ms")
        out = np.empty(len(mic))
        pos = 0
        while pos < len(mic):
            n = int(rng.choice([512, 512, 512, 256, 1024, 441, 37]))
            n = min(n, len(mic) - pos)
            indata = np.stack([mic[pos:pos + n], x[pos:pos + n]], axis=1).astype(np.float32)
            outdata = np.zeros((n, 1), dtype=np.float32)
            t0 = time.perf_counter()
            engine._callback(indata, outdata, n, None, None)
            load = (time.perf_counter() - t0) / (n / FS)
            worst_load = max(worst_load, load)
            loads.append((n, load))
            if n >= 256 and load > 1.0:
                spikes.append((k, pos, n, load, list(events)))
            out[pos:pos + n] = outdata[:, 0]
            pos += n
        processed += len(mic) / FS

        if not np.all(np.isfinite(out)):
            failures.append(f"segment {k}: non-finite output")
        if np.max(np.abs(out)) > 1.0001:
            failures.append(f"segment {k}: output beyond full scale")

        clean_mic = np.nan_to_num(mic, nan=0, posinf=0, neginf=0)
        last = slice(-2 * FS, None)
        depth = 10 * np.log10((np.mean(clean_mic[last] ** 2) + 1e-20) /
                              (np.mean(out[last] ** 2) + 1e-20))
        note = ""
        settled = k >= settled_after and "clipping burst" not in events \
            and not any("glitch" in e for e in events)
        if echo_only and settled and np.mean(x[last] ** 2) > 1e-6:
            # The gate may push depth higher; the filter alone must reach 20 dB.
            if depth < 20:
                failures.append(f"segment {k}: only {depth:.1f} dB cancellation once settled")
                note = "  <-- LOW"
        voice_db = None
        if np.any(voice) and settled:
            v = voice[last]
            voice_db = 10 * np.log10(np.mean(out[last] ** 2) / (np.mean(v ** 2) + 1e-20))
            if voice_db < -6:
                failures.append(f"segment {k}: voice attenuated by {-voice_db:.1f} dB")
                note = "  <-- VOICE LOST"
        while len(engine.delay_changes) > seen_changes:
            _, old_ms, new_ms = engine.delay_changes[seen_changes]
            events.append(f"delay {old_ms:.1f}->{new_ms:.1f} ms")
            seen_changes += 1
        rows.append((k, depth, voice_db, engine.bulk_delay_ms, ", ".join(events), note))

    stop.set()
    ui.join()
    engine.delay_estimator.stop()
    wall = time.perf_counter() - wall_start

    print(f"{'seg':>4} {'time':>6} {'depth dB':>9} {'voice dB':>9} {'delay ms':>9}  events")
    for k, depth, voice_db, delay, events, note in rows:
        vd = "" if voice_db is None else f"{voice_db:+.1f}"
        print(f"{k:4d} {k * SEG // 60:3d}:{k * SEG % 60:02d} {depth:9.1f} {vd:>9} {delay:9.1f}  {events}{note}")
    print()
    print(f"simulated {processed / 60:.1f} min in {wall:.1f} s  ->  {processed / wall:.1f}x real time")
    print(f"worst single callback: {100 * worst_load:.0f}% of its block's real-time budget")
    big = np.array([ld for n, ld in loads if n >= 256])
    print(f"blocks >= 256 samples: median {100 * np.median(big):.0f}%, 99.9th pct "
          f"{100 * np.percentile(big, 99.9):.0f}%, max {100 * big.max():.0f}%, "
          f"over budget: {int(np.sum(big > 1.0))} of {len(big)}")
    for k, pos, n, load, ev in spikes[:20]:
        print(f"  slow block: segment {k} at {pos / FS:.2f}s, {n} samples, "
              f"{100 * load:.0f}% of budget  {', '.join(ev)}")
    # Judge sustained slowness, not a single stall of the (shared, virtual)
    # test machine: one ~0.1 s hiccup on a CI runner made 8 blocks in a row
    # late while the median was 15%. If more than 1 block in 1000 runs late,
    # the 99.9th percentile goes over budget and this fails.
    p999 = float(np.percentile(big, 99.9))
    if p999 > 1.0:
        failures.append(f"audio too slow: 99.9th percentile block took "
                        f"{100 * p999:.0f}% of real time")
    print(f"filter resets by divergence guard: {engine.filter.resets}   operator-thread errors: {len(ui_errors)}")
    if ui_errors:
        failures.append(f"UI thread errors: {ui_errors[:3]}")
    if processed / wall < 2:
        failures.append(f"too slow: {processed / wall:.1f}x real time")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nPASSED")


if __name__ == "__main__":
    main()
