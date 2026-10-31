#!/usr/bin/env python3
"""Extract selected files from Apple's macOS 'payloadv2' streams.

Every `AssetData/payloadv2/payload.NNN` file is an independent `pbzx`
container of [8-byte uncompressed size][16-byte header][xz stream] blocks;
the decoded blocks of all files, in name order, form one continuous
AppleArchive (`YAA1`) stream.

Usage:
    aar-extract.py <asset.zip> <outdir> <path-regex> [...]
    aar-extract.py <asset.zip> --list [<path-regex> ...]
"""
import lzma
import re
import struct
import sys
import zipfile
from pathlib import Path

READ_CHUNK = 1 << 20


class BlockStream:
    """Decoded AppleArchive bytes, walking pbzx blocks of all payload files."""

    def __init__(self, zf, names):
        self.zf = zf
        self.names = names
        self.idx = 0
        self.file = None
        self.filebuf = b""
        self.blockbuf = b""
        self.pos = 0
        self.total = 0
        self.blocks = 0
        self.eof = False

    # ---- raw file bytes, across one file at a time ----
    def _open_next(self):
        while self.idx < len(self.names):
            name = self.names[self.idx]
            self.idx += 1
            self.file = self.zf.open(name)
            magic = self.file.read(4)
            if magic != b"pbzx":
                print("skip %s: magic %r" % (name, magic))
                self.file.close()
                self.file = None
                continue
            print("open %s" % name.split("/")[-1], flush=True)
            return True
        return False

    def _read_raw(self, n):
        while len(self.filebuf) < n:
            if self.file is None and not self._open_next():
                break
            chunk = self.file.read(READ_CHUNK)
            if not chunk:
                self.file.close()
                self.file = None
                continue
            self.filebuf += chunk
        out, self.filebuf = self.filebuf[:n], self.filebuf[n:]
        return out

    def _unread_raw(self, data):
        if data:
            self.filebuf = data + self.filebuf

    # ---- one decoded block ----
    def _next_block(self):
        hdr = self._read_raw(24)
        if len(hdr) < 24:
            return b""
        size = struct.unpack(">Q", hdr[:8])[0]
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        out = b""
        while not dec.eof:
            chunk = self._read_raw(READ_CHUNK)
            if not chunk:
                break
            out += dec.decompress(chunk)
        if dec.eof and dec.unused_data:
            self._unread_raw(dec.unused_data)
        self.blocks += 1
        print("  block %3d declared=%d decoded=%d" %
              (self.blocks, size, len(out)), flush=True)
        return out

    def read(self, n):
        while len(self.blockbuf) - self.pos < n and not self.eof:
            block = self._next_block()
            if not block:
                self.eof = True
                break
            if self.pos:
                self.blockbuf = self.blockbuf[self.pos:]
                self.pos = 0
            self.blockbuf += block
        out = self.blockbuf[self.pos:self.pos + n]
        self.pos += len(out)
        self.total += len(out)
        return out


def parse_header(stream):
    magic = stream.read(4)
    if len(magic) < 4:
        return None
    if magic not in (b"YAA1", b"AA01"):
        raise RuntimeError("bad entry magic %r" % magic)
    raw = stream.read(2)
    if len(raw) < 2:
        return None
    hdr_len = struct.unpack("<H", raw)[0]
    body = stream.read(hdr_len - 6)
    fields = {}
    blobs = 0
    i = 0
    while i + 4 <= len(body):
        key = body[i:i + 3].decode("latin-1")
        sub = body[i + 3:i + 4]
        i += 4
        if sub == b"*":
            fields[key] = True
        elif sub in b"1248":
            w = int(sub.decode())
            fields[key] = int.from_bytes(body[i:i + w], "little")
            i += w
        elif sub in b"ABC":
            w = {"A": 2, "B": 4, "C": 8}[sub.decode()]
            size = int.from_bytes(body[i:i + w], "little")
            fields[key] = size
            blobs += size
            i += w
        elif sub in b"FGHIJ":
            w = {"F": 4, "G": 20, "H": 32, "I": 48, "J": 64}[sub.decode()]
            fields[key] = body[i:i + w]
            i += w
        elif sub in b"ST":
            w = 8 if sub == b"S" else 12
            fields[key] = body[i:i + w]
            i += w
        elif sub == b"P":
            ln = int.from_bytes(body[i:i + 2], "little")
            fields[key] = body[i + 2:i + 2 + ln].decode("latin-1")
            i += 2 + ln
        else:
            raise RuntimeError("unknown subtype %r for key %r" % (sub, key))
    return fields, blobs


def payload_names(zf):
    return sorted(n for n in zf.namelist()
                  if re.match(r"AssetData/payloadv2/payload\.\d+$", n))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    zf = zipfile.ZipFile(argv[1])
    list_only = argv[2] == "--list"
    outdir = None if list_only else Path(argv[2])
    patterns = [re.compile(p) for p in argv[3:]] or [re.compile(".")]
    matched = [0] * len(patterns)

    stream = BlockStream(zf, payload_names(zf))
    entries = 0
    written = 0
    while True:
        try:
            parsed = parse_header(stream)
        except RuntimeError as exc:
            print("stop:", exc, "at archive offset", stream.total)
            return 1
        if parsed is None:
            break
        fields, blob_bytes = parsed
        typ = fields.get("TYP")
        if isinstance(typ, int):
            typ = chr(typ)
        path = fields.get("PAT")
        entries += 1
        if entries % 20000 == 0:
            print("  scanned %d entries, at %s" % (entries, path), flush=True)
        if path is not None:
            for pi, pat in enumerate(patterns):
                if pat.search(path):
                    matched[pi] += 1
                    if list_only:
                        print("%s %s" % (typ, path), flush=True)
                    else:
                        target = outdir / path
                        if typ == "D":
                            target.mkdir(parents=True, exist_ok=True)
                        elif typ == "L":
                            target.parent.mkdir(parents=True, exist_ok=True)
                            if target.is_symlink() or target.exists():
                                target.unlink()
                            target.symlink_to(fields.get("LNK", ""))
                        elif typ == "F":
                            target.parent.mkdir(parents=True, exist_ok=True)
                            data = stream.read(blob_bytes)
                            target.write_bytes(data)
                            written += 1
                            print("  wrote %-64s %d bytes" % (path, len(data)),
                                  flush=True)
                            break   # data already consumed
                    break
            else:
                stream.read(blob_bytes)
            if not list_only and all(m > 0 for m in matched):
                print("all patterns matched, stopping early")
                break
            continue
        stream.read(blob_bytes)
    print("done: %d entries scanned, %d files written" % (entries, written))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
