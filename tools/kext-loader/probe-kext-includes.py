#!/usr/bin/env python3
"""Probe which include combinations compile against the exported kernel headers.

Usage: python3 build/dis/probe-kext-includes.py
"""
import json
import os
import subprocess
import sys

ROOT = "/mnt/c/Users/username000101/Workspaces/MachOS-crossxnu"
CC_JSON = os.path.join(ROOT, "upstream/xnu/BUILD/obj/RELEASE_X86_64/compile_commands.json")
TMP = "/tmp/hx"

entries = json.load(open(CC_JSON))
entry = None
for e in entries:
    if "osfmk" in e["directory"]:
        entry = e
        break
if entry is None:
    sys.exit("no osfmk entry")

args = entry["arguments"]
keep = []
i = 0
while i < len(args):
    a = args[i]
    if a in ("-c", "-o", "-MF", "-MT", "-MQ"):
        i += 2
        continue
    if a in ("-MD", "-MMD"):
        i += 1
        continue
    if a.endswith((".c", ".o", ".d")):
        i += 1
        continue
    keep.append(a)
    i += 1

BODY = "\nint probe_fn(void) { return 0; }\n"

TESTS = {
    "J_kmod_miscprotos": "#include <mach/kmod.h>\n#include <kern/misc_protos.h>\n",
    "K_kmod_ktypes": "#include <mach/kmod.h>\n#include <sys/kernel_types.h>\n",
    "L_ktypes_only": "#include <sys/kernel_types.h>\n",
    "M_kmod_oslog": "#include <mach/kmod.h>\n#include <os/log.h>\n",
    "N_kmod_systm_ktypes": "#include <mach/kmod.h>\n#include <sys/kernel_types.h>\n",
    "O_kmod_mach_types": "#include <mach/kmod.h>\n#include <mach/mach_types.h>\n",
}

os.makedirs(TMP, exist_ok=True)
for name, head in sorted(TESTS.items()):
    src = os.path.join(TMP, name + ".c")
    with open(src, "w") as f:
        f.write(head + BODY)
    cmd = [args[0]] + keep[1:] + [
        "-c", src, "-o", os.path.join(TMP, name + ".o"),
        "-Wno-error", "-Wno-missing-prototypes", "-Wno-unused-function",
        "-Wno-macro-redefined",
    ]
    r = subprocess.run(cmd, cwd=entry["directory"], capture_output=True, text=True)
    errs = [l for l in r.stderr.splitlines() if "error:" in l]
    print("%-22s rc=%d errors=%d" % (name, r.returncode, len(errs)))
    for l in errs[:3]:
        print("    " + l[:170])
