#!/usr/bin/env python3
"""Append a __ROOTIMG segment to a Mach-O kernel collection.

crossxnu uses this to carry an HFS+ root image inside kernel.kc; the loader
maps the segment and the kernel hands it to memdev (mdevadd) as /dev/md0.
"""
import struct
import sys

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
PAGE = 0x1000


def align_up(x, a):
    return (x + a - 1) & ~(a - 1)


def main(src, image, dst):
    data = bytearray(open(src, 'rb').read())
    hdr = struct.unpack_from('<IiiIIIII', data, 0)
    if hdr[0] != MH_MAGIC_64:
        raise SystemExit('not a 64-bit Mach-O')
    ncmds, sizeofcmds = hdr[4], hdr[5]

    # Find the last segment end and the first section file offset, so we can
    # append one segment command without overwriting real text.
    off = 32
    max_vm_end = 0
    first_sect_off = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == LC_SEGMENT_64:
            segname = data[off + 8:off + 24].split(b'\0')[0]
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', data, off + 24)
            nsects = struct.unpack_from('<I', data, off + 64)[0]
            max_vm_end = max(max_vm_end, vmaddr + vmsize)
            so = off + 72
            for _s in range(nsects):
                s_off = struct.unpack_from('<I', data, so + 48)[0]
                if s_off and (first_sect_off is None or s_off < first_sect_off):
                    first_sect_off = s_off
                so += 80
        off += cmdsize

    cmd_off = 32 + sizeofcmds
    if first_sect_off is None:
        first_sect_off = 32 + sizeofcmds + 4096
    if cmd_off + 72 > first_sect_off:
        raise SystemExit(f'no room for __ROOTIMG command: cmd_off={cmd_off:#x} '
                         f'first section={first_sect_off:#x}')

    img = open(image, 'rb').read()
    fileoff = align_up(len(data), PAGE)
    vmaddr = align_up(max_vm_end, PAGE)
    vmsize = align_up(len(img), PAGE)

    # Segment command.
    seg = struct.pack('<II16sQQQQiiII',
                      LC_SEGMENT_64, 72, b'__ROOTIMG',
                      vmaddr, vmsize, fileoff, len(img),
                      7, 7, 0, 0)
    assert len(seg) == 72
    data[cmd_off:cmd_off + 72] = seg

    # Append image data.
    if len(data) < fileoff:
        data.extend(b'\0' * (fileoff - len(data)))
    data.extend(img)

    # Update header.
    struct.pack_into('<II', data, 16, ncmds + 1, sizeofcmds + 72)
    open(dst, 'wb').write(data)
    print(f'{dst}: __ROOTIMG vmaddr={vmaddr:#x} fileoff={fileoff:#x} '
          f'size={len(img):#x} vmsize={vmsize:#x}')


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: kc-add-rootimg.py kernel.kc root.hfs out.kc')
    main(sys.argv[1], sys.argv[2], sys.argv[3])
