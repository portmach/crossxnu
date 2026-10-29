#!/usr/bin/env bash
# Fetch the pinned upstream trees when the repo was cloned without submodules.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

clone_tag() {
    local url="$1" dest="$2" tag="$3"
    if [[ -d "${dest}/.git" ]]; then
        echo "skip ${dest}"
        return
    fi
    mkdir -p "$(dirname "${dest}")"
    git clone --depth 1 --branch "${tag}" "${url}" "${dest}"
}

clone_commit() {
    local url="$1" dest="$2" commit="$3"
    if [[ -d "${dest}/.git" ]]; then
        echo "skip ${dest}"
        return
    fi
    mkdir -p "$(dirname "${dest}")"
    git clone --depth 1 "${url}" "${dest}"
    git -C "${dest}" fetch --depth 1 origin "${commit}"
    git -C "${dest}" checkout --detach "${commit}"
}

clone_tag "https://github.com/apple-oss-distributions/xnu.git" \
    "${CROSSXNU_XNU}" "${CROSSXNU_XNU_TAG}"
clone_tag "https://github.com/apple-oss-distributions/bootstrap_cmds.git" \
    "${CROSSXNU_BOOTSTRAP}" "${CROSSXNU_BOOTSTRAP_TAG}"
clone_commit "https://github.com/apple-oss-distributions/AvailabilityVersions.git" \
    "${CROSSXNU_AVAILABILITY}" "${CROSSXNU_AVAILABILITY_COMMIT}"
clone_tag "https://github.com/apple-oss-distributions/libdispatch.git" \
    "${CROSSXNU_LIBDISPATCH}" "${CROSSXNU_LIBDISPATCH_TAG}"

echo "upstream trees ready"
