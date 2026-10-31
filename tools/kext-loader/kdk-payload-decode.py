#!/usr/bin/env python3
"""Decode a KDK .pkg Payload (pbzx variant with stored blocks) to plain cpio.

The KDK DMG unpacks to `Kernel Debug Kit/KernelDebugKit.pkg`, a xar whose
`KDK.pkg/Payload` is a pbzx stream.  Unlike the macOS asset payload this one
uses a 16-byte block header:

    'pbzx' | u64 flags | { u64 uncompressed, u64 compressed, data }*

and `data` is either a self-delimiting xz stream (when it starts with the xz
magic) or `compressed` bytes of stored odc-cpio data.

Usage:
  python3 tools/kext-loader/kdk-payload-decode.py KDk.pkg/Payload > payload.cpio
  python3 tools/kext-loader/kdk-payload-decode.py Payload --list | grep apfs
  python3 tools/kext-loader/kdk-payload-decode.py Payload --extract DIR ./System/Library/Extensions/apfs.kext

The whole DMG chain, without macOS tools:

  7z x -o out Kernel_Debug_Kit_*.dmg        # -> "Kernel Debug Kit/KernelDebugKit.pkg"
  bsdtar -xf out/"Kernel Debug Kit"/KernelDebugKit.pkg
  python3 kdk-payload-decode.py KDK.pkg/Payload > payload.cpio
  bsdtar -xf payload.cpio "./System/Library/Extensions/apfs.kext"
"""
import lzma
import struct
import subprocess
import sys

XZ = b"\xfd7zXZ\x00"


def blocks(path):
    """Yield ('xz'|'stored', payload_bytes)."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"pbzx":
            raise SystemExit("not a pbzx payload: %r" % head[:8])
        pos = 12
        f.seek(0)
        data = f.read()
    while pos + 16 <= len(data):
        _, comp = struct.unpack(">QQ", data[pos:pos + 16])
        body = pos + 16
        if data[body:body + 6] == XZ:
            dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
            out = dec.decompress(data[body:])
            used = len(data) - body - len(dec.unused_data)
            yield "xz", out
            pos = body + used
        else:
            yield "stored", data[body:body + comp]
            pos = body + comp


def main():
    path = sys.argv[1]
    if "--extract" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--extract") + 1]
        want = sys.argv[sys.argv.index("--extract") + 2]
        cpio = out_dir + ".cpio"
        with open(cpio, "wb") as f:
            for _, chunk in blocks(path):
                f.write(chunk)
        print("wrote", cpio, file=sys.stderr)
        subprocess.run(["bsdtar", "-xf", cpio, "-C", out_dir, want], check=False)
        return 0

    out = sys.stdout.buffer
    if "--list" in sys.argv:
        tmp = "/tmp/kdk-payload.cpio"
        with open(tmp, "wb") as f:
            for _, chunk in blocks(path):
                f.write(chunk)
        subprocess.run(["bsdtar", "-tf", tmp])
        return 0

    for kind, chunk in blocks(path):
        out.write(chunk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
