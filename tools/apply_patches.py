import sys, struct
sys.stdout.reconfigure(encoding='utf-8')

def fletcher64(data):
    words = struct.unpack('<1022I', data[8:])
    sum1 = 0
    sum2 = 0
    mod = 0xFFFFFFFF
    for w in words:
        sum1 = (sum1 + w) % mod
        sum2 = (sum2 + sum1) % mod
    
    check1 = mod - ((sum1 + sum2) % mod)
    check2 = mod - ((sum1 + check1) % mod)
    return (check2 << 32) | check1

def patch_launchd_binary():
    print("--- Patching build/dis/launchd.real ---")
    with open('build/dis/launchd.real', 'r+b') as f:
        data = bytearray(f.read())
        b1 = bytes(data[0x4662c:0x4662e])
        b2 = bytes(data[0x46632:0x46634])
        if b1 == b'\x75\x38' and b2 == b'\x75\x32':
            data[0x4662c:0x4662e] = b'\x90\x90'
            data[0x46632:0x46634] = b'\x90\x90'
            f.seek(0)
            f.write(data)
            print("build/dis/launchd.real patched successfully.")
        elif b1 == b'\x90\x90' and b2 == b'\x90\x90':
            print("build/dis/launchd.real already patched.")
        else:
            raise RuntimeError(f"Unexpected bytes in launchd.real: b1={b1.hex()}, b2={b2.hex()}")

