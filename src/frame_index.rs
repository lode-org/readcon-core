//! Frame offset index and its checked `.rcidx` sidecar.
//!
//! The sidecar stores the byte offset of every frame start in an
//! uncompressed CON file, so later reads skip the offset scan.
//! A sidecar is only used when its fingerprint matches the data file
//! (size, mtime, and a hash of the first and last 4 KiB) and its own
//! checksum is intact; any mismatch rebuilds the index instead.
//!
//! Layout (all integers little-endian):
//!
//! | bytes | field                                  |
//! |-------|----------------------------------------|
//! | 8     | magic `RCIDX\0\0\0`                    |
//! | 4     | format version (1)                     |
//! | 4     | reserved (0)                           |
//! | 8     | data file size in bytes                |
//! | 8     | data file mtime, ns since UNIX epoch   |
//! | 8     | FNV-1a 64 of first and last 4 KiB      |
//! | 8     | frame count `n`                        |
//! | 8 n   | frame start offsets                    |
//! | 8     | FNV-1a 64 of every preceding byte      |

use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use crate::error::ParseError;
use crate::iterators::ConFrameIterator;

const MAGIC: &[u8; 8] = b"RCIDX\0\0\0";
const VERSION: u32 = 1;
const EDGE: u64 = 4096;
const HEADER_LEN: usize = 8 + 4 + 4 + 8 + 8 + 8 + 8;

/// Frame start offsets for one data file, plus its total length.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrameIndex {
    /// Byte offset of each frame start, strictly increasing.
    pub offsets: Vec<u64>,
    /// Length of the data in bytes; the last frame ends here.
    pub data_len: u64,
}

impl FrameIndex {
    /// Number of frames.
    pub fn len(&self) -> usize {
        self.offsets.len()
    }

    /// True when the index has no frames.
    pub fn is_empty(&self) -> bool {
        self.offsets.is_empty()
    }

    /// Byte range `[start, end)` of frame `i`.
    pub fn range(&self, i: usize) -> Option<std::ops::Range<usize>> {
        let start = *self.offsets.get(i)? as usize;
        let end = self.offsets.get(i + 1).copied().unwrap_or(self.data_len) as usize;
        Some(start..end)
    }

    /// Scan `text` for frame starts, failing on the first malformed frame.
    pub fn scan(text: &str) -> Result<Self, ParseError> {
        Ok(FrameIndex {
            offsets: frame_start_offsets_checked(text)?
                .into_iter()
                .map(|o| o as u64)
                .collect(),
            data_len: text.len() as u64,
        })
    }
}

/// Frame start offsets, returning the skip error instead of truncating.
///
/// [`crate::iterators::frame_start_offsets`] stops silently at the first
/// malformed frame; an index written to disk must not do that.
pub fn frame_start_offsets_checked(text: &str) -> Result<Vec<usize>, ParseError> {
    let mut out = Vec::new();
    let mut scanner = ConFrameIterator::new(text);
    loop {
        let start = scanner.byte_pos();
        if start >= text.len() || text.as_bytes()[start..].iter().all(u8::is_ascii_whitespace) {
            break;
        }
        out.push(start);
        match scanner.forward_fast() {
            Some(Ok(())) => {}
            Some(Err(e)) => return Err(e),
            None => return Err(ParseError::IncompleteFrame),
        }
    }
    Ok(out)
}

