#!/usr/bin/env bash
# Build the static crossxnu APFS-root tool (tools/apfs-root/apfsroot.c).
#
# Like userland/init.c it is a static Mach-O with no libSystem and no dyld: it
# runs before launchd, on a patched recovery userland, and only uses raw
# syscalls.
#
# Usage: scripts/build-apfsroot.sh [output]
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

OUT="${1:-${CROSSXNU_BUILD}/apfsroot}"
SRC="${CROSSXNU_ROOT}/tools/apfs-root/apfsroot.c"

"${CROSSXNU_TOOLCHAIN}/bin/clang" \
    -target "${CROSSXNU_TARGET}" \
    -nostdlib -static -fno-stack-protector -ffreestanding -fno-builtin -O2 \
    -Wl,-e,_start \
    -o "${OUT}" "${SRC}"

echo "built ${OUT}"
"${CROSSXNU_TOOLCHAIN}/bin/otool" -l "${OUT}" | grep -E "filetype|LC_UNIXTHREAD" | head -3
