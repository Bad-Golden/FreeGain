# FreeGain (Python) — Windows/Mac, no C++/JUCE required

> **Status: early WIP.** The NLMS filter core has been functionally tested
> (see "What's been tested" below) and converges correctly on synthetic
> signals. The UI and OSC/XAir integration have **not** been tested against
> real hardware — no XAir unit or live audio was available to verify against
> in this environment.

This is a full rewrite of the earlier JUCE/C++ version, in Python, specifically
to remove the need for Xcode/Visual Studio/CMake/JUCE to build it. You only
need Python itself and a few `pip install`-able packages.

## What's been tested

The filter core and audio callback have been through a real stress-testing
pass (not just a single happy-path check). Three genuine bugs were found
and fixed as a result:

1. **Sliding-window energy going stale during double-talk freezes**, causing
   the adaptive filter to explode into NaN/huge values shortly after
   starting. Fixed by always updating the energy tracker every sample,
   independent of whether adaptation itself is frozen.
2. **Performance: the original per-sample Python loop only ran at ~0.18x
   real-time** at the production tap count (256 taps) -- meaning it could
   not keep up with live audio at all and would have caused constant
   dropouts. Rewritten to use a vectorized double-buffer approach (numpy
   dot product + array ops instead of a Python loop over each tap),
   now measured at **~5.3-5.6x real-time** at 256 taps / 44.1kHz on the
   machine this was tested on. Re-check on your own machine -- Python
   performance varies with CPU.
3. **A single non-finite sample (NaN/Inf) permanently corrupted the filter
   and gate**, since it propagates through every subsequent multiply-add
   forever. This is a realistic scenario (audio driver glitches, buffer
   underruns can produce a bad sample). Fixed with input sanitization
   (non-finite samples treated as silence) and a safety-net check that
   resets the filter taps if they ever go non-finite despite that.
4. **A zero-length audio block crashed the callback outright** (indexing
   an empty array). Some audio drivers send these transiently during
   device reconfiguration or stream start/stop. Fixed with an early-return
   guard.

5. **Wrong OSC socket architecture — would never have received real replies.**
   The original client sent from one socket and listened on a separate,
   independently-bound port. But both XAir and X32 reply to whichever port
   your request was *sent from* (confirmed against Behringer's own X32-OSC
   protocol documentation) — not to some other configured listen port.
   Rewritten (`mixer_osc_client.py`) to use a single shared socket for both
   sending and receiving, which is what the protocol actually requires.
   **This part is written against python-osc's documented API but has not
   been executed against the real library or real hardware** — no network
   access to install python-osc in the environment this was built in. Test
   this specifically before trusting it.
