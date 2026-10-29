#!/usr/bin/env bash
# Build PureDarwin kc-tools (kc-builder / prelink-builder) on Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

SRC="${CROSSXNU_UPSTREAM}/kc-tools"
WORK="${CROSSXNU_BUILD}/kc-tools-src"
OUT="${CROSSXNU_BUILD}/kc-tools"

[[ -d "${SRC}" ]] || { echo "error: kc-tools submodule missing" >&2; exit 1; }

rm -rf "${WORK}"
mkdir -p "${WORK}"
cp -a "${SRC}/." "${WORK}/"
cmake -S "${WORK}" -B "${WORK}/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "${WORK}/build" -j"$(nproc)"

mkdir -p "${OUT}/bin"
install -m 0755 "${WORK}/build/kc-builder" "${OUT}/bin/kc-builder"
install -m 0755 "${WORK}/build/prelink-builder" "${OUT}/bin/prelink-builder"

"${OUT}/bin/kc-builder" 2>&1 | head -2 || true
echo "kc-builder: ${OUT}/bin/kc-builder"
