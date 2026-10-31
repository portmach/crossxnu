#!/usr/bin/env python3
"""Fix kc-tools' section-relocation path for local UNSIGNED relocations.

ld64 stores local pointers as absolute vmaddrs in the image's own address
space (the image is linked at vmbase 0).  The section pass added the target
section address on top, corrupting them; only the placement slide is needed.
This is the same correction the LC_DYSYMTAB pass already uses.

Usage: python3 tools/kext-loader/fix-kc-tools-local-sect-relocs.py apply|revert
"""
import os
import sys

LINKER = os.path.expanduser("~/work/kc-tools/lib/linker.c")

OLD = """          case X86_64_RELOC_UNSIGNED: {
            uint64_t addend = r64(loc);
            w64(loc, target + addend);
            break;
          }"""

NEW = """          case X86_64_RELOC_UNSIGNED: {
            uint64_t addend = r64(loc);
            /*
             * The stored value is an absolute vmaddr in the image's own
             * address space (the image is linked at vmbase 0), so a local
             * reference only needs the placement slide.  Adding the target
             * section address on top corrupts it, which broke __kalloc_type
             * names and OSMetaClass strings.
             */
            w64(loc, r.r_extern ? target + addend : addend + load_vmaddr);
            break;
          }"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    src = open(LINKER).read()
    if mode == "revert":
        src = src.replace(NEW, OLD)
    else:
        if "only needs the placement slide" in src:
            print("already fixed")
            return 0
        if OLD not in src:
            sys.exit("anchor missing")
        src = src.replace(OLD, NEW, 1)
    open(LINKER, "w").write(src)
    print("section reloc path %s" % ("reverted" if mode == "revert" else "fixed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
