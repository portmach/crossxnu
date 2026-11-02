import os, sys, struct
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

def patch_kernel_binaries():
    print("--- Patching Kernel Binaries ---")
    # 1. IOUserClient::copyClientEntitlement AMFI NULL check
    orig1 = bytes.fromhex('488d0d56924c00488b09488d55f04889c74889deff91e001000085c07506488b45f0eb02')
    patched1 = bytes.fromhex('488b0d56924c004885c97418488d55f0505f535eff91e001000085c07506488b45f0eb02')
    assert len(orig1) == 36 and len(patched1) == 36

    targets1 = [
        ('build/kernel.kc', 0x84bfcb),
        ('build/kernel-plain.kc', 0x84bfcb),
        ('build/esp32.img', 0xac4fcb),
    ]
    for path, exp_offset in targets1:
        if not os.path.exists(path):
            print(f"{path} does not exist, skipping.")
            continue
        with open(path, 'r+b') as f:
            data = f.read()
            idx_orig = data.find(orig1)
            idx_patch = data.find(patched1)
            if idx_orig == exp_offset:
                f.seek(exp_offset)
                f.write(patched1)
                print(f"Patched AMFI null guard in {path} at 0x{exp_offset:x}")
            elif idx_patch == exp_offset:
                print(f"AMFI null guard in {path} at 0x{exp_offset:x} already patched.")
            else:
                raise RuntimeError(f"Could not find expected AMFI bytes in {path} (orig={idx_orig}, patch={idx_patch})")

    # 2. sys_record_system_event entitlement check bypass (allow launchd to record system events)
    orig2 = bytes.fromhex('85c00f8415010000')
    patched2 = bytes.fromhex('85c0909090909090')
    assert len(orig2) == 8 and len(patched2) == 8

    targets2 = [
        ('build/kernel.kc', 0x60ee59),
        ('build/kernel-plain.kc', 0x60ee59),
        ('build/esp32.img', 0x887e59),
    ]
    for path, exp_offset in targets2:
        if not os.path.exists(path):
            print(f"{path} does not exist, skipping.")
            continue
        with open(path, 'r+b') as f:
            data = f.read()
            cur = data[exp_offset:exp_offset+8]
            if cur == orig2:
                f.seek(exp_offset)
                f.write(patched2)
                print(f"Patched sys_record_system_event in {path} at 0x{exp_offset:x}")
            elif cur == patched2:
                print(f"sys_record_system_event in {path} at 0x{exp_offset:x} already patched.")
            else:
                raise RuntimeError(f"Could not find expected sys_record_system_event bytes in {path} at 0x{exp_offset:x} (cur={cur.hex()})")

