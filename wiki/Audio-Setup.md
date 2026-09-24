# Audio Setup

FreeGain works with **any** audio interface your computer can see. The
feedback canceller only needs:

1. the **vocal mic** signal,
2. a **reference** signal (what's going to the speakers), and
3. a way to send the **processed vocal** back to the console.

## Picking devices and channels

- **Audio in:** the device carrying both the vocal and reference signals.
  They must come from the **same** device.
- **Audio out:** where the processed vocal goes. Usually the same console
  interface, returned to a spare input channel.
- **Vocal mic input / Reference input:** which input number on that device
  carries each signal. Up to 64 inputs are listed.
- FreeGain uses the device's **native sample rate** (usually 48 kHz), so
  nothing is resampled.

On **Windows**, each device is listed once per driver type:

| Driver | Use it? |
| --- | --- |
| **[ASIO]** | Best choice when available. Most console USB drivers and Dante Virtual Soundcard |
| **[Windows WASAPI]** | Good fallback, all channels |
| **[Windows WDM-KS]** | Low latency, sometimes finicky |
| **[MME]**, **[DirectSound]** | Avoid; often only 2 channels and high latency |

On **Mac**, choose the **[Core Audio]** entry.

## Console drivers you may need

FreeGain has everything it needs built in, but your **console's own audio
driver** is separate:

| Console | Driver |
| --- | --- |
| Behringer / Midas XAir, X32, Wing, MR, M32 | Behringer USB driver on Windows (for all channels); class-compliant on Mac |
| Allen & Heath Qu, SQ, Avantis | A&H USB/ASIO driver on Windows |
| Yamaha TF, DM3 and others | Yamaha Steinberg USB Driver |
| Dante consoles (CL/QL, Rivage, dLive, Avantis) | Dante Virtual Soundcard (from Audinate) |
| Soundcraft Ui24R | No extra driver on Windows 10/11 |

If your console already shows up in a recording program (DAW), you
already have the driver.

## Dante networks

FreeGain works with Dante, through a Dante "soundcard" on the computer.
It doesn't speak the Dante protocol itself, and it doesn't need to:

1. **The console needs Dante.** Either it's built in (Yamaha CL/QL/DM7/
   Rivage, Allen & Heath Avantis with a Dante card, many others), or it
   comes from an expansion card (e.g. Behringer/Midas X-DANTE for X32/M32,
   Allen & Heath's Dante cards for SQ/dLive, Yamaha TF with a Dante card).
2. **Put the computer on the Dante network:** an Ethernet cable to the
   Dante switch or the console's Dante port. Use the primary network, and
   wired, not Wi-Fi.
3. **Install a Dante soundcard on the computer.** Two options:
   - **Dante Virtual Soundcard (DVS)** from Audinate. It's paid, and it makes
     the computer a Dante device with up to 64 channels in and out. It shows
     up in FreeGain as **[ASIO] Dante Virtual Soundcard** on Windows, or
     **[Core Audio] Dante Virtual Soundcard** on Mac.
   - A **Dante-to-USB adapter** (e.g. Audinate AVIO USB) plugged into the
     computer. It shows up as a normal USB audio device, with no software
     licence needed.
4. **Route the channels in Dante Controller** (free from Audinate):
   - console's vocal channel direct out → computer receive channel, e.g. 1
   - console's Main LR (or the monitor mix you're fighting) → computer
     receive channel, e.g. 2
   - computer transmit channel 1 (FreeGain's output) → a spare console input
5. **In FreeGain:** pick the Dante device in **Audio in / out**, set
   **Vocal mic input** = 1 and **Reference** = 2, and press **Apply**.

Tips:
- **Keep latency low.** In DVS, pick the lowest latency that runs without
  dropouts (e.g. 4 ms, or 1–2 ms on a dedicated network). The Dante
  latency adds to the feedback loop; FreeGain's automatic delay finder
  compensates for it, but lower is still better.
- **Sample rate:** set DVS to the same rate as the console (usually 48 kHz).
  FreeGain uses whatever rate the device runs at.
- **Console connection** (names, panic mute) goes over the console's
  *control* network port, which is often separate from the Dante port.
  Check your console's manual; FreeGain needs the control IP address.

## Routing the reference signal

The reference should be **exactly what feeds the speakers causing the
feedback**:
- Front-of-house feedback → route **Main LR** to a spare USB/Dante send.
- Wedge feedback → route that **monitor bus** to a spare USB/Dante send.

Then pick that send as the **Reference input** in FreeGain.

On most consoles the default USB routing sends channel *N* to USB input
*N*, so channel 1's mic is USB input 1. FreeGain assumes this when it shows
channel names from the console.

## Returning the processed vocal

Route FreeGain's **output** back into a spare console channel, for example
a USB return, and use that channel in the mix **instead of** the raw vocal
channel. Leave the raw channel muted or out of the mix, otherwise you hear
both.

## Latency

Audio is processed in blocks of 512 samples, about 10.7 ms at 48 kHz, plus
the interface's own buffering (1024 samples at 88.2/96 kHz: the same
~10.7 ms). That's fine for speech and most singing. If
the **dropouts** counter next to Cancellation depth keeps climbing, the
computer can't keep up; see [[Troubleshooting]].
