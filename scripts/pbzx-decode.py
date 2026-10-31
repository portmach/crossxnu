#!/usr/bin/env python3
"""Stream all payloadv2 pbzx blocks to stdout as one AppleArchive stream.

Each payload file is a `pbzx` container; its blocks are
[8-byte uncompressed size][16-byte header][xz stream], and the xz streams are
self-delimiting, so blocks are located by scanning for the xz magic.
"""
import lzma
import re
import struct
import sys
import zipfile

XZ = b"\xfd7zXZ\x00"


def main(path):
    zf = zipfile.ZipFile(path)
    names = sorted(n for n in zf.namelist()
                   if re.match(r"AssetData/payloadv2/payload\.\d+$", n))
    out = sys.stdout.buffer
    blocks = 0
    total = 0
    for name in names:
        data = zf.read(name)
        if data[:4] != b"pbzx":
            print("skip %s: %r" % (name, data[:8]), file=sys.stderr)
            continue
        pos = 4
        per_file = 0
        while True:
            start = data.find(XZ, pos, pos + 64)
            if start < 0:
                break
            size = struct.unpack(">Q", data[start - 24:start - 16])[0] \
                if start >= 24 else 0
            dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
            try:
                chunk = dec.decompress(data[start:])
            except lzma.LZMAError as exc:
                print("  %s: block at %d failed: %s" % (name, start, exc),
                      file=sys.stderr)
                break
            out.write(chunk)
            blocks += 1
            per_file += 1
            total += len(chunk)
            if not dec.eof:
                print("  %s: block at %d truncated" % (name, start),
                      file=sys.stderr)
                break
            pos = len(data) - len(dec.unused_data)
        print("%-12s %3d blocks (declared %d)" %
              (name.split("/")[-1], per_file, size), file=sys.stderr)
    out.flush()
    print("blocks=%d decoded=%d" % (blocks, total), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
