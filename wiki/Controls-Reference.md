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
| **Vocal goes back to the PA (feedback mode)** | On by default. For the normal case where FreeGain's output feeds the PA or monitors, so the loop is closed. The filter learns the room without learning the singer (pre-whitening), and the output is shifted up 5 Hz to keep the loop stable. Turn it off only for spill from a source that never contains this vocal; the filter then learns about 5x faster |
| **Room echo tail** | How much room reverb the filter models: 40 ms (small room), 85 ms (typical, default), 170 ms (large hall), 340 ms (very live). Longer cancels more in echoey rooms but learns more slowly and uses a little more CPU. Changing it keeps what's been learned |
| **Find speaker delay automatically** | Measures how late the speaker sound reaches the mic (needs music playing) and lines the signals up, so the echo tail is spent on the room, not on travel time. Handles delays up to 500 ms |
| **Speaker delay** | The measured delay, e.g. "9.2 ms". About 3 ms per metre between speaker and mic, plus any console/USB routing delay |
| **Relearn room** | Forgets what the filter learned, re-measures the delay and starts fresh. Use after moving mics or speakers |
| **Panic mute** | Mutes mute group 1, or the vocal channel on consoles without mute groups. Stays red while muted; click again to unmute |

## Main area

| Control | What it does |
| --- | --- |
| **Active / Bypassed** | Active = processing on. Bypassed = mic passes through untouched |
| **Input meter** | Vocal mic level, −60 to 0 dBFS |
| **Cancellation depth** | How much the filter is removing, in dB (0–30 dB scale). Also shows the audio CPU load, and a dropout count if the computer falls behind |
| **Mic gain** | −24 to +24 dB. Boosts or trims the vocal after echo cancelling and before the gate (so it also moves the vocal relative to the gate threshold). Changing it never forces a relearn. The Input meter shows the mic after this gain. Double-click to reset to 0 dB |
| **Output level** | −40 to +12 dB. The final level sent back to the console. Double-click to reset to 0 dB |
| **LIMIT** | Lights red when the soft output limiter is working (output within 1 dB of full scale). If it's on a lot, turn **Output level** down |
| **Threshold** | Gate threshold, −60 to 0 dB. Below it the output is turned down |
| **Attack** | How fast the gate opens, 0.5–50 ms |
| **Release** | How fast the gate closes, 10–1000 ms |
| **Output meter** | Processed vocal level |
| **Status line** | Sample rate, inputs in use, and any errors |
| **Save diagnostics…** | Saves a JSON report of the session (settings, devices, delay, CPU, dropouts, per-second cancellation history) to send with test results. No audio is recorded |

All settings are saved when you close the window.
