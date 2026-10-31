#!/usr/bin/env python3
"""Append an image as a new segment to a Mach-O kernel collection.

crossxnu carries its root file system inside kernel.kc this way: the
`__ROOTIMG` segment holds an HFS+ image, bsd_init.c hands it to memdev
(mdevadd) as /dev/md0.  The same trick with `__APFSIMG` gives the blockstorage
kext (tools/blockstorage-kext) an APFS container to publish when no AHCI disk
is attached, without a PCI bus, a block driver or a physical-memory mapping:
the segment is mapped by the
loader like any other part of the collection, so the kext can address it
directly and getsegbyname() finds it.

Usage: kc-add-segment.py KERNEL_KC IMAGE OUT_KC [SEGNAME]
       (SEGNAME defaults to __ROOTIMG)
"""
import struct
import sys

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
PAGE = 0x1000
SEGNAME_MAX = 16


def align_up(x, a):
    return (x + a - 1) & ~(a - 1)


def main(src, image, dst, segname='__ROOTIMG'):
    name = segname.encode()
    if len(name) > SEGNAME_MAX:
        raise SystemExit(f'segment name too long: {segname}')

    data = bytearray(open(src, 'rb').read())
    hdr = struct.unpack_from('<IiiIIIII', data, 0)
    if hdr[0] != MH_MAGIC_64:
        raise SystemExit('not a 64-bit Mach-O')
    ncmds, sizeofcmds = hdr[4], hdr[5]

    # Find the last segment end and the first section file offset, so one more
    # segment command fits in the header padding without overwriting text.
    off = 32
    max_vm_end = 0
    first_sect_off = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == LC_SEGMENT_64:
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
        raise SystemExit(f'no room for {segname} command: cmd_off={cmd_off:#x} '
                         f'first section={first_sect_off:#x}')

    img = open(image, 'rb').read()
    fileoff = align_up(len(data), PAGE)
    vmaddr = align_up(max_vm_end, PAGE)
    vmsize = align_up(len(img), PAGE)

    seg = struct.pack('<II16sQQQQiiII',
                      LC_SEGMENT_64, 72, name,
                      vmaddr, vmsize, fileoff, len(img),
                      7, 7, 0, 0)      # maxprot/initprot RWX, writable in memory
    assert len(seg) == 72
    data[cmd_off:cmd_off + 72] = seg

    if len(data) < fileoff:
        data.extend(b'\0' * (fileoff - len(data)))
    data.extend(img)

    struct.pack_into('<II', data, 16, ncmds + 1, sizeofcmds + 72)
    open(dst, 'wb').write(data)
    print(f'{dst}: {segname} vmaddr={vmaddr:#x} fileoff={fileoff:#x} '
          f'size={len(img):#x} vmsize={vmsize:#x}')


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5):
        raise SystemExit('usage: kc-add-segment.py kernel.kc image out.kc [SEGNAME]')
    main(*sys.argv[1:])
