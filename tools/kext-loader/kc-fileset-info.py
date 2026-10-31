#!/usr/bin/env python3
"""Inspect a kernel collection (MH_FILESET) and its embedded kext images.

For every LC_FILESET_ENTRY prints the entry id, the embedded Mach-O's type and
the load commands that matter for re-linking, and can dump details for one
entry: segments, LC_SYMTAB contents (undefined symbols included) and
LC_DYSYMTAB relocation tables.

Usage:
  python3 tools/kext-loader/kc-fileset-info.py KC [--grep apfs] [--detail apfs]
"""
import struct
import sys

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xb
LC_UUID = 0x1b
LC_FILESET_ENTRY = 0x80000035

CMDS = {
    0x19: "SEGMENT_64", 0x1b: "UUID", 0x2: "SYMTAB", 0xb: "DYSYMTAB",
    0x22: "DYLD_INFO", 0x80000022: "DYLD_INFO_ONLY",
    0x26: "FUNCTION_STARTS", 0x29: "DATA_IN_CODE", 0x2a: "SOURCE_VERSION",
    0x32: "BUILD_VERSION", 0x80000033: "EXPORTS_TRIE",
    0x80000034: "CHAINED_FIXUPS", 0x80000035: "FILESET_ENTRY",
    0x80000028: "MAIN", 0x25: "ENCRYPTION_INFO_64",
}


def cstr(b):
    return b.split(b"\0")[0].decode(errors="replace")


def image_cmds(data, off):
    if struct.unpack_from("<I", data, off)[0] != MH_MAGIC_64:
        return None
    _, _, _, ftype, ncmds, sizeofcmds, flags = struct.unpack_from("<IiiIIII", data, off)
    out = {"off": off, "ftype": ftype, "flags": flags, "cmds": [], "sizeofcmds": sizeofcmds}
    p = off + 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        out["cmds"].append((cmd, cmdsize, p))
        p += cmdsize
    return out


def segments(data, img):
    segs = []
    for cmd, cmdsize, p in img["cmds"]:
        if cmd != LC_SEGMENT_64:
            continue
        name = cstr(data[p + 8:p + 24])
        vm, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, p + 24)
        segs.append({"name": name, "vm": vm, "vmsz": vmsz, "foff": foff, "fsz": fsz})
    return segs


def symtab(data, img):
    for cmd, cmdsize, p in img["cmds"]:
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, p + 8)
            return symoff, nsyms, stroff, strsize
    return None


def dysymtab(data, img):
    for cmd, cmdsize, p in img["cmds"]:
        if cmd == LC_DYSYMTAB:
            return struct.unpack_from("<IIIIIIIIIIIIIIIIIIII", data, p + 8)
    return None


def main():
    path = sys.argv[1]
    grep = sys.argv[sys.argv.index("--grep") + 1].lower() if "--grep" in sys.argv else None
    detail = sys.argv[sys.argv.index("--detail") + 1].lower() if "--detail" in sys.argv else None
    data = open(path, "rb").read()

    prim = image_cmds(data, 0)
    if prim is None:
        sys.exit("not a 64-bit Mach-O: %s" % path)
    print("primary: ftype=0x%x ncmds=%d cmds=%s" % (
        prim["ftype"], len(prim["cmds"]),
        ",".join(sorted({CMDS.get(c, hex(c)) for c, _, _ in prim["cmds"]}))))

    entries = []
    for cmd, cmdsize, p in prim["cmds"]:
        if cmd != LC_FILESET_ENTRY:
            continue
        vm, foff = struct.unpack_from("<QQ", data, p + 8)
        idoff = struct.unpack_from("<I", data, p + 24)[0]
        entry_id = cstr(data[p + idoff:p + idoff + 96])
        entries.append((vm, foff, entry_id))

    print("fileset entries: %d" % len(entries))
    for vm, foff, entry_id in entries:
        if grep and grep not in entry_id.lower():
            continue
        img = image_cmds(data, foff)
        if img is None:
            print("  %-46s <not Mach-O at 0x%x>" % (entry_id, foff))
            continue
        have = ",".join(sorted({CMDS.get(c, hex(c)) for c, _, _ in img["cmds"]}))
        print("  vm=0x%-16x off=0x%-8x ftype=0x%-2x %-46s %s" % (vm, foff, img["ftype"], entry_id, have))

        if detail and detail in entry_id.lower():
            print("    --- segments ---")
            for s in segments(data, img):
                print("      %-16s vm=0x%-16x foff=0x%-8x filesz=0x%-8x vmsz=0x%x" %
                      (s["name"], s["vm"], s["foff"], s["fsz"], s["vmsz"]))
            st = symtab(data, img)
            if st:
                symoff, nsyms, stroff, strsize = st
                print("    --- symtab: %d symbols, strtab %d bytes @0x%x ---" %
                      (nsyms, strsize, stroff))
                undef = []
                defined = 0
                for i in range(nsyms):
                    e = symoff + i * 16
                    strx, ntype, sect, desc, value = struct.unpack_from("<IBBHQ", data, e)
                    name = cstr(data[stroff + strx:stroff + strx + 256])
                    if (ntype & 0x0e) == 0x0:  # N_UNDF
                        undef.append(name)
                    else:
                        defined += 1
                print("      defined=%d undefined=%d" % (defined, len(undef)))
                print("      first undefined: %s" % ", ".join(undef[:12]))
                if undef:
                    import collections
                    fam = collections.Counter()
                    for n in undef:
                        if "kpi" in n:
                            fam["kpi"] += 1
                    print("      sample of defined names not shown")
            dy = dysymtab(data, img)
            if dy:
                (ilocalsym, nlocalsym, iextdefsym, nextdefsym, iundefsym, nundefsym,
                 tocoff, ntoc, modtaboff, nmodtab, extrefsymoff, nextrefsyms,
                 indirectsymoff, nindirectsyms, extreloff, nextrel,
                 locreloff, nlocrel) = dy
                print("    --- dysymtab: nundefsym=%d extrel=%d locrel=%d ---" %
                      (nundefsym, nextrel, nlocrel))


if __name__ == "__main__":
    main()
