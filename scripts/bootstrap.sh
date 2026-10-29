#!/usr/bin/env bash
# One-time (per checkout) preparation for crossxnu.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

echo "== crossxnu bootstrap =="
echo "repo:   ${CROSSXNU_ROOT}"
echo "XNU:    ${CROSSXNU_XNU_TAG} (${CROSSXNU_XNU_VERSION})"

crossxnu_warn_if_slow_fs

for tool in clang clang++ ld64.lld llvm-ar llvm-strip llvm-nm llvm-otool \
            make git python3 bison flex m4; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "error: missing host tool: ${tool}" >&2
        echo "       Arch: sudo pacman -S --needed base-devel clang lld llvm git python bison flex m4" >&2
        exit 1
    fi
done

if [[ ! -d "${CROSSXNU_XNU}" ]]; then
    echo "initialising submodules (shallow)..."
    git -C "${CROSSXNU_ROOT}" submodule update --init --depth 1
fi

"${SCRIPT_DIR}/apply-patches.sh"
"${SCRIPT_DIR}/build-mig.sh"
"${SCRIPT_DIR}/build-host-tools.sh"
"${SCRIPT_DIR}/build-cctools.sh"
"${SCRIPT_DIR}/build-kc-tools.sh"
"${SCRIPT_DIR}/make-sdk.sh"
"${SCRIPT_DIR}/build-iig.sh"
"${SCRIPT_DIR}/generate-driverkit.sh"
"${SCRIPT_DIR}/build-firehose.sh"
"${SCRIPT_DIR}/build-cc-kext.sh"

cat <<EOF

bootstrap complete.

next:
  ./scripts/build.sh --arch x86_64 --config RELEASE --jobs "\$(nproc)"
EOF
