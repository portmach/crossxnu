#!/usr/bin/env python3
"""Report the instance size each OSMetaClass registers for a class in a kext.

Why this matters when building a kext against headers from an older SDK: a
subclass allocates `sizeof(Subclass)` bytes, which is the base class's size
plus the subclass's own members.  If the shipped base class grew new data
members since the header was written, the object is under-allocated and the
base class writes past its end - a corruption that surfaces far away.

Every class registers its size with `OSMetaClass::OSMetaClass(const char *,
const OSMetaClass *, unsigned int)`, so the number is baked into the kext's
static initialiser as an immediate operand.  This tool finds that call for a
class name and prints the size.

Usage:
  kext-class-size.py KEXT_BINARY [CLASS ...]
  (with no CLASS it lists every class it can recover)
"""

import struct
import sys

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_REG_RIP
except ImportError:
    raise SystemExit("needs capstone: pip install capstone")

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
FAT = (0xCAFEBABE, 0xCAFEBABF)
CPU_X86_64 = 0x01000007
OSMETACLASS_CTOR = "__ZN11OSMetaClassC2EPKcPKS_j"


def load_slice(path):
    data = open(path, "rb").read()
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in FAT:
        n = struct.unpack_from(">I", data, 4)[0]
        wide = magic == 0xCAFEBABF
        es = 32 if wide else 20
        for i in range(n):
            b = 8 + i * es
            if wide:
                ct, _, off, size = struct.unpack_from(">IIQQ", data, b)
            else:
                ct, _, off, size = struct.unpack_from(">IIII", data, b)
            if ct == CPU_X86_64:
                return data, off, size
        raise SystemExit("no x86_64 slice")
    return data, 0, len(data)


class MachO:
    def __init__(self, path):
        self.data, self.base, self.size = load_slice(path)
        d, b = self.data, self.base
        assert struct.unpack_from("<I", d, b)[0] == MH_MAGIC_64, "not a 64-bit Mach-O"
        ncmds, sizeofcmds = struct.unpack_from("<II", d, b + 16)
        p = b + 32
        self.segs = []
        self.symtab = None
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", d, p)
            if cmd == LC_SEGMENT_64:
                name = d[p + 8:p + 24].rstrip(b"\0").decode()
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", d, p + 24)
                nsects = struct.unpack_from("<I", d, p + 64)[0]
                seg = {"name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                       "fileoff": fileoff, "filesize": filesize, "sects": []}
                sp = p + 72
                for _s in range(nsects):
                    sname = d[sp:sp + 16].rstrip(b"\0").decode()
                    sseg = d[sp + 16:sp + 32].rstrip(b"\0").decode()
                    addr, sz = struct.unpack_from("<QQ", d, sp + 32)
                    soff = struct.unpack_from("<I", d, sp + 48)[0]
                    flags = struct.unpack_from("<I", d, sp + 64)[0]
                    seg["sects"].append({"sectname": sname, "segname": sseg,
                                         "addr": addr, "size": sz, "offset": soff,
                                         "flags": flags})
                    sp += 80
                self.segs.append(seg)
            elif cmd == LC_SYMTAB:
                symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", d, p + 8)
                self.symtab = (symoff, nsyms, stroff, strsize)
            p += cmdsize

    def text(self):
        """(vmaddr, bytes) of the executable segment's file image."""
        for s in self.segs:
            if s["name"] in ("__TEXT", "__TEXT_EXEC") and s["filesize"]:
                off = self.base + s["fileoff"]
                return s["vmaddr"], self.data[off:off + s["filesize"]]
        raise SystemExit("no text segment")

    def code_sections(self):
        """[(vmaddr, bytes)] of sections that hold instructions.

        Disassembling the whole __TEXT segment would stop at the first byte of
        __cstring, which lives in the same segment, so walk the sections and
        take only the ones flagged as code.
        """
        S_ATTR_SOME_INSTRUCTIONS = 0x00000400
        out = []
        for s in self.segs:
            for sec in s["sects"]:
                if not sec["size"] or not sec["offset"]:
                    continue
                is_code = (sec["flags"] & S_ATTR_SOME_INSTRUCTIONS) or \
                    sec["sectname"] in ("text", "stubs")
                if not is_code:
                    continue
                off = self.base + sec["offset"]
                out.append((sec["addr"], self.data[off:off + sec["size"]]))
        return out

    def va_to_fileoff(self, va):
        for s in self.segs:
            if s["vmaddr"] <= va < s["vmaddr"] + s["filesize"]:
                return s["fileoff"] + (va - s["vmaddr"])
        return None

    def find_string(self, va):
        off = self.va_to_fileoff(va)
        if off is None:
            return None
        end = self.data.find(b"\0", self.base + off)
        if end < 0:
            return None
        return self.data[self.base + off:end].decode("utf-8", "replace")

    def symbols(self):
        if not self.symtab:
            return {}
        symoff, nsyms, stroff, strsize = self.symtab
        out = {}
        for i in range(nsyms):
            n_strx, n_type, n_sect, n_desc, n_value = struct.unpack_from(
                "<IBBHQ", self.data, self.base + symoff + i * 16)
            if n_strx >= strsize:
                continue
            name = self.data[self.base + stroff + n_strx:].split(b"\0", 1)[0].decode(
                "utf-8", "replace")
            if n_value:
                out.setdefault(name, n_value)
        return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path, wanted = sys.argv[1], sys.argv[2:]
    mo = MachO(path)
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    # The constructor is an import here (it lives in the kernel), so its call
    # sites have a relocation placeholder instead of a target address.  Walk
    # the code and pair each class-name load with the size immediate that
    # precedes the following call.
    found = []
    for sec_va, sec in mo.code_sections():
        name = None
        size = None
        for insn in md.disasm(sec, sec_va):
            if insn.mnemonic == "lea" and len(insn.operands) == 2:
                dst, src = insn.operands
                if src.type == X86_OP_MEM and src.mem.base == X86_REG_RIP and \
                        insn.reg_name(dst.reg) == "rsi":
                    s = mo.find_string(insn.address + insn.size + src.mem.disp)
                    if s and s.replace("_", "").replace(":", "").isalnum():
                        name, size = s, None
            elif insn.mnemonic == "mov" and len(insn.operands) == 2:
                dst, src = insn.operands
                if src.type == X86_OP_IMM and insn.reg_name(dst.reg) == "ecx":
                    size = src.imm
            elif insn.mnemonic == "call":
                if name and size:
                    found.append((name, size))
                    size = None

    if wanted:
        wanted = set(wanted)
        found = [f for f in found if f[0] in wanted]
        missing = wanted - {f[0] for f in found}
        if missing:
            print("not found: %s" % ", ".join(sorted(missing)))

    print("%-40s %8s %8s" % ("class", "size", "hex"))
    for name, size in sorted(set(found)):
        print("%-40s %8d   0x%x" % (name, size, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
