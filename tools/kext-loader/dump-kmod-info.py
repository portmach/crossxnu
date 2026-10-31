#!/usr/bin/env python3
"""Dump the kmod_info of a kext embedded in a kernel collection (or a .kext).

Usage: python3 tools/kext-loader/dump-kmod-info.py build/kernel.kc 0xffffff80011c1000

Field offsets follow the packed-4 layout XNU uses for kmod_info_t:
  address 0x9c, size 0xa4, hdr_size 0xac, start 0xb4, stop 0xbc
(all 8-byte fields, after name[64] + version[64] and the 32-bit scalars).
"""
import struct
import sys

FIELDS = [
    ("next", 0x00, "ptr"),
    ("info_version", 0x08, "u32"),
    ("id", 0x0c, "u32"),
    ("name", 0x10, "str"),
    ("version", 0x50, "str"),
    ("reference_count", 0x90, "u32"),
    ("reference_list", 0x94, "ptr"),
    ("address", 0x9c, "ptr"),
    ("size", 0xa4, "ptr"),
    ("hdr_size", 0xac, "ptr"),
    ("start", 0xb4, "ptr"),
    ("stop", 0xbc, "ptr"),
]


def main():
    path = sys.argv[1]
    vmaddr = int(sys.argv[2], 16)
    data = open(path, "rb").read()
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off = 32
    hit = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            name = data[off + 8:off + 24].rstrip(b"\0").decode()
            segvm, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, off + 24)
            if segvm <= vmaddr < segvm + max(vmsz, fsz):
                hit = (name, segvm, foff)
        off += cmdsize

    if not hit:
        sys.exit("vmaddr 0x%x not inside any segment" % vmaddr)

    name, segvm, segfoff = hit
    pos = segfoff + (vmaddr - segvm)
    print("segment %s, kmod_info at file offset 0x%x" % (name, pos))

    for fname, foff, kind in FIELDS:
        raw = data[pos + foff:pos + foff + 8]
        if kind == "str":
            print("  %-16s @0x%03x = %r" %
                  (fname, foff, raw.split(b"\0")[0].decode(errors="replace")))
        elif kind == "u32":
            print("  %-16s @0x%03x = %d" %
                  (fname, foff, struct.unpack("<I", raw[:4])[0]))
        else:
            print("  %-16s @0x%03x = 0x%016x" %
                  (fname, foff, struct.unpack("<Q", raw)[0]))


if __name__ == "__main__":
    main()
