#!/usr/bin/env bash
# Create an APFS container image for QEMU bring-up tests.
#
# macOS' own newfs_apfs is a Mach-O binary and cannot run here, so we use the
# Linux reimplementation (linux-apfs/apfsprogs):
#
#   git clone --depth 1 https://github.com/linux-apfs/apfsprogs
#   (cd apfsprogs/lib && make) && (cd apfsprogs/mkapfs && make)
#
# mkapfs creates a container with a single volume and no role; setting the
# volume role (System/Data/Preboot) is a separate step once we can mount it.
#
# Usage: tools/bringup/make-apfs-image.sh [SIZE] [OUT] [LABEL]
set -euo pipefail

SIZE="${1:-512M}"
OUT="${2:-build/apfs.img}"
LABEL="${3:-crossxnu}"
MKAPFS="${MKAPFS:-$HOME/work/apfsprogs/mkapfs/mkapfs}"

[[ -x "${MKAPFS}" ]] || { echo "error: mkapfs not built (set MKAPFS=...)" >&2; exit 1; }

rm -f "${OUT}"
truncate -s "${SIZE}" "${OUT}"
"${MKAPFS}" -L "${LABEL}" "${OUT}"
file "${OUT}"
echo "APFS image: ${OUT}"
