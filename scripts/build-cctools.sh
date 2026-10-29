#!/usr/bin/env bash
# Build cctools-port's Apple-compatible ld64 for Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

SRC="${CROSSXNU_UPSTREAM}/cctools-port"
WORK="${CROSSXNU_BUILD}/cctools-src"
PREFIX="${CROSSXNU_BUILD}/cctools"
LLVM_CONFIG="$(command -v llvm-config || true)"

[[ -d "${SRC}/cctools" ]] || { echo "error: cctools-port submodule missing" >&2; exit 1; }
[[ -n "${LLVM_CONFIG}" ]] || { echo "error: llvm-config required" >&2; exit 1; }
command -v libtoolize >/dev/null || { echo "error: libtool required" >&2; exit 1; }

# env.sh puts our Darwin-target clang wrappers first in PATH.  cctools itself
# is host software, so use the real host compiler explicitly.
export CC="${CC:-/usr/bin/clang}"
export CXX="${CXX:-/usr/bin/clang++}"

# Build outside the submodule so upstream/cctools-port stays clean.
rm -rf "${WORK}"
mkdir -p "${WORK}"
cp -a "${SRC}/." "${WORK}/"

# git on Windows may check these out with CRLF; autoreconf/configure scripts
# need LF even when the repository is on /mnt/c.
find "${WORK}/cctools" -type f \( \
        -name 'configure' -o -name 'configure.ac' -o -name 'autogen.sh' \
        -o -name 'Makefile.in' -o -name 'Makefile.am' -o -name 'install-sh' \
        -o -name 'config.sub' -o -name 'config.guess' -o -name 'ltmain.sh' \
        -o -name '*.m4' \) -exec sed -i 's/\r$//' {} +

cd "${WORK}/cctools"
if [[ ! -x ./configure ]]; then
    ./autogen.sh
fi
./configure \
    --prefix="${PREFIX}" \
    --target=x86_64-apple-darwin11 \
    --with-llvm-config="${LLVM_CONFIG}"
make -j"$(nproc)"
make install
install -m 0755 "${WORK}/cctools/ld64/src/ld/ld" "${PREFIX}/bin/ld64"
install -m 0755 "${WORK}/cctools/misc/strip" "${PREFIX}/bin/strip"

"${PREFIX}/bin/ld64" -v | head -4
echo "ld64: ${PREFIX}/bin/ld64"