def patch_launchd_binary():
    print("--- Patching build/dis/launchd.real ---")
    if not os.path.exists('build/dis/launchd.real'):
        print("build/dis/launchd.real does not exist, skipping.")
        return
    with open('build/dis/launchd.real', 'r+b') as f:
        data = bytearray(f.read())
        # 1a. Console logging bypass when launchd.log is open
        b1 = bytes(data[0x4662c:0x4662e])
        b2 = bytes(data[0x46632:0x46634])
        if b1 == b'\x75\x38' and b2 == b'\x75\x32':
            data[0x4662c:0x4662e] = b'\x90\x90'
            data[0x46632:0x46634] = b'\x90\x90'
            print("build/dis/launchd.real console logging patched.")
        elif b1 == b'\x90\x90' and b2 == b'\x90\x90':
            print("build/dis/launchd.real console logging already patched.")
        else:
            raise RuntimeError(f"Unexpected bytes in launchd.real: b1={b1.hex()}, b2={b2.hex()}")

        # 1b. Force console output for all messages: 0x467f3: jne -> nop nop
        b3 = bytes(data[0x467f3:0x467f5])
        if b3 == b'\x75\x04':
            data[0x467f3:0x467f5] = b'\x90\x90'
            print("build/dis/launchd.real force console output patched.")
        elif b3 == b'\x90\x90':
            print("build/dis/launchd.real force console output already patched.")
        else:
            raise RuntimeError(f"Unexpected bytes at 0x467f3 in launchd.real: {b3.hex()}")

        # 2. Multi-user boot patch at 0x4ce84 (90 bytes)
        # Replaces rd=md0/Restore/Ramdisk checks with jmp 0x10004cede (eb 58 + 88 NOPs)
        expected_mu_orig = bytes.fromhex(
            '488b3df5230300488d356c000200e8f68afcffb3014c8d3513260300'
            '84c07530488d3d5a000200e88b3bfcff84c07520488d3d52000200e8'
            '7b3bfcff84c07510488d3d4a000200e86b3bfcff84c0740a41c60601'
            '881dd6250300'
        )
        patched_mu_bytes = b'\xeb\x58' + b'\x90' * 88
        assert len(expected_mu_orig) == 90
        assert len(patched_mu_bytes) == 90

        cur_mu = bytes(data[0x4ce84:0x4ce84 + 90])
        if cur_mu == expected_mu_orig:
            data[0x4ce84:0x4ce84 + 90] = patched_mu_bytes
            print("build/dis/launchd.real multi-user boot patched.")
        elif cur_mu == patched_mu_bytes:
            print("build/dis/launchd.real multi-user boot already patched.")
        else:
            raise RuntimeError(f"Unexpected bytes at 0x4ce84 in launchd.real: {cur_mu[:16].hex()}...")

        # 3. Bypass launchd.log init (init_launchd_logging) to prevent dispatch_sync lockup in kevent_id:
        # Patch 0x45e27: retq (0xc3)
        b_entry = bytes(data[0x45e27:0x45e28])
        if b_entry == b'\x55':
            data[0x45e27] = 0xc3
            print("build/dis/launchd.real 0x45e27 patched with retq.")
        elif b_entry == b'\xc3':
            print("build/dis/launchd.real 0x45e27 already patched with retq.")
        else:
            raise RuntimeError(f"Unexpected byte at 0x45e27 in launchd.real: {b_entry.hex()}")

        # Patch 0x4790f: 5 NOPs
        b_call = bytes(data[0x4790f:0x4790f+5])
        if b_call == b'\xe8\x13\xe5\xff\xff':
            data[0x4790f:0x4790f+5] = b'\x90' * 5
            print("build/dis/launchd.real 0x4790f callq 0x100045e27 NOP'd.")
        elif b_call == b'\x90' * 5:
            print("build/dis/launchd.real 0x4790f already NOP'd.")
        else:
            raise RuntimeError(f"Unexpected bytes at 0x4790f in launchd.real: {b_call.hex()}")

        # 4. Patch 0x48d30: NOP the panic jump on task failure (0f 84 ad 00 00 00 -> 90 * 6)
        b_panic = bytes(data[0x48d30:0x48d30+6])
        if b_panic == bytes.fromhex('0f84ad000000'):
            data[0x48d30:0x48d30+6] = b'\x90' * 6
            print("build/dis/launchd.real 0x48d30 task failure panic jump NOP'd.")
        elif b_panic == b'\x90' * 6:
            print("build/dis/launchd.real 0x48d30 already NOP'd.")
        else:
            raise RuntimeError(f"Unexpected bytes at 0x48d30 in launchd.real: {b_panic.hex()}")

        # 5. Patch embedded XML config: change RequireSuccess to IgnoreSuccess_ for tzinit
        tz_target = b'<key>tzinit</key>\n\t\t<dict>\n\t\t\t<key>Program</key>\n\t\t\t<string>/usr/libexec/tzinit</string>\n\t\t\t<key>PerformAfterUserspaceReboot</key>\n\t\t\t<true/>\n\t\t\t<key>RequireSuccess</key>'
        tz_patch  = b'<key>tzinit</key>\n\t\t<dict>\n\t\t\t<key>Program</key>\n\t\t\t<string>/usr/libexec/tzinit</string>\n\t\t\t<key>PerformAfterUserspaceReboot</key>\n\t\t\t<true/>\n\t\t\t<key>IgnoreSuccess_</key>'
        assert len(tz_target) == len(tz_patch)
        if tz_target in data:
            data = data.replace(tz_target, tz_patch)
            print("build/dis/launchd.real tzinit RequireSuccess -> IgnoreSuccess_ patched.")
        elif tz_patch in data:
            print("build/dis/launchd.real tzinit already IgnoreSuccess_.")
        else:
            raise RuntimeError("tzinit RequireSuccess pattern not found in launchd.real")

        f.seek(0)
        f.write(data)

