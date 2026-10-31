#!/usr/bin/env python3
"""Dump the kmod_info of a kext embedded in a kernel collection.

Usage: python3 build/dis/dump-kmod-info.py build/kernel.kc 0xffffff80011c1000
"""
import struct
import sys


def main():
    path = sys.argv[1]
    vmaddr = int(sys.argv[2], 16)
    data = open(path, "rb").read()
    magic, cputype, cpusub, ftype, ncmds, sizeofcmds = struct.unpack_from("<IiiIII", data, 0)
    off = 32
    segs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            name = data[off + 8:off + 24].rstrip(b"\0").decode()
            vm, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, off + 24)
            segs.append((name, vm, vmsz, foff, fsz))
        off += cmdsize

    print("filetype=0x%x ncmds=%d" % (ftype, ncmds))
    hit = None
    for name, vm, vmsz, foff, fsz in segs:
        if vm <= vmaddr < vm + max(vmsz, fsz):
            hit = (name, vm, foff)
            print("segment %s vm=0x%x vmsz=0x%x fileoff=0x%x" % (name, vm, vmsz, foff))
    if not hit:
        sys.exit("vmaddr 0x%x not inside any segment" % vmaddr)

    name, segoff, foff = hit
    pos = foff + (vmaddr - segoff)
    blob = data[pos:pos + 0xd0]

    fields = [
        ("next", 0), ("info_version", 8), ("id", 12), ("name", 16),
        ("version", 80), ("reference_count", 144), ("reference_list", 148),
        ("address", 156), ("size", 164), ("hdr_size", 172),
        ("start", 180), ("stop", 188),
    ]
    print("--- kmod_info at file offset 0x%x (packed-4 layout shown) ---" % pos)
    for fname, foff2 in fields:
        raw8 = blob[foff2:foff2 + 8]
        u64 = struct.unpack("<Q", raw8)[0] if len(raw8) == 8 else 0
        u32 = struct.unpack("<I", blob[foff2:foff2 + 4])[0]
        if fname in ("name", "version"):
            s = blob[foff2:foff2 + 64].split(b"\0")[0].decode(errors="replace")
            print("  %-16s @0x%03x = %r" % (fname, foff2, s))
        elif fname in ("next", "reference_list", "start", "stop"):
            print("  %-16s @0x%03x = 0x%016x" % (fname, foff2, u64))
        else:
            print("  %-16s @0x%03x = %d (0x%x)" % (fname, foff2, u32, u32))


if __name__ == "__main__":
    main()
