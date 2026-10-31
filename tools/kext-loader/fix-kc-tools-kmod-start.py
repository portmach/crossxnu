#!/usr/bin/env python3
"""Add kmod_info start/stop rebasing to kc-tools' linker.c.

ld64 emits kmod_info.start and kmod_info.stop as *classic local relocations*
into __TEXT.  kc-tools links a kext at a nonzero vmbase but does not rebase
those two slots (unlike the external relocations, they carry no symbol the
kernel symbol table can resolve), so the linked kext ends up with

    start = 0xf50          <- bare __text offset
    stop  = 0xf70

and OSKext rejects it with

    module start pointer is outside of kext range (start 0xf50 - kext starts at
    0xffffff80011c0000)
    -> kOSKextReturnInternalError (0xdc008007)

This script appends the fix to patch_kmod_info().

Usage: python3 build/dis/fix-kc-tools-kmod-start.py [--revert]
"""
import os
import sys

LINKER = os.path.expanduser("~/work/kc-tools/lib/linker.c")

DEFINES = """#define KMOD_OFF_ADDR_64 156
#define KMOD_OFF_SIZE_64 164
#define KMOD_OFF_ADDR_32 148
#define KMOD_OFF_SIZE_32 152
"""

DEFINES_WITH_START_STOP = DEFINES + """
/*
 * kmod_info_t is { ..., vm_address_t address; vm_size_t size;
 * vm_size_t hdr_size; kmod_start_func_t *start; kmod_stop_func_t *stop; }
 * with start/stop right after the three scalars.  The struct is packed to 4
 * bytes and the header does not spell the offsets out, so derive them.
 */
#define KMOD_OFF_START_64 (KMOD_OFF_ADDR_64 + 24)  /* 180 */
#define KMOD_OFF_STOP_64  (KMOD_OFF_START_64 + 8)  /* 188 */
#define KMOD_OFF_START_32 (KMOD_OFF_ADDR_32 + 12)  /* 160 */
#define KMOD_OFF_STOP_32  (KMOD_OFF_START_32 + 4)  /* 164 */
"""

ANCHOR = """  fprintf(stderr,
      " patched kmod_info: %s "
      "kmod=0x%llx address=0x%llx size=0x%llx\\n",
      lk->bundle_id ? lk->bundle_id : "<unknown>",
      (unsigned long long)lk->kmod_info_addr,
      (unsigned long long)image_start,
      (unsigned long long)image_size);

  return 0;
}
"""

PATCHED = """  /*
   * kmod_info.start / kmod_info.stop are function pointers into __TEXT.  A
   * kext linked at vmbase 0 holds them as bare offsets (0xf50, ...), and
   * ld64 records them as *local* relocations, which resolve to the section
   * address only when the kext is relocated.  kc-tools links the kext at its
   * final vmbase, but these two slots are not covered by the symbol table
   * fixups (there is no symbol for them to look up), so they stay bare and
   * OSKext rejects the kext with "module start pointer is outside of kext
   * range".  Rebase them here, once, after placement.
   */
  {
    const uint32_t kmod_off_start =
      mv.is64 ? KMOD_OFF_START_64 : KMOD_OFF_START_32;
    const uint32_t kmod_off_stop =
      mv.is64 ? KMOD_OFF_STOP_64 : KMOD_OFF_STOP_32;
    uint64_t start_foff = va_to_foff(lk->linked_data,
        lk->linked_size,
        lk->kmod_info_addr + kmod_off_start,
        kmod_field);
    uint64_t stop_foff = va_to_foff(lk->linked_data,
        lk->linked_size,
        lk->kmod_info_addr + kmod_off_stop,
        kmod_field);

    if (start_foff != UINT64_MAX && stop_foff != UINT64_MAX) {
      uint8_t *start_slot = lk->linked_data + start_foff;
      uint8_t *stop_slot  = lk->linked_data + stop_foff;
      uint64_t start_val = mv.is64 ? r64(start_slot) : r32(start_slot);
      uint64_t stop_val  = mv.is64 ? r64(stop_slot) : r32(stop_slot);

      /* A nonzero value below the image base can only be a bare offset. */
      if (start_val && start_val < image_start)
        start_val += image_start;
      if (stop_val && stop_val < image_start)
        stop_val += image_start;

      if (mv.is64) {
        w64(start_slot, start_val);
        w64(stop_slot, stop_val);
      } else {
        w32(start_slot, (uint32_t)start_val);
        w32(stop_slot, (uint32_t)stop_val);
      }

      fprintf(stderr,
          " patched kmod_info start/stop: %s start=0x%llx stop=0x%llx\\n",
          lk->bundle_id ? lk->bundle_id : "<unknown>",
          (unsigned long long)start_val,
          (unsigned long long)stop_val);
    }
  }

""" + ANCHOR


def main():
    revert = "--revert" in sys.argv
    src = open(LINKER).read()

    if revert:
        src = src.replace(DEFINES_WITH_START_STOP, DEFINES)
        src = src.replace(PATCHED, ANCHOR)
    else:
        if "KMOD_OFF_START_64" in src:
            print("already patched")
            return 0
        if ANCHOR not in src:
            sys.exit("anchor for patch_kmod_info not found; linker.c changed upstream?")
        src = src.replace(DEFINES, DEFINES_WITH_START_STOP, 1)
        src = src.replace(ANCHOR, PATCHED, 1)

    open(LINKER, "w").write(src)
    print("kc-tools linker.c %s" % ("reverted" if revert else "patched"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
