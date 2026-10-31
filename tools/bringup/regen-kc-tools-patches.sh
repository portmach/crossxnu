#!/usr/bin/env bash
# Regenerate the kc-tools patch series so it applies cumulatively.
#
# Why this exists: the patches in patches/kc-tools/ were each saved as a full
# diff from the pinned submodule, so patch N already contained everything
# patch N-1 did.  Applying them in order with `patch` therefore fails from the
# second one onwards (`Hunk #2 FAILED`, duplicate insertions).  scripts/
# build-kc-tools.sh applies them in order, so the series has to be a chain of
# increments, not a set of snapshots.
#
# Each stage tree is reconstructed from the archived snapshot patch, then the
# series is re-emitted as stage-to-stage deltas:
#
#   0001                       (unchanged: prelink layer, other files)
#   0002 = base -> S2          where Sn = base + 0001 + archived 000n
#   ...
#   0006 = S5 -> S6
#   0007 = S6 -> <working tree>  (the newest work, if a tree is given)
#
# Usage: regen-kc-tools-patches.sh [WORKING_TREE]
#   WORKING_TREE defaults to $KC_TOOLS_DEV, else $HOME/work/kc-tools.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/env.sh
source "${SCRIPT_DIR}/../../scripts/env.sh"

BASE="${CROSSXNU_UPSTREAM}/kc-tools"
PATCHES="${CROSSXNU_ROOT}/patches/kc-tools"
WORK_TREE="${1:-${KC_TOOLS_DEV:-$HOME/work/kc-tools}}"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

SNAPSHOT_STAGES=(0002 0003 0004 0005 0006)
DIRS=(include lib src)

[[ -d "${BASE}" ]] || { echo "error: ${BASE} missing" >&2; exit 1; }

# 1. keep the archived snapshots: they are the only record of each stage
mkdir -p "${TMP}/orig"
cp "${PATCHES}"/*.patch "${TMP}/orig/"

# Each archived 000n is a full snapshot from the pinned commit, so it must apply
# on its own.  Once this script has run, those files are increments instead and
# cannot be used as input again: say so clearly instead of dying inside patch.
for n in "${SNAPSHOT_STAGES[@]}"; do
    rm -rf "${TMP}/probe"
    cp -a "${BASE}" "${TMP}/probe"
    if ! patch -p1 -s --dry-run -d "${TMP}/probe" -i "${TMP}/orig/${n}"-*.patch 2>/dev/null; then
        cat >&2 <<EOF
error: patches/kc-tools/${n}-*.patch is not a snapshot from ${BASE}
       (this script rewrites the series in place, so re-running it needs the
       archived versions back first):
           git -C "${CROSSXNU_ROOT}" checkout -- patches/kc-tools/
EOF
        exit 1
    fi
done
rm -rf "${TMP}/probe"

stage_tree() {   # stage_tree N OUTDIR
    local n="$1" out="$2"
    rm -rf "${out}"
    cp -a "${BASE}" "${out}"
    # 0001 stays a separate, first patch (it touches prelink.c and fileset.c,
    # which none of the snapshots do).
    patch -p1 -s -d "${out}" -i "${TMP}/orig/0001-always-emit-prelink-info.patch"
    if [[ -n "${n}" ]]; then
        patch -p1 -s -d "${out}" -i "${TMP}/orig/${n}"-*.patch
    fi
}

emit_diff() {   # emit_diff FROM TO OUTFILE
    local from="$1" to="$2" out="$3"
    (
        cd "${TMP}"
        rm -rf dfrom dto
        mkdir -p dfrom dto
        # .orig/.rej are leftovers from earlier `patch` runs, not sources
        for d in "${DIRS[@]}"; do
            mkdir -p "dfrom/${d}" "dto/${d}"
            (cd "${from}/${d}" && tar -cf - --exclude='*.orig' --exclude='*.rej' .) |
                (cd "dfrom/${d}" && tar -xf -)
            (cd "${to}/${d}" && tar -cf - --exclude='*.orig' --exclude='*.rej' .) |
                (cd "dto/${d}" && tar -xf -)
        done
        find dfrom dto -type f -exec chmod 644 {} +
        git diff --no-index --src-prefix=a/ --dst-prefix=b/ dfrom dto > "${TMP}/raw.diff" || true
        sed -e 's|a/dfrom/|a/|g' -e 's|b/dto/|b/|g' "${TMP}/raw.diff" > "${out}"
        # a diff with no hunks is not a patch
        if ! grep -q '^@@' "${out}"; then
            echo "error: empty diff for ${out}" >&2
            exit 1
        fi
    )
    echo "wrote $(basename "${out}") ($(grep -c '^@@' "${out}") hunks)"
}

# 2. reconstruct every stage tree
prev="${TMP}/s1"
stage_tree "" "${prev}"
for n in "${SNAPSHOT_STAGES[@]}"; do
    stage_tree "${n}" "${TMP}/s_${n}"
done

# 3. emit the chain of increments, reusing the archived file names so the
#    documentation and `git log` references still line up
for n in "${SNAPSHOT_STAGES[@]}"; do
    out="$(ls "${TMP}/orig/${n}"-*.patch)"
    out="${PATCHES}/$(basename "${out}")"
    emit_diff "${prev}" "${TMP}/s_${n}" "${out}"
    prev="${TMP}/s_${n}"
done

# 4. the newest work: S6 -> the working tree the developer is on
if [[ -d "${WORK_TREE}" ]]; then
    if [[ -e "${PATCHES}/0007-arch-slice-and-chained-fixups-guard.patch" ]]; then
        out="${PATCHES}/0007-arch-slice-and-chained-fixups-guard.patch"
    else
        out="${PATCHES}/0007-newest-work.patch"
    fi
    if diff -rq --exclude=build --exclude=.git "${TMP}/s_0006" "${WORK_TREE}" >/dev/null 2>&1; then
        echo "working tree equals stage 6; leaving 0007 alone"
    else
        emit_diff "${TMP}/s_0006" "${WORK_TREE}" "${out}"
    fi
else
    echo "warning: ${WORK_TREE} not found; patches stop at 0006" >&2
fi
