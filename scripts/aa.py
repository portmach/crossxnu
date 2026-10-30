#!/usr/bin/env python3
"""Apple Archive (YAA1) and pbzx helpers for crossxnu.

Two containers show up in the macOS installer payloads:

  pbzx      "pbzx" + u64be blockSize, then chunks of
            {u64be uncompressedSize, u64be compressedSize, xz-stream}.
            Wraps `payloadv2/payload.NNN` and `payloadv2/fixup.manifest`.

  Apple     "YAA1" + u16le headerSize + fields, optionally followed by a data
  Archive   blob (DAT bytes) and an xattr blob (XAT bytes).

Field encoding: u32be key(24 bits) + subtype(8 bits), then a fixed value:

  '*'  flag, nothing follows        'A' 'B' 'C'  blob of 2 / 4 / 8 bytes
  '1'  '2'  '4'  '8'  uint         'F' 'G' 'H' 'I' 'J'  hash 4/20/32/48/64
  'S'  'T'  timespec 8 / 12        'P'  string, u16le length prefix + bytes

Integers are little-endian.  The archive is a flat sequence of entries: PAT
is the path, TYP the entry type ('D' directory, 'F' file, 'L' symlink), DAT
the file size, LNK the symlink target, MOD the mode.  Parent directories are
not guaranteed to be present as entries, so extraction creates them.
"""
import lzma
import os
import struct
import sys

MAGIC_AA = (b"YAA1", b"AA01")
MAGIC_PBZX = b"pbzx"

FIXED_SIZES = {
    "1": 1,
    "2": 2,
    "4": 4,
    "8": 8,
    "A": 2,
    "B": 4,
    "C": 8,
    "F": 4,
    "G": 20,
    "H": 32,
    "I": 48,
    "J": 64,
    "S": 8,
    "T": 12,
}


class AppleArchiveError(Exception):
    pass


def _key(name):
    return int.from_bytes(name.encode(), "big")


TYP, PAT, DAT, LNK, XAT, MOD = (_key(n) for n in ("TYP", "PAT", "DAT", "LNK", "XAT", "MOD"))


# --------------------------------------------------------------------------
# pbzx
# --------------------------------------------------------------------------
def pbzx_stream(src, dst):
    """Decode a pbzx stream from `src` into `dst` (file objects)."""
    magic = src.read(4)
    if magic != MAGIC_PBZX:
        raise AppleArchiveError("bad pbzx magic %r" % (magic,))
    block = struct.unpack(">Q", src.read(8))[0]
    total = 0
    while True:
        hdr = src.read(16)
        if not hdr:
            break
        if len(hdr) != 16:
            raise AppleArchiveError("truncated pbzx chunk header")
        uncomp, comp = struct.unpack(">QQ", hdr)
        if comp == 0:
            break
        data = src.read(comp)
        if len(data) != comp:
            raise AppleArchiveError("truncated pbzx chunk data")
        out = lzma.decompress(data) if data[:6] == b"\xfd7zXZ\x00" else data
        if uncomp and len(out) != uncomp:
            raise AppleArchiveError("pbzx chunk size mismatch")
        dst.write(out)
        total += len(out)
    return block, total


def pbzx_file(path, dst_path):
    """Decode `path` (pbzx) into `dst_path`; returns (block size, bytes)."""
    with open(path, "rb") as f, open(dst_path, "wb") as o:
        return pbzx_stream(f, o)


# --------------------------------------------------------------------------
# Apple Archive
# --------------------------------------------------------------------------
def _parse_fields(body):
    fields = {}
    pos = 0
    while pos < len(body):
        if pos + 4 > len(body):
            raise AppleArchiveError("truncated field key")
        word = struct.unpack(">I", body[pos : pos + 4])[0]
        pos += 4
        key = word >> 8
        sub = chr(word & 0xFF)
        if sub == "*":
            fields[key] = b""
            continue
        if sub == "P":
            n = int.from_bytes(body[pos : pos + 2], "little")
            pos += 2 + n
            fields[key] = body[pos - n : pos]
            continue
        n = FIXED_SIZES.get(sub)
        if n is None:
            raise AppleArchiveError("unknown field subtype %r" % (sub,))
        fields[key] = body[pos : pos + n]
        if len(fields[key]) != n:
            raise AppleArchiveError("truncated field value")
        pos += n
    return fields