/// Validate UTF-8 in newline-aligned slices, in parallel when available.
///
/// A newline byte never occurs inside a multi-byte UTF-8 sequence, so
/// slices cut just after a `\n` validate independently.
pub fn validate_utf8_sliced(bytes: &[u8]) -> Result<&str, std::str::Utf8Error> {
    const MIN_SLICE: usize = 8 << 20;
    let n_slices = (bytes.len() / MIN_SLICE).max(1);
    let mut cuts = Vec::with_capacity(n_slices + 1);
    cuts.push(0usize);
    for k in 1..n_slices {
        let target = k * bytes.len() / n_slices;
        let prev = *cuts.last().unwrap();
        if target <= prev {
            continue;
        }
        match memchr::memchr(b'\n', &bytes[target..]) {
            Some(p) => cuts.push(target + p + 1),
            None => break,
        }
    }
    cuts.push(bytes.len());
    cuts.dedup();
    let check = |w: &[usize]| -> Result<(), std::str::Utf8Error> {
        std::str::from_utf8(&bytes[w[0]..w[1]]).map(|_| ())
    };
    #[cfg(feature = "parallel")]
    {
        use rayon::prelude::*;
        let windows: Vec<&[usize]> = cuts.windows(2).collect();
        windows.par_iter().try_for_each(|w| check(w))?;
    }
    #[cfg(not(feature = "parallel"))]
    {
        for w in cuts.windows(2) {
            check(w)?;
        }
    }
    // SAFETY: every byte lies in exactly one validated slice, and slice
    // boundaries sit after ASCII newlines, so the whole buffer is UTF-8.
    Ok(unsafe { std::str::from_utf8_unchecked(bytes) })
}

/// Path of the sidecar for `path`: `foo.con` becomes `foo.con.rcidx`.
pub fn sidecar_path(path: &Path) -> PathBuf {
    let mut s = path.as_os_str().to_owned();
    s.push(".rcidx");
    PathBuf::from(s)
}

fn fnv1a(mut h: u64, bytes: &[u8]) -> u64 {
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}
const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Fingerprint {
    size: u64,
    mtime_ns: u64,
    edges: u64,
}

fn fingerprint(path: &Path) -> io::Result<Fingerprint> {
    let mut f = std::fs::File::open(path)?;
    let meta = f.metadata()?;
    let size = meta.len();
    let mtime_ns = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    let mut buf = vec![0u8; EDGE.min(size) as usize];
    f.read_exact(&mut buf)?;
    let mut h = fnv1a(FNV_OFFSET, &buf);
    let tail = EDGE.min(size);
    f.seek(SeekFrom::Start(size - tail))?;
    buf.resize(tail as usize, 0);
    f.read_exact(&mut buf)?;
    h = fnv1a(h, &buf);
    Ok(Fingerprint {
        size,
        mtime_ns,
        edges: h,
    })
}

fn encode(fp: Fingerprint, idx: &FrameIndex) -> Vec<u8> {
    let mut out = Vec::with_capacity(HEADER_LEN + 8 * idx.offsets.len() + 8);
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&VERSION.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes());
    out.extend_from_slice(&fp.size.to_le_bytes());
    out.extend_from_slice(&fp.mtime_ns.to_le_bytes());
    out.extend_from_slice(&fp.edges.to_le_bytes());
    out.extend_from_slice(&(idx.offsets.len() as u64).to_le_bytes());
    for o in &idx.offsets {
        out.extend_from_slice(&o.to_le_bytes());
    }
    let sum = fnv1a(FNV_OFFSET, &out);
    out.extend_from_slice(&sum.to_le_bytes());
    out
}

fn u64_at(b: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(b[at..at + 8].try_into().unwrap())
}

/// Decode a sidecar and check it against `fp`; `None` means stale or corrupt.
fn decode(bytes: &[u8], fp: Fingerprint) -> Option<FrameIndex> {
    if bytes.len() < HEADER_LEN + 8 || &bytes[..8] != MAGIC {
        return None;
    }
    if u32::from_le_bytes(bytes[8..12].try_into().unwrap()) != VERSION {
        return None;
    }
    let body = &bytes[..bytes.len() - 8];
    if fnv1a(FNV_OFFSET, body) != u64_at(bytes, bytes.len() - 8) {
        return None;
    }
    let stored = Fingerprint {
        size: u64_at(bytes, 16),
        mtime_ns: u64_at(bytes, 24),
        edges: u64_at(bytes, 32),
    };
    if stored != fp {
        return None;
    }
    let n = u64_at(bytes, 40) as usize;
    if body.len() != HEADER_LEN + 8 * n {
        return None;
    }
    let offsets: Vec<u64> = (0..n).map(|i| u64_at(bytes, HEADER_LEN + 8 * i)).collect();
    let ordered = offsets.windows(2).all(|w| w[0] < w[1]);
    if !ordered || offsets.last().is_some_and(|&o| o >= fp.size) {
        return None;
    }
    Some(FrameIndex {
        offsets,
        data_len: fp.size,
    })
}

