"""
check_macos_min.py -- fail the build if anything inside a macOS .app needs
a newer macOS than we promise to support.

Reads the minimum-OS field (LC_BUILD_VERSION / LC_VERSION_MIN_MACOSX)
from every Mach-O binary in the bundle. Wheels such as numpy's publish
separate builds for recent macOS only, and pip on a new build machine
happily picks those -- producing an app that silently won't start on
older Macs.

Usage: python packaging/check_macos_min.py dist/FreeGain.app 11.0
"""

import os
import struct
import sys

LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32


def _version(packed: int) -> tuple:
    return (packed >> 16, (packed >> 8) & 0xFF)


def min_versions(path: str) -> list:
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 8:
        return []
    offsets = []
    if struct.unpack_from("<I", data, 0)[0] in (0xFEEDFACF, 0xFEEDFACE):
        offsets = [0]
    elif struct.unpack_from(">I", data, 0)[0] == 0xCAFEBABE:  # universal binary
        count = struct.unpack_from(">I", data, 4)[0]
        offsets = [struct.unpack_from(">5I", data, 8 + i * 20)[2] for i in range(count)]
    found = []
    for base in offsets:
        is64 = struct.unpack_from("<I", data, base)[0] == 0xFEEDFACF
        ncmds = struct.unpack_from("<I", data, base + 16)[0]
        pos = base + (32 if is64 else 28)
        for _ in range(ncmds):
            cmd, size = struct.unpack_from("<II", data, pos)
            if cmd == LC_BUILD_VERSION:
                found.append(_version(struct.unpack_from("<I", data, pos + 12)[0]))
            elif cmd == LC_VERSION_MIN_MACOSX:
                found.append(_version(struct.unpack_from("<I", data, pos + 8)[0]))
            pos += size
    return found


def main():
    bundle, limit = sys.argv[1], tuple(int(x) for x in sys.argv[2].split("."))
    too_new = []
    for root, _dirs, files in os.walk(bundle):
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            try:
                versions = min_versions(path)
            except (OSError, struct.error):
                continue
            if versions and max(versions) > limit:
                too_new.append((max(versions), os.path.relpath(path, bundle)))
    if too_new:
        print(f"These files need a macOS newer than {sys.argv[2]}:")
        for version, path in sorted(too_new):
            print(f"  {version[0]}.{version[1]}  {path}")
        sys.exit(1)
    print(f"OK: everything in {bundle} runs on macOS {sys.argv[2]} or newer.")


if __name__ == "__main__":
    main()
