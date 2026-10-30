#!/usr/bin/env bash
# Guard rail for publishing: the repository must contain sources, patches and
# documentation only.
#
# crossxnu boots a real macOS userland, and the easiest way to break the legal
# boundary in docs/legal.md is to commit something that was extracted from
# macOS "just to test".  This script fails if that happens.
#
# Usage: scripts/check-publish.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"
cd "${CROSSXNU_ROOT}"

fail=0
MAX_KB=256

# 1. Forbidden file types: Mach-O binaries, disk images, archives of macOS bits.
forbidden='\.(dylib|so|a|o|dmg|ipsw|hfs|iso|img|fd|kc|kext|kernelcache|pkg|xar|aa|pbzx)$'
while IFS= read -r f; do
    echo "forbidden artifact tracked: ${f}" >&2
    fail=1
done < <(git ls-files | grep -Ei "${forbidden}" || true)

# 2. Anything large enough to be a binary payload.
while IFS= read -r f; do
    [[ -f "${f}" ]] || continue
    kb=$(( $(stat -c %s "${f}") / 1024 ))
    if (( kb > MAX_KB )); then
        echo "tracked file larger than ${MAX_KB} KiB: ${f} (${kb} KiB)" >&2
        fail=1
    fi
done < <(git ls-files)

# 3. Mach-O magic in tracked files, whatever their extension.
while IFS= read -r f; do
    [[ -f "${f}" ]] || continue
    magic=$(head -c 4 "${f}" 2>/dev/null | od -An -tx1 | tr -d ' \n')
    case "${magic}" in
         feedface|feedfacf|cefaedfe|cffaedfe|cafebabe|bebafeca) 
            echo "Mach-O payload tracked: ${f}" >&2
            fail=1
            ;;
    esac
done < <(git ls-files)

if (( fail )); then
    echo
    echo "check-publish: FAILED (see messages above)" >&2
    exit 1
fi

echo "check-publish: ok — $(git ls-files | wc -l) tracked files, no binaries"
