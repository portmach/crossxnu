#!/usr/bin/env python3
"""Classify every kext of an extracted KDK by architecture and fixup style.

Motivation: a kernel collection built for x86_64 cannot host a kext that only
ships an arm64 slice, and a kext that uses LC_DYLD_CHAINED_FIXUPS needs a
linker that applies the chains.  Both facts decide which kexts are usable, so
scan the tree and print a table instead of discovering it one panic at a time.

Usage:
  kdk-slice-scan.py KEXTS_DIR [--only NAME ...] [--summary]
"""

import argparse
import os
import struct
import sys

LC_SEGMENT_64 = 0x19
LC_DYLD_CHAINED_FIXUPS = 0x34 | 0x80000000
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x22 | 0x80000000
LC_DYSYMTAB = 0xB

FAT = (0xCAFEBABE, 0xCAFEBABF)
CPU_X86_64 = 0x01000007
CPU_ARM64 = 0x0100000C


def slices(data):
    """[(cputype, offset, size)] for a thin or fat Mach-O."""
    if len(data) < 8:
        return []
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in FAT:
        n = struct.unpack_from(">I", data, 4)[0]
        wide = magic == 0xCAFEBABF
        es = 32 if wide else 20
        out = []
        for i in range(n):
            b = 8 + i * es
            if wide:
                ct, cst, off, sz, _, _ = struct.unpack_from(">IIQQII", data, b)
            else:
                ct, cst, off, sz, _ = struct.unpack_from(">IIIII", data, b)
            out.append((ct, off, sz))
        return out
    mt = struct.unpack_from("<I", data, 0)[0]
    if mt in (0xFEEDFACF, 0xFEEDFACE):
        ct = struct.unpack_from("<I", data, 4)[0]
        return [(ct, 0, len(data))]
    return []


def scan_slice(data, off, size):
    """(has_chainfix, ptr_formats, has_dyld_info, has_dysymtab, nseg) for a slice."""
    if off + 32 > len(data):
        return None
    magic = struct.unpack_from("<I", data, off)[0]
    if magic != 0xFEEDFACF:
        return {"chain": None, "fmt": set(), "dyld_info": None, "dysymtab": None,
                "nseg": 0}
    ncmds, sizeofcmds = struct.unpack_from("<II", data, off + 16)
    p = off + 32
    end = p + sizeofcmds
    chain = None
    fmt = set()
    dyld_info = False
    dysymtab = False
    nseg = 0
    for _ in range(ncmds):
        if p + 8 > end:
            break
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmdsize < 8:
            break
        if cmd == LC_SEGMENT_64:
            nseg += 1
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            dataoff, datasize = struct.unpack_from("<II", data, p + 8)
            chain = (dataoff, datasize)
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            fields = struct.unpack_from("<10I", data, p + 8)
            if any(fields):
                dyld_info = True
        elif cmd == LC_DYSYMTAB:
            dysymtab = True
        p += cmdsize

    if chain:
        base = off + chain[0]
        if base + 28 <= len(data):
            starts_off = struct.unpack_from("<I", data, base + 4)[0]
            img = base + starts_off
            seg_count = struct.unpack_from("<I", data, img)[0]
            for si in range(min(seg_count, 64)):
                soff = struct.unpack_from("<I", data, img + 4 + si * 4)[0]
                if soff == 0:
                    continue
                ss = img + soff
                if ss + 8 > len(data):
                    continue
                fmt.add(struct.unpack_from("<H", data, ss + 6)[0])
    return {"chain": chain, "fmt": fmt, "dyld_info": dyld_info,
            "dysymtab": dysymtab, "nseg": nseg}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--chainfix", action="store_true",
                    help="list only x86_64 kexts using chained fixups")
    args = ap.parse_args()

    rows = []
    for name in sorted(os.listdir(args.dir)):
        if not name.endswith(".kext"):
            continue
        stem = name[:-5]
        if args.only and not any(o == stem for o in args.only):
            continue
        exe = os.path.join(args.dir, name, "Contents", "MacOS", stem)
        if not os.path.exists(exe):
            # fall back to whatever CFBundleExecutable-ish file exists
            macos = os.path.join(args.dir, name, "Contents", "MacOS")
            cand = [f for f in os.listdir(macos)] if os.path.isdir(macos) else []
            if not cand:
                rows.append((stem, "no-exec", "-", "-"))
                continue
            exe = os.path.join(macos, cand[0])
        try:
            data = open(exe, "rb").read()
        except OSError as e:
            rows.append((stem, "unreadable", str(e), "-"))
            continue

        sl = slices(data)
        archs = {}
        for ct, off, size in sl:
            if ct == CPU_X86_64:
                archs["x86_64"] = scan_slice(data, off, size)
            elif ct == CPU_ARM64:
                archs["arm64"] = scan_slice(data, off, size)

        if not archs:
            rows.append((stem, "no-macho", "-", "-"))
            continue

        archname = "+".join(archs.keys())
        x = archs.get("x86_64")
        if x:
            chain = "chainfix" if x["chain"] else ("dyldinfo" if x["dyld_info"] else "plain")
            fmt = ",".join(str(f) for f in sorted(x["fmt"]))
            rows.append((stem, archname, chain, fmt or "-"))
        else:
            a = archs["arm64"]
            chain = "chainfix" if a["chain"] else ("dyldinfo" if a["dyld_info"] else "plain")
            fmt = ",".join(str(f) for f in sorted(a["fmt"]))
            rows.append((stem, archname + "(NO-x86_64)", "arm:" + chain, fmt or "-"))

    if args.chainfix:
        rows = [r for r in rows if r[2] == "chainfix"]

    w = max(len(r[0]) for r in rows) if rows else 10
    for stem, arch, chain, fmt in rows:
        print("%-*s  %-26s  %-9s  %s" % (w, stem, arch, chain, fmt))

    if args.summary:
        from collections import Counter
        c = Counter()
        for _, arch, chain, _f in rows:
            c["arm64-only" if "NO-x86_64" in arch else "has-x86_64"] += 1
            if chain == "chainfix":
                c["x86_64-chained"] += 1
        print("\n", dict(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
