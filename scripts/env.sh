# shellcheck shell=bash
# Common paths and environment for crossxnu scripts.
#
# Source this file; do not execute it.

set -euo pipefail

CROSSXNU_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CROSSXNU_ROOT

export CROSSXNU_UPSTREAM="${CROSSXNU_UPSTREAM:-${CROSSXNU_ROOT}/upstream}"
export CROSSXNU_XNU="${CROSSXNU_XNU:-${CROSSXNU_UPSTREAM}/xnu}"
export CROSSXNU_BOOTSTRAP="${CROSSXNU_BOOTSTRAP:-${CROSSXNU_UPSTREAM}/bootstrap_cmds}"
export CROSSXNU_AVAILABILITY="${CROSSXNU_AVAILABILITY:-${CROSSXNU_UPSTREAM}/AvailabilityVersions}"
export CROSSXNU_LIBDISPATCH="${CROSSXNU_LIBDISPATCH:-${CROSSXNU_UPSTREAM}/libdispatch}"

export CROSSXNU_BUILD="${CROSSXNU_BUILD:-${CROSSXNU_ROOT}/build}"
export CROSSXNU_SDK="${CROSSXNU_SDK:-${CROSSXNU_BUILD}/sdk}"
export CROSSXNU_MIGDIR="${CROSSXNU_MIGDIR:-${CROSSXNU_BUILD}/mig}"
export CROSSXNU_TOOLCHAIN="${CROSSXNU_TOOLCHAIN:-${CROSSXNU_ROOT}/toolchain}"

export CROSSXNU_SDK_VERSION="${CROSSXNU_SDK_VERSION:-26.5}"
export CROSSXNU_TARGET="${CROSSXNU_TARGET:-x86_64-apple-macos26.5}"

# XNU tag and its version, used for RC_DARWIN_KERNEL_VERSION.
source "${CROSSXNU_ROOT}/scripts/versions.sh"

export PATH="${CROSSXNU_TOOLCHAIN}/bin:${PATH}"

crossxnu_warn_if_slow_fs() {
    case "${CROSSXNU_ROOT}" in
        /mnt/*)
            cat >&2 <<'EOF'
warning: the repository is on a Windows-mounted filesystem (/mnt/...).
         XNU builds are several times slower there.  Clone into ~/src for
         real builds; bootstrap-only steps are fine.
EOF
            ;;
    esac
}