def patch_apfs_image():
    print("--- Patching build/apfs2g.img ---")
    with open('build/apfs2g.img', 'r+b') as f:
        # 1. Patch launchd copies inside apfs2g.img
        for base_off in [0x27fcd000, 0x2805f000]:
            f.seek(base_off + 0x4662c)
            b1 = f.read(2)
            f.seek(base_off + 0x46632)
            b2 = f.read(2)
            if b1 == b'\x75\x38' and b2 == b'\x75\x32':
                f.seek(base_off + 0x4662c)
                f.write(b'\x90\x90')
                f.seek(base_off + 0x46632)
                f.write(b'\x90\x90')
                print(f"Patched launchd.real copy at 0x{base_off:x}")
            elif b1 == b'\x90\x90' and b2 == b'\x90\x90':
                print(f"launchd.real copy at 0x{base_off:x} already patched.")
            else:
                raise RuntimeError(f"Unexpected bytes at 0x{base_off:x}: b1={b1.hex()}, b2={b2.hex()}")

        # 2. Patch Block 0x324fa000 (DREC for com.crossxnu.hello.plist)
        f.seek(0x324fa000)
        blk = bytearray(f.read(4096))
        assert fletcher64(blk) == struct.unpack('<Q', blk[:8])[0], "Block 0x324fa000 checksum mismatch before edit"

        t_off, t_len = struct.unpack('<HH', blk[40:44])
        key_area_start = 56 + t_off + t_len
        k_off, k_len, v_off, v_len = struct.unpack('<HHHH', blk[56 + 33*8 : 56 + 34*8])
        k_pos = key_area_start + k_off
        v_pos = 4096 - v_off

        # Check key
        namelen_and_hash = struct.unpack('<I', blk[k_pos+8:k_pos+12])[0]
        namelen = namelen_and_hash & 0x3ff
        name = blk[k_pos+12:k_pos+12+namelen].rstrip(b'\x00')
        assert name == b'com.crossxnu.hello.plist', f"Expected com.crossxnu.hello.plist, got {name}"

        # Current val: target_inode, ftype
        target_inode = struct.unpack('<Q', blk[v_pos:v_pos+8])[0]
        ftype = struct.unpack('<H', blk[v_pos+16:v_pos+18])[0]
        print(f"DREC before: target_inode=0x{target_inode:x}, ftype=0x{ftype:x}")
        if target_inode == 0x25f and ftype == 0xa:
            # Update to target_inode=0x15, ftype=0x8 (regular file)
            blk[v_pos:v_pos+8] = struct.pack('<Q', 0x15)
            blk[v_pos+16:v_pos+18] = struct.pack('<H', 0x8)
            new_cksum = fletcher64(blk)
            blk[:8] = struct.pack('<Q', new_cksum)
            assert fletcher64(blk) == new_cksum

            f.seek(0x324fa000)
            f.write(blk)
            print("Block 0x324fa000 patched and checksum updated.")
        elif target_inode == 0x15 and ftype == 0x8:
            print("Block 0x324fa000 already points to inode 0x15 as DT_REG.")
        else:
            raise RuntimeError(f"Unexpected DREC values: target=0x{target_inode:x}, ftype=0x{ftype:x}")

        # 3. Patch Block 0x324fb000 (Inode 0x25f mode)
        f.seek(0x324fb000)
        blk = bytearray(f.read(4096))
        assert fletcher64(blk) == struct.unpack('<Q', blk[:8])[0], "Block 0x324fb000 checksum mismatch before edit"

        t_off, t_len = struct.unpack('<HH', blk[40:44])
        key_area_start = 56 + t_off + t_len
        k_off, k_len, v_off, v_len = struct.unpack('<HHHH', blk[56 + 9*8 : 56 + 10*8])
        k_pos = key_area_start + k_off
        v_pos = 4096 - v_off

        raw_key = struct.unpack('<Q', blk[k_pos:k_pos+8])[0]
        assert raw_key == 0x300000000000025f, f"Expected key 0x300000000000025f, got 0x{raw_key:x}"
        mode = struct.unpack('<H', blk[v_pos+0x50:v_pos+0x52])[0]
        print(f"Inode 0x25f mode before: 0x{mode:04x} (octal {oct(mode)})")
        if mode == 0xa1ed:
            # Update mode to 0x81a4 (S_IFREG | 0644)
            blk[v_pos+0x50:v_pos+0x52] = struct.pack('<H', 0x81a4)
            new_cksum = fletcher64(blk)
            blk[:8] = struct.pack('<Q', new_cksum)
            assert fletcher64(blk) == new_cksum

            f.seek(0x324fb000)
            f.write(blk)
            print("Block 0x324fb000 patched and checksum updated.")
        elif mode == 0x81a4:
            print("Inode 0x25f already mode 0x81a4.")
        else:
            raise RuntimeError(f"Unexpected inode mode: 0x{mode:04x}")

        # 4. Write script payload into block 0x2d310 (extent for Inode 0x72e)
        script = (
            b"#!/bin/sh\n"
            b"exec >/dev/console 2>&1\n"
            b"echo \"crossxnu: launchd spawned a job as pid $$\"\n"
            b"/bin/echo -n \"crossxnu: uname = \"\n"
            b"/usr/bin/uname -v\n"
            b"exit 0\n"
        )
        script_block = script + b"\x00" * (4096 - len(script))
        f.seek(0x2d310 * 4096)
        f.write(script_block)
        print("Written hello script payload to block 0x2d310.")

        # 5. Patch Block 0x3254d000 (DREC for rc.temporaryDataVolume -> Inode 0x72e as DT_REG)
        f.seek(0x3254d000)
        blk = bytearray(f.read(4096))
        assert fletcher64(blk) == struct.unpack('<Q', blk[:8])[0], "Block 0x3254d000 checksum mismatch before edit"

        t_off, t_len = struct.unpack('<HH', blk[40:44])
        key_area_start = 56 + t_off + t_len
        k_off, k_len, v_off, v_len = struct.unpack('<HHHH', blk[56 + 2*8 : 56 + 3*8])
        k_pos = key_area_start + k_off
        v_pos = 4096 - v_off

        namelen_and_hash = struct.unpack('<I', blk[k_pos+8:k_pos+12])[0]
        namelen = namelen_and_hash & 0x3ff
        name = blk[k_pos+12:k_pos+12+namelen].rstrip(b'\x00')
        assert name == b'rc.temporaryDataVolume', f"Expected rc.temporaryDataVolume, got {name}"

        target_inode = struct.unpack('<Q', blk[v_pos:v_pos+8])[0]
        ftype = struct.unpack('<H', blk[v_pos+16:v_pos+18])[0]
        print(f"rc.temporaryDataVolume DREC before: target_inode=0x{target_inode:x}, ftype=0x{ftype:x}")
        if target_inode == 0x733 and ftype == 0xa:
            blk[v_pos:v_pos+8] = struct.pack('<Q', 0x72e)
            blk[v_pos+16:v_pos+18] = struct.pack('<H', 0x8)
            new_cksum = fletcher64(blk)
            blk[:8] = struct.pack('<Q', new_cksum)
            assert fletcher64(blk) == new_cksum

            f.seek(0x3254d000)
            f.write(blk)
            print("Block 0x3254d000 patched and checksum updated.")
        elif target_inode == 0x72e and ftype == 0x8:
            print("Block 0x3254d000 already points to inode 0x72e as DT_REG.")
        else:
            raise RuntimeError(f"Unexpected DREC values: target=0x{target_inode:x}, ftype=0x{ftype:x}")

    print("build/apfs2g.img patched successfully.")

if __name__ == '__main__':
    patch_launchd_binary()
    patch_apfs_image()
