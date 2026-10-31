#!/usr/bin/env python3
"""Re-target an extracted Apple kext onto our own XNU build.

The kext images inside a kernel collection are fully linked: every reference
to a kernel symbol is encoded as a direct branch or a rip-relative operand
pointing at the address that symbol had in *Apple's* kernel.  Our kernel is
built from the same source but its symbols sit at different addresses, so the
image cannot be loaded as-is.

This tool rewrites exactly those references:

  * direct call/jmp whose target lies in the collection's kernel image,
  * rip-relative operands (code reading kernel globals, vtables, ...),
  * pointer-sized values in data sections that point into the kernel image,

mapping Apple address -> symbol name (the collection's own symbol table) ->
our address (our kernel's symbol table).  References inside the kext and
references into other kexts of the collection are left untouched: those keep
working as long as every kext is loaded at the address it has in the
collection.

Usage:
  python3 tools/kext-loader/kc-retarget.py KC KEXT OUR_KERNEL OUT [--apply]

Without --apply it only reports what it would change.
"""
import os
import struct
import subprocess
import sys

from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_REG_RIP

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_FILESET_ENTRY = 0x80000035

NM = os.environ.get("CROSSXNU_NM", "build/cctools/bin/x86_64-apple-darwin11-nm")
DATA_SECTIONS = {"__got", "__data", "__const", "__bss", "__common",
                 "__mod_init_func", "__mod_term_func", "__kmod_info",
                 "__os_log", "__cstring"}


def cstr(b):
    return b.split(b"\0")[0].decode(errors="replace")


def parse_image(data, off):
    """Segments (name, vm, vmsz, foff, fsz, sections) + symtab addr->name."""
    if struct.unpack_from("<I", data, off)[0] != MH_MAGIC_64:
        return None
    ncmds = struct.unpack_from("<I", data, off + 16)[0]
    p = off + 32
    segs = []
    symtab = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_SEGMENT_64:
            name = cstr(data[p + 8:p + 24])
            vm, vmsz, foff, fsz = struct.unpack_from("<QQQQ", data, p + 24)
            nsects = struct.unpack_from("<I", data, p + 64)[0]
            sects = []
            for j in range(nsects):
                sec = p + 72 + j * 80
                sname = cstr(data[sec:sec + 16])
                addr, size = struct.unpack_from("<QQ", data, sec + 32)
                soff = struct.unpack_from("<I", data, sec + 48)[0]
                sects.append((sname, addr, size, soff))
            segs.append({"name": name, "vm": vm, "vmsz": vmsz, "foff": foff,
                         "fsz": fsz, "sects": sects})
        elif cmd == LC_SYMTAB:
            symtab = struct.unpack_from("<IIII", data, p + 8)
        p += cmdsize
    assert symtab is not None

    symoff, nsyms, stroff, strsize = symtab
    syms = {}
    for i in range(nsyms):
        e = symoff + i * 16
        strx, ntype, nsec, desc, value = struct.unpack_from("<IBBHQ", data, e)
        if not value or (ntype & 0x0e) not in (0x0e, 0x02):
            continue
        name = cstr(data[stroff + strx:stroff + strx + 200])
        if name and value not in syms:
            syms[value] = name
    return {"segs": segs, "syms": syms, "off": off}


def collection(kc_path):
    data = open(kc_path, "rb").read()
    kernel = parse_image(data, 0)
    assert kernel
    entries = []
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd == LC_FILESET_ENTRY:
            vm, foff = struct.unpack_from("<QQ", data, p + 8)
            idoff = struct.unpack_from("<I", data, p + 24)[0]
            entries.append((cstr(data[p + idoff:p + idoff + 96]), foff))
        p += cmdsize
    return data, kernel, entries


def ranges(image):
    return [(s["vm"], s["vm"] + s["vmsz"]) for s in image["segs"] if s["vmsz"]]


def in_ranges(addr, rs):
    for lo, hi in rs:
        if lo <= addr < hi:
            return True
    return False


