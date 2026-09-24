# FreeGain — feedback suppression for live consoles (Windows & Mac)

📖 **Full documentation: see the [Wiki](../../wiki)** (setup guides for every
console, troubleshooting, FAQ).

FreeGain listens to a vocal mic and to the signal feeding your speakers.
It measures how late the speaker sound reaches the mic, learns the room's
echo with a frequency-domain adaptive filter (up to 340 ms of reverb), and
subtracts the predicted feedback and room spill from the mic. In a
simulated closed loop with realistic singing it gives **6–9 dB more usable
gain before feedback** than bypass, with the voice as clean as bypass at
normal levels. It hasn't been confirmed on a real PA yet. A gate
follows the filter. For many consoles the app can also talk to the desk
over the network, to show channel names and to give you a panic mute.

It's pure Python: no Visual Studio, Xcode, CMake or JUCE needed.

> **Status: beta, not yet proven on a live rig.** The DSP and console
> drivers are covered by an automated test suite (see [Testing](#testing)),
> and the drivers have been run against simulated consoles over real
> network sockets.
> It has **not** been run against real console hardware yet. Try it at
> soundcheck, not for the first time mid-show.

## Supported consoles

**Audio: any console.** FreeGain processes audio through whatever interface
gets the console's signals into the computer:
- the console's own USB interface (XAir, X32, Wing, TF, Qu, SQ, Ui24R...)
- Dante Virtual Soundcard (CL/QL/Rivage, dLive, Avantis...)
- any audio interface fed from the console's direct outs or aux sends

Choose **Any console (audio only)** if yours isn't listed below. Everything
except the remote-control features still works.

**Remote control (channel names + panic mute)** is built in for these:

| Brand | Models | Protocol | Names | Panic mute uses | Status |
| --- | --- | --- | --- | --- | --- |
| Behringer | XR12, XR16, XR18, X18 | OSC (UDP 10024) | yes | mute group 1 | documented |
| Behringer | X32, Compact, Producer, Rack, Core | OSC (UDP 10023) | yes | mute group 1 | documented |
| Midas | MR12, MR18 | OSC (UDP 10024) | yes | mute group 1 | documented |
| Midas | M32, M32R, M32C, M32 Live | OSC (UDP 10023) | yes | mute group 1 | documented |
| Behringer | Wing, Wing Rack, Wing Compact | OSC (UDP 2223) | yes | mute group 1 | experimental |
| Yamaha | TF1/3/5, TF Rack, DM3, DM7, QL1/5, CL1/3/5, Rivage PM | RCP (TCP 49280) | yes | mute group 1 | experimental |
| Allen & Heath | Qu-16/24/32, Qu-Pac, Qu-SB, Avantis | MIDI over TCP (51325) | no | vocal channel mute | experimental |
| Allen & Heath | dLive (MixRack) | MIDI over TCP (51328) | no | vocal channel mute | experimental |
| Allen & Heath | SQ-5/6/7 | MIDI NRPN over TCP (51325) | no | vocal channel mute | experimental |
| Soundcraft | Ui12, Ui16, Ui24R | WebSocket | yes | vocal channel mute | experimental |
| Other | Anything that speaks OSC | Generic OSC (configurable) | configurable | configurable | experimental |

*Documented* means the protocol is widely published and used by many
tools. *Experimental* means the driver was written from the manufacturer's
or community protocol documents but hasn't been tried on that desk yet.
If you test one, please report back, whether it works or not.

Console-specific setup:
- **Yamaha:** the computer and console must be on the same network.
- **Allen & Heath:** the MIDI channel set on the console must match. The
  default here is channel 1 (Qu/SQ/Avantis) or 12 (dLive). To use a
  different one, see [Console options](#console-options).
- **Behringer Wing:** OSC must be enabled in the Wing's remote settings.

## Download (no install needed)

**Windows:** download `FreeGain-Windows.zip`, unzip it and double-click
**`FreeGain.exe`**. It's a single self-contained file, so there's no Python
or anything else to install. The app isn't code-signed yet, so the first
launch may show "Windows protected your PC": click **More info → Run
anyway**.

**Mac:** download `FreeGain-macOS-AppleSilicon.zip` for M1/M2/M3/M4 Macs,
or `FreeGain-macOS-Intel.zip` for Intel Macs. To check which one you have,
open  → About This Mac: "Chip: Apple M…" means Apple Silicon, and
"Processor: … Intel" means Intel. Unzip it and drag `FreeGain.app` to
Applications. Needs macOS 11 (Big Sur) or newer. The app isn't notarized
by Apple yet, so the first launch says Apple "could not verify" it: go to
**System Settings → Privacy & Security** and click **Open Anyway**, or run
`xattr -dr com.apple.quarantine /Applications/FreeGain.app` in Terminal.

The downloads are built automatically by GitHub Actions
(`.github/workflows/build.yml`). Every push produces them under the run's
**Artifacts**, and pushing a tag like `v1.0.0` publishes them as a GitHub
Release. To build the Windows exe yourself, run
`packaging\build_windows.bat`, or on any OS:
`pyinstaller packaging/freegain.spec`.

## Running from source (Windows)

1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/).
   Tick **"Add python.exe to PATH"** in the installer.
2. Connect the console's audio to the PC (USB, Dante, or an interface).
   For remote control, also put the console on the same network as the PC.
3. Double-click **`run_freegain.bat`**. The first run sets up a private
   Python environment (`.venv`) and installs the dependencies, which takes
   about a minute. Later runs start straight away.

To do it by hand instead:

```
pip install -r requirements.txt
python freegain_app.py
```

## Running from source (Mac)

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python freegain_app.py
```

## Using it

1. **Console.** Pick the brand and model, or "Any console (audio only)".
2. **Audio in / out.** Pick the console's audio interface and press
   **Apply**. Each device shows its driver type in brackets. On Windows,
   choose the **[ASIO]** entry if there is one (most console USB drivers
   and Dante Virtual Soundcard), otherwise **[Windows WASAPI]**. The [MME]
   entry often shows only 2 channels. The status line
   at the bottom shows the sample rate in use, which is the device's native
   rate. Press ↻ if you plugged the interface in after starting the app.
3. **Vocal mic input / Reference input.** Pick which input carries the vocal
   mic and which carries the speaker feed. On most consoles the default USB
   routing sends channel N to USB input N. For the reference, route your
   main mix (or the monitor bus you're fighting) to a spare USB/Dante send
   on the console, then select that input here.
4. **Output.** The processed vocal goes out on the selected output device.
   Return it to the console on a spare input and use that channel in place
   of the raw mic.
5. **Connect (optional).** Enter the console's IP and press **Connect**.
   The label turns green ("connected") once the console actually answers.
   On consoles that support it, channel names then appear in the input
   pickers.
6. **Vocal goes back to the PA (feedback mode)**, on by default. Use it
   whenever FreeGain's output is in the PA or monitors, which is the normal
   case for fighting feedback. It learns the room without learning the
   singer, and shifts the output up by 5 Hz to keep the loop stable. Turn it
   off only when the reference never contains this vocal (e.g. cancelling a
   band's spill into a podium mic); the filter then learns faster.
7. **Room echo tail** sets how much reverb the filter models: 40 ms (small
   room), 85 ms (typical, the default), 170 ms (large hall) or 340 ms (very
   live). Longer cancels more in reverberant rooms but takes longer to learn.
   Changing it keeps what has already been learned.
   **Find speaker delay automatically** measures how late the speaker sound
   reaches the mic (it needs music playing) and shows it under the checkbox.
8. **Relearn room** clears what the filter has learned and re-measures the
   delay. Use it after moving mics or speakers.
9. **Panic mute** stays lit while the mute is active. On consoles with mute
   groups it toggles mute group 1, so assign the channels you want silenced
   to that group. On other consoles it mutes the selected vocal channel,
   assuming console channel N comes in as input N.
10. **Mic gain** (−24 to +24 dB) and **Output level** (−40 to +12 dB) set
    the vocal level into the gate and the final level sent back to the
    console. Mic gain is applied after the echo canceller, so changing it
    never forces a relearn. Gain changes glide smoothly (no clicks), and a
    soft limiter keeps the output below full scale; the **LIMIT** light
    next to the Output meter shows when it's working. Double-click a level
    slider to reset it to 0 dB.
11. **Active / Bypassed** switches processing off and passes the mic through
   untouched.
12. **Save diagnostics…** (bottom right) writes a JSON report of the session:
    settings, devices, measured delay, CPU load, dropouts, and a per-second
    history of cancellation depth and levels. Send it along with test reports.

Settings (IP, console model, devices, channels, gate) are saved to
`local_config.json` when you close the window. That file sits next to
`freegain_app.py` when running from source, in `%APPDATA%\FreeGain` for
the Windows exe, and in `~/Library/Application Support/FreeGain` for the
Mac app.

### Console options

Protocol details can be overridden per console model in
`local_config.json` under `"console_options"`. The file is created after
the first run; edit it while the app is closed. Some examples:

```json
"console_options": {
  "dlive": { "midi_channel": 1 },
  "tf5": { "port": 49280 },
  "generic_osc": {
    "port": 8000,
    "max_channels": 24,
    "name_address": "/ch/{ch}/name",
    "channel_mute_address": "/ch/{ch}/mute",
    "channel_mute_values": [0, 1],
    "mute_group_address": "/mutegroup/{n}",
    "keepalive": []
  }
}
```

Allowed keys: `port`, `max_channels`, `midi_channel`, `name_address`,
`mute_group_address`, `mute_group_values`, `channel_mute_address`,
`channel_mute_values`, `fader_address`, `keepalive`. In OSC addresses,
`{ch}` is the channel number and `{n}` the mute group; use `{ch:02d}` for
zero-padded numbers. The `*_values` pairs are `[unmuted, muted]`.

## Files

| File | What it does |
| --- | --- |
| `freegain_app.py` | tkinter UI |
| `audio_engine.py` | Audio I/O (`sounddevice`) and channel routing; runs the filter and gate |
| `fdaf_filter.py` | The echo canceller: partitioned-block frequency-domain adaptive filter |
| `delay_estimator.py` | Measures the speaker-to-mic delay (GCC-PHAT) on a background thread |
| `pem_filter.py` | Feedback-mode canceller: pre-whitened (prediction error method) so it learns the room, not the singer |
| `freq_shift.py` | Low-latency 5 Hz frequency shifter used in feedback mode |
| `levels.py` | Smoothly-ramped gain and the soft output limiter |
| `diagnostics.py` | Builds the "Save diagnostics" report |
| `nlms_filter.py` | Original sample-by-sample NLMS filter (kept for reference) and the cancellation-depth helper |
| `simple_gate.py` | Envelope gate/expander |
| `consoles/profiles.py` | The console model list |
| `consoles/osc.py` | OSC driver (Behringer, Midas, Wing, Generic OSC) |
| `consoles/yamaha_rcp.py` | Yamaha RCP driver |
| `consoles/allen_heath.py` | Allen & Heath MIDI-over-TCP driver |
| `consoles/soundcraft_ui.py` | Soundcraft Ui WebSocket driver |
| `benchmark.py` | Measures real-time headroom on your machine |
| `run_freegain.bat` | One-click Windows launcher when running from source |
| `packaging/` | PyInstaller spec, Windows build script, icon, download read-me |

## Performance

The echo canceller works on blocks in the frequency domain, so even the
longest echo tail uses little CPU. Check your headroom with:

```
python benchmark.py
```

On the development machine (whole chain, 48 kHz, 512-sample blocks):

| Echo tail | Taps | Feedback mode (default) | Spill mode |
| --- | --- | --- | --- |
| 40 ms | 2048 | ~10% CPU | ~4% CPU |
| 85 ms | 4096 | ~10% CPU | ~5% CPU |
| 170 ms | 8192 | ~13% CPU | ~7% CPU |
| 340 ms | 16384 | ~18% CPU | ~11% CPU |

Feedback mode costs more because it also models the voice (pre-whitening)
and runs the frequency shifter. The 340 ms tail in feedback mode is the
heaviest setting and learns slowest; prefer 85 or 170 ms unless the room
really needs it.

The app shows live CPU load next to "Cancellation depth". If the dropout
counter keeps rising, pick a shorter echo tail.

## Testing

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

The suite covers:

- **Echo canceller:** convergence in simulated rooms (1–20 ms speaker
  delay, 3–150 ms reverb), background noise, double-talk (singing over the
  PA without the voice being learned or damaged), re-learning after a mic
  moves, NaN/Inf, clipping, DC, silence, divergence recovery, irregular
  block sizes, a two-minute stability run, and speed per echo tail.
- **Delay finder:** accuracy from 0 to 400 ms with noise and talking (within
  1 ms), silence and unrelated audio (no false estimate), feedback loops
  (the vocal inside the reference is ignored), ring-buffer wrap-around.
- **Gate:** gating behaviour, NaN handling, block vs per-sample equivalence,
  sample-rate changes.
- **Audio engine:** channel routing, automatic delay compensation (including
  a 120 ms delay), echo-tail changes, relearn timing, clipping, NaN input,
  irregular block sizes, diagnostics, and controls changed from another
  thread while audio runs. No sound card needed.
- **Console stress:** garbage-packet floods, malformed and huge replies,
  console reboots and reconnects, rapid connect/disconnect (no thread leaks).
- **Console drivers:** every model in the list builds a working driver.
  Round trips run against fake consoles on localhost: OSC (XAir, X32, Wing,
  Generic) over UDP, Yamaha RCP and Allen & Heath over TCP. Also covered:
  exact Allen & Heath MIDI bytes, Soundcraft message parsing, reconnect
  when no console is present, garbage data, malformed meter blobs.

GitHub Actions runs the suite on Windows and Linux for every push.

The **closed-loop test** simulates the real use case: a singer into a mic,
FreeGain's output going to the PA, and the PA going back into the mic. It
measures how much more gain you get before feedback, with voice quality
checked too:

```
python tests/stress_feedback_loop.py
```

There's also a long **soak test** that plays a simulated gig through the real
audio engine: music at changing levels, a singer coming and going, the mic
being moved, the speaker delay jumping, silence, clipping, driver glitches,
irregular block sizes, and settings changed during playback:

```
python tests/stress_soak.py --minutes 30
```

## Known limitations

- **Not yet verified on real hardware.** This is especially true of the
  drivers marked experimental.
- **No channel names for Allen & Heath.** Their name protocol differs by
  family.
- **Names assume default routing.** The input pickers assume console
  channel N arrives as input N. If you've changed the routing, trust the
  input number, not the name.
- **Not supported yet:** PreSonus StudioLive, DiGiCo and Roland use closed
  or undocumented protocols, so they have no remote control. Audio-only
  mode works with them.

## License

MIT, Peninsula Pulse DJs. Independent implementation using publicly
documented techniques (adaptive echo cancellation; the consoles' published
remote-control protocols). Not affiliated with Alpha Labs, Behringer,
Midas, Music Tribe, Yamaha, Allen & Heath, Soundcraft or Harman.
