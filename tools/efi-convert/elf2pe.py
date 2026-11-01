#!/usr/bin/env python3
"""Convert a gnu-efi style ELF shared object into a PE32+ EFI application.

gnu-efi's documented build step is

    objcopy -j .text -j .data ... --target=efi-app-x86_64 loader.so loader.efi

and the binutils on this machine are built without the PE/EFI targets, so the
conversion is done here instead.  The loader links `-shared -Bsymbolic` and only
carries R_X86_64_RELATIVE relocations, which map one to one onto PE
IMAGE_REL_BASED_DIR64 entries; everything else about the image is a straight
copy of the allocated sections into a PE section table.

Usage: elf2pe.py INPUT.so OUTPUT.efi
"""
import argparse
import struct
import sys

# ELF bits we need
PT_LOAD = 1
SHT_NOBITS = 8
SHF_ALLOC = 0x2
EM_X86_64 = 62

# PE constants
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_EXECUTABLE_IMAGE = 0x0002
IMAGE_FILE_LARGE_ADDRESS_AWARE = 0x0020
IMAGE_SUBSYSTEM_EFI_APPLICATION = 10
SECTION_ALIGNMENT = 0x1000
FILE_ALIGNMENT = 0x200

SCN_CNT_CODE = 0x00000020
SCN_CNT_INITIALIZED_DATA = 0x00000040
SCN_MEM_DISCARDABLE = 0x02000000
SCN_MEM_EXECUTE = 0x20000000
SCN_MEM_READ = 0x40000000
SCN_MEM_WRITE = 0x80000000

R_X86_64_RELATIVE = 8


def align_up(value, alignment):
    return (value + alignment - 1) // alignment * alignment


class Elf:
    def __init__(self, data):
        self.data = data
        if data[:4] != b"\x7fELF" or data[4] != 2:
            raise SystemExit("not an ELF64 file")
        (self.e_type, self.e_machine, _, self.e_entry, self.e_phoff,
         self.e_shoff, _, _, self.e_phentsize, self.e_phnum,
         self.e_shentsize, self.e_shnum,
         self.e_shstrndx) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)

        if self.e_machine != EM_X86_64:
            raise SystemExit("only x86_64 is supported")

        self.sections = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            (name, sh_type, flags, addr, offset, size, link, info, addralign,
             entsize) = struct.unpack_from("<IIQQQQIIQQ", data, off)
            self.sections.append({
                "index": i, "type": sh_type, "flags": flags, "addr": addr,
                "offset": offset, "size": size, "link": link,
                "entsize": entsize,
            })
        self._names()

    def _names(self):
        tab_sec = self.sections[self.e_shstrndx]
        tab = self.data[tab_sec["offset"]:tab_sec["offset"] + tab_sec["size"]]
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            name_off = struct.unpack_from("<I", self.data, off)[0]
            end = tab.find(b"\0", name_off)
            self.sections[i]["name"] = tab[name_off:end].decode("ascii",
                                                               "replace")

    def by_name(self, name):
        for sec in self.sections:
            if sec["name"] == name:
                return sec
        return None

    def relocations(self):
        """(r_offset, r_type) of every RELA entry."""
        out = []
        for sec in self.sections:
            if sec["type"] != 4:      # SHT_RELA
                continue
            for off in range(sec["offset"], sec["offset"] + sec["size"], sec["entsize"] or 24):
                r_offset, r_info, _ = struct.unpack_from("<QQq", self.data, off)
                out.append((r_offset, r_info & 0xFFFFFFFF))
        return out


def build_sections(elf):
    """Allocated, file-backed sections, in address order."""
    # Only what the image needs at run time.  .dynsym/.dynamic/.rela and the
    # hash tables are link-time artifacts: the base relocations have already
    # been turned into a .reloc section below, and the firmware resolves
    # nothing by name.
    keep_names = {".text", ".data", ".rodata", ".sdata", ".bss",
                  ".data.rel.ro"}

    keep = []
    for sec in elf.sections:
        if not (sec["flags"] & SHF_ALLOC):
            continue
        if sec["name"] not in keep_names:
            continue
        if sec["type"] == SHT_NOBITS:
            data = bytes(sec["size"])
        else:
            data = elf.data[sec["offset"]:sec["offset"] + sec["size"]]
        keep.append({"name": sec["name"], "rva": sec["addr"], "data": data,
                     "flags": sec["flags"]})
    keep.sort(key=lambda s: s["rva"])

    # Keep the ELF virtual addresses as RVAs: the entry point and the RELATIVE
    # relocations are expressed in that address space, so re-laying the
    # sections out would leave the entry point pointing at nothing.
    for sec in keep:
        if sec["rva"] % SECTION_ALIGNMENT:
            raise SystemExit("section %s is not page aligned" % sec["name"])
    return keep


def build_relocs(elf, sections):
    """PE base relocation table from the ELF R_X86_64_RELATIVE entries."""
    entries = {}
    skipped = 0
    for r_offset, r_type in elf.relocations():
        if r_type != R_X86_64_RELATIVE:
            skipped += 1
            continue
        page = r_offset & ~0xFFF
        entries.setdefault(page, []).append(r_offset & 0xFFF)
    if skipped:
        print("warning: %d relocations of unsupported types skipped" % skipped)

    out = bytearray()
    for page in sorted(entries):
        offsets = sorted(entries[page])
        body = bytearray()
        for off in offsets:
            body += struct.pack("<H", (10 << 12) | off)   # IMAGE_REL_BASED_DIR64
        # Pad with ABSOLUTE entries so the block is a multiple of four bytes.
        while (8 + len(body)) % 4:
            body += struct.pack("<H", 0)
        out += struct.pack("<II", page, 8 + len(body)) + body
    return bytes(out)