6. **Now supports both XAir and X32**, since they use the identical OSC
   address scheme and differ only in UDP port (XAir=10024, X32=10023,
   both confirmed against Behringer's protocol doc) and channel-count
   ceiling (XAir up to 18, X32 up to 32). See `console_profiles.py`. A
   console-type dropdown in the UI selects which profile to connect with.
7. **Panic-mute button didn't reflect actual mute state.** It only ever
   sent "mute on" and reverted its own color after 400ms regardless of
   whether the mixer was still muted -- so the button could look normal
   while the mixer was actually still muted. Fixed to be a real toggle:
   it now sends explicit mute-on/mute-off and stays visually lit for as
   long as the mute is actually active.

Beyond those fixes, the following were verified and behave correctly:
- Convergence on synthetic feedback signals (residual energy drops ~25x,
  settles near the theoretical best-case floor)
- Numerical stability over 20,000+ samples at production settings, no
  NaN/Inf, bounded filter taps
- Edge cases: silent reference, silent mic, both silent, full-scale loud
  signal, perfect zero-delay unity feedback (near-total cancellation),
  a single impulse, an abrupt mid-stream change in the feedback path
  (correctly re-converges), and sustained loud "double-talk" (correctly
  stays mostly frozen rather than corrupting the filter)
- The OSC meter-blob parser and channel-number extractor don't crash on
  empty, truncated, over-claimed-count, or negative-count/malformed input

**Still untested**: the tkinter UI has never been opened on a real screen,
`sounddevice`'s interaction with actual XAir/X32 USB audio hasn't been
verified, and **`mixer_osc_client.py` has never actually talked to a real
mixer or even a real python-osc install** (no network access to install
it in the environment this was built in). The meter-blob byte *layout*
itself (as opposed to the parser's crash-safety) is still a best guess,
not confirmed against real mixer traffic. Treat the OSC layer as the
least-trustworthy part of this project until someone runs it against
actual hardware.

## What's implemented

- `nlms_filter.py` — the adaptive filter core, tested as described above.
- `simple_gate.py` — basic gate/expander.
- `console_profiles.py` — port/channel-count differences between XAir and
  X32 (both confirmed against Behringer's own protocol documentation).
- `mixer_osc_client.py` — OSC control-plane client (channel names, meters,
  mute groups, fader control) using `python-osc`, supporting both console
  families via `console_profiles.py`. Uses a single shared socket for
  send+receive, matching how the protocol actually replies (see bug #5
  above) — untested against real hardware/library.
- `audio_engine.py` — USB audio I/O via `sounddevice`, wires mic + reference
  channels through the filter and gate.
- `freegain_app.py` — tkinter UI: bypass, relearn room, panic mute, a
  console-type picker (XAir/X32), vocal/reference channel dropdowns with
  live-signal indicator dots (channel list length adjusts to the selected
  console's channel ceiling), gate sliders, input/output/cancellation-depth
  meters, OSC connect field.

## Known gaps (same as the JUCE version)

- **Channel-selection is cosmetic.** The dropdowns show and update live
  channel names via OSC, but selecting a different entry doesn't yet change
  which physical audio channel is used — `audio_engine.py` still assumes
  input channel 0 = mic, channel 1 = reference regardless of what's selected.
- **Meter blob parsing is a best guess**, not verified against a real XAir.
- **Performance**: the filter processes one sample at a time in a Python
  loop. This is fine for testing and moderate use but is not as CPU-efficient
  as a compiled implementation — if you hear glitches/dropouts, try reducing
  `num_taps` in `audio_engine.py` or increasing `block_size`.

## Setup (Windows)

1. Install Python 3.10+ from python.org (check "Add python.exe to PATH"
   during install).
2. Open Command Prompt in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Plug in your mixer via USB. Run:
   ```
   python freegain_app.py
   ```
   In the app, pick your console type (XAir or X32) from the dropdown at
   the top before hitting Connect — this determines the OSC port (10024
   vs 10023) and how many channels show up in the vocal-channel picker.
4. If it can't open the default audio device automatically, list your
   available devices first:
   ```
   python -c "import sounddevice as sd; print(sd.query_devices())"
   ```
   Find your XAir's entry and note its index, then pass `device=<index>`
   to `self.engine.start()` in `freegain_app.py` (`_start_audio` method).

## Setup (Mac)

Same steps — `python3` instead of `python` if both Python 2 and 3 are
present, everything else identical. This is the advantage of the Python
rewrite: no Xcode required at all, just Python + pip.

## Testing the filter yourself before trusting it on real audio

Before running against your actual XAir, it's worth re-running a synthetic
test like the one used to catch the bug above:

```python
import numpy as np
from nlms_filter import NLMSFilter

n = 5000
reference = np.random.randn(n) * 0.3
feedback = np.zeros(n)
feedback[5:] = reference[:-5] * 0.6  # fake feedback path
mic = feedback + np.random.randn(n) * 0.02  # + fake "voice"

f = NLMSFilter(num_taps=256, step_size=0.5)
out = f.process_block(reference, mic)
print("early:", np.mean(out[:200]**2), "late:", np.mean(out[-500:]**2))
# "late" should be much smaller than "early", and neither should be NaN.
```

## License

MIT, Peninsula Pulse DJs. Independent implementation using publicly
documented techniques (NLMS adaptive filtering; the public Behringer/Midas
XAir OSC command set). Not affiliated with Alpha Labs, Behringer, Midas,
or Music Tribe.
