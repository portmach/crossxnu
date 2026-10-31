#!/usr/bin/env python3
"""Make a Mach-O that declares LC_DYLD_CHAINED_FIXUPS, for linker testing.

Needed because the KDK ships no x86_64 kext that uses chained fixups (only
arm64e slices do), so `kc-builder`'s refusal path cannot be exercised with a
real kext.  Rewriting an existing 16-byte linkedit_data_command
(LC_BUILD_VERSION) into LC_DYLD_CHAINED_FIXUPS keeps the load-command area
consistent and is enough to prove the guard fires before any pointer is
touched.

Usage:
  make-chainfix-sample.py KEXT.kext OUT.kext
  make-chainfix-sample.py --check OUT.kext    # expect rejection by kc-builder
"""
import os
import shutil
import struct
import sys

LC_BUILD_VERSION = 0x2A
LC_DYLD_CHAINED_FIXUPS = 0x34 | 0x80000000
MH_MAGIC_64 = 0xFEEDFACF

CPU = {0x01000007: "x86_64", 0x0100000C: "arm64", 0x00000007: "i386"}


def find_binary(kext_dir):
    macos = os.path.join(kext_dir, "Contents", "MacOS")
    if not os.path.isdir(macos):
        raise SystemExit("%s: no Contents/MacOS" % kext_dir)
    names = [n for n in os.listdir(macos)
             if os.path.isfile(os.path.join(macos, n))]
    if not names:
        raise SystemExit("%s: no executable" % kext_dir)
    return os.path.join(macos, sorted(names)[0])


def slice_offsets(data):
    """File offset/size of the x86_64 (or only) slice."""
    if len(data) < 8:
        raise SystemExit("not a Mach-O")
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in (0xCAFEBABE, 0xCAFEBABF):
        n = struct.unpack_from(">I", data, 4)[0]
        wide = magic == 0xCAFEBABF
        es = 32 if wide else 20
        for i in range(n):
            b = 8 + i * es
            if wide:
                ct, _, off, size = struct.unpack_from(">IIQQ", data, b)
            else:
                ct, _, off, size = struct.unpack_from(">IIII", data, b)
            if ct == 0x01000007:
                return off, size
        # arm64-only input: patch that slice instead
        b = 8
        if wide:
            _, _, off, size = struct.unpack_from(">IIQQ", data, b)
        else:
            _, _, off, size = struct.unpack_from(">IIII", data, b)
        return off, size
    return 0, len(data)


def patch(data):
    off, size = slice_offsets(data)
    if struct.unpack_from("<I", data, off)[0] != MH_MAGIC_64:
        raise SystemExit("slice at 0x%x is not a 64-bit Mach-O" % off)
    cputype = struct.unpack_from("<I", data, off + 4)[0]
    ncmds = struct.unpack_from("<I", data, off + 16)[0]
    p = off + 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_BUILD_VERSION:
            if cmdsize != 16:
                raise SystemExit("LC_BUILD_VERSION is %d bytes, expected 16" % cmdsize)
            struct.pack_into("<I", data, p, LC_DYLD_CHAINED_FIXUPS)
            return CPU.get(cputype, "cputype %#x" % cputype)
        p += cmdsize
    raise SystemExit("no LC_BUILD_VERSION command to repurpose")


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)

    if sys.argv[1] == "--check":
        sample = sys.argv[2]
        data = bytearray(open(sample, "rb").read())
        print("check %s: arch %s patched" % (sample, patch(bytearray(data))))
        return 0

    kext, out = sys.argv[1], sys.argv[2]
    if os.path.isdir(out):
        shutil.rmtree(out)
    shutil.copytree(kext, out)

    binary = find_binary(out)
    data = bytearray(open(binary, "rb").read())
    arch = patch(data)
    open(binary, "wb").write(bytes(data))
    print("patched %s (%s): LC_BUILD_VERSION -> LC_DYLD_CHAINED_FIXUPS"
          % (binary, arch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
