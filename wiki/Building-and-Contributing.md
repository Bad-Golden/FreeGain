# Building and Contributing

## Project layout

| Path | What it is |
| --- | --- |
| `freegain_app.py` | tkinter UI |
| `audio_engine.py` | Audio I/O (sounddevice/PortAudio), channel routing, runs filter + gate |
| `fdaf_filter.py` | Echo canceller (partitioned-block frequency-domain adaptive filter) |
| `delay_estimator.py` | Speaker-to-mic delay finder (GCC-PHAT, background thread) |
| `diagnostics.py` | "Save diagnostics" report |
| `nlms_filter.py` | Original NLMS filter (reference) and cancellation-depth helper |
| `simple_gate.py` | Envelope gate/expander |
| `consoles/` | Console drivers and the model list (`profiles.py`) |
| `tests/` | pytest suite, including fake consoles over real sockets |
| `benchmark.py` | Real-time headroom check |
| `packaging/` | PyInstaller spec, icon, Windows build script, macOS compatibility check |
| `wiki/` | These wiki pages |
| `.github/workflows/` | Tests, builds, wiki publishing |

## Run from source

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python freegain_app.py
```

## Tests

```
python -m pytest
```

The suite covers the echo canceller in simulated rooms (including
double-talk and room changes), the delay finder, the gate, the audio
callback (no sound card needed), and every console driver against
simulated consoles over UDP/TCP, including garbage floods and reconnects.
GitHub Actions runs it on Windows and Linux for every push.

### Soak test

A long simulated gig through the real audio engine: music at changing
levels, a singer coming and going, the mic moved, the speaker delay
jumping, silence, clipping, driver glitches, irregular block sizes and
settings changed during playback. It prints a per-segment table and fails
on any invalid output, lost voice, poor cancellation or slow processing:

```
python tests/stress_soak.py --minutes 30
```

## Building the apps

The apps are built with PyInstaller from `packaging/freegain.spec`:

```
pip install pyinstaller
pyinstaller --noconfirm --clean packaging/freegain.spec
```

- **Windows** → `dist/FreeGain.exe`, a single file. Or double-click
  `packaging\build_windows.bat`.
- **macOS** → `dist/FreeGain.app`. Build on the same architecture you're
  targeting (Intel or Apple Silicon).

### Automatic builds

`.github/workflows/build.yml` runs on every push and produces three
artifacts:
- `FreeGain-Windows`
- `FreeGain-macOS-AppleSilicon`
- `FreeGain-macOS-Intel`

The Mac builds swap in numpy's older-macOS wheels, and
`packaging/check_macos_min.py` fails the build if anything in the app
needs a macOS newer than 11 (Big Sur).

### Releases

Push a tag like `v1.0.0` and the workflow attaches all three downloads to
a GitHub Release:

```
git tag v1.0.0
git push origin v1.0.0
```

## Adding a console

1. **OSC console:** add an entry to `consoles/profiles.py` with the port,
   channel count and address templates (see the `_X32_OSC` and
   `_WING_OSC` families). No new code is usually needed.
2. **New protocol:** subclass `ConsoleDriver` (`consoles/base.py`), or
   `TCPDriver` (`consoles/tcp.py`) for TCP consoles. Implement
   `connect`, `request_all_channel_names`, `set_mute_group` and/or
   `set_channel_mute`, and set the `supports_*` flags. Register it in
   `consoles/__init__.py`.
3. Add a test in `tests/test_consoles.py` against a fake console
   (`tests/fakes.py`).
4. Mark it `"status": "experimental"` until someone confirms it on real
   hardware.

## Editing this wiki

The wiki pages live in the repository's `wiki/` folder. Edit them there;
`.github/workflows/wiki.yml` publishes them to the GitHub wiki on every
push to `main`. Edits made directly on the wiki website are overwritten
by the next publish.
