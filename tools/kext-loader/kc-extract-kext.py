#!/usr/bin/env python3
"""Carve one kext out of a kernel collection into a standalone .kext bundle.

The collection stores each kext as a complete Mach-O image whose segments
point at absolute file offsets of the collection.  This script copies those
segment ranges to a new compact file, rewrites every load-command offset that
refers to the old layout (segments, LC_SYMTAB, LC_DYSYMTAB, LC_FUNCTION_STARTS,
LC_DYLD_INFO/EXPORTS_TRIE) and writes

    OUT/<bundle-id>.kext/Contents/Info.plist
    OUT/<bundle-id>.kext/Contents/MacOS/<executable>

The info dictionary comes from the collection's __PRELINK_INFO when present,
otherwise a minimal one is synthesized.

Usage:
  python3 tools/kext-loader/kc-extract-kext.py KC BUNDLE_ID_PREFIX OUT_DIR
"""
import os
import plistlib
import struct
import sys

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xb
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LC_FILESET_ENTRY = 0x80000035
LC_UUID = 0x1b


def cstr(b):
    return b.split(b"\0")[0].decode(errors="replace")


def find_entry(data, want):
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_FILESET_ENTRY:
            vm, foff = struct.unpack_from("<QQ", data, p + 8)
            idoff = struct.unpack_from("<I", data, p + 24)[0]
            entry_id = cstr(data[p + idoff:p + idoff + 96])
            if want in entry_id:
                return entry_id, vm, foff
        p += cmdsize
    return None


def prelink_info(data):
    """Return the parsed _PrelinkInfoDictionary, or None."""
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SEGMENT_64:
            name = cstr(data[p + 8:p + 24])
            if name == "__PRELINK_INFO":
                vm, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, p + 24)
                blob = data[foff:foff + fsz]
                start = blob.find(b"<?xml")
                if start < 0:
                    return None
                end = blob.find(b"</plist>", start)
                if end < 0:
                    return None
                try:
                    return plistlib.loads(blob[start:end + len(b"</plist>")])
                except Exception:
                    return None
        p += cmdsize
    return None


def main():
    kc_path, want, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    data = open(kc_path, "rb").read()

    found = find_entry(data, want)
    if not found:
        sys.exit("kext matching %r not found" % want)
    entry_id, vmaddr, img_off = found
    print("kext: %s vm=0x%x fileoff=0x%x" % (entry_id, vmaddr, img_off))

    ncmds = struct.unpack_from("<I", data, img_off + 16)[0]
    sizeofcmds = struct.unpack_from("<I", data, img_off + 20)[0]
    hdr_end = img_off + 32 + sizeofcmds

    # Collect the segments first: they define the new file layout.
    p = img_off + 32
    segs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SEGMENT_64:
            name = cstr(data[p + 8:p + 24])
            sg_vm, sg_vmsz, sg_foff, sg_fsz = struct.unpack_from("<QQQQ", data, p + 24)
            segs.append({"name": name, "vm": sg_vm, "vmsz": sg_vmsz,
                         "foff": sg_foff, "fsz": sg_fsz, "lc": p})
        p += cmdsize

    if not segs:
        sys.exit("image has no segments")

    # New layout: keep the original header bytes, then place each segment at a
    # page-aligned offset in the order they appear, preserving vmaddr order.
    base_foff = min(s["foff"] for s in segs if s["fsz"] or s["name"] != "__LINKEDIT")
    new = bytearray(data[img_off:hdr_end])
    delta = {}                    # old fileoff -> new fileoff
    cursor = (len(new) + 0xfff) & ~0xfff
    for s in segs:
        if s["fsz"] == 0:
            delta[s["foff"]] = cursor
            continue
        old = s["foff"]
        new_foff = cursor
        delta[old] = new_foff
        chunk = data[old:old + s["fsz"]]
        if len(new) < new_foff:
            new.extend(b"\0" * (new_foff - len(new)))
        new.extend(chunk)
        cursor = (len(new) + 0xfff) & ~0xfff
        # Patch the segment command's fileoff (vmaddr stays as in the
        # collection: the image keeps its own address space).
        struct.pack_into("<Q", new, s["lc"] - img_off + 40, new_foff)

        # A segment's sections carry their own absolute file offsets, so they
        # must be shifted by the same amount (section_64.offset / .reloff).
        nsects = struct.unpack_from("<I", data, s["lc"] + 64)[0]
        sec_base = s["lc"] + 72
        for j in range(nsects):
            sec = sec_base + j * 80
            sec_off = struct.unpack_from("<I", data, sec + 48)[0]
            sec_reloff = struct.unpack_from("<I", data, sec + 56)[0]
            if sec_off:
                struct.pack_into("<I", new, sec - img_off + 48, new_foff + (sec_off - s["foff"]))
            if sec_reloff:
                struct.pack_into("<I", new, sec - img_off + 56, new_foff + (sec_reloff - s["foff"]))

    # Shift the offsets that point into __LINKEDIT.  Every one of them lives in
    # a segment, so the delta of that segment applies.
    def shift(off):
        if off == 0:
            return 0
        for s in segs:
            if s["foff"] <= off < s["foff"] + s["fsz"]:
                return delta[s["foff"]] + (off - s["foff"])
        return off

    p = img_off + 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        q = p - img_off
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, p + 8)
            struct.pack_into("<IIII", new, q + 8, shift(symoff), nsyms, shift(stroff), strsize)
        elif cmd == LC_DYSYMTAB:
            vals = list(struct.unpack_from("<18I", data, p + 8))
            for i in (6, 8, 10, 12, 14, 16):        # tocoff, modtaboff, extrefsymoff, indirectsymoff, extreloff, locreloff
                vals[i] = shift(vals[i])
            struct.pack_into("<18I", new, q + 8, *vals)
        elif cmd in (LC_FUNCTION_STARTS, LC_DATA_IN_CODE, LC_DYLD_EXPORTS_TRIE,
                     LC_DYLD_CHAINED_FIXUPS):
            dataoff = struct.unpack_from("<I", data, p + 8)[0]
            struct.pack_into("<I", new, q + 8, shift(dataoff))
        elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            vals = list(struct.unpack_from("<10I", data, p + 8))
            for i in (0, 2, 4, 6, 8):               # rebase/bind/weak/lazy/export offset
                vals[i] = shift(vals[i])
            struct.pack_into("<10I", new, q + 8, *vals)
        p += cmdsize

    # Bundle payload.
    info = prelink_info(data)
    info_dict = None
    if info:
        for d in info.get("_PrelinkInfoDictionary", []):
            if d.get("CFBundleIdentifier") == entry_id:
                info_dict = d
                break

    exe_name = entry_id
    if info_dict:
        exe_name = info_dict.get("CFBundleExecutable", exe_name)

    bundle = os.path.join(out_dir, entry_id + ".kext")
    os.makedirs(os.path.join(bundle, "Contents", "MacOS"), exist_ok=True)
    exe_path = os.path.join(bundle, "Contents", "MacOS", exe_name)
    with open(exe_path, "wb") as f:
        f.write(new)

    if info_dict:
        # Drop the prelink bookkeeping keys: they describe the old layout.
        clean = {k: v for k, v in info_dict.items() if not k.startswith("_Prelink")}
        with open(os.path.join(bundle, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump(clean, f)

    print("wrote %s (%d bytes)" % (exe_path, os.path.getsize(exe_path)))
    print("segments:")
    for s in segs:
        print("  %-16s vm=0x%-16x new_foff=0x%-8x filesz=0x%x" %
              (s["name"], s["vm"], delta[s["foff"]], s["fsz"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
