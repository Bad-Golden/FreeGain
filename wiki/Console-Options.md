# Console Options

Protocol details can be changed per console model without touching code.
Edit `local_config.json` **while FreeGain is closed**. It's created after
the first run:

| Platform | Location |
| --- | --- |
| Windows (exe) | `%APPDATA%\FreeGain\local_config.json` |
| Mac (app) | `~/Library/Application Support/FreeGain/local_config.json` |
| From source | next to `freegain_app.py` |

Add a `"console_options"` section keyed by console model:

```json
"console_options": {
  "dlive": { "midi_channel": 1 },
  "tf5":   { "port": 49280 },
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

## Allowed keys

| Key | Meaning |
| --- | --- |
| `port` | Network port on the console |
| `max_channels` | How many input channels to list and query |
| `midi_channel` | Allen & Heath MIDI channel (1–16) |
| `name_address` | OSC address that queries and returns a channel name |
| `channel_mute_address` | OSC address that mutes a channel |
| `channel_mute_values` | `[unmuted, muted]` values sent to that address |
| `mute_group_address` | OSC address for a mute group |
| `mute_group_values` | `[unmuted, muted]` values for mute groups |
| `fader_address` | OSC address for a channel fader (0.0–1.0) |
| `keepalive` | OSC addresses re-sent every few seconds to keep subscriptions alive |

In OSC addresses, `{ch}` is the channel number and `{n}` the mute-group
number. Use `{ch:02d}` for zero-padded numbers (`01`, `02`…).

Example: the X32 profile uses `/ch/{ch:02d}/mix/on` with values `[1, 0]`,
because on X32 "on = 1" means **not** muted.

## Model keys

`audio_only`, `xr12`, `xr16`, `xr18`, `x32`, `x32_rack`, `wing`, `mr12`,
`mr18`, `m32`, `m32r`, `m32c`, `tf1`, `tf3`, `tf5`, `tf_rack`, `dm3`,
`dm7`, `ql1`, `ql5`, `cl1`, `cl3`, `cl5`, `rivage`, `qu16`, `qu24`,
`qu32`, `qu_pac`, `qu_sb`, `avantis`, `dlive`, `sq5`, `sq6`, `sq7`,
`ui12`, `ui16`, `ui24r`, `generic_osc`.

## Adding a console permanently

Models live in `consoles/profiles.py`. A console that speaks OSC usually
needs only a new entry there; see [[Building and Contributing]].
