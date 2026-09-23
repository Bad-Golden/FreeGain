# Console Setup

Connecting FreeGain to your console over the network is **optional**. It
adds:
- **Live channel names** in the input pickers
- **Panic mute**: one button to mute the vocal instantly

Audio processing works without it.

## Connecting

1. Put the computer and console on the **same network**.
2. In FreeGain, choose the **Console** brand and model.
3. Type the console's **IP address** in **Mixer IP** and press **Connect**
   (or press Enter).
4. The label turns **green, "Connected to …"**, once the console actually
   answers. If it stays on "Waiting for …", check the IP and network.

## Supported consoles

| Brand | Models | Protocol | Names | Panic mute uses | Status |
| --- | --- | --- | --- | --- | --- |
| Behringer | XR12, XR16, XR18, X18 | OSC, UDP 10024 | yes | mute group 1 | documented |
| Behringer | X32, Compact, Producer, Rack, Core | OSC, UDP 10023 | yes | mute group 1 | documented |
| Midas | MR12, MR18 | OSC, UDP 10024 | yes | mute group 1 | documented |
| Midas | M32, M32R, M32C, M32 Live | OSC, UDP 10023 | yes | mute group 1 | documented |
| Behringer | Wing, Wing Rack, Wing Compact | OSC, UDP 2223 | yes | mute group 1 | experimental |
| Yamaha | TF1/3/5, TF Rack, DM3, DM7, QL1/5, CL1/3/5, Rivage PM | RCP, TCP 49280 | yes | mute group 1 | experimental |
| Allen & Heath | Qu-16/24/32, Qu-Pac, Qu-SB, Avantis | MIDI over TCP 51325 | no | vocal channel mute | experimental |
| Allen & Heath | dLive (MixRack) | MIDI over TCP 51328 | no | vocal channel mute | experimental |
| Allen & Heath | SQ-5/6/7 | MIDI NRPN over TCP 51325 | no | vocal channel mute | experimental |
| Soundcraft | Ui12, Ui16, Ui24R | WebSocket | yes | vocal channel mute | experimental |
| Other | Anything that speaks OSC | Generic OSC | configurable | configurable | experimental |
| Any | Everything else | none (audio only) | – | – | – |

- **Documented:** the protocol is widely published and used by many tools.
- **Experimental:** written from the manufacturer's or community protocol
  documents but not yet tried on that console. The app labels these.
  **Please report back** whether yours works.

## Panic mute

- On consoles **with mute groups**, Panic mute toggles **mute group 1**.
  Assign the channels you want silenced to mute group 1 on the console.
- On consoles **without** remote mute groups, it mutes the **selected vocal
  channel**, assuming console channel *N* = input *N*.
- The button stays **red while muted** and unmutes exactly what it muted.

## Brand notes

### Behringer / Midas (X32, XAir, M32, MR)
- Works out of the box on the default ports.

### Behringer Wing
- Make sure **OSC is enabled** in the Wing's remote/network settings.

### Yamaha (TF, DM, QL, CL, Rivage)
- Uses Yamaha's RCP text protocol on TCP port 49280, the same one
  third-party controllers use.
- The console and computer must be on the same subnet.

### Allen & Heath (Qu, SQ, dLive, Avantis)
- FreeGain sends standard A&H MIDI-over-TCP messages.
- **The MIDI channel must match the console's MIDI setting.** Defaults
  here: channel 1 (Qu, SQ, Avantis) and channel 12 (dLive). To change it,
  see [[Console Options]].
- Channel names aren't fetched, because A&H's name protocol differs per
  family.

### Soundcraft Ui
- Connects the same way the Ui web app does. Names arrive automatically on
  connect.

## Not supported for remote control
PreSonus StudioLive, DiGiCo and Roland use closed protocols. Use **Any
console (audio only)**; feedback suppression works the same.
