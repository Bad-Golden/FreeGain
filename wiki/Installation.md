# Installation

FreeGain comes as a ready-to-run app. **You don't need Python or anything
else** unless you want to run it from source.

## Where to download

Every change pushed to GitHub builds fresh downloads automatically:

1. Open the repository's **Actions** tab and click the latest successful
   **build** run.
2. Scroll to **Artifacts** and download the one for your computer. You
   need to be signed in to GitHub.

| File | For |
| --- | --- |
| `FreeGain-Windows` | Windows 10/11, 64-bit |
| `FreeGain-macOS-Intel` | Macs with an Intel processor |
| `FreeGain-macOS-AppleSilicon` | Macs with an Apple M1/M2/M3/M4 chip |

GitHub wraps each artifact in an extra zip, so unzip twice.

When a version tag such as `v1.0.0` is pushed, the same files are also
published on the repository's **Releases** page, which anyone can download
without signing in.

## Windows

1. Right-click the zip and choose **Extract All… → Extract**. Don't run it
   from inside the zip.
2. Open the extracted folder and double-click **`FreeGain.exe`**.
3. The first time, Windows may show **"Windows protected your PC"**. Click
   **More info → Run anyway**. This appears because the app isn't
   code-signed; Windows remembers your choice.

Settings are saved in `%APPDATA%\FreeGain\local_config.json`.

## Mac

**Which download?** Apple menu → **About This Mac**:
- "Processor: … Intel" → **FreeGain-macOS-Intel**
- "Chip: Apple M…" → **FreeGain-macOS-AppleSilicon**

1. Double-click the zip, then drag **FreeGain.app** into **Applications**.
2. **First launch.** FreeGain isn't notarized by Apple yet, so macOS says
   it "could not verify FreeGain is free of malware". To open it anyway:
   - **Big Sur / Monterey / Ventura / Sonoma:** right-click FreeGain.app →
     **Open** → **Open**.
   - **Sequoia and newer:** open FreeGain once, click **Done**, then go to
     **System Settings → Privacy & Security**, scroll down and click
     **Open Anyway**.
   - **Any version, from Terminal:**
     ```
     xattr -dr com.apple.quarantine /Applications/FreeGain.app
     ```
3. Allow **microphone access** when asked. FreeGain needs it to hear your
   console.

Settings are saved in `~/Library/Application Support/FreeGain/local_config.json`.

## Running from source (optional)

Only needed if you want to change the code.

**Windows:** install Python 3.10+ from
[python.org](https://www.python.org/downloads/) and tick **"Add python.exe
to PATH"**. Then double-click `run_freegain.bat`. The first run downloads
the four required packages (about a minute, needs internet).

**Mac / Linux:**
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python freegain_app.py
```

Required packages: `numpy`, `sounddevice`, `python-osc`, `websocket-client`.
