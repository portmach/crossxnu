#!/usr/bin/env python3
"""Measure how far an Apple kext is from being usable with our kernel.

For one kext inside a kernel collection it reports:

  * how many of its undefined symbols our kernel provides,
  * how many are provided by other kexts in the collection,
  * how many are missing everywhere,
  * whether the kext image carries relocation tables at all (a prelinked
    collection usually has none, which means the code is already bound to
    Apple kernel addresses and cannot be re-linked by a normal linker).

Usage:
  python3 tools/kext-loader/kc-symbol-coverage.py KC OUR_KERNEL [--kext apfs]
"""
import os
import struct
import subprocess
import sys

# cctools nm, not the host GNU nm: the kernel is a Mach-O file.
NM = os.environ.get("CROSSXNU_NM", "build/cctools/bin/x86_64-apple-darwin11-nm")

MH_MAGIC_64 = 0xfeedfacf
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xb
LC_FILESET_ENTRY = 0x80000035
LC_SEGMENT_64 = 0x19


def cstr(b):
    return b.split(b"\0")[0].decode(errors="replace")


def find_entries(data):
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p, out = 32, []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_FILESET_ENTRY:
            vm, foff = struct.unpack_from("<QQ", data, p + 8)
            idoff = struct.unpack_from("<I", data, p + 24)[0]
            out.append((cstr(data[p + idoff:p + idoff + 96]), vm, foff))
        p += cmdsize
    return out


def image_symbols(data, off):
    """Return (defined names, undefined names, extrel count)."""
    ncmds = struct.unpack_from("<I", data, off + 16)[0]
    p = off + 32
    symtab = None
    extrel = 0
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SYMTAB:
            symtab = struct.unpack_from("<IIII", data, p + 8)
        elif cmd == LC_DYSYMTAB:
            vals = struct.unpack_from("<18I", data, p + 8)
            extrel = vals[15] + vals[17]
        p += cmdsize
    if not symtab:
        return [], [], extrel
    symoff, nsyms, stroff, strsize = symtab
    defined, undefined = [], []
    for i in range(nsyms):
        e = symoff + i * 16
        strx, ntype = struct.unpack_from("<IB", data, e)
        name = cstr(data[stroff + strx:stroff + strx + 256])
        if not name:
            continue
        if (ntype & 0x0e) == 0:      # N_UNDF
            undefined.append(name)
        elif (ntype & 0x0e) in (0x0e, 0x02):  # N_SECT / N_ABS
            defined.append(name)
    return defined, undefined, extrel


def our_kernel_symbols(path):
    out = subprocess.run([NM, path], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("nm failed: " + out.stderr[-200:])
    syms = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[-1]
        if not name or name.startswith("("):
            continue
        syms.add(name.lstrip("_"))
    return syms


def main():
    kc_path, kernel_path = sys.argv[1], sys.argv[2]
    want = "apfs"
    if "--kext" in sys.argv:
        want = sys.argv[sys.argv.index("--kext") + 1].lower()

    data = open(kc_path, "rb").read()
    entries = find_entries(data)
    target = None
    provided = {}          # symbol -> [kext ids]
    for eid, vm, off in entries:
        defined, undefined, extrel = image_symbols(data, off)
        for s in defined:
            provided.setdefault(s, []).append(eid)
        if want in eid.lower():
            target = (eid, off, undefined, extrel, vm)

    if not target:
        sys.exit("kext matching %r not found in collection" % want)

    eid, off, undefined, extrel, vm = target
    ours = our_kernel_symbols(kernel_path)

    in_ours = [s for s in undefined if s.lstrip("_") in ours]
    from_kexts = [s for s in undefined if s.lstrip("_") not in ours and s in provided]
    missing = [s for s in undefined if s.lstrip("_") not in ours and s not in provided]

    print("kext: %s (vm=0x%x, fileoff=0x%x)" % (eid, vm, off))
    print("relocation tables: %d%s" % (extrel,
          "  <-- fully linked, cannot be re-linked by a plain linker"
          if extrel == 0 else ""))
    print("undefined symbols: %d" % len(undefined))
    print("  provided by our kernel:   %5d (%.1f%%)" %
          (len(in_ours), 100.0 * len(in_ours) / max(1, len(undefined))))
    print("  provided by other kexts:  %5d" % len(from_kexts))
    print("  missing everywhere:       %5d" % len(missing))
    if missing:
        print("\nfirst missing symbols:")
        for s in missing[:25]:
            print("  " + s)


if __name__ == "__main__":
    main()
