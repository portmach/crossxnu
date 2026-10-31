#!/usr/bin/env python3
"""Create synthetic codeless kexts for libraries a kext declares but that the
KDK does not ship.

apfs declares `OSBundleLibraries_x86_64` (an architecture-specific variant of
OSBundleLibraries) containing `com.apple.driver.AppleEFINVRAM`, which the KDK
does not contain at all.  OSKext refuses to load a kext whose declared library
is not registered, so a stub entry with the right identifier and version is
enough: no symbols are imported from it (the symbol closure is already
satisfied by the kernel and the other kexts).

Usage:
  python3 tools/kext-loader/make-codeless-stubs.py OUT_DIR KEXT_DIR [KEXT_DIR...]
"""
import os
import plistlib
import sys

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>CFBundleIdentifier</key>
\t<string>{bid}</string>
\t<key>CFBundleVersion</key>
\t<string>{ver}</string>
\t<key>CFBundlePackageType</key>
\t<string>KEXT</string>
\t<key>CFBundleName</key>
\t<string>{name}</string>
\t<key>OSBundleCompatibleVersion</key>
\t<string>{ver}</string>
</dict>
</plist>
"""


def libs(info):
    out = {}
    for key in ("OSBundleLibraries", "OSBundleLibraries_x86_64",
                "OSBundleLibraries_arm64", "OSBundleLibraries_arm64e"):
        for lib, ver in (info.get(key) or {}).items():
            out[lib] = ver
    return out


def main():
    out_dir = sys.argv[1]
    kext_dirs = sys.argv[2:]

    provided = set()
    needed = {}
    for kd in kext_dirs:
        plist = os.path.join(kd, "Contents", "Info.plist")
        if not os.path.exists(plist):
            plist = os.path.join(kd, "Info.plist")
        try:
            info = plistlib.load(open(plist, "rb"))
        except Exception:
            continue
        provided.add(info.get("CFBundleIdentifier"))
        for lib, ver in libs(info).items():
            if lib.startswith("com.apple.kpi."):
                continue
            needed.setdefault(lib, ver)

    missing = {k: v for k, v in needed.items() if k not in provided}
    print("provided: %d, needed: %d, missing: %d" % (len(provided), len(needed), len(missing)))
    for bid, ver in sorted(missing.items()):
        name = bid.split(".")[-1]
        d = os.path.join(out_dir, name + ".kext", "Contents")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "Info.plist"), "w") as f:
            f.write(PLIST.format(bid=bid, ver=ver, name=name))
        print("stub:", bid, ver, "->", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