def patch_apfs_image():
    print("--- Patching build/apfs2g.img ---")
    if not os.path.exists('build/apfs2g.img'):
        print("build/apfs2g.img does not exist, skipping.")
        return
    with open('build/apfs2g.img', 'r+b') as f:
        # 1. Patch launchd copies inside apfs2g.img
        expected_mu_orig = bytes.fromhex(
            '488b3df5230300488d356c000200e8f68afcffb3014c8d3513260300'
            '84c07530488d3d5a000200e88b3bfcff84c07520488d3d52000200e8'
            '7b3bfcff84c07510488d3d4a000200e86b3bfcff84c0740a41c60601'
            '881dd6250300'
        )
        patched_mu_bytes = b'\xeb\x58' + b'\x90' * 88

        for base_off in [0x27fcd000, 0x2805f000]:
            # 1a. Console logging bypass patch
            f.seek(base_off + 0x4662c)
            b1 = f.read(2)
            f.seek(base_off + 0x46632)
            b2 = f.read(2)
            if b1 == b'\x75\x38' and b2 == b'\x75\x32':
                f.seek(base_off + 0x4662c)
                f.write(b'\x90\x90')
                f.seek(base_off + 0x46632)
                f.write(b'\x90\x90')
                print(f"Patched launchd.real console logging at 0x{base_off:x}")
            elif b1 == b'\x90\x90' and b2 == b'\x90\x90':
                print(f"launchd.real console logging at 0x{base_off:x} already patched.")
            else:
                raise RuntimeError(f"Unexpected bytes at 0x{base_off:x}: b1={b1.hex()}, b2={b2.hex()}")

            # 1b. Force console output for all messages: 0x467f3: jne -> nop nop
            f.seek(base_off + 0x467f3)
            b3 = f.read(2)
            if b3 == b'\x75\x04':
                f.seek(base_off + 0x467f3)
                f.write(b'\x90\x90')
                print(f"Patched launchd.real force console output at 0x{base_off:x}")
            elif b3 == b'\x90\x90':
                print(f"launchd.real force console output at 0x{base_off:x} already patched.")
            else:
                raise RuntimeError(f"Unexpected bytes at 0x{base_off+0x467f3:x}: b3={b3.hex()}")

            # 1c. Multi-user boot patch
            f.seek(base_off + 0x4ce84)
            cur = f.read(90)
            if cur == expected_mu_orig:
                f.seek(base_off + 0x4ce84)
                f.write(patched_mu_bytes)
                print(f"Patched launchd.real multi-user boot at 0x{base_off:x}")
            elif cur == patched_mu_bytes:
                print(f"launchd.real multi-user boot at 0x{base_off:x} already patched.")
            else:
                raise RuntimeError(f"Unexpected bytes at 0x{base_off+0x4ce84:x}: {cur[:16].hex()}...")

            # 1d. Bypass launchd.log init (init_launchd_logging) to prevent dispatch_sync lockup in kevent_id:
            f.seek(base_off + 0x45e27)
            b_entry = f.read(1)
            if b_entry == b'\x55':
                f.seek(base_off + 0x45e27)
                f.write(b'\xc3')
                print(f"Patched launchd.real init_launchd_logging retq at 0x{base_off+0x45e27:x}")
            elif b_entry == b'\xc3':
                print(f"launchd.real init_launchd_logging at 0x{base_off+0x45e27:x} already retq.")
            else:
                raise RuntimeError(f"Unexpected byte at 0x{base_off+0x45e27:x}: {b_entry.hex()}")

            f.seek(base_off + 0x4790f)
            b_call = f.read(5)
            if b_call == b'\xe8\x13\xe5\xff\xff':
                f.seek(base_off + 0x4790f)
                f.write(b'\x90' * 5)
                print(f"Patched launchd.real callq init_launchd_logging at 0x{base_off+0x4790f:x}")
            elif b_call == b'\x90' * 5:
                print(f"launchd.real callq init_launchd_logging at 0x{base_off+0x4790f:x} already NOP'd.")
            else:
                raise RuntimeError(f"Unexpected bytes at 0x{base_off+0x4790f:x}: {b_call.hex()}")

            # 1e. NOP the panic jump on task failure at 0x48d30
            f.seek(base_off + 0x48d30)
            b_panic = f.read(6)
            if b_panic == bytes.fromhex('0f84ad000000'):
                f.seek(base_off + 0x48d30)
                f.write(b'\x90' * 6)
                print(f"Patched launchd.real task failure panic jump at 0x{base_off+0x48d30:x}")
            elif b_panic == b'\x90' * 6:
                print(f"launchd.real task failure panic jump at 0x{base_off+0x48d30:x} already NOP'd.")
            else:
                raise RuntimeError(f"Unexpected bytes at 0x{base_off+0x48d30:x}: {b_panic.hex()}")

            # 1f. Patch embedded XML config for tzinit
            tz_target = b'<key>tzinit</key>\n\t\t<dict>\n\t\t\t<key>Program</key>\n\t\t\t<string>/usr/libexec/tzinit</string>\n\t\t\t<key>PerformAfterUserspaceReboot</key>\n\t\t\t<true/>\n\t\t\t<key>RequireSuccess</key>'
            tz_patch  = b'<key>tzinit</key>\n\t\t<dict>\n\t\t\t<key>Program</key>\n\t\t\t<string>/usr/libexec/tzinit</string>\n\t\t\t<key>PerformAfterUserspaceReboot</key>\n\t\t\t<true/>\n\t\t\t<key>IgnoreSuccess_</key>'
            f.seek(base_off + 0x6ed8c + 5955)
            tz_snip = f.read(len(tz_target))
            if tz_snip == tz_target:
                f.seek(base_off + 0x6ed8c + 5955)
                f.write(tz_patch)
                print(f"Patched launchd.real tzinit RequireSuccess -> IgnoreSuccess_ at 0x{base_off+0x6ed8c+5955:x}")
            elif tz_snip == tz_patch:
                print(f"launchd.real tzinit at 0x{base_off+0x6ed8c+5955:x} already IgnoreSuccess_.")
            else:
                raise RuntimeError(f"Unexpected bytes for tzinit at 0x{base_off+0x6ed8c+5955:x}: {tz_snip}")

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

        # 2b. Ensure updated com.crossxnu.hello.plist in block 0xcccd000
        f.seek(0xcccd000)
        cur_plist = f.read(613)
        with open("userland/com.crossxnu.hello.plist", "rb") as pf:
            desired_plist = pf.read()
        assert len(desired_plist) == 613, f"Expected 613 bytes, got {len(desired_plist)}"
        if cur_plist != desired_plist:
            f.seek(0xcccd000)
            f.write(desired_plist)
            print("Block 0xcccd000 updated with new com.crossxnu.hello.plist.")
        else:
            print("Block 0xcccd000 already contains updated com.crossxnu.hello.plist.")

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
    patch_kernel_binaries()
    patch_launchd_binary()
    patch_apfs_image()
