# Controls Reference

## Top rows

| Control | What it does |
| --- | --- |
| **Console** (brand + model) | Which console to remote-control. Choose "Any console (audio only)" to skip remote control. Models marked *experimental* are shown in amber |
| **Mixer IP** | The console's network address |
| **Connect** | Connects to the console. The label shows *Waiting…*, *Connected* (green) or *stopped responding* (red) |
| **Audio in / out** | Audio devices, labelled with driver type (ASIO, WASAPI, Core Audio…) |
| **Apply** | (Re)starts audio with the selected devices and inputs |
| **↻** | Re-scans for audio devices |

## Left panel

| Control | What it does |
| --- | --- |
| **Vocal mic input** | Input carrying the vocal mic. Shows console channel names when connected. The dot is green when there's signal |
| **Reference (speaker feed) input** | Input carrying what goes to the speakers. The dot is green when there's signal |
| **Relearn room** | Forgets what the filter learned and starts fresh. Use after moving mics or speakers |
| **Panic mute** | Mutes mute group 1, or the vocal channel on consoles without mute groups. Stays red while muted; click again to unmute |

## Main area

| Control | What it does |
| --- | --- |
| **Active / Bypassed** | Active = processing on. Bypassed = mic passes through untouched |
| **Input meter** | Vocal mic level, −60 to 0 dBFS |
| **Cancellation depth** | How much the filter is removing, in dB (0–30 dB scale). Also shows a dropout count if the computer falls behind |
| **Threshold** | Gate threshold, −60 to 0 dB. Below it the output is turned down |
| **Attack** | How fast the gate opens, 0.5–50 ms |
| **Release** | How fast the gate closes, 10–1000 ms |
| **Output meter** | Processed vocal level |
| **Status line** | Sample rate, inputs in use, and any errors |

All settings are saved when you close the window.
