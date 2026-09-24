"""
diagnostics.py

Builds the report written by the "Save diagnostics" button: everything
needed to understand a test session without screenshots -- app and system
versions, audio devices, settings, the filter's state, the measured
speaker delay, CPU load, dropouts, a per-second history of cancellation
depth and levels, console connection state and recent status messages.

The report is plain JSON so it can be read by eye or loaded into a
spreadsheet. It contains no audio.
"""

import json
import platform
import sys
import time
from pathlib import Path

from version import __version__


def build_report(engine, console=None, config=None, devices=None, messages=None) -> dict:
    report = {
        "freegain_version": __version__,
        "created": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "system": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "frozen_app": bool(getattr(sys, "frozen", False)),
        },
        "audio": engine.diagnostics(),
        "settings": dict(config or {}),
        "devices": [
            {"index": i, "name": name, "host_api": api, "inputs": ins, "outputs": outs}
            for i, name, api, ins, outs in (devices or [])
        ],
        "recent_messages": list(messages or [])[-100:],
    }
    try:
        import numpy
        report["system"]["numpy"] = numpy.__version__
    except Exception:  # pragma: no cover
        pass
    if console is not None:
        report["console"] = {
            "driver": type(console).__name__,
            "model": console.profile.get("label"),
            "host": console.host,
            "connected": console.connected,
            "responding": console.is_responding(),
            "seconds_since_reply": (round(time.monotonic() - console.last_reply_time, 1)
                                    if console.last_reply_time else None),
            "supports": {
                "names": console.supports_names,
                "mute_groups": console.supports_mute_groups,
                "channel_mute": console.supports_channel_mute,
            },
        }
    return report


def default_filename() -> str:
    return time.strftime("freegain-diagnostics-%Y%m%d-%H%M%S.json")


def default_folder() -> Path:
    for candidate in (Path.home() / "Desktop", Path.home() / "Documents", Path.home()):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def write_report(report: dict, path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
