#!/usr/bin/env bash
# Build a kernel collection that carries the APFS container inside itself.
#
# The collection gets the same Apple APFS kexts as build-apfs-kc.sh plus our
# rammedia kext, and then the APFS image is appended as an __APFSIMG segment:
# the loader maps it, the kext finds it with getsegbyname() and publishes an
# IOBlockStorageDevice, IOStorageFamily's generic driver turns that into an
# IOMedia, and AppleAPFSContainerSchemeWholeDisk probes it.
#
# No PCI, no ACPI, no physical-memory bookkeeping - the segment is ordinary
# kernel memory, writable, so APFS may write to it (changes last until reboot).
#
# Usage: tools/kext-loader/build-apfs-image-kc.sh [KDK_EXT_DIR] [IMAGE]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/env.sh
source "${SCRIPT_DIR}/../../scripts/env.sh"

KDK_EXT="${1:-/tmp/kdkroot/System/Library/Extensions}"
IMAGE="${2:-${CROSSXNU_BUILD}/apfs64.img}"
PLAIN_KC="${CROSSXNU_BUILD}/kernel-plain.kc"
OUT_KC="${CROSSXNU_BUILD}/kernel.kc"

[[ -f "${IMAGE}" ]] || { echo "error: missing APFS image ${IMAGE}" >&2; exit 1; }
[[ -d "${CROSSXNU_BUILD}/rammedia-kext/com.crossxnu.driver.CrossXnuRAMStorage.kext" ]] || {
    echo "error: rammedia kext not built; run tools/kext-loader/build-rammedia-kext.py" >&2
    exit 1
}

kexts=(
    "${KDK_EXT}/corecrypto.kext"
    "${KDK_EXT}/AppleImage4.kext"
    "${KDK_EXT}/AppleEffaceableStorage.kext"
    "${KDK_EXT}/IOStorageFamily.kext"
    "${KDK_EXT}/CoreAnalyticsFamily.kext"
    "${KDK_EXT}/apfs.kext"
    "${CROSSXNU_BUILD}/rammedia-kext/com.crossxnu.driver.CrossXnuRAMStorage.kext"
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

python3 "${SCRIPT_DIR}/../../scripts/kc-add-segment.py" \
    "${PLAIN_KC}" "${IMAGE}" "${OUT_KC}" __APFSIMG

ls -l "${OUT_KC}"
