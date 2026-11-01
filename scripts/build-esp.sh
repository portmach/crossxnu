#!/usr/bin/env bash
# Rebuild the EFI system partition image from build/esp, the kernel collection
# and the root ramdisk.
#
# The ESP holds the loader (build/esp/EFI/BOOT/BOOTX64.EFI, built by
# scripts/build-loader.sh), the collection and the root image.  Keep it big
# enough for the ramdisk: the root image is ~600 MB.
#
# Usage: scripts/build-esp.sh [SIZE_MB]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

SIZE_MB="${1:-1200}"
ESP="${CROSSXNU_BUILD}/esp32.img"
ESP_TREE="${CROSSXNU_BUILD}/esp"
KC="${CROSSXNU_BUILD}/kernel.kc"
RAMDISK="${CROSSXNU_RAMDISK:-$HOME/rec-new.hfs}"

[[ -f "${ESP_TREE}/EFI/BOOT/BOOTX64.EFI" ]] || {
    echo "error: no loader in ${ESP_TREE}; run scripts/build-loader.sh" >&2; exit 1; }
[[ -f "${KC}" ]] || { echo "error: missing ${KC}" >&2; exit 1; }
[[ -f "${RAMDISK}" ]] || { echo "error: missing ramdisk ${RAMDISK}" >&2; exit 1; }

rm -f "${ESP}"
truncate -s "${SIZE_MB}M" "${ESP}"
mkfs.vfat -F 32 -n CROSSXNU "${ESP}" >/dev/null
mmd -i "${ESP}" ::/EFI
mmd -i "${ESP}" ::/EFI/BOOT
mcopy -i "${ESP}" "${ESP_TREE}/EFI/BOOT/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI
if [[ -f "${ESP_TREE}/EFI/BOOT/boot-args.txt" ]]; then
    mcopy -i "${ESP}" "${ESP_TREE}/EFI/BOOT/boot-args.txt" ::/EFI/BOOT/boot-args.txt
fi
mcopy -i "${ESP}" "${KC}" ::/EFI/BOOT/kernel
mcopy -i "${ESP}" "${RAMDISK}" ::/ramdisk.img

echo "ESP ${ESP} (${SIZE_MB} MB):"
mdir -i "${ESP}" ::/EFI/BOOT | tail -n +3
