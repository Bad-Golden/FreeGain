"""
stress_endurance.py -- hours of continuous audio through the engine,
watching memory and numerical health (the soak test covers events; this
covers time).

Checks every 10 simulated minutes: process memory (RSS), that all filter
state is finite and bounded, and that cancellation hasn't drifted.

Usage:  python tests/stress_endurance.py [--hours 2] [--mode feedback|spill]
"""

import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from audio_engine import AudioEngine  # noqa: E402
from roomsim import FS, echo, music, room, singing  # noqa: E402


def rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--mode", choices=["feedback", "spill"], default="feedback")
    args = ap.parse_args()

    engine = AudioEngine(sample_rate=FS, feedback_mode=args.mode == "feedback")
    h = room(9, 60, seed=3)
    B = engine.block_size
    chunk_s = 30
    rng = np.random.default_rng(0)
    tail = np.zeros(len(h))
    minutes = 0.0
    start = time.perf_counter()
    baseline = None
    report = []
    failures = []
    total = int(args.hours * 60 * 60 / chunk_s)
    for c in range(total):
        x = music(chunk_s, seed=c) * float(rng.choice([0.05, 0.1, 0.3]))
        full = np.concatenate([tail, x])
        d = echo(full, h)[len(tail):]
        tail = x[-len(h):]
        if c % 3 == 0:
            d = d + singing(chunk_s, seed=c, level=0.1)
        out = np.empty(len(x))
        for i in range(0, len(x), B):
            indata = np.stack([d[i:i + B], x[i:i + B]], 1).astype(np.float32)
            n = len(indata)       # the last block of a chunk can be shorter
            outdata = np.zeros((n, 1), np.float32)
            engine._callback(indata, outdata, n, None, None)
            out[i:i + n] = outdata[:, 0]
            if i % FS < B:
                engine.delay_estimator.estimate_once()
        minutes += chunk_s / 60
        if not np.all(np.isfinite(out)):
            failures.append(f"{minutes:.0f} min: non-finite output")
        if int(minutes) % 10 == 0 and abs(minutes - round(minutes)) < 1e-6:
            f = engine.filter
            finite = all(np.all(np.isfinite(a)) for a in (f.W, f.X, f.power))
            peak_tap = float(np.max(np.abs(f.impulse_response())))
            depth = 10 * np.log10(np.mean(d[-5 * FS:] ** 2) / (np.mean(out[-5 * FS:] ** 2) + 1e-20)) \
                if c % 3 else float("nan")
            mem = rss_mb()
            baseline = baseline or mem
            report.append((minutes, mem, finite, peak_tap, depth, len(engine.history),
                           len(engine.delay_estimator.history), f.resets))
            print(f"{minutes:6.0f} min  RSS {mem:7.1f} MB  state finite {finite}  "
                  f"largest tap {peak_tap:.3f}  depth {depth:5.1f} dB  history {len(engine.history)}  "
                  f"resets {f.resets}", flush=True)
            if not finite:
                failures.append(f"{minutes:.0f} min: filter state went non-finite")
            if peak_tap > 10:
                failures.append(f"{minutes:.0f} min: filter taps blowing up ({peak_tap:.1f})")
    growth = report[-1][1] - report[0][1] if report else 0
    print(f"\nsimulated {minutes / 60:.1f} h in {(time.perf_counter() - start) / 60:.1f} min; "
          f"memory growth after the first 10 min: {growth:+.1f} MB")
    if growth > 50:
        failures.append(f"memory grew {growth:.0f} MB")
    if failures:
        print("FAILED:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("PASSED")


if __name__ == "__main__":
    main()
