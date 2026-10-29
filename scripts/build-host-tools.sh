#!/usr/bin/env bash
# Build the small host-compatibility library used by XNU's SETUP tools.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

mkdir -p "${CROSSXNU_TOOLCHAIN}/lib"
"${CROSSXNU_REAL_HOST_CLANG:-/usr/bin/clang}" -c -O2 -I"${CROSSXNU_TOOLCHAIN}/include" \
    -o "${CROSSXNU_TOOLCHAIN}/lib/hostcompat.o" \
    "${CROSSXNU_TOOLCHAIN}/lib/hostcompat.c"
llvm-ar rcs "${CROSSXNU_TOOLCHAIN}/lib/libhostcompat.a" \
    "${CROSSXNU_TOOLCHAIN}/lib/hostcompat.o"

echo "built ${CROSSXNU_TOOLCHAIN}/lib/libhostcompat.a"
