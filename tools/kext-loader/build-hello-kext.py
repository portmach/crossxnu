#!/usr/bin/env python3
"""Build the hello kext using the exact argument list the kernel build uses."""
import json
import os
import subprocess
import sys

ROOT = "/mnt/c/Users/username000101/Workspaces/MachOS-crossxnu"
CC_JSON = os.path.join(ROOT, "upstream/xnu/BUILD/obj/RELEASE_X86_64/compile_commands.json")
LD = os.path.join(ROOT, "build/cctools/bin/ld64")
OUT = os.path.join(ROOT, "build/hello-kext")
SRC = os.path.join(ROOT, "tools/hello-kext/hello.c")
OBJ = os.path.join(OUT, "hello.o")
BIN = os.path.join(OUT, "com.crossxnu.hello.kext/Contents/MacOS/crossxnu_hello")

entries = json.load(open(CC_JSON))
picked = None
for e in entries:
    if "/kern/" in e["file"] or "osfmk" in e["directory"]:
        picked = e
        break
if picked is None:
    sys.exit("no osfmk entry")
print("using:", picked["directory"], picked["file"])

args = list(picked["arguments"])
cc = args[0]
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

os.makedirs(os.path.dirname(BIN), exist_ok=True)
cmd = [cc] + keep[1:] + ["-c", SRC, "-o", OBJ, "-Wno-error", "-Wno-missing-prototypes", "-Wno-unused-function"]
res = subprocess.run(cmd, cwd=picked["directory"], capture_output=True, text=True)
if res.returncode != 0:
    print("COMPILE FAILED")
    print(res.stderr[-3000:])
    sys.exit(1)
print("object:", os.path.getsize(OBJ), "bytes")

link = [LD, "-kext", "-static", "-arch", "x86_64", "-o", BIN, OBJ,
        "-undefined", "dynamic_lookup"]
res = subprocess.run(link, capture_output=True, text=True)
print("ld:", res.returncode)
print(res.stderr[-2000:])
if res.returncode != 0 or not os.path.exists(BIN):
    sys.exit(1)
subprocess.run(["cp", os.path.join(ROOT, "tools/hello-kext/Info.plist"),
                os.path.join(OUT, "com.crossxnu.hello.kext/Contents/Info.plist")])
print("built:", BIN, os.path.getsize(BIN), "bytes")
