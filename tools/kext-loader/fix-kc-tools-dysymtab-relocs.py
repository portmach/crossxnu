#!/usr/bin/env python3
"""Teach kc-tools to apply LC_DYSYMTAB relocations for kexts.

Why: ld64 stores a kext's relocations in LC_DYSYMTAB's external and local
relocation tables, not in the section headers.  For such an image every
section has nreloc == 0, so kc-tools' per-section relocation pass never sees
an entry.  Consequences observed on hello.kext:

    call printf            -> e8 00 00 00 00     (call to next instruction)
    kmod_info.start/stop   -> 0xf50 / 0xf70      (bare __text offsets)

The kext then "starts" and panics with "Data/Stack execution not permitted".

Usage:
  python3 tools/kext-loader/fix-kc-tools-dysymtab-relocs.py apply|revert
"""
import os
import sys

LINKER = os.path.expanduser("~/work/kc-tools/lib/linker.c")

HELPERS = """/*
 * Relocations of a kext live in LC_DYSYMTAB, not in the section headers.
 * ld64 fills in the external and local relocation tables and leaves every
 * section's nreloc at 0, so the per-section pass in link_kext() never sees a
 * single entry.  Left unapplied, an external branch keeps the addend-only
 * encoding (e8 00 00 00 00, i.e. "call the next instruction") and local
 * pointer slots keep bare __text offsets.
 *
 * dyld applies these entries as "value + slide".  We instead re-link the
 * kext at a different vmbase, so each entry needs the fully relocated value:
 *
 *   extern + UNSIGNED : slot = symbol_va + addend
 *   extern + pcrel    : slot = symbol_va - (pc + 4 + extra) + addend
 *   local  + UNSIGNED : slot = slot + (delta applied to every section)
 *   local  + pcrel    : slot = target_section_va - (pc + 4 + extra) + addend
 *
 * r_address is an offset in the image's original vmaddr space, therefore
 *   file offset = r_address - text_vmaddr + text_fileoff
 *   pc          = r_address + load_vmaddr
 */
static void
apply_dysymtab_relocations(uint8_t *buf, uint64_t linked_size,
    const struct dysymtab_command *dysym,
    const uint64_t *sym_addrs, uint32_t nsyms,
    const uint64_t *orig_sec_addr, uint32_t total_sects,
    uint64_t load_vmaddr, uint64_t text_vmaddr, uint64_t text_fileoff)
{
  if (!dysym)
    return;

  const uint32_t table_off[2] = { dysym->extreloff, dysym->locreloff };
  const uint32_t table_cnt[2] = { dysym->nextrel, dysym->nlocrel };

  for (int t = 0; t < 2; t++) {
    if (table_cnt[t] == 0 || table_off[t] == 0)
      continue;
    if ((uint64_t)table_off[t] + (uint64_t)table_cnt[t] * sizeof(struct relocation_info) > linked_size)
      continue;

    const struct relocation_info *relocs =
      (const struct relocation_info *)(buf + table_off[t]);
    for (uint32_t i = 0; i < table_cnt[t]; i++) {
      struct relocation_info r = relocs[i];
      uint64_t va = (uint64_t)(uint32_t)r.r_address;
      uint64_t foff = va - text_vmaddr + text_fileoff;
      uint64_t pc = va + load_vmaddr;
      uint64_t target = 0;

      if (foff + 8 > linked_size)
        continue;

      uint8_t *loc = buf + foff;

      if (r.r_extern) {
        if (r.r_symbolnum >= nsyms)
          continue;
        target = sym_addrs[r.r_symbolnum];
        if (!target)
          continue;               /* unresolved kernel symbol */
      } else {
        uint32_t si = r.r_symbolnum;
        if (si < 1 || si > total_sects)
          continue;
        target = orig_sec_addr[si - 1] + load_vmaddr;
      }

      switch (r.r_type) {
      case X86_64_RELOC_UNSIGNED: {
        uint64_t addend = (r.r_length == RL_QUAD) ? r64(loc) : (uint64_t)(uint32_t)r32(loc);
        uint64_t val = r.r_extern ? target + addend : addend + load_vmaddr;
        if (r.r_length == RL_QUAD)
          w64(loc, val);
        else
          w32(loc, (uint32_t)val);
        break;
      }
      case X86_64_RELOC_SIGNED:
      case X86_64_RELOC_BRANCH:
      case X86_64_RELOC_GOT_LOAD:
      case X86_64_RELOC_GOT:
      case X86_64_RELOC_SIGNED_1:
      case X86_64_RELOC_SIGNED_2:
      case X86_64_RELOC_SIGNED_4: {
        int extra = (r.r_type == X86_64_RELOC_SIGNED_1) ? 1 :
                    (r.r_type == X86_64_RELOC_SIGNED_2) ? 2 :
                    (r.r_type == X86_64_RELOC_SIGNED_4) ? 4 : 0;
        int64_t addend = (int32_t)r32(loc);
        int64_t rel = (int64_t)target - (int64_t)(pc + 4 + extra) + addend;
        w32(loc, (uint32_t)(int32_t)rel);
        break;
      }
      default:
        /* SUBTRACTOR needs its pair; kexts from ld64 do not use it here. */
        break;
      }
    }
  }
}

int link_kext("""

