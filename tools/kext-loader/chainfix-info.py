#!/usr/bin/env python3
"""Dump the LC_DYLD_CHAINED_FIXUPS payload of a Mach-O / kext.

Apple's newer kexts (KDK 26.x) are linked with chained fixups instead of
LC_DYLD_INFO rebase/bind opcodes, so a loader that only understands the latter
silently leaves every pointer in a chained (encoded) state.  This tool reports
what is actually in the binary so the linker can be extended with evidence
rather than guesses.

Usage:
  chainfix-info.py FILE [--chains N] [--verbose]
"""

import argparse
import os
import struct
import sys

LC_DYLD_CHAINED_FIXUPS = 0x34 | 0x80000000
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xCEFAEDFE
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF

LC_SEGMENT = 0x1
LC_SEGMENT_64 = 0x19

# dyld_chained_ptr_format
PTR_FORMAT_NAMES = {
    1: "ARM64E",
    2: "PTR_64",
    3: "PTR_32",
    4: "PTR_32_CACHE",
    5: "PTR_32_FIRMWARE",
    6: "PTR_64_OFFSET",
    7: "ARM64E_KERNEL",
    8: "PTR_64_KERNEL_CACHE",
    9: "X86_64_KERNEL_CACHE",
    10: "ARM64E_USERLAND",
    11: "ARM64E_FIRMWARE",
    12: "X86_64_USERLAND_OFFSETS",
    13: "ARM64E_USERLAND24",
    14: "ARM64E_SHARED_CACHE",
}
PTR_FORMAT_64BIT = {1, 2, 6, 7, 8, 9, 10, 11, 12, 13, 14}

# dyld_chained_import_format
IMPORT_FORMATS = {
    1: ("DYLD_CHAINED_IMPORT", 4),
    2: ("DYLD_CHAINED_IMPORT_ADDEND", 8),
    3: ("DYLD_CHAINED_IMPORT_ADDEND64", 16),
}

START_NONE = 0xFFFF
START_MULTI = 0xFFFE


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def cstr(b, o):
    e = b.find(b"\0", o)
    if e < 0:
        e = len(b)
    return b[o:e].decode("utf-8", "replace"), e + 1


def slice_macho(data):
    """Return (offset, size) of the 64-bit little-endian Mach-O slice."""
    if len(data) < 8:
        raise SystemExit("not a Mach-O: file too short")
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in (FAT_MAGIC, FAT_MAGIC_64):
        nfat = struct.unpack_from(">I", data, 4)[0]
        wide = magic == FAT_MAGIC_64
        entsize = 32 if wide else 20
        for i in range(nfat):
            base = 8 + i * entsize
            if wide:
                cputype, _, offset, size = struct.unpack_from(">IIQQ", data, base)
            else:
                cputype, _, offset, size = struct.unpack_from(">IIII", data, base)
            if cputype in (0x01000007, 0x7):  # x86_64
                return offset, size
        raise SystemExit("fat file has no x86_64 slice")
    return 0, len(data)


def parse_macho(data):
    base, size = slice_macho(data)
    magic = u32(data, base)
    if magic in (MH_CIGAM_64, MH_CIGAM):
        raise SystemExit("big-endian Mach-O is not supported")
    if magic == MH_MAGIC_64:
        is64 = True
    elif magic == MH_MAGIC:
        is64 = False
    else:
        raise SystemExit("not a Mach-O")

    ncmds, sizeofcmds = struct.unpack_from("<II", data, base + 16)
    hdrsize = 32 if is64 else 28
    off = base + hdrsize
    end = off + sizeofcmds

    segs = []
    chain_cmd = None
    for _ in range(ncmds):
        if off + 8 > end:
            break
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmdsize < 8:
            break
        if cmd in (LC_SEGMENT_64, LC_SEGMENT):
            if cmd == LC_SEGMENT_64:
                name = data[off + 8:off + 24].rstrip(b"\0").decode()
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, off + 24)
                nsects = u32(data, off + 64)
            else:
                name = data[off + 8:off + 24].rstrip(b"\0").decode()
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<IIII", data, off + 24)
                nsects = u32(data, off + 48)
            segs.append({
                "name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                "fileoff": fileoff, "filesize": filesize, "nsects": nsects,
            })
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            dataoff, datasize = struct.unpack_from("<II", data, off + 8)
            chain_cmd = (dataoff, datasize)
        off += cmdsize

    return {
        "base": base, "size": size, "is64": is64,
        "segs": segs, "chain": chain_cmd,
    }


