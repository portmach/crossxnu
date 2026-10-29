#!/usr/bin/env bash
# Build the phase-1 libcc_kext.a shim.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

CC="${CROSSXNU_TOOLCHAIN}/bin/clang"
AR="${AR:-llvm-ar}"
OUT="${CROSSXNU_BUILD}/cc_kext"
SRC="${CROSSXNU_TOOLCHAIN}/lib/cc_kext_stubs.c"

mkdir -p "${OUT}" "${CROSSXNU_SDK}/usr/local/lib/kernel"

"${CC}" -target x86_64-apple-macos26.5 -arch x86_64 \
    -mkernel -msoft-float -nostdlibinc -fno-builtin -fno-common -O2 \
    -DAPPLE -DKERNEL -DKERNEL_PRIVATE -DXNU_KERNEL_PRIVATE -DPRIVATE \
    -D__MACHO__=1 -Dx86_64 -DX86_64 -D__X86_64__ -DLP64 \
    -DPAGE_SIZE_FIXED -D__APPLE__=1 \
    -c "${SRC}" -o "${OUT}/cc_kext_stubs.o"

"${AR}" --format=darwin rcs "${CROSSXNU_SDK}/usr/local/lib/kernel/libcc_kext.a" \
    "${OUT}/cc_kext_stubs.o"

echo "libcc_kext.a: ${CROSSXNU_SDK}/usr/local/lib/kernel/libcc_kext.a"
