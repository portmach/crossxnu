#!/usr/bin/env bash
# Apply the crossxnu patch series to upstream/xnu.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

XNU="${CROSSXNU_XNU}"
SERIES="${CROSSXNU_ROOT}/patches/series"

if [[ ! -d "${XNU}/.git" && ! -f "${XNU}/.git" ]]; then
    echo "error: ${XNU} is not a git checkout" >&2
    exit 1
fi

# Start from a clean tree.  Untracked build products (BUILD/) survive.
git -C "${XNU}" checkout -- .

while IFS= read -r patch; do
    patch="${patch%$'\r'}"
    [[ -z "${patch}" || "${patch}" == \#* ]] && continue
    p="${CROSSXNU_ROOT}/patches/${patch}"
    if [[ ! -f "${p}" ]]; then
        echo "error: missing patch ${p}" >&2
        exit 1
    fi
    echo "applying ${patch}"
    git -C "${XNU}" apply --verbose "${p}"
done < "${SERIES}"

echo "patches applied to ${XNU}"
