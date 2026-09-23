FreeGain -- live feedback suppression for mixing consoles
==========================================================

WINDOWS
  1. Unzip this folder anywhere (Desktop, Documents, a USB stick...).
  2. Double-click FreeGain.exe. Nothing to install, no Python needed.
  3. The first time, Windows may show "Windows protected your PC",
     because the app isn't code-signed. Click "More info", then
     "Run anyway". Windows remembers that choice.

MAC
  1. Unzip and drag FreeGain.app to Applications.
  2. The first time, right-click FreeGain.app and choose Open (it isn't
     notarized by Apple), then allow microphone access when asked.

GETTING STARTED
  1. Console: pick your brand and model, or "Any console (audio only)".
  2. Audio in / out: pick your console's audio interface and press Apply.
     On Windows, pick the [ASIO] entry if there is one (most console USB
     drivers and Dante Virtual Soundcard), otherwise [Windows WASAPI].
  3. Vocal mic input: the input carrying the vocal mic.
     Reference input: the input carrying your speaker/main mix feed.
  4. Send the output back to a spare console input and use that channel
     in place of the raw mic.
  5. Optional: enter the console's IP and press Connect for channel names
     and the Panic mute button.

Settings are saved in %APPDATA%\FreeGain\local_config.json on Windows,
or ~/Library/Application Support/FreeGain on Mac.

This is beta software that hasn't yet been proven on a live rig. Try it at
soundcheck first.
