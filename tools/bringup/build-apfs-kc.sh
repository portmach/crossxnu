#!/usr/bin/env bash
# Build a kernel collection that contains Apple's APFS (from the KDK) plus the
# small set of KDK kexts it imports from, and our hello.kext as a canary.
#
# Dependency order matters: kc-builder merges each kext's exported symbols as
# it links, so providers must come first.  The order below is the reverse of
# the BFS discovery order printed by tools/kext-loader/kdk-deps.py.
#
# Usage: build/dis/build-apfs-kc.sh [KDK_EXT_DIR]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/env.sh
source "${SCRIPT_DIR}/../../scripts/env.sh"

KDK_EXT="${1:-/tmp/kdkroot/System/Library/Extensions}"

kexts=(
    "${KDK_EXT}/corecrypto.kext"
    "${KDK_EXT}/AppleImage4.kext"
    "${KDK_EXT}/AppleEffaceableStorage.kext"
    "${KDK_EXT}/IOStorageFamily.kext"
    "${KDK_EXT}/CoreAnalyticsFamily.kext"
    "${KDK_EXT}/apfs.kext"
    "${CROSSXNU_BUILD}/hello-kext/com.crossxnu.hello.kext"
)

args=()
for k in "${kexts[@]}"; do
    [[ -d "${k}" ]] || { echo "error: missing kext ${k}" >&2; exit 1; }
    args+=(--kext "${k}")
done

# apfs also declares OSBundleLibraries on libraries that provide no symbols it
# imports (personality-only dependencies), so they are not in the symbol
# closure: add them as codeless entries so OSKext can resolve them.
for c in AppleEFINVRAM IOCryptoAcceleratorFamily CoreTrust; do
    if [[ -d "${KDK_EXT}/${c}.kext" ]]; then
        args+=(--codeless "${KDK_EXT}/${c}.kext")
    else
        echo "warning: ${c}.kext missing from KDK" >&2
    fi
done

exec "${SCRIPT_DIR}/../../scripts/build-fileset.sh" "${args[@]}" --with-kpi
