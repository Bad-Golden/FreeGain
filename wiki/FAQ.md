# FAQ

**Is FreeGain free?**
Yes. It's MIT-licensed open source.

**Do I need to install Python?**
No. Use `FreeGain.exe` (Windows) or `FreeGain.app` (Mac). Python is only
needed to run from source.

**Does it work with my console?**
Audio processing works with **any** console whose audio reaches the
computer (USB, Dante, or an interface). Remote control (names and panic
mute) is built in for 36 models plus any OSC console; see [[Console Setup]].

**What does it actually remove?**
Sound from the speakers that leaks back into the vocal mic: the build-up
that turns into feedback, and speaker spill. It doesn't remove crowd noise
or other instruments on stage that aren't in the reference signal.

**Will it change how the voice sounds?**
It aims not to. It only subtracts what it predicts came from the speakers,
and stops adapting while someone is singing. The gate afterwards can be
set gently or effectively turned off (threshold at −60 dB).

**How much latency does it add?**
About 11 ms of processing blocks at 48 kHz, plus your interface's own
buffering.

**Does it replace a feedback suppressor or ringing out the system?**
No. Treat it as another tool. Ring out and EQ your system as usual, and
use FreeGain for extra headroom on problem vocals.

**Windows or Mac?**
Both. Windows 10/11 64-bit, and macOS 11 (Big Sur) or newer on Intel or
Apple Silicon.

**Why does my computer warn me when I open it?**
The app isn't code-signed or notarized yet; that costs money every year.
It's a one-time click; see [[Installation]].

**Has it been used at a real gig?**
Not yet. It's beta software with an automated test suite, but no one has
confirmed it on a live rig. Try it at soundcheck first, and please report
how it goes.

**Where are my settings stored?**
See [[Console Options]] for the `local_config.json` locations.
