#!/usr/bin/env bash
# Verify that the patch series reproduces the intended tree byte for byte.
set -u
ROOT=/mnt/c/Users/username000101/Workspaces/MachOS-crossxnu
cd "$ROOT/upstream/xnu" || exit 1
git checkout -- . || exit 1
cd "$ROOT" || exit 1
bash scripts/apply-patches.sh >/tmp/apply.log 2>&1
echo "apply=$?"
tail -3 /tmp/apply.log
rc=0
for f in bsd/dev/i386/systemcalls.c osfmk/i386/bsd_i386.c bsd/kern/kern_fork.c \
         osfmk/kern/bsd_kern.c osfmk/kern/sched_prim.c \
         bsd/pthread/pthread_shims.c bsd/pthread/pthread_workqueue.c \
         bsd/pthread/workqueue_internal.h; do
    if cmp -s "/tmp/cur-ok/$f" "upstream/xnu/$f"; then
        echo "OK   $f"
    else
        echo "DIFF $f"
        rc=1
    fi
done
exit $rc
