# FreeGain — feedback suppression for Behringer XAir / X32 (Windows & Mac)

FreeGain listens to a vocal mic and to the signal feeding your speakers.
It learns the acoustic path between the two with an NLMS adaptive filter
and subtracts the predicted feedback and room spill from the mic. A gate
follows the filter, and the app talks to the mixer over OSC for channel
names, meters and a panic mute.

It's pure Python: no Visual Studio, Xcode, CMake or JUCE needed.

> **Status: beta, not yet proven on a live rig.** The DSP and OSC layers
> are covered by an automated test suite (see [Testing](#testing)), and the
> OSC client has been run against a simulated mixer over real UDP sockets.
> It has **not** been run against real XAir/X32 hardware yet. Try it at
> soundcheck, not for the first time mid-show.

## Quick start (Windows)

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/).
   Tick **"Add python.exe to PATH"** in the installer.
2. Plug the mixer in over USB. For OSC control, also have it on the same
   network as the PC.
3. Double-click **`run_freegain.bat`**. The first run sets up a private
   Python environment (`.venv`) and installs the dependencies, which takes
   about a minute. Later runs start straight away.

To do it by hand instead:

```
pip install -r requirements.txt
python freegain_app.py
```

## Quick start (Mac)

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python freegain_app.py
```

## Using it

1. **Audio in / out.** Pick the mixer's USB audio device (e.g. "X18/XR18")
   and press **Apply**. The status line at the bottom shows the sample rate
   in use, which is the device's native rate. Press ↻ if you plugged the
   mixer in after starting the app.
2. **Vocal mic input / Reference input.** Pick which USB channel carries the
   vocal mic and which carries the speaker feed. On XAir/X32 the default USB
   routing sends mixer channel N to USB input N. For the reference, route
   your main mix (or the monitor bus you're fighting) to a spare USB send in
   the mixer's routing page, then select that USB channel here.
3. **Output.** The processed vocal goes out on the selected output device.
   Return it to the mixer on a USB return channel and use that channel in
   place of the raw mic.
4. **Connect (optional).** Choose XAir or X32/M32, enter the mixer's IP and
   press **Connect**. The label turns green ("connected") once the mixer
   actually replies. Channel names then appear in the input pickers.
5. **Relearn room** clears what the filter has learned. Use it after moving
   mics or speakers.
6. **Panic mute** toggles mute group 1 on the mixer and stays lit while the
   mute is active. Assign the channels you want silenced to mute group 1.
7. **Active / Bypassed** switches processing off and passes the mic through
   untouched.

Settings (IP, console type, devices, channels, gate) are saved to
`local_config.json` when you close the window.

## Files

| File | What it does |
| --- | --- |
| `freegain_app.py` | tkinter UI |
| `audio_engine.py` | USB audio I/O (`sounddevice`) and channel routing; runs the filter and gate |
| `nlms_filter.py` | NLMS adaptive filter plus the cancellation-depth estimate |
| `simple_gate.py` | Envelope gate/expander |
| `mixer_osc_client.py` | OSC client (names, meters, mute groups, faders, keepalive) |
| `console_profiles.py` | Per-family differences: port, channel count, meter encoding |
| `benchmark.py` | Measures real-time headroom on your machine |
| `run_freegain.bat` | One-click Windows launcher |

## Performance

The filter works one sample at a time in Python, with numpy doing the
per-tap math. Check your headroom with:

```
python benchmark.py
```

Anything comfortably above 1× real time works. On the development machine
256 taps at 48 kHz ran at about 4.6× real time for filter plus gate. If the
dropout counter next to "Cancellation depth" keeps rising, lower `num_taps`
in `AudioEngine`, or raise `block_size` (which adds latency).

## Testing

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

The suite covers:

- **Filter:** convergence, running-energy accuracy across buffer wraps,
  NaN/Inf input, empty or mismatched blocks, reset.
- **Gate:** gating behaviour, NaN handling, block vs per-sample equivalence,
  sample-rate changes.
- **Audio engine:** channel routing, relearn timing, clipping, zero-length
  blocks, dropout counting. No sound card needed.
- **OSC client:** full round trip against a fake mixer on localhost (reply
  routing, channel names, mute, meters, keepalive), invalid IPs, garbage
  datagrams, malformed meter blobs, both meter encodings.

GitHub Actions runs the suite on Windows and Linux for every push.

## Known limitations

- **Not yet verified on real hardware.** The meter blob encodings (XAir:
  int16 in 1/256 dB; X32: float32) follow the community-documented
  protocol but haven't been checked against captured traffic. The UI
  doesn't display mixer meters yet.
- The input pickers assume the mixer's default USB routing when showing
  channel names. If you've changed routing, trust the USB number, not the
  name.
- Panic mute is fixed to mute group 1.

## License

MIT, Peninsula Pulse DJs. Independent implementation using publicly
documented techniques (NLMS adaptive filtering; the public Behringer/Midas
OSC command set). Not affiliated with Alpha Labs, Behringer, Midas, or
Music Tribe.
