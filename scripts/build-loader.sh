#!/usr/bin/env bash
# Build the EFI loader with RAMDisk support and install it into build/esp.
#
# Upstream's pinned commit disables the ramdisk path ("temp: Disable ramdisk
# netboot for now, unreliable on real hardware"), but crossxnu boots its root
# image from it: the loader reads \ramdisk.img, hands it to the kernel through
# /chosen/memory-map and appends rd=md0.  The patch below re-enables both
# halves (load in main.c, devtree property in devtree.c).
#
# The final ELF -> PE conversion normally comes from
#   objcopy --target=efi-app-x86_64
# and the binutils here are built without the PE targets, so
# tools/efi-convert/elf2pe.py does that step instead.
#
# Usage: scripts/build-loader.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

LOADER_SRC="${CROSSXNU_XNU_LOADER:-${CROSSXNU_ROOT}/upstream/xnu-loader}"
PATCH="${CROSSXNU_ROOT}/patches/xnu-loader/0001-enable-ramdisk.patch"
BUILD_DIR="${CROSSXNU_BUILD}/xnu-loader"
GNU_EFI_DIR="${CROSSXNU_GNU_EFI_DIR:-$HOME/work/gnu-efi-install}"
OUT="${CROSSXNU_BUILD}/esp/EFI/BOOT/BOOTX64.EFI"

[[ -d "${LOADER_SRC}" ]] || { echo "error: no loader tree at ${LOADER_SRC}" >&2; exit 1; }
[[ -d "${GNU_EFI_DIR}" ]] || { echo "error: no gnu-efi at ${GNU_EFI_DIR}" >&2; exit 1; }

# Build from a copy so the submodule stays at its pin.
rm -rf "${BUILD_DIR}/src-tree"
mkdir -p "${BUILD_DIR}"
cp -R "${LOADER_SRC}" "${BUILD_DIR}/src-tree"
rm -rf "${BUILD_DIR}/src-tree/build" "${BUILD_DIR}/src-tree/.git"

if [[ -f "${PATCH}" ]]; then
    git -C "${BUILD_DIR}/src-tree" init -q 2>/dev/null || true
    ( cd "${BUILD_DIR}/src-tree" && patch -p1 --silent < "${PATCH}" )
fi

cmake -S "${BUILD_DIR}/src-tree" -B "${BUILD_DIR}/cmake" \
      -DGNU_EFI_DIR="${GNU_EFI_DIR}" >/dev/null
# The .efi target is expected to fail here: that is the objcopy step we
# replace.  Build only as far as the shared object.
cmake --build "${BUILD_DIR}/cmake" -j"${CROSSXNU_JOBS:-4}" --target loader_objs >/dev/null
cmake --build "${BUILD_DIR}/cmake" -j"${CROSSXNU_JOBS:-4}" 2>&1 | grep -v "objcopy" || true

SO="${BUILD_DIR}/cmake/xnu-loader.so"
[[ -f "${SO}" ]] || { echo "error: ${SO} was not produced" >&2; exit 1; }

mkdir -p "$(dirname "${OUT}")"
python3 "${CROSSXNU_ROOT}/tools/efi-convert/elf2pe.py" "${SO}" "${OUT}"
echo "loader: ${OUT}"
