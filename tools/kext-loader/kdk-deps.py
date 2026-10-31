#!/usr/bin/env python3
"""Resolve a kext's cross-kext dependencies into a KDK kext set.

Given a kext and a directory of KDK kexts, find which kexts export the
symbols the target imports but the kernel does not provide, then repeat for
those kexts (transitive closure).

Usage:
  python3 tools/kext-loader/kdk-deps.py KEXT_DIR TARGET.kext OUR_KERNEL

Prints the ordered kext list (dependencies first) and the unresolved symbols.
"""
import os
import struct
import subprocess
import sys

MH_MAGIC = 0xfeedfacf
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
FAT_MAGIC = 0xcafebabe
NM = os.environ.get("CROSSXNU_NM", "build/cctools/bin/x86_64-apple-darwin11-nm")


def slice_x86(path):
    d = open(path, "rb").read()
    if len(d) < 8:
        return None
    magic, nfat = struct.unpack_from(">II", d, 0)
    if magic == FAT_MAGIC:
        for i in range(nfat):
            cputype, cpusub, off, size, align = struct.unpack_from(">iiIII", d, 8 + i * 20)
            if cputype == 0x01000007:          # CPU_TYPE_X86_64
                return d[off:off + size]
        return None
    if struct.unpack_from("<I", d, 0)[0] == MH_MAGIC:
        return d
    return None


def symbols(d):
    """(defined names, undefined names) of a thin Mach-O."""
    if not d or struct.unpack_from("<I", d, 0)[0] != MH_MAGIC:
        return set(), set()
    ncmds = struct.unpack_from("<I", d, 16)[0]
    p = 32
    symtab = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, p)
        if cmd == LC_SYMTAB:
            symtab = struct.unpack_from("<IIII", d, p + 8)
        p += cmdsize
    if not symtab:
        return set(), set()
    symoff, nsyms, stroff, strsize = symtab
    defined, undef = set(), set()
    for i in range(nsyms):
        e = symoff + i * 16
        strx, ntype = struct.unpack_from("<IB", d, e)
        name = d[stroff + strx:stroff + strx + 240].split(b"\0")[0].decode(errors="replace")
        if not name:
            continue
        t = ntype & 0x0e
        if t == 0x0e:
            defined.add(name)
        elif t == 0 and not (ntype & 0xe0):
            undef.add(name)
    return defined, undef


def kernel_symbols(path):
    out = subprocess.run([NM, "-n", path], capture_output=True, text=True)
    have = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            have.add(parts[-1])
    return have


def kext_id(bundle):
    try:
        txt = open(os.path.join(bundle, "Contents", "Info.plist"), "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    i = txt.find("<key>CFBundleIdentifier</key>")
    if i < 0:
        return None
    j = txt.find("<string>", i)
    k = txt.find("</string>", j)
    return txt[j + 8:k].strip() if j > 0 and k > 0 else None


def main():
    kext_dir, target, kernel = sys.argv[1:4]

    exporters = {}          # symbol -> [bundle paths]
    for name in sorted(os.listdir(kext_dir)):
        if not name.endswith(".kext"):
            continue
        bundle = os.path.join(kext_dir, name)
        exe = os.path.join(bundle, "Contents", "MacOS",
                           os.path.basename(bundle)[:-5])
        if not os.path.exists(exe):
            continue
        defined, _ = symbols(slice_x86(exe))
        for s in defined:
            exporters.setdefault(s, []).append(bundle)

    have = kernel_symbols(kernel)
    target_exe = os.path.join(target, "Contents", "MacOS", os.path.basename(target)[:-5])
    _, undef = symbols(slice_x86(target_exe))

    order, seen, pending = [], set(), [target]
    unresolved = set()
    while pending:
        bundle = pending.pop(0)
        if bundle in seen:
            continue
        seen.add(bundle)
        exe = os.path.join(bundle, "Contents", "MacOS", os.path.basename(bundle)[:-5])
        _, need = symbols(slice_x86(exe))
        for s in sorted(need):
            if s in have or s in unresolved:
                continue
            providers = [p for p in exporters.get(s, []) if p != bundle]
            if not providers:
                unresolved.add(s)
                continue
            for p in providers[:1]:
                if p not in seen and p not in pending:
                    pending.append(p)
        order.append(bundle)

    print("dependency order (%d kexts):" % len(order))
    for b in order:
        print("  %-46s %s" % (kext_id(b) or "?", b))
    if unresolved:
        print("\nunresolved symbols: %d" % len(unresolved))
        for s in sorted(unresolved)[:20]:
            print("  " + s)


if __name__ == "__main__":
    main()
