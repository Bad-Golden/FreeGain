"""
consoles/profiles.py

The console model list. Each model points at a driver and a protocol
family; models in a family share everything except their channel count
and label.

"status" is shown in the UI so nobody is surprised:
  documented    -- protocol widely documented and used by many tools
  experimental  -- written from published docs, not yet tried on hardware
"""

# ---------- protocol families ----------

_X32_OSC = {
    "driver": "osc",
    "port": 10023,
    "name_address": "/ch/{ch:02d}/config/name",
    "mute_group_address": "/config/mute/{n}",
    "channel_mute_address": "/ch/{ch:02d}/mix/on",
    "channel_mute_values": [1, 0],  # "mix/on" = 1 means NOT muted
    "fader_address": "/ch/{ch:02d}/mix/fader",
    "keepalive": ["/xremote"],
    "meter_request": ["/meters", "/meters/1"],
    "meter_format": "float32",
    "status": "documented",
}

_XAIR_OSC = dict(_X32_OSC, port=10024, meter_format="int16_db")

_WING_OSC = {
    "driver": "osc",
    "port": 2223,
    "name_address": "/ch/{ch}/name",
    "mute_group_address": "/mgrp/{n}/mute",
    "channel_mute_address": "/ch/{ch}/mute",
    "channel_mute_values": [0, 1],
    "fader_address": None,
    "keepalive": [],
    "status": "experimental",
}

_YAMAHA_RCP = {"driver": "yamaha_rcp", "port": 49280, "status": "experimental"}

_AH_NOTE = {"driver": "allen_heath", "port": 51325, "mute_style": "note",
            "midi_channel": 1, "status": "experimental"}
_AH_NRPN = dict(_AH_NOTE, mute_style="nrpn")

_SOUNDCRAFT_UI = {"driver": "soundcraft_ui", "status": "experimental"}


def _models(brand, family, models):
    return {key: dict(family, brand=brand, label=label, max_channels=channels)
            for key, (label, channels) in models.items()}


CONSOLE_PROFILES = {
    "audio_only": {
        "driver": "none", "brand": "Any console (audio only)",
        "label": "No remote control -- audio interface only",
        "max_channels": 64, "status": "documented",
    },
    **_models("Behringer", _XAIR_OSC, {
        "xr12": ("XR12", 12),
        "xr16": ("XR16", 16),
        "xr18": ("XR18 / X18", 16),
    }),
    **_models("Behringer", _X32_OSC, {
        "x32": ("X32 / X32 Compact / X32 Producer", 32),
        "x32_rack": ("X32 Rack / X32 Core", 32),
    }),
    **_models("Behringer", _WING_OSC, {
        "wing": ("Wing / Wing Rack / Wing Compact", 40),
    }),
    **_models("Midas", _XAIR_OSC, {
        "mr12": ("MR12", 12),
        "mr18": ("MR18", 16),
    }),
    **_models("Midas", _X32_OSC, {
        "m32": ("M32 / M32 Live", 32),
        "m32r": ("M32R / M32R Live", 32),
        "m32c": ("M32C", 32),
    }),
    **_models("Yamaha", _YAMAHA_RCP, {
        "tf1": ("TF1", 40),
        "tf3": ("TF3", 48),
        "tf5": ("TF5", 48),
        "tf_rack": ("TF Rack", 40),
        "dm3": ("DM3", 16),
        "dm7": ("DM7", 120),
        "ql1": ("QL1", 32),
        "ql5": ("QL5", 64),
        "cl1": ("CL1", 48),
        "cl3": ("CL3", 64),
        "cl5": ("CL5", 72),
        "rivage": ("Rivage PM series", 144),
    }),
    **_models("Allen & Heath", _AH_NOTE, {
        "qu16": ("Qu-16", 16),
        "qu24": ("Qu-24", 24),
        "qu32": ("Qu-32", 32),
        "qu_pac": ("Qu-Pac", 32),
        "qu_sb": ("Qu-SB", 32),
        "avantis": ("Avantis", 64),
    }),
    **_models("Allen & Heath", dict(_AH_NOTE, port=51328, midi_channel=12), {
        "dlive": ("dLive (MixRack)", 128),
    }),
    **_models("Allen & Heath", _AH_NRPN, {
        "sq5": ("SQ-5", 48),
        "sq6": ("SQ-6", 48),
        "sq7": ("SQ-7", 48),
    }),
    **_models("Soundcraft", _SOUNDCRAFT_UI, {
        "ui12": ("Ui12", 12),
        "ui16": ("Ui16", 16),
        "ui24r": ("Ui24R", 24),
    }),
    "generic_osc": dict(
        _X32_OSC, brand="Other", label="Generic OSC (set addresses in local_config.json)",
        max_channels=32, status="experimental"),
}

DEFAULT_PROFILE = "xr18"

# Options a user may override per console via local_config.json's
# "console_options" (e.g. a non-default MIDI channel or OSC addresses).
OVERRIDABLE_KEYS = {
    "port", "max_channels", "midi_channel", "name_address", "mute_group_address",
    "mute_group_values", "channel_mute_address", "channel_mute_values",
    "fader_address", "keepalive",
}


def brands() -> list:
    seen = []
    for profile in CONSOLE_PROFILES.values():
        if profile["brand"] not in seen:
            seen.append(profile["brand"])
    return seen


def models_for_brand(brand: str) -> list:
    return [key for key, p in CONSOLE_PROFILES.items() if p["brand"] == brand]
