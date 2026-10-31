#!/usr/bin/env bash
# Regenerate patch 0024 (pthread) and 0028 (bring-up tracing) relative to the
# tree that has every other patch applied.
set -euo pipefail
ROOT=/mnt/c/Users/username000101/Workspaces/MachOS-crossxnu
cd "$ROOT"
XNU=upstream/xnu
STAMP=/tmp/cur-ok
mkdir -p "$STAMP"

PTHREAD="bsd/pthread/pthread_shims.c bsd/pthread/pthread_workqueue.c bsd/pthread/workqueue_internal.h"
TRACE="libkern/c++/OSKext.cpp osfmk/device/subrs.c bsd/kern/bsd_init.c bsd/dev/i386/systemcalls.c osfmk/i386/bsd_i386.c bsd/kern/kern_fork.c osfmk/kern/bsd_kern.c osfmk/kern/sched_prim.c"
ALL="$PTHREAD $TRACE"

# 1. snapshot the intended state
for f in $ALL; do
    mkdir -p "$STAMP/$(dirname "$f")"
    cp "$XNU/$f" "$STAMP/$f"
done

# 2. build the base tree: everything except 0024 and 0028
cd "$XNU"
git checkout -- .
while IFS= read -r patch; do
    patch="${patch%$'\r'}"
    [[ -z "$patch" || "$patch" == \#* ]] && continue
    [[ "$patch" == 0024-* || "$patch" == 0028-* ]] && continue
    git apply "$ROOT/patches/$patch"
done < "$ROOT/patches/series"

# 3. stage the base so that "git diff" shows only the new deltas
git add -u

# 4. restore the intended state on top of the base
for f in $ALL; do
    cp "$STAMP/$f" "$f"
done

# 5. emit the patches
git diff -- $PTHREAD > "$ROOT/patches/0024-pthread-kext-replacement.patch"
git diff -- $TRACE  > "$ROOT/patches/0028-bringup-tracing.patch"
git reset -q
wc -l "$ROOT/patches/0024-pthread-kext-replacement.patch" "$ROOT/patches/0028-bringup-tracing.patch"