/// Read the sidecar for `path` if it exists and matches the data file.
pub fn read_sidecar(path: &Path) -> io::Result<Option<FrameIndex>> {
    let bytes = match std::fs::read(sidecar_path(path)) {
        Ok(b) => b,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e),
    };
    Ok(decode(&bytes, fingerprint(path)?))
}

/// Write the sidecar for `path` atomically (temp file plus rename).
pub fn write_sidecar(path: &Path, idx: &FrameIndex) -> io::Result<()> {
    let fp = fingerprint(path)?;
    if fp.size != idx.data_len {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "frame index length does not match the data file size",
        ));
    }
    let dst = sidecar_path(path);
    let mut tmp = dst.as_os_str().to_owned();
    tmp.push(".tmp");
    let tmp = PathBuf::from(tmp);
    {
        let mut f = std::fs::File::create(&tmp)?;
        f.write_all(&encode(fp, idx))?;
        f.sync_all()?;
    }
    std::fs::rename(&tmp, &dst)
}

/// Return a trusted index for `text` (the contents of `path`).
///
/// Uses the sidecar when it is valid; otherwise scans and, when
/// `write_back` is set, refreshes the sidecar (write errors are ignored,
/// so read-only directories still work).
pub fn load_or_build(path: &Path, text: &str, write_back: bool) -> Result<FrameIndex, ParseError> {
    if let Ok(Some(idx)) = read_sidecar(path) {
        if idx.data_len == text.len() as u64 {
            return Ok(idx);
        }
    }
    let idx = FrameIndex::scan(text)?;
    if write_back {
        let _ = write_sidecar(path, &idx);
    }
    Ok(idx)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(n: usize) -> String {
        let one = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.con"
        ))
        .unwrap();
        one.repeat(n)
    }

    #[test]
    fn checked_scan_matches_legacy_scan() {
        let text = fixture(7);
        let legacy = crate::iterators::frame_start_offsets(&text);
        assert_eq!(frame_start_offsets_checked(&text).unwrap(), legacy);
        assert_eq!(legacy.len(), 7);
    }

    #[test]
    fn checked_scan_reports_truncation() {
        let text = fixture(3);
        let cut = &text[..text.len() - 40];
        assert!(frame_start_offsets_checked(cut).is_err());
    }

    #[test]
    fn sliced_utf8_matches_std() {
        let mut s = "é\n".repeat(5 << 20);
        s.push_str("ü end\n");
        assert!(validate_utf8_sliced(s.as_bytes()).is_ok());
        let mut bad = s.into_bytes();
        let mid = bad.len() / 2;
        bad[mid] = 0xff;
        assert!(validate_utf8_sliced(&bad).is_err());
    }

    #[test]
    fn sidecar_roundtrip_and_staleness() {
        let dir = std::env::temp_dir().join(format!("rcidx-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("t.con");
        let text = fixture(5);
        std::fs::write(&con, &text).unwrap();
        let idx = load_or_build(&con, &text, true).unwrap();
        assert_eq!(read_sidecar(&con).unwrap(), Some(idx.clone()));
        for i in 0..idx.len() {
            let r = idx.range(i).unwrap();
            assert!(
                crate::iterators::ConFrameIterator::new(&text[r])
                    .next()
                    .unwrap()
                    .is_ok()
            );
        }
        // Corrupt one offset byte: checksum must reject it.
        let side = sidecar_path(&con);
        let mut b = std::fs::read(&side).unwrap();
        b[HEADER_LEN] ^= 1;
        std::fs::write(&side, &b).unwrap();
        assert_eq!(read_sidecar(&con).unwrap(), None);
        // Change the data file: fingerprint must reject the old sidecar.
        write_sidecar(&con, &idx).unwrap();
        let text2 = fixture(6);
        std::fs::write(&con, &text2).unwrap();
        assert_eq!(read_sidecar(&con).unwrap(), None);
        assert_eq!(load_or_build(&con, &text2, true).unwrap().len(), 6);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
