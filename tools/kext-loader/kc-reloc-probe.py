#!/usr/bin/env python3
"""Show LC_DYSYMTAB relocations of a kext embedded in a kernel collection.

Answers the question that decides the extraction strategy: are the kext's
relocations already applied in the collection (slots hold absolute kernel
addresses) or still pending (slots hold addend-only values, e.g. 0)?

Usage:
  python3 tools/kext-loader/kc-reloc-probe.py KC com.apple.filesystems.apfs
"""
import struct
import sys

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xb
LC_FILESET_ENTRY = 0x80000035

# dysymtab_command, 18 uint32 after cmd/cmdsize
DYSYMTAB_FIELDS = [
    "ilocalsym", "nlocalsym", "iextdefsym", "nextdefsym", "iundefsym",
    "nundefsym", "tocoff", "ntoc", "modtaboff", "nmodtab", "extrefsymoff",
    "nextrefsyms", "indirectsymoff", "nindirectsyms", "extreloff", "nextrel",
    "locreloff", "nlocrel",
]

RELOC_TYPES = ["UNSIGNED", "SIGNED", "BRANCH", "GOT_LOAD", "GOT", "SUBTRACTOR",
               "SIGNED_1", "SIGNED_2", "SIGNED_4"]


def cstr(b):
    return b.split(b"\0")[0].decode(errors="replace")


def find_entry(data, want):
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_FILESET_ENTRY:
            vm, foff = struct.unpack_from("<QQ", data, p + 8)
            idoff = struct.unpack_from("<I", data, p + 24)[0]
            entry_id = cstr(data[p + idoff:p + idoff + 96])
            if want in entry_id:
                return vm, foff, entry_id
        p += cmdsize
    return None


def main():
    path, want = sys.argv[1], sys.argv[2]
    data = open(path, "rb").read()
    vm, off, entry_id = find_entry(data, want)
    print("entry: %s vm=0x%x fileoff=0x%x" % (entry_id, vm, off))

    ncmds = struct.unpack_from("<I", data, off + 16)[0]
    p = off + 32
    symtab = dysym = None
    segs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SYMTAB:
            symtab = struct.unpack_from("<IIII", data, p + 8)
        elif cmd == LC_DYSYMTAB:
            vals = struct.unpack_from("<18I", data, p + 8)
            dysym = dict(zip(DYSYMTAB_FIELDS, vals))
        elif cmd == LC_SEGMENT_64:
            name = cstr(data[p + 8:p + 24])
            v, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, p + 24)
            segs.append((name, v, vmsz, foff, fsz))
        p += cmdsize

    symoff, nsyms, stroff, strsize = symtab
    print("symtab: %d syms, strtab @0x%x (%d bytes)" % (nsyms, stroff, strsize))
    print("dysymtab: nundefsym=%d extrel=%d locrel=%d" %
          (dysym["nundefsym"], dysym["nextrel"], dysym["nlocrel"]))

    def sym_name(i):
        e = symoff + i * 16
        strx = struct.unpack_from("<I", data, e)[0]
        return cstr(data[stroff + strx:stroff + strx + 256])

    def va_to_off(va):
        for name, v, vmsz, foff, fsz in segs:
            if v <= va < v + max(vmsz, fsz):
                return foff + (va - v)
        return None

    print("\n--- external relocations (first 12) ---")
    for i in range(min(12, dysym["nextrel"])):
        e = dysym["extreloff"] + i * 8
        r_address, bits = struct.unpack_from("<II", data, e)
        symnum = bits & 0xffffff
        pcrel = (bits >> 24) & 1
        length = (bits >> 25) & 3
        extern = (bits >> 27) & 1
        rtype = (bits >> 28) & 0xf
        site = va_to_off(r_address)
        if site is None:
            continue
        if length == 3:
            cur = struct.unpack_from("<Q", data, site)[0]
        elif length == 2:
            cur = struct.unpack_from("<i", data, site)[0]
        else:
            cur = struct.unpack_from("<h", data, site)[0]
        print("  %-9s %-22s pcrel=%d extern=%d sym=%-4d site=0x%x value=0x%x" %
              (RELOC_TYPES[rtype], sym_name(symnum), pcrel, extern, symnum,
               r_address, cur & 0xffffffffffffffff))

    print("\n--- local relocations (first 8) ---")
    for i in range(min(8, dysym["nlocrel"])):
        e = dysym["locreloff"] + i * 8
        r_address, bits = struct.unpack_from("<II", data, e)
        section = bits & 0xffffff
        length = (bits >> 25) & 3
        rtype = (bits >> 28) & 0xf
        site = va_to_off(r_address)
        if site is None:
            continue
        cur = struct.unpack_from("<Q", data, site)[0] if length == 3 else struct.unpack_from("<i", data, site)[0]
        print("  %-9s sect=%-4d site=0x%x value=0x%x" % (RELOC_TYPES[rtype], section, r_address, cur & 0xffffffffffffffff))


if __name__ == "__main__":
    main()
