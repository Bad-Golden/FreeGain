"""
console_profiles.py

Behringer/Midas XAir and X32 use the same general OSC address scheme
(both are documented in Behringer's own OSC protocol PDFs) but differ in:
  - UDP port: X32/M32 family = 10023, XAir family = 10024
  - Channel count: XAir models max out at 16-18 input channels depending
    on model (X18, XR18, XR16, XR12); X32 supports up to 32.
  - Meter blob encoding: XAir sends signed 16-bit values in 1/256 dB
    units; X32/M32 send 32-bit floats as linear 0..1 levels. Both are
    little-endian and prefixed with an int32 value count.

This is just configuration data -- the actual OSC address patterns
("/ch/01/mix/fader" etc.) are identical between the two families, so
MixerOSCClient itself doesn't need to change, just which profile it's
configured with.
"""

CONSOLE_PROFILES = {
    "xair": {
        "label": "Behringer XAir (X18 / XR18 / XR16 / XR12)",
        "port": 10024,
        "max_channels": 18,  # XR18's ceiling; X18/XR16/XR12 have fewer --
                              # the dropdown just won't get names for
                              # channels your specific model doesn't have.
        "meter_format": "int16_db",
    },
    "x32": {
        "label": "Behringer X32 family",
        "port": 10023,
        "max_channels": 32,
        "meter_format": "float32",
    },
    "m32": {
        "label": "Midas M32",
        # Same protocol family as X32 -- identical port and channel count.
        "port": 10023,
        "max_channels": 32,
        "meter_format": "float32",
    },
}

DEFAULT_PROFILE = "xair"
