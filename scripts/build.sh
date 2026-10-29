#!/usr/bin/env bash
# Build the XNU kernel with LLVM/clang on a non-Apple host.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

ARCH="x86_64"
CONFIG="RELEASE"
JOBS="$(nproc)"
TARGET="all"
LOG=""
SECURITY="permissive"

usage() {
    cat <<EOF
usage: $0 [--arch x86_64] [--config RELEASE|DEVELOPMENT|DEBUG]
          [--security permissive|strict]
          [--jobs N] [--target all|install|...] [--log FILE]

Environment:
  CROSSXNU_BUILD   build directory (default: <repo>/build)
  CROSSXNU_SDK     synthetic SDK  (default: <build>/sdk)

Security:
  permissive  (default) TrustCache/CodeSignature are not enforced
  strict      leave Apple's enforcement in place (future; not ready)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --arch)     ARCH="$2"; shift 2 ;;
        --config)   CONFIG="$2"; shift 2 ;;
        --security) SECURITY="$2"; shift 2 ;;
        --jobs|-j)  JOBS="$2"; shift 2 ;;
        --target)   TARGET="$2"; shift 2 ;;
        --log)      LOG="$2"; shift 2 ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

case "${SECURITY}" in
    permissive) SECURITY_PERMISSIVE=1 ;;
    strict)     SECURITY_PERMISSIVE=0 ;;
    *) echo "error: --security must be permissive or strict" >&2; exit 2 ;;
esac

case "${ARCH}" in
    x86_64|X86_64) ARCH_UC="X86_64" ;;
    *) echo "error: only x86_64 is supported in phase 1" >&2; exit 2 ;;
esac
CONFIG_UC="$(echo "${CONFIG}" | tr '[:lower:]' '[:upper:]')"
case "${CONFIG_UC}" in
    RELEASE|DEVELOPMENT|DEBUG) ;;
    *) echo "error: unsupported configuration ${CONFIG}" >&2; exit 2 ;;
esac

if [[ ! -x "${CROSSXNU_LD64}" ]]; then
    echo "error: cctools ld64 missing at ${CROSSXNU_LD64}" >&2
    echo "       run: ./scripts/build-cctools.sh" >&2
    exit 1
fi
if [[ -z "${CROSSXNU_SDK}" || ! -d "${CROSSXNU_SDK}/usr/local/include/kernel" ]]; then
    echo "error: synthetic SDK missing; run ./scripts/make-sdk.sh" >&2
    exit 1
fi
if [[ ! -x "${CROSSXNU_MIGDIR}/mig" || ! -x "${CROSSXNU_MIGDIR}/migcom" ]]; then
    echo "error: MIG missing; run ./scripts/build-mig.sh" >&2
    exit 1
fi
if [[ ! -f "${CROSSXNU_TOOLCHAIN}/lib/libhostcompat.a" ]]; then
    echo "error: host compat missing; run ./scripts/build-host-tools.sh" >&2
    exit 1
fi

crossxnu_warn_if_slow_fs

# Diagnostics introduced by newer clang that Apple's clang did not emit.
# These affect warnings only, not code generation or the ABI.
CFLAGS_EXTRA_VALUE="-Wno-unsafe-buffer-usage"
CFLAGS_EXTRA_VALUE+=" -Wno-reserved-identifier"
CFLAGS_EXTRA_VALUE+=" -Wno-deprecated-declarations"
CFLAGS_EXTRA_VALUE+=" -Wno-shadow-header"
CFLAGS_EXTRA_VALUE+=" -Wno-lifetime-safety-intra-tu-suggestions"
CFLAGS_EXTRA_VALUE+=" -Wno-lifetime-safety-invalidation"
CFLAGS_EXTRA_VALUE+=" -Wno-lifetime-safety-cross-tu-suggestions"
CFLAGS_EXTRA_VALUE+=" -Wno-lifetime-safety-cross-tu-constructor-suggestions"
CFLAGS_EXTRA_VALUE+=" -Wno-unused-but-set-variable"
CFLAGS_EXTRA_VALUE+=" -Wno-unused-but-set-global"
CFLAGS_EXTRA_VALUE+=" -Wno-void-pointer-to-int-cast"
CFLAGS_EXTRA_VALUE+=" -Wno-pointer-to-int-cast"
CFLAGS_EXTRA_VALUE+=" -Wno-implicit-int-float-conversion"
CFLAGS_EXTRA_VALUE+=" -Wno-vla"
CFLAGS_EXTRA_VALUE+=" -Wno-gnu-folding-constant"
CFLAGS_EXTRA_VALUE+=" -Wno-unused-private-field"
CFLAGS_EXTRA_VALUE+=" -DOS_FIREHOSE_SPI=1"
CFLAGS_EXTRA_VALUE+=" -DOS_VOUCHER_ACTIVITY_SPI_TYPES=1"
CFLAGS_EXTRA_VALUE+=" -DCROSSXNU_SECURITY_PERMISSIVE=${SECURITY_PERMISSIVE}"
if [[ "${SECURITY}" == "permissive" ]]; then
    CFLAGS_EXTRA_VALUE+=" -I${CROSSXNU_TOOLCHAIN}/shims/permissive"
