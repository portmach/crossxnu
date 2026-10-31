//! Extract selected files from a streaming AppleArchive (`YAA1`/`AA01`) on
//! stdin, using the `apple-archive` crate for header parsing.
//!
//! Usage: aar-tool <outdir> <substring> [<substring> ...]
//!
//! Entry data is skipped by the declared blob length.  Some payload entries
//! carry data the header does not describe, which desynchronises the stream;
//! when that happens we resynchronise on the next `YAA1`/`AA01` magic instead
//! of giving up, so a handful of lost entries do not stop the extraction.

use apple_archive::{FieldKey, Header};
use std::fs;
use std::io::{self, Cursor, Read, Write};
use std::path::Path;

const MAGICS: [&[u8; 4]; 2] = [b"YAA1", b"AA01"];

struct Src {
    inner: io::StdinLock<'static>,
    pending: Vec<u8>,
}

impl Src {
    fn new() -> Src {
        Src { inner: io::stdin().lock(), pending: Vec::new() }
    }

    fn read_exact_opt(&mut self, buf: &mut [u8]) -> bool {
        let mut filled = 0;
        while filled < buf.len() {
            if !self.pending.is_empty() {
                let take = (buf.len() - filled).min(self.pending.len());
                buf[filled..filled + take].copy_from_slice(&self.pending[..take]);
                self.pending.drain(..take);
                filled += take;
                continue;
            }
            match self.inner.read(&mut buf[filled..]) {
                Ok(0) => return false,
                Ok(n) => filled += n,
                Err(_) => return false,
            }
        }
        true
    }

    /// Skip forward to the next entry magic; returns false at end of stream.
    fn resync(&mut self) -> bool {
        let mut win: Vec<u8> = std::mem::take(&mut self.pending);
        let mut tmp = [0u8; 1 << 16];
        loop {
            if let Some(i) = MAGICS
                .iter()
                .filter_map(|m| win.windows(4).position(|w| w == *m))
                .min()
            {
                self.pending = win.split_off(i);
                return true;
            }
            if win.len() > 3 {
                let keep = win.len() - 3;
                win.drain(..keep);
            }
            match self.inner.read(&mut tmp) {
                Ok(0) => return false,
                Ok(n) => win.extend_from_slice(&tmp[..n]),
                Err(_) => return false,
            }
        }
    }
}

fn is_magic(b: &[u8]) -> bool {
    MAGICS.iter().any(|m| &m[..] == b)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let outdir = Path::new(&args[1]).to_path_buf();
    let pats: Vec<String> = args[2..].to_vec();
    let mut src = Src::new();
    let mut buf = vec![0u8; 1 << 20];
    let mut entries = 0u64;
    let mut written = 0u64;
    let mut resyncs = 0u64;

    loop {
        let mut head = [0u8; 6];
        if !src.read_exact_opt(&mut head) {
            break;
        }
        let mut hdr_len = u16::from_le_bytes([head[4], head[5]]) as usize;
        if !is_magic(&head[..4]) || hdr_len < 6 {
            resyncs += 1;
            eprintln!("desync after {entries} entries (resync #{resyncs})");
            if !src.resync() {
                break;
            }
            continue;
        }
        if hdr_len > 4096 {
            hdr_len = 4096; /* implausible; resync below will catch it */
        }
        let mut hdr = vec![0u8; hdr_len];
        hdr[..6].copy_from_slice(&head);
        if !src.read_exact_opt(&mut hdr[6..]) {
            break;
        }
        let mut cur = Cursor::new(&hdr[..]);
        let header = match Header::read(&mut cur) {
            Ok(h) => h,
            Err(e) => {
                eprintln!("header error after {entries} entries: {e:?}");
                if !src.resync() {
                    break;
                }
                continue;
            }
        };
        let path = header
            .get_string(FieldKey::PAT)
            .map(|b| String::from_utf8_lossy(b).to_string())
            .unwrap_or_default();
        let typ = header
            .get_uint(FieldKey::TYP)
            .map(|v| (v as u8) as char)
            .unwrap_or('?');
        let mut left = header.blob_data_len();
        entries += 1;
        if entries % 50000 == 0 {
            eprintln!("scanned {entries} entries, at {path}");
        }
        if !path.is_empty() && pats.iter().any(|p| path.contains(p.as_str())) {
            let target = outdir.join(&path);
            match typ {
                'D' => {
                    let _ = fs::create_dir_all(&target);
                    println!("dir  {path}");
                }
                'L' => {
                    if let Some(parent) = target.parent() {
                        let _ = fs::create_dir_all(parent);
                    }
                    let link = header
                        .get_string(FieldKey::LNK)
                        .map(|b| String::from_utf8_lossy(b).to_string())
                        .unwrap_or_default();
                    let _ = fs::remove_file(&target);
                    let _ = std::os::unix::fs::symlink(&link, &target);
                    println!("link {path} -> {link}");
                }
                'F' => {
                    if let Some(parent) = target.parent() {
                        let _ = fs::create_dir_all(parent);
                    }
                    let mut file = fs::File::create(&target).expect("create");
                    while left > 0 {
                        let take = std::cmp::min(left as usize, buf.len());
                        if !src.read_exact_opt(&mut buf[..take]) {
                            eprintln!("short data for {path}");
                            return;
                        }
                        file.write_all(&buf[..take]).expect("write");
                        left -= take as u64;
                    }
                    written += 1;
                    let size = target.metadata().map(|m| m.len()).unwrap_or(0);
                    println!("file {path} ({size} bytes)");
                    continue;
                }
                _ => {}
            }
        }
        while left > 0 {
            let take = std::cmp::min(left as usize, buf.len());
            if !src.read_exact_opt(&mut buf[..take]) {
                eprintln!("truncated stream while skipping {path}");
                println!("done: {entries} entries, {written} files, {resyncs} resyncs");
                return;
            }
            left -= take as u64;
        }
    }
    println!("done: {entries} entries, {written} files, {resyncs} resyncs");
}
