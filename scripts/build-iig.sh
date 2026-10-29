#!/usr/bin/env bash
# Build the portable IIG generator (iig-port) on a non-Apple host.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

SRC="${CROSSXNU_UPSTREAM}/iig-port"
OUT="${CROSSXNU_BUILD}/iig"
CXX="${CROSSXNU_REAL_HOST_CXX:-/usr/bin/c++}"

if [[ ! -f "${SRC}/iig.cpp" ]]; then
    echo "error: iig-port not found at ${SRC}" >&2
    echo "       run: git submodule update --init --depth 1 upstream/iig-port" >&2
    exit 1
fi
if ! command -v llvm-config >/dev/null 2>&1; then
    echo "error: llvm-config is required for iig-port" >&2
    exit 1
fi
if ! ldconfig -p 2>/dev/null | grep -q 'libclang\.so'; then
    echo "error: libclang is required for iig-port (install clang)" >&2
    exit 1
fi

mkdir -p "${OUT}"
# Intentional word splitting: llvm-config prints flags, not a single argument.
# shellcheck disable=SC2046
"${CXX}" -std=c++17 $(llvm-config --cxxflags) \
    "${SRC}/iig.cpp" $(llvm-config --ldflags) -lclang -o "${OUT}/iig"

"${OUT}/iig" --version
