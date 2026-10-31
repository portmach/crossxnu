#!/usr/bin/env python3
"""Try to recover the kernel symbol table that Apple strips from a KC.

The collection's primary image has LC_SYMTAB zeroed, but __LINKEDIT still
seems to contain a dense string table with kernel symbol names.  This looks
for the matching nlist_64 array: a long run of 16-byte records whose n_value
lies in the kernel's address range and whose n_strx indexes into a string
table that starts right after the run.

Usage:
  python3 tools/kext-loader/kc-recover-syms.py KC [-o out.txt]
"""
import struct
import sys

STRTAB_LO = 0x3000000
STRTAB_HI = 0x4078000
KERNEL_LO = 0xFFFFFF8000200000
KERNEL_HI = 0xFFFFFF8004200000


def plausible(data, off, strtab):
    if off + 16 > len(data):
        return None
    strx, ntype, nsec, ndesc, value = struct.unpack_from("<IBBHQ", data, off)
    if (ntype & 0x0e) not in (0x00, 0x02, 0x0e):
        return None
    if ntype & 0xf0:                 # no stab entries
        return None
    if value and not (KERNEL_LO <= value < KERNEL_HI):
        return None
    if strx == 0:
        return (value, "")
    if not (STRTAB_LO <= strtab + strx < STRTAB_HI):
        return None
    end = strtab + strx
    raw = data[end:end + 200]
    nul = raw.find(b"\0")
    if nul <= 1:
        return None
    name = raw[:nul]
    if not all(0x20 < c < 0x7f for c in name):
        return None
    return (value, name.decode())


def main():
    path = sys.argv[1]
    out = None
    if "-o" in sys.argv:
        out = sys.argv[sys.argv.index("-o") + 1]
    data = open(path, "rb").read()

    # Candidate string tables: a long stretch of printable names separated by
    # NULs, starting with '_'.
    best = None
    off = STRTAB_LO
    while off < STRTAB_HI - 64:
        if data[off:off + 1] == b"_":
            run_end = off
            names = 0
            p = off
            while p < STRTAB_HI:
                nul = data.find(b"\0", p, p + 256)
                if nul < 0:
                    break
                chunk = data[p:nul]
                if not chunk or not all(0x20 < c < 0x7f for c in chunk):
                    break
                names += 1
                p = nul + 1
            if names > 2000:
                best = (off, p, names)
                break
            off = max(p, off + 1)
            continue
        off += 1

    if not best:
        sys.exit("no dense symbol string table found")
    strtab, strtab_end, names = best
    print("symbol string table at 0x%x-0x%x (%d strings)" % (strtab, strtab_end, names))

    # The nlist array normally sits immediately before the string table.
    for align in (0, 8):
        start = strtab - align
        run = 0
        while start - 16 >= 0:
            if plausible(data, start - 16, strtab) is None:
                break
            start -= 16
            run += 1
        if run > 1000:
            count = run
            print("nlist array: 0x%x .. 0x%x (%d symbols)" % (start, strtab, count))
            syms = []
            bad = 0
            for i in range(count):
                r = plausible(data, start + i * 16, strtab)
                if r is None:
                    bad += 1
                    continue
                syms.append(r)
            print("parsed %d symbols, %d unreadable" % (len(syms), bad))
            if out:
                with open(out, "w") as f:
                    for value, name in syms:
                        f.write("%016x %s\n" % (value, name))
                print("wrote", out)
            for value, name in syms[:5]:
                print("  %016x %s" % (value, name))
            return 0
        start = strtab
    sys.exit("nlist array not found before the string table")


if __name__ == "__main__":
    main()