fi

if [[ -z "${LOG}" ]]; then
    mkdir -p "${CROSSXNU_BUILD}/log"
    LOG="${CROSSXNU_BUILD}/log/build-${CONFIG_UC}-${ARCH_UC}-$(date +%Y%m%d-%H%M%S).log"
fi

echo "building XNU ${CROSSXNU_XNU_TAG} (${CONFIG_UC}, ${ARCH_UC})"
echo "  SECURITY: ${SECURITY} (CROSSXNU_SECURITY_PERMISSIVE=${SECURITY_PERMISSIVE})"
if [[ "${SECURITY}" == "permissive" ]]; then
    echo "  TrustCache/CodeSignature are NOT enforced — see SECURITY.md"
fi
echo "  source: ${CROSSXNU_XNU}"
echo "  SDK:    ${CROSSXNU_SDK}"
echo "  log:    ${LOG}"

set +e
make -C "${CROSSXNU_XNU}" -j"${JOBS}" \
    XCRUN="${CROSSXNU_TOOLCHAIN}/bin/xcrun" \
    SDKROOT_RESOLVED="${CROSSXNU_SDK}" \
    SDKVERSION="${CROSSXNU_SDK_VERSION}" \
    PLATFORM=MacOSX \
    PLATFORMPATH="${CROSSXNU_SDK}/MacOSX.platform" \
    HOST_SDKROOT_RESOLVED="/" \
    HOST_OS_VERSION="${CROSSXNU_MACOS_VERSION}" \
    CC="${CROSSXNU_TOOLCHAIN}/bin/clang" \
    CXX="${CROSSXNU_TOOLCHAIN}/bin/clang++" \
    HOST_CC="${CROSSXNU_TOOLCHAIN}/bin/clang-host" \
    MIG="${CROSSXNU_MIGDIR}/mig" \
    MIGCOM="${CROSSXNU_MIGDIR}/migcom" \
    LIBTOOL="${CROSSXNU_TOOLCHAIN}/bin/libtool" \
    STRIP="${CROSSXNU_BUILD}/cctools/bin/strip" \
    NM="${CROSSXNU_TOOLCHAIN}/bin/nm" \
    OTOOL="${CROSSXNU_TOOLCHAIN}/bin/otool" \
    LIPO="${CROSSXNU_TOOLCHAIN}/bin/lipo" \
    UNIFDEF="${CROSSXNU_TOOLCHAIN}/bin/unifdef" \
    DSYMUTIL="${CROSSXNU_TOOLCHAIN}/bin/dsymutil" \
    PLUTIL="${CROSSXNU_TOOLCHAIN}/bin/plutil" \
    CTFCONVERT="${CROSSXNU_TOOLCHAIN}/bin/ctf-noop" \
    CTFMERGE="${CROSSXNU_TOOLCHAIN}/bin/ctf-noop" \
    CTFINSERT="${CROSSXNU_TOOLCHAIN}/bin/ctf-noop" \
    CTFDUMP="${CROSSXNU_TOOLCHAIN}/bin/ctf-noop" \
    HOST_CODESIGN="/bin/true" \
    HOST_CODESIGN_ALLOCATE="/bin/true" \
    HOST_FLEX="/usr/bin/flex" \
    HOST_BISON="/usr/bin/bison" \
    HOST_GM4="/usr/bin/m4" \
    SYSCTL_HW_PHYSICALCPU="${SYSCTL_HW_PHYSICALCPU:-$(nproc)}" \
    SYSCTL_HW_LOGICALCPU="${SYSCTL_HW_LOGICALCPU:-$(nproc)}" \
    BUILD_DSYM=0 \
    DO_CTFMERGE=0 \
    ARCH_CONFIGS="${ARCH_UC}" \
    KERNEL_CONFIGS="${CONFIG_UC}" \
    RC_DARWIN_KERNEL_VERSION="${CROSSXNU_XNU_VERSION}" \
    CFLAGS_EXTRA="${CFLAGS_EXTRA_VALUE}" \
    BUILD_LTO=0 \
    LDFLAGS_KERNEL_ONLY_SUBARCH_x86_64="" \
    LD_KERNEL_LIBS="${CROSSXNU_SDK}/usr/local/lib/kernel/libcc_kext.a" \
    "${TARGET}" 2>&1 | tee "${LOG}"
BUILD_STATUS=${PIPESTATUS[0]}
set -e
if [[ ${BUILD_STATUS} -ne 0 ]]; then
    echo "build failed (exit ${BUILD_STATUS}); see ${LOG}" >&2
    exit "${BUILD_STATUS}"
fi

echo
echo "build finished; kernel candidates:"
find "${CROSSXNU_XNU}/BUILD/obj" -maxdepth 2 -name 'kernel*' -type f 2>/dev/null | head -20 || true
