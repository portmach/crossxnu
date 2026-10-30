#!/usr/bin/env bash
# Build the static crossxnu init stub.
#
# The kernel execs /sbin/launchd as pid 1 with no stdio descriptors, so an
# interpreted init dies with EBADF before it can print anything.  The stub is
# a static Mach-O (no libSystem, no dyld): it opens /dev/console, wires it to
# fd 0/1/2 and execs /bin/sh on /etc/rc.local.
#
# Usage: scripts/build-init.sh [output]
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

OUT="${1:-${CROSSXNU_BUILD}/init}"
SRC="${CROSSXNU_ROOT}/userland/init.c"

"${CROSSXNU_TOOLCHAIN}/bin/clang" \
    -target "${CROSSXNU_TARGET}" \
    -nostdlib -static -fno-stack-protector \
    -Wl,-e,_start \
    -o "${OUT}" "${SRC}"

echo "built ${OUT}"
"${CROSSXNU_TOOLCHAIN}/bin/otool" -l "${OUT}" | grep -E "filetype|LC_UNIXTHREAD" | head -3