def characteristics(sec):
    name = sec["name"]
    if name == ".text":
        return SCN_CNT_CODE | SCN_MEM_EXECUTE | SCN_MEM_READ
    if name in (".data", ".sdata", ".bss"):
        return SCN_CNT_INITIALIZED_DATA | SCN_MEM_READ | SCN_MEM_WRITE
    if name == ".reloc":
        return (SCN_CNT_INITIALIZED_DATA | SCN_MEM_READ |
                SCN_MEM_DISCARDABLE)
    if sec["flags"] & 0x1:        # SHF_WRITE
        return SCN_CNT_INITIALIZED_DATA | SCN_MEM_READ | SCN_MEM_WRITE
    return SCN_CNT_INITIALIZED_DATA | SCN_MEM_READ


def convert(elf_path, out_path):
    data = open(elf_path, "rb").read()
    elf = Elf(data)

    sections = build_sections(elf)
    reloc = build_relocs(elf, sections)

    # .reloc goes after the last allocated section.
    last_end = max(s["rva"] + len(s["data"]) for s in sections)
    reloc_rva = align_up(last_end, SECTION_ALIGNMENT)
    sections.append({"name": ".reloc", "rva": reloc_rva, "data": reloc,
                     "flags": 0})

    size_of_image = align_up(reloc_rva + len(reloc), SECTION_ALIGNMENT)

    nsec = len(sections)
    optional_size = 240                      # PE32+ optional header
    headers_size = 0x40 + 4 + 20 + optional_size + 40 * nsec
    size_of_headers = align_up(headers_size, FILE_ALIGNMENT)

    # Lay the sections out in the file.
    file_off = size_of_headers
    for sec in sections:
        sec["file_off"] = file_off
        sec["raw_size"] = align_up(len(sec["data"]), FILE_ALIGNMENT)
        sec["characteristics"] = characteristics(sec)
        file_off += sec["raw_size"]

    out = bytearray()

    # DOS header
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    out += dos

    out += b"PE\0\0"
    out += struct.pack("<HHIIIHH", IMAGE_FILE_MACHINE_AMD64, nsec, 0, 0, 0,
                       optional_size,
                       IMAGE_FILE_EXECUTABLE_IMAGE |
                       IMAGE_FILE_LARGE_ADDRESS_AWARE)

    text = [s for s in sections if s["name"] == ".text"]
    opt = bytearray(optional_size)
    struct.pack_into("<H", opt, 0, 0x20B)                      # PE32+
    struct.pack_into("<I", opt, 4, sum(align_up(len(s["data"]), FILE_ALIGNMENT) for s in text))
    struct.pack_into("<I", opt, 8, sum(s["raw_size"] for s in sections if s["name"] != ".text"))
    struct.pack_into("<I", opt, 16, elf.e_entry)               # AddressOfEntryPoint
    struct.pack_into("<I", opt, 20, text[0]["rva"] if text else 0x1000)
    struct.pack_into("<Q", opt, 24, 0)                         # ImageBase
    struct.pack_into("<I", opt, 32, SECTION_ALIGNMENT)
    struct.pack_into("<I", opt, 36, FILE_ALIGNMENT)
    struct.pack_into("<H", opt, 40, 0)                         # OS version
    struct.pack_into("<H", opt, 48, 0)                         # image version
    struct.pack_into("<H", opt, 52, 0)                         # subsystem version
    struct.pack_into("<I", opt, 56, size_of_image)
    struct.pack_into("<I", opt, 60, size_of_headers)
    struct.pack_into("<H", opt, 68, IMAGE_SUBSYSTEM_EFI_APPLICATION)
    struct.pack_into("<Q", opt, 72, 0x100000)                  # stack reserve
    struct.pack_into("<Q", opt, 80, 0x1000)                    # stack commit
    struct.pack_into("<Q", opt, 88, 0x100000)                  # heap reserve
    struct.pack_into("<Q", opt, 96, 0x1000)                    # heap commit
    struct.pack_into("<I", opt, 108, 16)                       # NumberOfRvaAndSizes
    out += opt

    for sec in sections:
        name = sec["name"].encode("ascii")[:8]
        out += name.ljust(8, b"\0")
        out += struct.pack("<IIIIIIHHI", len(sec["data"]), sec["rva"],
                           sec["raw_size"], sec["file_off"], 0, 0, 0, 0,
                           sec["characteristics"])

    out += bytes(size_of_headers - len(out))

    for sec in sections:
        body = sec["data"] + bytes(sec["raw_size"] - len(sec["data"]))
        assert len(out) == sec["file_off"], (len(out), sec["file_off"])
        out += body

    open(out_path, "wb").write(out)
    print("%s: %d sections, image 0x%x, reloc %d bytes, entry 0x%x"
          % (out_path, nsec, size_of_image, len(reloc), elf.e_entry))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input")
    ap.add_argument("output")
    args = ap.parse_args(argv)
    convert(args.input, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
