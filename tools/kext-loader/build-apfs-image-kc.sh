#!/usr/bin/env bash
# Build a kernel collection that carries the storage kext and, optionally, an
# APFS image inside the collection.
#
# The collection gets the same Apple APFS kexts as build-apfs-kc.sh plus our
# blockstorage kext.  That kext drives an AHCI-attached disk when QEMU has one
# (see tools/kext-loader/boot-serial.ps1 -ExtraArgs); otherwise it falls back
# to the __APFSIMG segment appended here: the loader maps it, the kext finds it
# with getsegbyname() and publishes an IOBlockStorageDevice, IOStorageFamily's
# generic driver turns that into an IOMedia, and AppleAPFSContainerSchemeWholeDisk
# probes it.
#
# Pass "none" as the image to skip the segment: with a real AHCI disk the
# collection then stays small, which matters because it has to fit below the
# loader's bootinfo block at 0x2800000.
#
# Usage: tools/kext-loader/build-apfs-image-kc.sh [KDK_EXT_DIR] [IMAGE|none]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/env.sh
source "${SCRIPT_DIR}/../../scripts/env.sh"

KDK_EXT="${1:-/tmp/kdkroot/System/Library/Extensions}"
IMAGE="${2:-${CROSSXNU_BUILD}/apfs64.img}"
PLAIN_KC="${CROSSXNU_BUILD}/kernel-plain.kc"
OUT_KC="${CROSSXNU_BUILD}/kernel.kc"

if [[ "${IMAGE}" != "none" ]]; then
    [[ -f "${IMAGE}" ]] || { echo "error: missing APFS image ${IMAGE}" >&2; exit 1; }
fi
[[ -d "${CROSSXNU_BUILD}/blockstorage-kext/com.crossxnu.driver.CrossXnuBlockStorage.kext" ]] || {
    echo "error: blockstorage kext not built; run tools/kext-loader/build-blockstorage-kext.py" >&2
    exit 1
}

kexts=(
    "${KDK_EXT}/corecrypto.kext"
    "${KDK_EXT}/AppleImage4.kext"
    "${KDK_EXT}/AppleEffaceableStorage.kext"
    "${KDK_EXT}/IOStorageFamily.kext"
    "${KDK_EXT}/CoreAnalyticsFamily.kext"
    "${KDK_EXT}/apfs.kext"
    "${CROSSXNU_BUILD}/blockstorage-kext/com.crossxnu.driver.CrossXnuBlockStorage.kext"
)

args=()
for k in "${kexts[@]}"; do
    [[ -d "${k}" ]] || { echo "error: missing kext ${k}" >&2; exit 1; }
    args+=(--kext "${k}")
done

# apfs declares OSBundleLibraries on libraries that provide none of the symbols
# it imports (personality-only dependencies), so they are outside the symbol
# closure and must be present as codeless entries.  AppleEFINVRAM does not
# exist in the KDK at all; build/codeless-stubs holds a synthetic stand-in.
STUBS="${CROSSXNU_BUILD}/codeless-stubs"
for c in AppleEFINVRAM IOCryptoAcceleratorFamily CoreTrust; do
    if [[ -d "${KDK_EXT}/${c}.kext" ]]; then
        args+=(--codeless "${KDK_EXT}/${c}.kext")
    elif [[ -d "${STUBS}/${c}.kext" ]]; then
        args+=(--codeless "${STUBS}/${c}.kext")
    else
        echo "warning: no codeless entry for ${c}" >&2
    fi
done

"${SCRIPT_DIR}/../../scripts/build-fileset.sh" "${args[@]}" --with-kpi >/dev/null
mv "${CROSSXNU_BUILD}/kernel.kc" "${PLAIN_KC}"

if [[ "${IMAGE}" == "none" ]]; then
    cp "${PLAIN_KC}" "${OUT_KC}"
else
    python3 "${SCRIPT_DIR}/../../scripts/kc-add-segment.py" \
        "${PLAIN_KC}" "${IMAGE}" "${OUT_KC}" __APFSIMG
fi

ls -l "${OUT_KC}"
