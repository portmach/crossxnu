#!/usr/bin/env python3
"""Print the entry of each ZALLOC-rank startup hook.

The apfs collection panics inside vm_mem_bootstrap(), after the hook that
prints "VM bootstrap done" (ZALLOC/SECOND).  These hooks run after it, so a
breadcrumb at the top of each says which one faults.

Usage: python3 tools/kext-loader/instrument-zalloc-hooks.py apply|revert
"""
import os
import sys

XNU = os.path.join(os.path.dirname(__file__), "..", "..", "upstream/xnu")
XNU = os.path.normpath(XNU)

HOOKS = [
    ("osfmk/kern/kalloc.c", "kalloc_init"),
    ("osfmk/kern/thread.c", "thread_zone_startup"),
    ("osfmk/vm/vm_compressor_pager.c", "vm_compressor_slots_init"),
    ("osfmk/vm/vm_fault.c", "vm_rtfault_record_init"),
    ("osfmk/kern/zalloc.c", "zone_early_alloc_cleanup"),
    ("osfmk/kern/zalloc.c", "zone_init"),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    done = 0
    for rel, func in HOOKS:
        path = os.path.join(XNU, rel)
        src = open(path).read()
        marker = 'printf("cx-hook: %s\\n");\n' % func
        if mode == "revert":
            if marker in src:
                src = src.replace("\t" + marker, "", 1)
                open(path, "w").write(src)
                done += 1
            continue
        if marker in src:
            print("%s already instrumented" % func)
            continue
        # Find the function definition and its opening brace.
        pat = "\n" + func + "("
        i = src.find(pat)
        if i < 0:
            print("warning: %s not found in %s" % (func, rel))
            continue
        j = src.find("\n{\n", i)
        if j < 0 or j - i > 400:
            print("warning: body of %s not found" % func)
            continue
        insert = j + 3
        src = src[:insert] + "\t" + marker + src[insert:]
        open(path, "w").write(src)
        print("instrumented %s (%s)" % (func, rel))
        done += 1
    print("done: %d" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
