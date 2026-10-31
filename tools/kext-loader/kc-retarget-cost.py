#!/usr/bin/env python3
"""Estimate how much work it is to re-target an extracted Apple kext.

Counts, for an extracted kext image:
  * direct call/jmp sites in __text whose target is outside the image,
  * pointer-sized values in __got/__DATA_CONST/__DATA that point outside it,
and resolves those external addresses through the *collection's* symbol tables
(primary kernel + every kext image) to symbol names, then checks how many of
those names our own kernel provides.

Usage:
  python3 tools/kext-loader/kc-retarget-cost.py KC EXTRACTED_KEXT OUR_KERNEL
"""
import os
import struct
import subprocess
import sys

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_FILESET_ENTRY = 0x80000035

NM = os.environ.get("CROSSXNU_NM", "build/cctools/bin/x86_64-apple-darwin11-nm")
KERNEL_RANGE = (0xFFFFFF8000000000, 0xFFFFFFFF00000000)


def cstr(b):
    return b.split(b"\0")[0].decode(errors="replace")


def segments(data, off):
    ncmds = struct.unpack_from("<I", data, off + 16)[0]
    p = off + 32
    segs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SEGMENT_64:
            name = cstr(data[p + 8:p + 24])
            vm, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, p + 24)
            nsects = struct.unpack_from("<I", data, p + 64)[0]
            sects = []
            for j in range(nsects):
                sec = p + 72 + j * 80
                sname = cstr(data[sec:sec + 16])
                addr, size = struct.unpack_from("<QQ", data, sec + 32)
                soff = struct.unpack_from("<I", data, sec + 48)[0]
                sects.append((sname, addr, size, soff))
            segs.append({"name": name, "vm": vm, "vmsz": vmsz, "foff": foff, "fsz": fsz, "sects": sects})
        p += cmdsize
    return segs


def kext_symbols(data, off, segs):
    ncmds = struct.unpack_from("<I", data, off + 16)[0]
    p = off + 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, p + 8)
            out = {}
            for i in range(nsyms):
                e = symoff + i * 16
                strx, ntype, sect, desc, value = struct.unpack_from("<IBBHQ", data, e)
                name = cstr(data[stroff + strx:stroff + strx + 200])
                if name and (ntype & 0x0e) in (0x0e, 0x02) and value:
                    out.setdefault(value, name)
            return out
        p += cmdsize
    return {}


def collection_symbols(kc):
    data = open(kc, "rb").read()
    syms = {}
    # The primary image is the kernel itself.
    syms.update(kext_symbols(data, 0, segments(data, 0)))
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_FILESET_ENTRY:
            _, foff = struct.unpack_from("<QQ", data, p + 8)
            syms.update(kext_symbols(data, foff, segments(data, foff)))
        p += cmdsize
    return syms


def our_symbols(path):
    out = subprocess.run([NM, path], capture_output=True, text=True)
    have = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[-1]
        if name.startswith("(") or not name:
            continue
        have.add(name.lstrip("_"))
    return have


def main():
    kc, kext_path, kernel = sys.argv[1], sys.argv[2], sys.argv[3]
    data = open(kext_path, "rb").read()
    segs = segments(data, 0)
    ranges = [(s["vm"], s["vm"] + s["vmsz"]) for s in segs if s["vmsz"]]

    def inside(addr):
        return any(lo <= addr < hi for lo, hi in ranges)

    text = None
    for s in segs:
        for sname, addr, size, soff in s["sects"]:
            if sname == "__text":
                text = (addr, size, soff)
    if not text:
        sys.exit("no __text")

    taddr, tsize, toff = text
    blob = data[toff:toff + tsize]

    calls = 0
    external = {}
    i = 0
    n = len(blob)
    while i < n - 5:
        op = blob[i]
        if op in (0xE8, 0xE9):                      # call/jmp rel32
            rel = struct.unpack_from("<i", blob, i + 1)[0]
            target = (taddr + i + 5 + rel) & 0xFFFFFFFFFFFFFFFF
            calls += 1
            if not inside(target):
                external[target] = external.get(target, 0) + 1
            i += 5
            continue
        i += 1

    ptrs = {}
    for s in segs:
        for sname, addr, size, soff in s["sects"]:
            if sname not in ("__got", "__data", "__const", "__bss", "__common"):
                continue
            if not size or not soff:
                continue
            raw = data[soff:soff + size]
            for k in range(0, len(raw) - 8, 8):
                val = struct.unpack_from("<Q", raw, k)[0]
                if KERNEL_RANGE[0] <= val < KERNEL_RANGE[1] and not inside(val):
                    ptrs[val] = ptrs.get(val, 0) + 1

    csyms = collection_symbols(kc)
    ours = our_symbols(kernel)

    def resolve(addr):
        name = csyms.get(addr)
        if name is None:
            return None
        return name, (name.lstrip("_") in ours)

    resolved = unresolved = 0
    missing_in_ours = 0
    for addr in list(external)[:20000]:
        r = resolve(addr)
        if r is None:
            unresolved += 1
        else:
            resolved += 1
            if not r[1]:
                missing_in_ours += 1

    print("__text: 0x%x bytes, direct call/jmp sites: %d" % (tsize, calls))
    print("  targets inside image:     %d" % (calls - sum(external.values())))
    print("  targets outside image:    %d (%d distinct addresses)" %
          (sum(external.values()), len(external)))
    print("  of those resolve via KC symtabs: %d, unresolved: %d" % (resolved, unresolved))
    print("  resolved but absent from our kernel: %d" % missing_in_ours)
    print("pointer slots out of image: %d (%d distinct values)" %
          (sum(ptrs.values()), len(ptrs)))
    pres = punres = pmiss = 0
    for addr in ptrs:
        r = resolve(addr)
        if r is None:
            punres += 1
        else:
            pres += 1
            if not r[1]:
                pmiss += 1
    print("  of those resolve: %d, unresolved: %d, absent from our kernel: %d" %
          (pres, punres, pmiss))


if __name__ == "__main__":
    main()