def decode_imports(data, hdr, chain_off, chain_size):
    """Return (imports, symbols_blob) decoded per the header's format."""
    imports_off = u32(data, chain_off + 8)
    symbols_off = u32(data, chain_off + 12)
    imports_count = u32(data, chain_off + 16)
    imports_format = u32(data, chain_off + 20)
    symbols_format = u32(data, chain_off + 24)

    if imports_format not in IMPORT_FORMATS:
        raise SystemExit("unknown imports_format %d" % imports_format)
    fmt_name, entsize = IMPORT_FORMATS[imports_format]

    symblob = data[chain_off + symbols_off:chain_off + chain_size]
    if symbols_format == 1:
        import zlib
        symblob = zlib.decompress(symblob)
    elif symbols_format != 0:
        raise SystemExit("unsupported symbols_format %d" % symbols_format)

    imports = []
    p = chain_off + imports_off
    for _ in range(imports_count):
        if imports_format == 1:
            (raw,) = struct.unpack_from("<I", data, p)
            lib_ordinal = raw & 0xFF
            weak = (raw >> 8) & 1
            name_off = raw >> 9
            addend = 0
        elif imports_format == 2:
            (raw,) = struct.unpack_from("<I", data, p)
            lib_ordinal = raw & 0xFF
            weak = (raw >> 8) & 1
            name_off = raw >> 9
            addend = struct.unpack_from("<i", data, p + 4)[0]
        else:
            lib_ordinal = u16(data, p)
            weak = u16(data, p + 2) & 1
            name_off = u32(data, p + 4)
            addend = struct.unpack_from("<q", data, p + 8)[0]
        name, _ = cstr(symblob, name_off)
        imports.append({
            "raw": raw, "lib_ordinal": lib_ordinal, "weak": weak,
            "name": name, "addend": addend,
        })
        p += entsize

    return imports, {
        "imports_format": fmt_name, "imports_count": imports_count,
        "symbols_format": symbols_format, "symbols_blob_size": len(symblob),
    }


def decode_ptr64_bind(val, is_kernel_cache):
    if is_kernel_cache:
        ordinal = val & 0xFFFFFF          # 24 bits
        addend = (val >> 24) & 0xFF       # 8 bits
        nxt = (val >> 51) & 0x7FF         # 11 bits
        return {"ordinal": ordinal, "addend": addend, "next": nxt, "bind": True}
    ordinal = val & 0xFFFFFF
    addend = (val >> 24) & 0xFF
    nxt = (val >> 51) & 0xFFF
    return {"ordinal": ordinal, "addend": addend, "next": nxt, "bind": True}


