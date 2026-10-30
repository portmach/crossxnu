#!/usr/bin/env python3
"""Extract the macOS system root from an installer `payloadv2` asset.

The installer asset (`com_apple_MobileAsset_MacSoftwareUpdate/*.zip`) stores the
system as `AssetData/payloadv2/payload.NNN`, each a pbzx stream wrapping one
self-contained Apple Archive.  Payloads are independent deltas: their union is
the new system volume.  `fixup.manifest` (also pbzx + Apple Archive) carries
the root-level fixups such as firmlinks and volume symlinks, and `links.txt`
lists link paths.

Typical use:

    scripts/extract-payloadv2.py --asset SharedSupport.zip --root ~/root
    scripts/extract-payloadv2.py --asset SharedSupport.zip --root ~/root \\
        --payloads 0-52 --jobs 6
    scripts/extract-payloadv2.py --asset SharedSupport.zip --root ~/root \\
        --fixup

The script needs nothing beyond CPython 3 (lzma) — no macOS tooling.
"""
import argparse
import os
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aa  # noqa: E402

PAYLOAD_ENTRY = "AssetData/payloadv2/payload.%03d"
ENTRY_PREFIX = "AssetData/payloadv2/"
METADATA = (
    "payload_chunks.txt",
    "data_payload",
    "prepare_payload",
    "firmlinks_payload",
    "links.txt",
    "fixup.manifest",
)


def decode_entry(zip_path, member, dest):
    """pbzx-decode one zip member into `dest`; returns decompressed size."""
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as src, open(dest, "wb") as out:
        _, total = aa.pbzx_stream(src, out)
    return total


def work(job):
    zip_path, member, index, root, parts = job
    archive = os.path.join(parts, "payload.%03d.aar" % index)
    t0 = time.time()
    try:
        raw = decode_entry(zip_path, member, archive)
        files, dirs, links, nbytes = aa.extract(archive, root)
        return (index, raw, files, dirs, links, nbytes, time.time() - t0, "")
    except Exception as exc:  # noqa: BLE001 - report, keep going
        return (index, 0, 0, 0, 0, 0, time.time() - t0, "%s: %s" % (type(exc).__name__, exc))
    finally:
        if os.path.exists(archive):
            os.unlink(archive)


def parse_range(text):
    first, _, last = text.partition("-")
    return int(first), int(last or first)


def extract_fixup(zip_path, root, parts):
    """Apply `fixup.manifest` (root fixups) on top of the payload tree.

    The manifest lists every path in the volume with an empty DAT, so file
    entries must not be written — only directories, symlinks and modes.
    """
    member = ENTRY_PREFIX + "fixup.manifest"
    archive = os.path.join(parts, "fixup.manifest.aar")
    raw = decode_entry(zip_path, member, archive)
    files, dirs, links, nbytes = aa.extract(
        archive, root, write_files=False, defer_modes=True
    )
    os.unlink(archive)
    print(
        "fixup.manifest: %d bytes -> files=%d dirs=%d links=%d bytes=%d"
        % (raw, files, dirs, links, nbytes)
    )


def extract_metadata(zip_path, dest):
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in METADATA:
            member = ENTRY_PREFIX + name
            try:
                info = zf.getinfo(member)
            except KeyError:
                continue
            with zf.open(info) as src, open(os.path.join(dest, name), "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            print("metadata: %s (%d bytes)" % (name, info.file_size))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asset", required=True, help="installer asset zip")
    ap.add_argument("--root", required=True, help="output root directory")
    ap.add_argument("--payloads", default="0-52", help="payload index range (default 0-52)")
    ap.add_argument("--jobs", type=int, default=4, help="parallel payloads (default 4)")
    ap.add_argument("--parts", default=None, help="scratch dir for decoded archives")
    ap.add_argument("--fixup", action="store_true", help="also apply fixup.manifest")
    ap.add_argument("--metadata", action="store_true", help="also dump payloadv2 metadata")
    args = ap.parse_args(argv)

    zip_path = os.path.abspath(args.asset)
    root = os.path.abspath(args.root)
    parts = os.path.abspath(args.parts or os.path.join(root, "..", "payloadv2-parts"))
    os.makedirs(parts, exist_ok=True)
    os.makedirs(root, exist_ok=True)

    first, last = parse_range(args.payloads)
    if args.metadata:
        extract_metadata(zip_path, os.path.join(parts, "metadata"))

    jobs = [
        (zip_path, PAYLOAD_ENTRY % i, i, root, parts) for i in range(first, last + 1)
    ]
    t0 = time.time()
    done = 0
    failed = 0
    totals = [0, 0, 0, 0, 0]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(work, job) for job in jobs]
        for fut in as_completed(futures):
            index, raw, files, dirs, links, nbytes, elapsed, err = fut.result()
            done += 1
            if err:
                failed += 1
                print("[FAIL] payload.%03d %s" % (index, err), flush=True)
                continue
            totals[0] += raw
            totals[1] += files
            totals[2] += dirs
            totals[3] += links
            totals[4] += nbytes
            print(
                "[ok] payload.%03d archive=%d files=%d dirs=%d links=%d bytes=%d %.1fs"
                % (index, raw, files, dirs, links, nbytes, elapsed),
                flush=True,
            )

    if args.fixup and not failed:
        extract_fixup(zip_path, root, parts)

    print(
        "extracted %d/%d payloads: archive=%d files=%d dirs=%d links=%d bytes=%d in %.1fs"
        % (
            done - failed,
            len(jobs),
            totals[0],
            totals[1],
            totals[2],
            totals[3],
            totals[4],
            time.time() - t0,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
