#!/usr/bin/env python3
"""Set (or show) an APFS volume role in a container image.

launchd wants the volumes it mounts to carry roles (System, Data, Preboot),
but mkapfs - the only APFS formatter that runs without macOS - creates a
volume with role NONE and offers no switch for it.  The role is a plain
little-endian u16 in the volume superblock, protected by the object's
Fletcher-64 checksum, so patching both is enough.

Offsets come from the APFS reference (include/apfs/raw.h in apfsprogs):
    apfs_nx_superblock: nx_magic @0x20, nx_block_size @0x24, nx_fs_oid[] @0xB8
    apfs_superblock:    apfs_magic @0x20, apfs_role @0x3C4
    object checksum:    o_cksum @0x0 == fletcher64(block + 8, blocksize - 8)

Usage:
  apfs-set-role.py IMAGE [--volume N] [--role system|data|preboot|user|vm|...]
  apfs-set-role.py IMAGE --show
"""
import argparse
import struct
import sys

NX_MAGIC = b'NXSB'
APSB_MAGIC = b'APSB'

NX_MAGIC_OFF = 0x20
NX_BLOCK_SIZE_OFF = 0x24
NX_FS_OID_OFF = 0xB8
NX_MAX_FS = 100

VOL_MAGIC_OFF = 0x20
VOL_ROLE_OFF = 0x3C4
VOL_UUID_OFF = 0xF0

ROLES = {
    'none': 0x0000,
    'system': 0x0001,
    'user': 0x0002,
    'recovery': 0x0004,
    'vm': 0x0008,
    'preboot': 0x0010,
    'installer': 0x0020,
    'data': 1 << 6,
    'baseband': 2 << 6,
    'update': 3 << 6,
    'xart': 4 << 6,
    'hardware': 5 << 6,
    'backup': 6 << 6,
}


def fletcher64(block):
    """APFS object checksum over the block body (checksum field excluded)."""
    body = block[8:]
    sum1 = 0
    sum2 = 0
    for i in range(0, len(body) - 3, 4):
        sum1 += struct.unpack_from('<I', body, i)[0]
        sum2 += sum1
    c1 = 0xFFFFFFFF - ((sum1 + sum2) % 0xFFFFFFFF)
    c2 = 0xFFFFFFFF - ((sum1 + c1) % 0xFFFFFFFF)
    return (c2 << 32) | c1


def find_volume_blocks(f, block_size):
    """Block numbers of every APSB object in the image.

    nx_fs_oid[] holds *virtual* OIDs, which have to be resolved through the
    container's object map B-tree; for containers we create ourselves with
    mkapfs, scanning for the volume superblock magic is both simpler and
    enough (there is one volume, and it is small enough to scan).
    """
    f.seek(0, 2)
    total = f.tell() // block_size
    hits = []
    for block in range(total):
        f.seek(block * block_size + VOL_MAGIC_OFF)
        if f.read(4) == APSB_MAGIC:
            hits.append(block)
    return hits


def read_block(f, block_size, index):
    f.seek(index * block_size)
    data = f.read(block_size)
    if len(data) != block_size:
        raise SystemExit("short read at block %d" % index)
    return bytearray(data)


def role_name(role):
    for name, value in ROLES.items():
        if value == role:
            return name
    return '0x%x' % role


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--volume', type=int, default=0)
    ap.add_argument('--role')
    ap.add_argument('--show', action='store_true')
    args = ap.parse_args()

    with open(args.image, 'r+b') as f:
        head = f.read(4096)
        if head[NX_MAGIC_OFF:NX_MAGIC_OFF + 4] != NX_MAGIC:
            raise SystemExit("not an APFS container (no NXSB at 0x20)")
        block_size = struct.unpack_from('<I', head, NX_BLOCK_SIZE_OFF)[0]
        if block_size < 512 or block_size > 65536:
            raise SystemExit("implausible container block size %d" % block_size)

        volumes = find_volume_blocks(f, block_size)
        print("container: block size %d, %d volume superblock(s)"
              % (block_size, len(volumes)))

        if not volumes:
            raise SystemExit("no APFS volume superblock found")
        if args.volume >= len(volumes):
            raise SystemExit("no volume %d" % args.volume)

        for i, block in enumerate(volumes):
            vol = read_block(f, block_size, block)
            role = struct.unpack_from('<H', vol, VOL_ROLE_OFF)[0]
            uuid = vol[VOL_UUID_OFF:VOL_UUID_OFF + 16].hex()
            print("  volume %d: block %-6d role %-9s %s"
                  % (i, block, role_name(role), uuid))

            if args.show or not args.role or i != args.volume:
                continue

            if args.role not in ROLES:
                raise SystemExit("unknown role %r (known: %s)"
                                 % (args.role, ', '.join(sorted(ROLES))))
            new_role = ROLES[args.role]
            struct.pack_into('<H', vol, VOL_ROLE_OFF, new_role)
            struct.pack_into('<Q', vol, 0, fletcher64(vol))

            f.seek(block * block_size)
            f.write(vol)
            print("  volume %d: role %s -> %s (checksum rewritten)"
                  % (i, role_name(role), role_name(new_role)))

    return 0


if __name__ == '__main__':
    sys.exit(main())
