#!/usr/bin/env python3
"""Write the manifest that apfsroot uses to populate the APFS volume.

The guest has no libSystem and no directory-walking code (see
tools/apfs-root/apfsroot.c), and the tree is built here on the host anyway
(docs/userland.md), so the list of entries is generated from the same directory
the ramdisk is built from.

Format, one entry per line, tab separated:

    D<TAB>0755<TAB>System/Library
    F<TAB>0755<TAB>bin/ls
    L<TAB>0000<TAB>etc/rc.local<TAB>../private/etc/rc.local

Directories, files and symlinks are emitted in lexicographic order of their
relative path, which guarantees a parent directory always comes before its
children.

Usage: gen-apfs-manifest.py ROOT OUTPUT [--skip NAME ...]
"""
import argparse
import os
import stat
import sys

# Top-level entries that must not be copied into the APFS root: devfs is
# mounted there by apfsroot, and mnt* are bring-up mount points.
DEFAULT_SKIP = {"dev", "mnt1", "mnt2", "mnt3", "mnt4", "mnt5", "mnt6",
                "mnt7", "mnt8", "mnt9", "mnt10", "mnt11"}


def collect(root, skip):
    entries = []
    skipped = []

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""

        keep = []
        for name in dirnames:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            if not rel_dir and name in skip:
                skipped.append(rel)
                continue
            keep.append(name)
        dirnames[:] = sorted(keep)

        for name in dirnames:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            st = os.lstat(os.path.join(dirpath, name))
            entries.append(("D", st.st_mode, rel, None))

        for name in filenames:
            rel = os.path.join(rel_dir, name) if rel_dir else name
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                entries.append(("L", st.st_mode, rel, os.readlink(path)))
            elif stat.S_ISREG(st.st_mode):
                entries.append(("F", st.st_mode, rel, None))
            else:
                skipped.append(rel)

    return entries, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    ap.add_argument("output")
    ap.add_argument("--skip", action="append", default=[])
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    skip = DEFAULT_SKIP | set(args.skip)

    entries, skipped = collect(root, skip)
    entries.sort(key=lambda e: e[2])

    total = 0
    with open(args.output, "w") as out:
        for kind, mode, rel, target in entries:
            if kind == "L":
                out.write("L\t%04o\t%s\t%s\n" % (stat.S_IMODE(mode), rel, target))
            else:
                out.write("%s\t%04o\t%s\n" % (kind, stat.S_IMODE(mode), rel))
            if kind == "F":
                total += os.lstat(os.path.join(root, rel)).st_size

    print("%s: %d entries, %d files, %.1f MiB of file data"
          % (args.output, len(entries),
             sum(1 for e in entries if e[0] == "F"), total / (1 << 20)))
    if skipped:
        print("skipped %d entries: %s%s"
              % (len(skipped), ", ".join(sorted(skipped)[:8]),
                 " ..." if len(skipped) > 8 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
