# How It Works

## The idea

Feedback and speaker spill happen because the vocal mic picks up the
speakers. FreeGain gets a copy of the speaker signal (the **reference**)
and continuously learns the path from speaker to mic: delay, room
reflections, EQ of the space. It predicts how much of that reference is in
the mic and **subtracts the prediction**. What's left is mostly the voice.

This is the same family of technique used for echo cancellation in phones
and conferencing systems.

## Signal chain

```
reference ─► [ delay finder ] ─► [ bulk delay ] ─► [ adaptive filter ] ── prediction ──┐
                                                                                        ▼
mic ───────────────────────────────────────────────────────────────────────────► (−) ──► [ gate ] ──► output
```

## The delay finder

Sound takes about 3 ms per metre to travel from speaker to mic, and console
USB/Dante routing can add more. A background thread measures this delay
once a second with **GCC-PHAT** cross-correlation over the last ~2.7 s of
audio. It picks the earliest strong peak, which is the direct sound rather
than a louder reflection. It only accepts an estimate when the peak clearly
stands out and two estimates in a row agree. The reference is then delayed
by that amount (minus a 5 ms safety margin), so the filter's taps are spent
on the room's reverb, not on dead time. In a feedback loop the vocal also
appears in the reference, but *after* the mic; the finder only searches the
other direction, so it isn't fooled.

## The adaptive filter (PBFDAF)

- A **partitioned-block frequency-domain adaptive filter**, the same family
  as the Speex/MDF echo cancellers in video-call software.
- It models 40–340 ms of room response (2,048–16,384 taps at 48 kHz),
  depending on the **Room echo tail** setting.
- It works on blocks of 256 samples using FFTs, so a 16,384-tap filter still
  runs about 9× faster than real time in Python. Blocks that are a multiple
  of 256 add **no latency**.
- Each frequency bin learns at a speed normalised by the reference's power
  in that bin, so it behaves the same at any level or tone balance.
- **Double-talk protection:** once the room is learned, the learning speed
  equals the estimated fraction of the leftover that is still *echo*. Echo
  rises and falls together with the prediction and a voice doesn't, so this
  is measured from how the two co-vary. While someone sings, learning nearly
  stops and the voice isn't learned as feedback. In testing, the voice passed
  through within 1 dB, with the music still cancelled 33–39 dB below it,
  even when the voice was as loud as the PA. A sudden jump in the leftover
  also slows learning immediately.
- **Safety:** bad samples (NaN/Inf from driver glitches) are treated as
  silence. If the filter ever makes the signal louder for several blocks in
  a row, or its state becomes invalid, it resets itself.
- **Cancellation depth** is the ratio of mic power to leftover power over
  each block, in dB.

In simulated rooms (speaker 3–7 m away, 30–150 ms of reverb) it cancels
25–90 dB after a few seconds of music. The previous 5 ms filter managed
0 dB in the same rooms.

## The gate

A simple envelope gate/expander after the filter. Below the threshold, the
output is scaled down in proportion to how far below it is. Attack and
release control how fast it opens and closes.

## Remote control

Console drivers live in `consoles/`:

| Driver | Consoles | Transport |
| --- | --- | --- |
| `osc.py` | Behringer/Midas X32, XAir, M32, MR, Wing, Generic OSC | OSC over UDP, one socket for send and receive |
| `yamaha_rcp.py` | Yamaha TF, DM, QL, CL, Rivage | RCP text lines over TCP |
| `allen_heath.py` | Qu, SQ, dLive, Avantis | MIDI bytes over TCP |
| `soundcraft_ui.py` | Ui12/16/24R | WebSocket |

All drivers share one interface (`consoles/base.py`): connect, names,
mute group, channel mute. Keep-alives, reconnects and "is it responding?"
are handled per protocol.

## Threads

- **Audio thread:** processes each block. It never prints, blocks or
  touches the UI.
- **Driver threads:** network receive and keep-alive.
- **UI thread:** tkinter. Driver events are passed through a queue, since
  tkinter isn't thread-safe.
