# Troubleshooting

## Installing and opening

**Windows: "Windows protected your PC"**
Click **More info → Run anyway**. It appears because the app isn't
code-signed.

**Windows: `run_freegain.bat` says Python is missing, or "Installing
requirements failed"**
`run_freegain.bat` is for running from **source** and needs Python. Use
**`FreeGain.exe`** instead; it needs nothing installed (see
[[Installation]]). If you do want the source version, read the lines
starting with `ERROR` above the message. They give the real cause, often a
network or firewall blocking pypi.org.

**Windows: nothing happens / it runs from inside the zip**
Extract the zip first (**right-click → Extract All**), then run the file
from the extracted folder.

**Mac: "Apple could not verify FreeGain is free of malware"**
Expected for apps that aren't notarized. See
[Installation → Mac](Installation#mac) for the one-time steps, or run
`xattr -dr com.apple.quarantine /Applications/FreeGain.app` in Terminal.

**Mac: "FreeGain can't be opened" / "not supported on this Mac"**
You probably downloaded the wrong version. Intel Macs need
**FreeGain-macOS-Intel**; M1/M2/M3/M4 Macs need
**FreeGain-macOS-AppleSilicon**. FreeGain needs **macOS 11 (Big Sur) or
newer**.

## Audio

**Status line says "Audio not running: …"**
- Pick your console's interface in **Audio in** and press **Apply**.
- Press **↻** if you plugged the interface in after starting FreeGain.
- On Windows try the **[ASIO]** or **[Windows WASAPI]** entry.

**"… has 2 input channel(s), but channel N was selected"**
You chose an input number the device doesn't have. On Windows this usually
means you picked the **[MME]** entry. Choose **[ASIO]** or **[WASAPI]** to
see all channels, or install the console's driver (see [[Audio Setup]]).

**Input meter doesn't move**
- Check the **Vocal mic input** number matches where the mic arrives.
- Check the console actually sends that channel over USB/Dante.
- Mac: allow microphone access in **System Settings → Privacy & Security →
  Microphone**.

**Cancellation depth stays at 0 dB**
- Is the button set to **Active**, not Bypassed?
- The **Reference** must carry what's going to the speakers, and there must
  be sound coming out of them. With a silent reference there's nothing to
  cancel.
- Vocal and Reference must be **different** inputs.

**Cancellation depth is low (under ~10 dB)**
- Check **Speaker delay** in the left panel. If it keeps saying
  "measuring…", the reference and mic don't share enough sound: play music
  through the speakers, and check the Reference is the feed those speakers
  get.
- Try a longer **Room echo tail** (170 ms) in big or echoey rooms.
- If the reference passes through processing the mic doesn't hear (heavy
  compression, pitch/delay effects), take the reference from before those
  effects.
- Press **Save diagnostics…** and send the file.

**Dropouts counter keeps climbing / crackles**
The computer can't keep up. Close other programs, use ASIO on Windows, or
run `python benchmark.py` from source to check headroom. Developers can
lower `num_taps` or raise `block_size` in `AudioEngine`.

**I hear the vocal twice / with an echo**
Both the raw mic channel and FreeGain's return are in the mix. Use only
the return channel.

## Console connection

**Stays on "Waiting for …"**
- Check the IP (it's shown in the console's network settings).
- Computer and console must be on the same network/subnet.
- Pick the right **model**, since ports differ between families.
- Behringer Wing: enable OSC on the console.
- Firewalls can block UDP; allow FreeGain through.

**"… stopped responding"**
The console was reachable but went quiet: network dropped, console
rebooted, or IP changed. Press **Connect** again.

**Panic mute does nothing**
- Mute-group consoles: assign channels to **mute group 1** on the console.
- Allen & Heath: the **MIDI channel** must match the console's setting
  ([[Console Options]]).

**No channel names**
Allen & Heath doesn't provide them. For other consoles, check you're
connected (green label).

## Still stuck?
Open an **Issue** on GitHub with:
- the file from **Save diagnostics…** (bottom right of the window),
- your console model,
- a screenshot of FreeGain, including the bottom status line.