def decode_ptr64_rebase(val, fmt):
    if fmt == 8 or fmt == 9:
        target = val & 0x3FFFFFFF         # 30 bits
        cache_level = (val >> 30) & 0x3
        diversity = (val >> 32) & 0xFFFF
        addr_div = (val >> 48) & 1
        key = (val >> 49) & 0x3
        nxt = (val >> 51) & 0x7FF
        is_auth = (val >> 62) & 1
        return {"target": target, "cache_level": cache_level,
                "diversity": diversity, "addr_div": addr_div, "key": key,
                "next": nxt, "is_auth": is_auth, "bind": False}
    high8 = (val >> 36) & 0xFF
    target = val & 0xFFFFFFFFF            # 36 bits
    nxt = (val >> 51) & 0xFFF
    return {"target": (high8 << 56) | target, "high8": high8, "next": nxt,
            "bind": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--chains", type=int, default=0,
                    help="walk and print the first N fixup chains")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    with open(args.file, "rb") as f:
        data = f.read()

    m = parse_macho(data)
    segs = m["segs"]
    print("file:            %s" % args.file)
    print("slice base:      0x%x  size 0x%x  is64=%d" % (m["base"], m["size"], m["is64"]))
    print("segments:        %d" % len(segs))
    for i, s in enumerate(segs):
        print("  [%d] %-16s vmaddr 0x%016x vmsize 0x%-9x fileoff 0x%-7x filesize 0x%x"
              % (i, s["name"], s["vmaddr"], s["vmsize"], s["fileoff"], s["filesize"]))

    if not m["chain"]:
        print("LC_DYLD_CHAINED_FIXUPS: absent")
        return 0

    dataoff, datasize = m["chain"]
    chain_off = m["base"] + dataoff
    print("LC_DYLD_CHAINED_FIXUPS: dataoff 0x%x datasize 0x%x" % (dataoff, datasize))

    version = u32(data, chain_off + 0)
    starts_off = u32(data, chain_off + 4)
    print("  fixups_version:   %d" % version)

    imports, imeta = decode_imports(data, m, chain_off, datasize)
    print("  imports:          %d (%s, symbols_format=%d, %d bytes)"
          % (imeta["imports_count"], imeta["imports_format"],
             imeta["symbols_format"], imeta["symbols_blob_size"]))
    for i, imp in enumerate(imports[:40]):
        print("    [%3d] lib %-4d %s%s" % (i, imp["lib_ordinal"], imp["name"],
                                           " +%d" % imp["addend"] if imp["addend"] else ""))
    if len(imports) > 40:
        print("    ... %d more" % (len(imports) - 40))

    img = chain_off + starts_off
    seg_count = u32(data, img)
    print("  seg_count:        %d" % seg_count)
    if seg_count > len(segs):
        print("  WARN: seg_count %d > image segments %d" % (seg_count, len(segs)))

    total_fixups = 0
    binds = 0
    for si in range(min(seg_count, len(segs))):
        off = u32(data, img + 4 + si * 4)
        if off == 0:
            print("  seg[%d] %-16s (no fixups)" % (si, segs[si]["name"]))
            continue
        ss = img + off
        ssize = u32(data, ss)
        page_size = u16(data, ss + 4)
        ptr_format = u16(data, ss + 6)
        seg_offset = u64(data, ss + 8)
        max_valid = u32(data, ss + 16)
        page_count = u16(data, ss + 20)
        fmt_name = PTR_FORMAT_NAMES.get(ptr_format, "?%d" % ptr_format)
        print("  seg[%d] %-16s size %-4d page_size 0x%-5x format %d (%s)"
              % (si, segs[si]["name"], ssize, page_size, ptr_format, fmt_name))
        print("        segment_offset 0x%x max_valid_pointer 0x%x page_count %d"
              % (seg_offset, max_valid, page_count))

        seg = segs[si]
        seg_file = m["base"] + seg["fileoff"]

        for pi in range(page_count):
            start = u16(data, ss + 22 + pi * 2)
            if start == START_NONE:
                continue
            if start == START_MULTI:
                print("        page %d: START_MULTI (not supported here)" % pi)
                continue
            page_start_off = pi * page_size
            chain_val_off = start
            n = 0
            while True:
                file_off = seg_file + page_start_off + chain_val_off
                if file_off + 8 > len(data):
                    print("        page %d: chain runs past EOF" % pi)
                    break
                val = u64(data, file_off)
                is_bind = (val >> 62) & 1
                if is_bind:
                    d = decode_ptr64_bind(val, ptr_format in (8, 9))
                    binds += 1
                    kind = "BIND ordinal=%d addend=%d" % (d["ordinal"], d["addend"])
                    if d["ordinal"] < len(imports):
                        kind += " (%s)" % imports[d["ordinal"]]["name"]
                else:
                    d = decode_ptr64_rebase(val, ptr_format)
                    kind = "REBASE target=0x%x" % d["target"]
                total_fixups += 1
                if args.chains and total_fixups <= args.chains:
                    print("        page %2d +0x%-6x %016x  %s  next=%d"
                          % (pi, page_start_off + chain_val_off, val, kind, d["next"]))
                nxt = d["next"]
                if nxt == 0:
                    break
                chain_val_off += nxt * 4
                n += 1
                if n > 100000:
                    break

    print("  fixups:           %d (%d binds)" % (total_fixups, binds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
