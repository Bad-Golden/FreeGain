# PyInstaller spec for FreeGain.
#
# Build (from the repository root, on the target OS):
#   pip install -r requirements.txt pyinstaller
#   pyinstaller packaging/freegain.spec
#
# Output: dist/FreeGain.exe on Windows, dist/FreeGain.app on macOS.
# Console drivers are imported lazily by consoles/__init__.py, so they are
# listed explicitly as hidden imports to make sure they're bundled.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "packaging" / "freegain.ico")

a = Analysis(
    [str(ROOT / "freegain_app.py")],
    pathex=[str(ROOT)],
    datas=[(ICON, ".")] + collect_data_files("_sounddevice_data"),
    hiddenimports=[
        "consoles.osc",
        "consoles.yamaha_rcp",
        "consoles.allen_heath",
        "consoles.soundcraft_ui",
        "websocket",
    ],
    excludes=["pytest", "PIL", "matplotlib", "scipy", "pandas"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS: a normal .app bundle (one-file .app bundles are deprecated).
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name="FreeGain",
              console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="FreeGain", upx=False)
    app = BUNDLE(coll, name="FreeGain.app", bundle_identifier="org.freegain.app",
                 info_plist={"NSMicrophoneUsageDescription":
                             "FreeGain processes live microphone audio to cancel feedback."})
else:
    # Windows: one self-contained FreeGain.exe.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="FreeGain",
        icon=ICON,
        console=False,  # windowed app, no black console box
        upx=False,      # UPX-packed exes trip antivirus heuristics far more often
    )
