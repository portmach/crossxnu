#!/usr/bin/env bash
# Generate DriverKit headers and .iig.cpp implementations from XNU's .iig IDL
# using the portable iig-port generator.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

XNU="${CROSSXNU_XNU}"
SDK="${CROSSXNU_SDK}"
IIG="${CROSSXNU_BUILD}/iig/iig"
SUPPORT="${CROSSXNU_TOOLCHAIN}/shims/iig/include"
OUT_IMPL="${XNU}/iokit/DriverKit"
OUT_EDITS="${CROSSXNU_BUILD}/driverkit/edits"
OUT_HEADERS="${SDK}/usr/local/include/kernel/DriverKit"

if [[ ! -x "${IIG}" ]]; then
    echo "error: iig not built; run ./scripts/build-iig.sh" >&2
    exit 1
fi

mkdir -p "${OUT_HEADERS}" "${OUT_EDITS}" "${OUT_IMPL}"

# patches/0008 removes DriverKit-dependent entries from iokit/conf/files so
# that a no-IIG build can get as far as possible.  Now that IIG exists, use
# the unmodified file-list so all generated sources are compiled.
git -C "${XNU}" show HEAD:iokit/conf/files > "${XNU}/iokit/conf/files"

# The test .iig.cpp lives under Tests/, where the kernel build's VPATH does not
# look.  It is a DriverKit test, not kernel code; keep it out of the kernel.
sed -i '/TestDextRematch\.iig\.cpp/d' "${XNU}/iokit/conf/files"

# The generated .iig.cpp files are build products; keep them out of git.
# They live next to the .iig inputs because iokit/conf/files refers to them
# by relative path (./DriverKit/Name.iig.cpp).
CLANG_ARGS=(
    -I"${SUPPORT}"
    -I"${XNU}/iokit"
    -I"${XNU}/osfmk"
    -I"${XNU}/bsd"
    -I"${XNU}/libkern"
    -I"${XNU}/EXTERNAL_HEADERS"
    -x c++ -std=gnu++2b -fblocks
    -D__IIG=1 -DDRIVERKIT_PRIVATE=1 -DPRIVATE_WIFI_ONLY=1
    -DXNU_PLATFORM_MacOSX=1
)

# Same order as the iig-port XNU verification manifest.
for name in \
    IOBufferMemoryDescriptor IODMACommand IODataQueueDispatchSource \
    IODispatchQueue IODispatchSource IOEventLink IOExtensiblePaniclog \
    IOInterruptDispatchSource IOMemoryDescriptor IOMemoryMap IOService \
    IOServiceNotificationDispatchSource IOServiceStateNotificationDispatchSource \
    IOUserClient IOUserServer IOWorkGroup OSAction OSObject; do
    def="${XNU}/iokit/DriverKit/${name}.iig"
    [[ -f "${def}" ]] || { echo "error: missing ${def}" >&2; exit 1; }
    echo "IIG ${name}"
    "${IIG}" --def "${def}" \
        --header "${OUT_HEADERS}/${name}.h" \
        --impl "${OUT_IMPL}/${name}.iig.cpp" \
        --edits "${OUT_EDITS}/${name}.edits" \
        --framework-name DriverKit \
        --deployment-target 26.5 \
        -- "${CLANG_ARGS[@]}"
done

# The test suite's IIG input is not part of the kernel target but is listed in
# iokit/conf/files.  Generate it too, into the path config expects.
TEST_DEF="${XNU}/iokit/Tests/TestServices/TestDextRematch.iig"
if [[ -f "${TEST_DEF}" ]]; then
    echo "IIG TestDextRematch"
    "${IIG}" --def "${TEST_DEF}" \
        --header "${OUT_HEADERS}/TestDextRematch.h" \
        --impl "${XNU}/iokit/Tests/TestServices/TestDextRematch.iig.cpp" \
        --edits "${OUT_EDITS}/TestDextRematch.edits" \
        --framework-name DriverKit \
        --deployment-target 26.5 \
        -- "${CLANG_ARGS[@]}"
fi

# XNU compiles DriverKit/*.iig.cpp with the object directory as cwd.  Put the
# generated implementations there as well as in the source tree.
for rel in "${XNU}"/BUILD/obj/*/iokit/RELEASE; do
    if [[ -d "${rel}" ]]; then
        mkdir -p "${rel}/DriverKit"
        cp "${OUT_IMPL}"/*.iig.cpp "${rel}/DriverKit/"
    fi
done
# Also prepare the default path for a clean build.
DEFAULT_OBJ="${XNU}/BUILD/obj/RELEASE_X86_64/iokit/RELEASE"
mkdir -p "${DEFAULT_OBJ}/DriverKit"
cp "${OUT_IMPL}"/*.iig.cpp "${DEFAULT_OBJ}/DriverKit/"

echo "DriverKit generated: headers in ${OUT_HEADERS}, impls in ${OUT_IMPL}"