SCAN_ANCHOR = """    } else if (cmd == LC_SYMTAB) {
      symcmd = (const struct symtab_command *)lcp;
"""

SCAN_INSTR = """    } else if (cmd == LC_SYMTAB) {
      symcmd = (const struct symtab_command *)lcp;
    } else if (cmd == LC_DYSYMTAB) {
      dysym = (const struct dysymtab_command *)lcp;
"""

DECL_ANCHOR = """  const struct symtab_command *symcmd = NULL;
  const uint8_t *dyld_info = NULL;   // LC_DYLD_INFO(_ONLY) command
"""

DECL_INSTR = """  const struct symtab_command *symcmd = NULL;
  const struct dysymtab_command *dysym = NULL;  // kext relocation tables
  const uint8_t *dyld_info = NULL;   // LC_DYLD_INFO(_ONLY) command
  uint64_t text_vmaddr = 0;          // first segment, for r_address -> file
  uint64_t text_fileoff = 0;
  uint64_t orig_sec_addr[256];       // section vmaddrs before relocation
  uint32_t n_orig_sec = 0;
"""

REC_ANCHOR = """        MachoSect sec;
        macho_sect_get(&mv, sp, &sec);
        macho_sect_set(&mv, sp, sec.addr + load_vmaddr, sec.offset, sec.reloff);
"""

REC_INSTR = """        MachoSect sec;
        macho_sect_get(&mv, sp, &sec);
        if (n_orig_sec < sizeof(orig_sec_addr) / sizeof(orig_sec_addr[0]))
          orig_sec_addr[n_orig_sec++] = sec.addr;
        macho_sect_set(&mv, sp, sec.addr + load_vmaddr, sec.offset, sec.reloff);
"""

TEXT_ANCHOR = """      if (nseginfo < 32) {
        seginfo[nseginfo].fileoff = sg.fileoff;
"""

TEXT_INSTR = """      if (nseginfo == 0) {
        text_vmaddr = sg.vmaddr;
        text_fileoff = sg.fileoff;
      }
      if (nseginfo < 32) {
        seginfo[nseginfo].fileoff = sg.fileoff;
"""

CALL_ANCHOR = """  if (nerrs)
    fprintf(stderr, "  link_kext: %u unresolved symbols\\n", nerrs);
"""

CALL_INSTR = """  if (nerrs)
    fprintf(stderr, "  link_kext: %u unresolved symbols\\n", nerrs);

  /* Keeps ld64's LC_DYSYMTAB relocation tables from being ignored. */
  apply_dysymtab_relocations(buf, sl, dysym,
      sym_addrs, nsyms, orig_sec_addr, n_orig_sec,
      load_vmaddr, text_vmaddr, text_fileoff);
"""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    src = open(LINKER).read()

    if mode == "revert":
        src = src.replace(HELPERS + "int link_kext(", "int link_kext(")
        src = src.replace(SCAN_INSTR, SCAN_ANCHOR)
        src = src.replace(DECL_INSTR, DECL_ANCHOR)
        src = src.replace(REC_INSTR, REC_ANCHOR)
        src = src.replace(TEXT_INSTR, TEXT_ANCHOR)
        src = src.replace(CALL_INSTR, CALL_ANCHOR)
    else:
        if "apply_dysymtab_relocations" in src:
            print("already patched")
            return 0
        for anchor in (SCAN_ANCHOR, DECL_ANCHOR, REC_ANCHOR, TEXT_ANCHOR, CALL_ANCHOR):
            if anchor not in src:
                sys.exit("anchor not found; linker.c changed upstream?")
        src = src.replace("int link_kext(", HELPERS, 1)
        src = src.replace(SCAN_ANCHOR, SCAN_INSTR, 1)
        src = src.replace(DECL_ANCHOR, DECL_INSTR, 1)
        src = src.replace(REC_ANCHOR, REC_INSTR, 1)
        src = src.replace(TEXT_ANCHOR, TEXT_INSTR, 1)
        src = src.replace(CALL_ANCHOR, CALL_INSTR, 1)

    open(LINKER, "w").write(src)
    print("kc-tools linker.c %s" % ("reverted" if mode == "revert" else "patched"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
