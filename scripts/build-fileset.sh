#!/usr/bin/env bash
# Assemble a kernel collection from the built XNU kernel.
#
# Usage:
#   ./scripts/build-fileset.sh [kext.kext ...]
#
# With no kexts this still creates an MH_FILESET (kc-tools puts the kernel's
# segments at the top level).  Real boot needs the platform/IOKit kexts too.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

KERNEL="${CROSSXNU_XNU}/BUILD/obj/RELEASE_X86_64/kernel"
KCB="${CROSSXNU_BUILD}/kc-tools/bin/kc-builder"
OUT="${CROSSXNU_BUILD}/kernel.kc"

[[ -x "${KCB}" ]] || { echo "error: kc-builder missing; run ./scripts/build-kc-tools.sh" >&2; exit 1; }
[[ -f "${KERNEL}" ]] || { echo "error: kernel not built" >&2; exit 1; }

args=(-kernel "${KERNEL}")
for kext in "$@"; do
    args+=(-kext "${kext}")
done
"${KCB}" "${args[@]}" -o "${OUT}"

file "${OUT}"
echo "kernel collection: ${OUT}"
