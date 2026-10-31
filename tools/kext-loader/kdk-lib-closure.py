#!/usr/bin/env python3
"""Build the full OSBundleLibraries closure for a set of KDK kexts.

Symbol-level dependencies (kdk-deps.py) are not enough: OSKext also refuses a
kext whose declared OSBundleLibraries are not registered, even when none of
their symbols are used.  This walks the Info.plist dependency graph across the
whole KDK extension directory and emits the ordering plus codeless entries.

Usage:
  python3 tools/kext-loader/kdk-lib-closure.py KEXT_DIR ROOT_ID [ROOT_ID ...]
    --kexts-out FILE      write kext bundle paths (link order) one per line
    --codeless-out FILE   write codeless bundle paths one per line
"""
import os
import plistlib
import sys


def main():
    ext_dir = sys.argv[1]
    roots = []
    for a in sys.argv[2:]:
        if a.startswith("--"):
            break
        roots.append(a)
    kexts_out = codeless_out = None
    if "--kexts-out" in sys.argv:
        kexts_out = sys.argv[sys.argv.index("--kexts-out") + 1]
    if "--codeless-out" in sys.argv:
        codeless_out = sys.argv[sys.argv.index("--codeless-out") + 1]

    by_id = {}
    for name in sorted(os.listdir(ext_dir)):
        if not name.endswith(".kext"):
            continue
        path = os.path.join(ext_dir, name)
        plist = os.path.join(path, "Contents", "Info.plist")
        if not os.path.exists(plist):
            continue
        try:
            info = plistlib.load(open(plist, "rb"))
        except Exception:
            continue
        bid = info.get("CFBundleIdentifier")
        if bid:
            by_id[bid] = (path, info)

    # BFS over OSBundleLibraries.
    kexts, codeless, seen = [], [], set()
    queue = list(roots)
    while queue:
        bid = queue.pop(0)
        if bid in seen:
            continue
        seen.add(bid)
        if bid not in by_id:
            print("missing bundle: %s" % bid, file=sys.stderr)
            continue
        path, info = by_id[bid]
        has_exe = os.path.exists(os.path.join(path, "Contents", "MacOS",
                                              info.get("CFBundleExecutable", "")))
        (kexts if has_exe else codeless).append(path)
        for lib in (info.get("OSBundleLibraries") or {}):
            if lib.startswith("com.apple.kpi."):
                continue
            queue.append(lib)

    # Link order: dependencies first.  Simple approximation: reverse BFS order.
    kexts.reverse()
    print("kexts (%d):" % len(kexts))
    for k in kexts:
        print("  " + k)
    print("codeless (%d):" % len(codeless))
    for c in codeless:
        print("  " + c)
    if kexts_out:
        open(kexts_out, "w").write("\n".join(kexts) + "\n")
    if codeless_out:
        open(codeless_out, "w").write("\n".join(codeless) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
