# Quick Start

Get from "just installed" to "cancelling feedback" in about five minutes.

## 1. Connect the audio

FreeGain needs two signals from your console and sends one back:

| Signal | What it is | Typical source |
| --- | --- | --- |
| **Vocal mic** (in) | The mic you're fighting feedback on | Console channel's USB/Dante direct out |
| **Reference** (in) | What's going to the speakers | Main LR, or the monitor bus that feeds back |
| **Processed vocal** (out) | The cleaned-up mic | Back into a spare console channel |

See [[Audio Setup]] for console-specific routing.

## 2. Pick your console

At the top of the window, choose the **Console** brand and model. If yours
isn't listed, choose **Any console (audio only)**. Everything except
channel names and panic mute still works.

## 3. Pick the audio device

- **Audio in / out:** choose your console's audio interface and press
  **Apply**.
  - Windows: prefer the **[ASIO]** entry, otherwise **[Windows WASAPI]**.
    **[MME]** often shows only 2 channels.
  - Mac: choose the **[Core Audio]** entry.
- The bottom status line should say **"Audio running at 48000 Hz…"**.

## 4. Pick the inputs

- **Vocal mic input:** the input carrying the vocal mic.
- **Reference (speaker feed) input:** the input carrying your speaker mix.

The dots next to each picker light up green when there's signal on that
input.

## 5. Use the output

Send FreeGain's output back into the console on a spare channel, and use
that channel in your mix **instead of** the raw vocal channel.

## 6. Let it learn

- Make sure the button says **Active**.
- Play **music** through the speakers at a normal level. Within a few
  seconds, **Speaker delay** (left panel) shows how late the speakers reach
  the mic, and the **Cancellation depth** meter rises as FreeGain learns the
  room. 15–30 dB is a good real-world result.
- Leave **Vocal goes back to the PA (feedback mode)** ticked whenever
  FreeGain's output goes to the PA or monitors.
- Pick a **Room echo tail** to suit the room: 85 ms (typical) is the
  default. Try 170 ms in a big or echoey hall.
- If you move mics or speakers, press **Relearn room**.
- Press **Save diagnostics…** (bottom right) after a test and send the file.
  It records everything needed to tune FreeGain for your room.

## 7. Optional: connect to the console

Enter the console's IP address and press **Connect**. The status turns
green once the console answers. Channel names then show in the input
pickers, and **Panic mute** becomes available. See [[Console Setup]].
