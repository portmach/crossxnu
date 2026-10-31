#!/usr/bin/env python3
"""Temporary: print local UNSIGNED relocations applied by kc-tools."""
import os
import sys

LINKER = os.path.expanduser("~/work/kc-tools/lib/linker.c")

ANCHOR = """        uint64_t val = r.r_extern ? target + addend : addend + load_vmaddr;
"""
INSTR = """        uint64_t val = r.r_extern ? target + addend : addend + load_vmaddr;
        if (getenv("KC_DEBUG_LOCAL") && !r.r_extern && va >= 0x1c6000 && va < 0x1c9000)
          fprintf(stderr, "  localUNSIGNED @0x%llx addend=0x%llx -> 0x%llx\\n",
                  (unsigned long long)va, (unsigned long long)addend,
                  (unsigned long long)val);
"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    src = open(LINKER).read()
    if mode == "revert":
        src = src.replace(INSTR, ANCHOR)
    else:
        if "KC_DEBUG_LOCAL" in src:
            print("already")
            return 0
        if ANCHOR not in src:
            sys.exit("anchor missing")
        src = src.replace(ANCHOR, INSTR, 1)
    open(LINKER, "w").write(src)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
