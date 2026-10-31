#!/usr/bin/env python3
"""Add kprintf breadcrumbs between the early kernel_bootstrap() steps.

The apfs collection panics between vm_mem_bootstrap() and thread_init() and
startup_debug=1 produces nothing (its log needs STARTUP_SUB_KPRINTF), so we
print a line after each step instead.

Usage: python3 build/dis/instrument-bootstrap.py apply|revert
"""
import os
import re
import sys

SRC = os.path.join(os.path.dirname(__file__), "..", "..",
                   "upstream/xnu/osfmk/kern/startup.c")
SRC = os.path.normpath(SRC)

STEPS = [
    "vm_mem_bootstrap", "atm_init", "console_init", "stackshot_init",
    "mac_policy_init", "PMAP_ACTIVATE_KERNEL", "mapping_free_prime",
    "machine_init", "thread_machine_init_template", "clock_init",
    "thread_group_init", "coalitions_init", "code_signing_init",
    "task_init", "thread_init",
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    src = open(SRC).read()

    if mode == "revert":
        src = re.sub(r'\n\tkprintf\("cx-step: [A-Za-z_]+ done\\n"\);', "", src)
        open(SRC, "w").write(src)
        print("reverted")
        return 0

    if "cx-step:" in src:
        print("already instrumented")
        return 0

    for step in STEPS:
        # Find the call as a statement of its own line.
        pattern = re.compile(r"\n(\t" + re.escape(step) + r"\([^\n]*\);\n)")
        m = pattern.search(src)
        if not m:
            print("warning: %s not found" % step)
            continue
        line = m.group(1)
        src = src[:m.start(1) + len(line)] + \
            "\tkprintf(\"cx-step: %s done\\n\");\n" % step + \
            src[m.start(1) + len(line):]

    open(SRC, "w").write(src)
    count = src.count("cx-step:")
    print("instrumented %d steps" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
