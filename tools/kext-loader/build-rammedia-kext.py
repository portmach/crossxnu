#!/usr/bin/env python3
"""Build the rammedia kext (IOBlockStorageDevice over a kernel segment).

Reuses the kernel's own C++ compile flags so the kext is built against exactly
the headers the kernel was built from (`-fapple-kext`, the same IOService /
OSObject layout), plus the Kernel.framework storage headers fetched by
tools/kext-loader/fetch-sdk-headers.ps1 into build/sdk-ext.

Usage: build-rammedia-kext.py [--verbose]
"""
import json
import os
import subprocess
import sys

ROOT = "/mnt/c/Users/username000101/Workspaces/MachOS-crossxnu"
CC_JSON = os.path.join(ROOT, "upstream/xnu/BUILD/obj/RELEASE_X86_64/compile_commands.json")
EXT_HEADERS = os.path.join(ROOT, "build/sdk-ext/Kernel.framework/Versions/A/Headers")
LD = os.path.join(ROOT, "build/cctools/bin/ld64")
SRC = os.path.join(ROOT, "tools/rammedia-kext/rammedia.cpp")
PLIST = os.path.join(ROOT, "tools/rammedia-kext/Info.plist")
OUT = os.path.join(ROOT, "build/rammedia-kext")
BUNDLE = os.path.join(OUT, "com.crossxnu.driver.CrossXnuRAMStorage.kext")
OBJ = os.path.join(OUT, "rammedia.o")
BIN = os.path.join(BUNDLE, "Contents/MacOS/crossxnu_ramstorage")

verbose = "--verbose" in sys.argv

if not os.path.isdir(EXT_HEADERS):
    sys.exit("missing %s; run tools/kext-loader/fetch-sdk-headers.ps1" % EXT_HEADERS)

entries = json.load(open(CC_JSON))

# Prefer a kernel C++ unit that already pulls in IOKit: its macro set is the
# one kext code sees, and a C unit's flags clash on clock_t (bsd vs kern).
picked = None
for want in ("OSKext.cpp", "IOCatalogue.cpp", "IOService.cpp", "OSObject.cpp"):
    for e in entries:
        if e["file"].endswith(want):
            picked = e
            break
    if picked:
        break
if picked is None:
    sys.exit("no suitable C++ entry in compile_commands.json")

args = list(picked["arguments"])
keep, i = [], 0
while i < len(args):
    a = args[i]
    if a in ("-c", "-o", "-MF", "-MT", "-MQ"):
        i += 2
        continue
    if a in ("-MD", "-MMD"):
        i += 1
        continue
    if a.endswith((".c", ".cc", ".cpp", ".cxx", ".m", ".mm", ".S", ".s", ".o", ".d")):
        i += 1
        continue
    keep.append(a)
    i += 1

os.makedirs(os.path.dirname(BIN), exist_ok=True)

compile_cmd = [keep[0]] + keep[1:] + [
    "-I", EXT_HEADERS,
    "-Wno-error", "-Wno-unused-parameter",
    "-x", "c++", "-c", SRC, "-o", OBJ,
]
if verbose:
    print(" ".join(compile_cmd))
res = subprocess.run(compile_cmd, cwd=picked["directory"], capture_output=True, text=True)
if res.returncode != 0:
    print(res.stderr[-6000:])
    sys.exit("compile failed")
print("object: %d bytes" % os.path.getsize(OBJ))

link_cmd = [LD, "-kext", "-static", "-arch", "x86_64", "-o", BIN, OBJ,
            "-undefined", "dynamic_lookup"]
if verbose:
    print(" ".join(link_cmd))
res = subprocess.run(link_cmd, capture_output=True, text=True)
if res.returncode != 0:
    print(res.stderr[-4000:])
    sys.exit("link failed")
print("binary: %d bytes" % os.path.getsize(BIN))

subprocess.run(["cp", PLIST, os.path.join(BUNDLE, "Contents/Info.plist")], check=True)
print("bundle: %s" % BUNDLE)
