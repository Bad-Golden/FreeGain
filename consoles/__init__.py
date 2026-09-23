"""
consoles -- remote-control drivers for many mixing consoles.

    from consoles import create_driver
    driver = create_driver("tf5")
    driver.on_channel_name = ...
    driver.connect("192.168.0.128")
"""

from .base import AudioOnlyDriver, ConsoleDriver
from .profiles import (CONSOLE_PROFILES, DEFAULT_PROFILE, OVERRIDABLE_KEYS, brands,
                       models_for_brand)

__all__ = ["CONSOLE_PROFILES", "DEFAULT_PROFILE", "ConsoleDriver", "brands",
           "create_driver", "models_for_brand"]


def _driver_class(name: str):
    # Imported lazily so e.g. python-osc is only needed for OSC consoles.
    if name == "osc":
        from .osc import OSCDriver
        return OSCDriver
    if name == "yamaha_rcp":
        from .yamaha_rcp import YamahaRCPDriver
        return YamahaRCPDriver
    if name == "allen_heath":
        from .allen_heath import AllenHeathDriver
        return AllenHeathDriver
    if name == "soundcraft_ui":
        from .soundcraft_ui import SoundcraftUiDriver
        return SoundcraftUiDriver
    if name == "none":
        return AudioOnlyDriver
    raise ValueError(f"Unknown driver '{name}'")


def create_driver(console_key: str, overrides: dict = None) -> ConsoleDriver:
    if console_key not in CONSOLE_PROFILES:
        raise ValueError(f"Unknown console '{console_key}', "
                         f"expected one of {list(CONSOLE_PROFILES)}")
    profile = dict(CONSOLE_PROFILES[console_key])
    for key, value in (overrides or {}).items():
        if key in OVERRIDABLE_KEYS:
            profile[key] = value
    return _driver_class(profile["driver"])(profile)
