#!/usr/bin/env bash
# Build libfirehose_kernel.a from libdispatch's firehose_buffer.c.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

XNU="${CROSSXNU_XNU}"
LIBDISPATCH="${CROSSXNU_LIBDISPATCH}"
SDK="${CROSSXNU_SDK}"
OUT="${CROSSXNU_BUILD}/firehose"
MIG="${CROSSXNU_MIGDIR}/mig"
CC="${CROSSXNU_TOOLCHAIN}/bin/clang"
AR="${AR:-llvm-ar}"
SRC="${LIBDISPATCH}/src/firehose"

[[ -x "${MIG}" ]] || { echo "error: MIG not built" >&2; exit 1; }
[[ -f "${SRC}/firehose_buffer.c" ]] || { echo "error: firehose source not found" >&2; exit 1; }

mkdir -p "${OUT}" "${SDK}/usr/local/lib/kernel"

mig_args=(
    -DKERNEL=1 -novouchers
    -I"${LIBDISPATCH}"
    -I"${SRC}"
    -I"${XNU}/osfmk"
    -I"${XNU}/bsd"
    -I"${XNU}/EXTERNAL_HEADERS"
    -I"${SDK}/usr/local/include/kernel"
)

MIGCOM="${CROSSXNU_MIGDIR}/migcom" MIGCC="${CC}" \
    "${MIG}" "${mig_args[@]}" \
    -header "${OUT}/firehose.h" \
    -server "${OUT}/firehoseServer.c" \
    -user "${OUT}/firehoseUser.c" \
    "${SRC}/firehose.defs"

MIGCOM="${CROSSXNU_MIGDIR}/migcom" MIGCC="${CC}" \
    "${MIG}" "${mig_args[@]}" \
    -header "${OUT}/firehose_reply.h" \
    -sheader "${OUT}/firehose_replyServer.h" \
    -server "${OUT}/firehose_replyServer.c" \
    -user "${OUT}/firehose_replyUser.c" \
    "${SRC}/firehose_reply.defs"

"${CC}" \
    -target x86_64-apple-macos26.5 -arch x86_64 \
    -mkernel -msoft-float -nostdlibinc -fno-builtin -fno-common -O2 \
    -DAPPLE -DKERNEL -DKERNEL_PRIVATE -DXNU_KERNEL_PRIVATE -DPRIVATE \
    -D__MACHO__=1 -Dx86_64 -DX86_64 -D__X86_64__ -DLP64 \
    -DPAGE_SIZE_FIXED -D__APPLE__=1 \
    -I"${OUT}" \
    -I"${LIBDISPATCH}" \
    -I"${SRC}" \
    -I"${XNU}/osfmk" \
    -I"${XNU}/bsd" \
    -I"${XNU}/libkern" \
    -I"${XNU}/libkern/firehose" \
    -I"${XNU}/EXTERNAL_HEADERS" \
    -I"${XNU}/BUILD/obj/EXPORT_HDRS/osfmk" \
    -I"${XNU}/BUILD/obj/EXPORT_HDRS/bsd" \
    -I"${XNU}/BUILD/obj/EXPORT_HDRS/libkern" \
    -I"${SDK}/usr/local/include/kernel" \
    -c "${SRC}/firehose_buffer.c" -o "${OUT}/firehose_buffer.o"

"${AR}" --format=darwin rcs "${SDK}/usr/local/lib/kernel/libfirehose_kernel.a" \
    "${OUT}/firehose_buffer.o"

echo "libfirehose_kernel.a: ${SDK}/usr/local/lib/kernel/libfirehose_kernel.a"