def our_kernel_symbols(path):
    out = subprocess.run([NM, "-n", path], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("nm failed on %s: %s" % (path, out.stderr[-200:]))
    m = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[-1]
        if name.startswith("(") or not name:
            continue
        try:
            addr = int(parts[0], 16)
        except ValueError:
            continue
        if addr:
            m.setdefault(name, addr)
    return m


def main():
    kc_path, kext_path, kernel_path, out_path = sys.argv[1:5]
    apply = "--apply" in sys.argv

    kc_data, kernel, entries = collection(kc_path)
    kernel_ranges = ranges(kernel)
    kext_ranges = []
    for eid, foff in entries:
        img = parse_image(kc_data, foff)
        if img:
            kext_ranges.append((eid, ranges(img)))
    print("kernel image: %d ranges, %d symbols" % (len(kernel_ranges), len(kernel["syms"])))
    print("collection: %d kexts" % len(entries))

    kext = parse_image(open(kext_path, "rb").read(), 0)
    if not kext:
        sys.exit("not a Mach-O: %s" % kext_path)
    data = bytearray(open(kext_path, "rb").read())
    own_ranges = ranges(kext)
    ours = our_kernel_symbols(kernel_path)

    def kext_owner(addr):
        for eid, rs in kext_ranges:
            if in_ranges(addr, rs):
                return eid
        return None

    def to_ours(addr):
        """Apple kernel address -> our address, via the collection symtab."""
        name = kernel["syms"].get(addr)
        if name is None:
            return None, None
        return ours.get(name), name

    patches = []      # (file_offset, size, new_bytes, kind, detail)
    stats = {"call_ok": 0, "call_miss": 0, "rip_ok": 0, "rip_miss": 0,
             "ptr_ok": 0, "ptr_miss": 0, "kext_refs": 0, "internal": 0}
    misses = {}

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    # --- code ---
    for seg in kext["segs"]:
        for sname, addr, size, soff in seg["sects"]:
            if not (sname.startswith("__text") or sname in ("__stubs", "__init_text")):
                continue
            code = bytes(data[soff:soff + size])
            for ins in md.disasm(code, addr):
                target = None
                field = None
                kind = None
                if ins.mnemonic in ("call", "jmp", "je", "jne", "jz", "jnz", "jb",
                                    "jbe", "ja", "jae", "jl", "jle", "jg", "jge",
                                    "js", "jns", "jo", "jno") and len(ins.operands) == 1:
                    op = ins.operands[0]
                    if op.type == X86_OP_IMM:
                        target = op.imm
                        field = ins.encoding.imm_offset
                        kind = "call"
                elif len(ins.operands) >= 1:
                    for op in ins.operands:
                        if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                            target = (ins.address + ins.size + op.mem.disp) & 0xFFFFFFFFFFFFFFFF
                            field = ins.encoding.disp_offset
                            kind = "rip"
                            break

                if target is None:
                    continue
                if in_ranges(target, own_ranges):
                    stats["internal"] += 1
                    continue
                if kext_owner(target) is not None:
                    stats["kext_refs"] += 1
                    continue
                if not in_ranges(target, kernel_ranges):
                    continue

                addr_ours, name = to_ours(target)
                key = "call" if kind == "call" else "rip"
                if addr_ours is None:
                    stats[key + "_miss"] += 1
                    misses.setdefault(target, 0)
                    misses[target] += 1
                    continue

                ins_off = soff + (ins.address - addr)
                if kind == "call":
                    new_val = addr_ours - (ins.address + ins.size)
                    assert -(1 << 31) <= new_val < (1 << 31), hex(new_val)
                    patches.append((ins_off + field, 4, struct.pack("<i", new_val),
                                    "call", name))
                    stats["call_ok"] += 1
                else:
                    new_disp = (addr_ours - (ins.address + ins.size)) & 0xFFFFFFFF
                    patches.append((ins_off + field, 4, struct.pack("<I", new_disp),
                                    "rip", name))
                    stats["rip_ok"] += 1

    # --- data ---
    for seg in kext["segs"]:
        for sname, addr, size, soff in seg["sects"]:
            if sname not in DATA_SECTIONS or not size or not soff:
                continue
            for k in range(0, size - 7, 8):
                val = struct.unpack_from("<Q", data, soff + k)[0]
                if in_ranges(val, own_ranges):
                    continue
                if kext_owner(val) is not None:
                    stats["kext_refs"] += 1
                    continue
                if not in_ranges(val, kernel_ranges):
                    continue
                addr_ours, name = to_ours(val)
                if addr_ours is None:
                    stats["ptr_miss"] += 1
                    misses.setdefault(val, 0)
                    misses[val] += 1
                    continue
                patches.append((soff + k, 8, struct.pack("<Q", addr_ours), "ptr", name))
                stats["ptr_ok"] += 1

    print("\nreferences into Apple's kernel image:")
    print("  call/jmp rewritten: %d, unresolved: %d" % (stats["call_ok"], stats["call_miss"]))
    print("  rip-relative rewritten: %d, unresolved: %d" %
          (stats["rip_ok"], stats["rip_miss"]))
    print("  data pointers rewritten: %d, unresolved: %d" %
          (stats["ptr_ok"], stats["ptr_miss"]))
    print("left alone: %d references into other kexts, %d internal" %
          (stats["kext_refs"], stats["internal"]))
    if misses:
        print("\nunresolved kernel addresses: %d distinct" % len(misses))
        for addr, cnt in sorted(misses.items(), key=lambda kv: -kv[1])[:15]:
            near = max((a for a in kernel["syms"] if a <= addr), default=None)
            extra = ""
            if near is not None:
                extra = " (nearest symbol %s +0x%x)" % (kernel["syms"][near], addr - near)
            print("  0x%x x%d%s" % (addr, cnt, extra))

    if not apply:
        print("\nre-run with --apply to write %s" % out_path)
        return 0

    for off, size, blob, kind, name in patches:
        data[off:off + size] = blob
    with open(out_path, "wb") as f:
        f.write(data)
    print("\nwrote %s (%d patches)" % (out_path, len(patches)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
