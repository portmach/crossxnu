#!/usr/bin/env python3
"""Build a standalone HFS+ volume image from a directory, without macOS.

`xorrisofs -hfsplus` writes a hybrid ISO9660 + HFS+ image: the HFS+ volume is
appended to the ISO at an offset that depends on the ISO layout.  The kernel
mounts the raw volume, so the HFS+ part has to be cut out:

    xorrisofs -hfsplus -o tree.iso tree/
    hfs-image.py tree/ out.hfs          # finds the volume and cuts it

The HFS+ volume header lives at volume_start + 1024 and starts with "H+"
followed by the version (4 or 5), so the volume is located by scanning for it
instead of assuming a fixed offset.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile

VOLUME_HEADER_OFFSET = 1024
HFS_SIGNATURE = b"H+"


def find_volume_start(iso_path):
    with open(iso_path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        step = 1 << 20
        pos = 0
        carry = b""
        while pos < size:
            block = f.read(step)
            if not block:
                break
            data = carry + block
            base = pos - len(carry)
            idx = 0
            while True:
                idx = data.find(HFS_SIGNATURE, idx)
                if idx < 0:
                    break
                header = base + idx
                start = header - VOLUME_HEADER_OFFSET
                if start >= 0 and start % 512 == 0:
                    version = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
                    if version in (4, 5):
                        return start, size
                idx += 1
            carry = data[-2:]
            pos += len(block)
    raise SystemExit("%s: no HFS+ volume header found" % iso_path)


def cut(iso_path, out_path):
    start, size = find_volume_start(iso_path)
    with open(iso_path, "rb") as src, open(out_path, "wb") as out:
        src.seek(start)
        left = size - start
        while left:
            chunk = src.read(min(left, 1 << 20))
            if not chunk:
                break
            out.write(chunk)
            left -= len(chunk)
    return start, size - start


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", help="directory with the file system tree")
    ap.add_argument("output", help="HFS+ image to write")
    ap.add_argument("--xorrisofs", default="xorrisofs")
    ap.add_argument("--keep-iso", action="store_true", help="keep the hybrid ISO")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    output = os.path.abspath(args.output)
    if shutil.which(args.xorrisofs) is None:
        raise SystemExit("%s not found" % args.xorrisofs)

    iso = output + ".iso"
    cmd = [
        args.xorrisofs,
        "-quiet",
        "-hfsplus",
        "-no-pad",
        "-o",
        iso,
        root,
    ]
    subprocess.run(cmd, check=True)
    start, length = cut(iso, output)
    print(
        "%s: volume at 0x%x, %d bytes -> %s"
        % (args.xorrisofs, start, length, output)
    )
    if not args.keep_iso:
        os.unlink(iso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
