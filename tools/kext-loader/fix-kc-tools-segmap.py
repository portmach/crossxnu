#!/usr/bin/env python3
"""Fix kc-tools: map relocation addresses through the segment table.

The LC_DYSYMTAB relocation pass computed a file offset as
`r_address - text_vmaddr + text_fileoff`, which is only correct when every
segment's file offset equals its vmaddr.  apfs.kext from the KDK breaks that
assumption (__DATA_CONST vmaddr 0x1c6000 lives at file offset 0x1c5000), so
its __kalloc_type relocations were written 0x1000 bytes past the real
pointers: the views kept image-relative values and the kernel crashed in
kalloc_init() while comparing type names.

The pass now uses the original (pre-relocation) segment table captured in
link_kext().

Usage: python3 tools/kext-loader/fix-kc-tools-segmap.py apply|revert
"""
import os
import sys

LINKER = os.path.expanduser("~/work/kc-tools/lib/linker.c")

SIG_OLD = """static void
apply_dysymtab_relocations(uint8_t *buf, uint64_t linked_size,
    const struct dysymtab_command *dysym,
    const uint64_t *sym_addrs, uint32_t nsyms,
    const uint64_t *orig_sec_addr, uint32_t total_sects,
    uint64_t load_vmaddr, uint64_t text_vmaddr, uint64_t text_fileoff)
{"""

SIG_NEW = """typedef struct { uint64_t vm; uint64_t foff; uint64_t fsize; } OrigSeg;

/* r_address is in the image's original vmaddr space; convert it with the
 * segment table captured before the vmaddrs were relocated. */
static uint64_t
orig_va_to_foff(const OrigSeg *segs, uint32_t nsegs, uint64_t va)
{
  for (uint32_t i = 0; i < nsegs; i++) {
    if (va >= segs[i].vm && va < segs[i].vm + segs[i].fsize) {
      return segs[i].foff + (va - segs[i].vm);
    }
  }
  return UINT64_MAX;
}

static void
apply_dysymtab_relocations(uint8_t *buf, uint64_t linked_size,
    const struct dysymtab_command *dysym,
    const uint64_t *sym_addrs, uint32_t nsyms,
    const uint64_t *orig_sec_addr, uint32_t total_sects,
    uint64_t load_vmaddr, const OrigSeg *segs, uint32_t nsegs)
{"""

BODY_OLD = """      struct relocation_info r = relocs[i];
      uint64_t va = (uint64_t)(uint32_t)r.r_address;
      uint64_t foff = va - text_vmaddr + text_fileoff;
      uint64_t pc = va + load_vmaddr;
      uint64_t target = 0;

      if (foff + 8 > linked_size)
        continue;
"""

BODY_NEW = """      struct relocation_info r = relocs[i];
      uint64_t va = (uint64_t)(uint32_t)r.r_address;
      uint64_t foff = orig_va_to_foff(segs, nsegs, va);
      uint64_t pc = va + load_vmaddr;
      uint64_t target = 0;

      if (foff == UINT64_MAX || foff + 8 > linked_size)
        continue;
"""

CALL_OLD = """  apply_dysymtab_relocations(buf, sl, dysym,
      sym_addrs, nsyms, orig_sec_addr, n_orig_sec,
      load_vmaddr, text_vmaddr, text_fileoff);"""

CALL_NEW = """  apply_dysymtab_relocations(buf, sl, dysym,
      sym_addrs, nsyms, orig_sec_addr, n_orig_sec,
      load_vmaddr, orig_segs, n_orig_segs);"""

DECL_OLD = """  uint64_t text_vmaddr = 0;          // first segment, for r_address -> file
  uint64_t text_fileoff = 0;
"""

DECL_NEW = """  OrigSeg  orig_segs[32];            // segment vmaddr/fileoff before relocation
  uint32_t n_orig_segs = 0;
"""

TEXT_OLD = """      if (nseginfo == 0) {
        text_vmaddr = sg.vmaddr;
        text_fileoff = sg.fileoff;
      }
"""

TEXT_NEW = """      if (n_orig_segs < 32) {
        orig_segs[n_orig_segs].vm = sg.vmaddr;
        orig_segs[n_orig_segs].foff = sg.fileoff;
        orig_segs[n_orig_segs].fsize = sg.filesize;
        n_orig_segs++;
      }
"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    src = open(LINKER).read()

    if mode == "revert":
        src = src.replace(SIG_NEW, SIG_OLD)
        src = src.replace(BODY_NEW, BODY_OLD)
        src = src.replace(CALL_NEW, CALL_OLD)
        src = src.replace(DECL_NEW, DECL_OLD)
        src = src.replace(TEXT_NEW, TEXT_OLD)
    else:
        if "orig_va_to_foff" in src:
            print("already fixed")
            return 0
        for a in (SIG_OLD, BODY_OLD, CALL_OLD, DECL_OLD, TEXT_OLD):
            if a not in src:
                sys.exit("anchor missing: %r" % a[:60])
        src = src.replace(SIG_OLD, SIG_NEW, 1)
        src = src.replace(BODY_OLD, BODY_NEW, 1)
        src = src.replace(CALL_OLD, CALL_NEW, 1)
        src = src.replace(DECL_OLD, DECL_NEW, 1)
        src = src.replace(TEXT_OLD, TEXT_NEW, 1)

    open(LINKER, "w").write(src)
    print("kc-tools linker.c %s" % ("reverted" if mode == "revert" else "fixed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