def entries(src):
    """Yield (path, type, size, xattr size, fields) for each archive entry."""
    while True:
        magic = src.read(4)
        if not magic:
            return
        if magic not in MAGIC_AA:
            raise AppleArchiveError("bad Apple Archive magic %r" % (magic,))
        size = struct.unpack("<H", src.read(2))[0]
        body = src.read(size - 6)
        if len(body) != size - 6:
            raise AppleArchiveError("truncated header")
        fields = _parse_fields(body)
        path = fields.get(PAT, b"").decode("utf-8", "surrogateescape")
        typ = int.from_bytes(fields.get(TYP, b"\0"), "little")
        data_size = int.from_bytes(fields.get(DAT, b"\0"), "little")
        xat_size = int.from_bytes(fields.get(XAT, b"\0"), "little")
        yield path, chr(typ or 0), data_size, xat_size, fields


def extract(archive, root, write_files=True, apply_modes=True, defer_modes=False):
    """Extract `archive` below `root`.

    `write_files=False` applies only structure (directories, symlinks, modes of
    existing files) and never truncates file contents.  That is what
    `fixup.manifest` needs: it lists every path with an empty DAT, so writing
    its file entries would zero out the whole tree.

    `defer_modes=True` collects modes and applies them after the tree is
    created, deepest entry first.  Volume manifests contain read-only
    directories, and chmod'ing them while extracting blocks later entries.

    Returns (files, dirs, links, bytes).
    """
    files = dirs = links = nbytes = 0
    pending = []

    def set_mode(dest, fields):
        mode = fields.get(MOD)
        if not mode:
            return
        value = int.from_bytes(mode, "little") & 0o7777
        if defer_modes:
            pending.append((dest, value))
            return
        try:
            os.chmod(dest, value)
        except OSError:
            pass

    with open(archive, "rb") as src:
        for path, typ, data_size, xat_size, fields in entries(src):
            if not path:
                continue
            dest = os.path.join(root, path)
            parent = os.path.dirname(dest)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if typ == "D":
                os.makedirs(dest, exist_ok=True)
                if apply_modes:
                    set_mode(dest, fields)
                if xat_size:
                    src.seek(xat_size, os.SEEK_CUR)
                dirs += 1
            elif typ == "F":
                if write_files:
                    with open(dest, "wb") as out:
                        left = data_size
                        while left:
                            chunk = src.read(min(left, 1 << 20))
                            if not chunk:
                                raise AppleArchiveError("truncated data for %s" % path)
                            out.write(chunk)
                            left -= len(chunk)
                    nbytes += data_size
                elif data_size:
                    nbytes += data_size
                if xat_size:
                    src.seek(xat_size, os.SEEK_CUR)
                if apply_modes and os.path.exists(dest):
                    set_mode(dest, fields)
                files += 1
            elif typ == "L":
                target = fields.get(LNK, b"").decode("utf-8", "surrogateescape")
                if os.path.lexists(dest):
                    os.unlink(dest)
                os.symlink(target, dest)
                if xat_size:
                    src.seek(xat_size, os.SEEK_CUR)
                links += 1
            else:
                raise AppleArchiveError("unsupported entry type %r (%s)" % (typ, path))

    for dest, value in reversed(pending):
        try:
            os.chmod(dest, value)
        except OSError:
            pass
    return files, dirs, links, nbytes


def list_entries(archive):
    with open(archive, "rb") as src:
        for path, typ, data_size, xat_size, _ in entries(src):
            if path:
                yield typ, data_size, path
            if typ == "F":
                src.seek(data_size + xat_size, os.SEEK_CUR)
            elif typ in ("D", "L"):
                src.seek(xat_size, os.SEEK_CUR)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
USAGE = """usage:
  aa.py list    <archive.aar>
  aa.py extract <archive.aar> <output-dir>
  aa.py unpbxz  <file.pbzx> <output-file>
"""


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(USAGE)
        return 2
    cmd = argv[1]
    if cmd == "list":
        for typ, size, path in list_entries(argv[2]):
            print("%s %12d %s" % (typ, size, path))
        return 0
    if cmd == "extract":
        root = argv[3] if len(argv) > 3 else "."
        os.makedirs(root, exist_ok=True)
        files, dirs, links, nbytes = extract(argv[2], root)
        print("%s: files=%d dirs=%d links=%d bytes=%d" % (argv[2], files, dirs, links, nbytes))
        return 0
    if cmd == "unpbxz":
        if len(argv) < 4:
            sys.stderr.write(USAGE)
            return 2
        block, total = pbzx_file(argv[2], argv[3])
        print("%s: block=%d out=%d" % (argv[2], block, total))
        return 0
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
