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
reference ─┐
           ▼
     [ NLMS adaptive filter ] ── prediction ──┐
                                              ▼
mic ────────────────────────────────────► (−) ──► [ gate ] ──► output
```

## The adaptive filter (NLMS)

- A **normalized least-mean-squares** filter with 256 taps, about 5.3 ms
  of room response at 48 kHz.
- Every sample it compares the prediction with the actual mic and nudges
  the taps to reduce the error, scaled by the reference's recent energy so
  it behaves the same at any level.
- **Double-talk protection:** when the leftover signal suddenly jumps well
  above its recent average (someone is actually singing or talking), the
  filter stops adapting. That way it doesn't learn the voice as feedback
  and cancel it.
- **Safety:** bad samples (NaN/Inf from driver glitches) are treated as
  silence, and the filter resets itself if its state ever becomes invalid.
- **Cancellation depth** is the ratio of mic power to leftover power over
  each block, in dB.

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
