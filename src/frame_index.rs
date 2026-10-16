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

/// Smallest slice before UTF-8 validation is split on newlines.
const UTF8_SLICE_MIN: usize = 8 << 20;

/// `k * len / n_slices` without wrapping the numerator.
///
/// The cut is always in `0..=len`. A wrapping `usize` product can point
/// past the buffer on a huge file.
fn utf8_slice_target(len: usize, index: usize, n_slices: usize) -> usize {
    let n = n_slices.max(1) as u128;
    let target = (index as u128) * (len as u128) / n;
    usize::try_from(target).unwrap_or(len).min(len)
}

/// `err` came from `bytes[start..]`. Report it against the whole buffer.
///
/// `error_len` counts only the invalid sequence. A multi-byte lead followed
/// by a non-continuation is `Some`, and the next byte is what proves it.
/// A prefix that stops on the lead is an incomplete character, so
/// `from_utf8` reports `None` and the error looks truncated.
fn reject_with_absolute_utf8(
    bytes: &[u8],
    start: usize,
    err: std::str::Utf8Error,
) -> Result<(), std::str::Utf8Error> {
    let end = match err.error_len() {
        Some(len) => start
            .saturating_add(err.valid_up_to())
            .saturating_add(len)
            .saturating_add(1),
        None => bytes.len(),
    };
    let end = end.min(bytes.len());
    if let Err(adjusted) = std::str::from_utf8(&bytes[..end]) {
        return Err(adjusted);
    }
    std::str::from_utf8(bytes).map(|_| ())
}

/// Validate UTF-8 in newline-aligned slices, in parallel when available.
///
/// A newline byte never occurs inside a multi-byte UTF-8 sequence, so
/// slices cut just after a `\n` validate independently.
pub fn validate_utf8_sliced(bytes: &[u8]) -> Result<&str, std::str::Utf8Error> {
    let n_slices = (bytes.len() / UTF8_SLICE_MIN).max(1);
    let mut cuts = Vec::with_capacity(n_slices + 1);
    cuts.push(0usize);
    for k in 1..n_slices {
        let target = utf8_slice_target(bytes.len(), k, n_slices);
        let prev = *cuts.last().unwrap();
        if target <= prev || target >= bytes.len() {
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
        match std::str::from_utf8(&bytes[w[0]..w[1]]) {
            Ok(_) => Ok(()),
            Err(err) => reject_with_absolute_utf8(bytes, w[0], err),
        }
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

fn modified_ns(meta: &std::fs::Metadata) -> u64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

fn hash_edges(head: &[u8], tail: &[u8]) -> u64 {
    fnv1a(fnv1a(FNV_OFFSET, head), tail)
}

/// FNV-1a of the first and last 4 KiB, matching [`fingerprint`].
fn edge_hash(bytes: &[u8]) -> u64 {
    let n = bytes.len();
    let head_n = (EDGE as usize).min(n);
    let tail_n = (EDGE as usize).min(n);
    hash_edges(&bytes[..head_n], &bytes[n - tail_n..])
}

fn fingerprint(path: &Path) -> io::Result<Fingerprint> {
    let mut f = std::fs::File::open(path)?;
    let meta = f.metadata()?;
    let size = meta.len();
    let head_n = EDGE.min(size) as usize;
    let tail_n = EDGE.min(size) as usize;
    let mut head = vec![0u8; head_n];
    f.read_exact(&mut head)?;
    f.seek(SeekFrom::Start(size - tail_n as u64))?;
    let mut tail = vec![0u8; tail_n];
    f.read_exact(&mut tail)?;
    Ok(Fingerprint {
        size,
        mtime_ns: modified_ns(&meta),
        edges: hash_edges(&head, &tail),
    })
}

/// Fingerprint of the inode opened here when its bytes are exactly `text`.
///
/// `None` means `path` is no longer that buffer. The size and edge hash
/// describe `text`; mtime is from the same snapshot, so a later replace
/// cannot be stored under this index.
fn fingerprint_if_same(path: &Path, text: &[u8]) -> io::Result<Option<Fingerprint>> {
    let mut file = std::fs::File::open(path)?;
    let meta = file.metadata()?;
    if meta.len() != text.len() as u64 {
        return Ok(None);
    }
    let mut offset = 0usize;
    let mut buf = [0u8; 64 * 1024];
    while offset < text.len() {
        let want = (text.len() - offset).min(buf.len());
        let n = file.read(&mut buf[..want])?;
        if n == 0 || text[offset..offset + n] != buf[..n] {
            return Ok(None);
        }
        offset += n;
    }
    Ok(Some(Fingerprint {
        size: meta.len(),
        mtime_ns: modified_ns(&meta),
        edges: edge_hash(text),
    }))
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
    let n = usize::try_from(u64_at(bytes, 40)).ok()?;
    let table = n.checked_mul(8)?;
    let expected = HEADER_LEN.checked_add(table)?;
    if body.len() != expected {
        return None;
    }
    let offsets: Vec<u64> = (0..n).map(|i| u64_at(bytes, HEADER_LEN + i * 8)).collect();
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

fn write_encoded(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let dst = sidecar_path(path);
    let mut tmp = dst.as_os_str().to_owned();
    tmp.push(".tmp");
    let tmp = PathBuf::from(tmp);
    {
        let mut f = std::fs::File::create(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
    }
    std::fs::rename(&tmp, &dst)
}

/// Write the sidecar for `path` atomically (temp file plus rename).
///
/// The fingerprint describes `path` as it exists at this call. Scanning
/// an earlier buffer and then calling this can store that fingerprint
/// with stale offsets. [`load_or_build`] writes only when the file still
/// matches the scanned buffer.
pub fn write_sidecar(path: &Path, idx: &FrameIndex) -> io::Result<()> {
    let fp = fingerprint(path)?;
    if fp.size != idx.data_len {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "frame index length does not match the data file size",
        ));
    }
    write_encoded(path, &encode(fp, idx))
}

/// Publish `idx` only when `path` still contains exactly `text`.
fn write_sidecar_for_text(path: &Path, text: &str, idx: &FrameIndex) -> io::Result<()> {
    if idx.data_len != text.len() as u64 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "frame index length does not match the data file size",
        ));
    }
    let Some(fp) = fingerprint_if_same(path, text.as_bytes())? else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "frame index does not match the data file contents",
        ));
    };
    write_encoded(path, &encode(fp, idx))
}

/// Return a trusted index for `text` (the contents of `path`).
///
/// Uses the sidecar when it is valid; otherwise scans and, when
/// `write_back` is set, refreshes the sidecar. The refresh is skipped
/// when `path` no longer contains `text`, so a same-length replace cannot
/// be stored with these offsets. Write errors are ignored, so read-only
/// directories still work.
pub fn load_or_build(path: &Path, text: &str, write_back: bool) -> Result<FrameIndex, ParseError> {
    if let Ok(Some(idx)) = read_sidecar(path) {
        if idx.data_len == text.len() as u64 {
            return Ok(idx);
        }
    }
    let idx = FrameIndex::scan(text)?;
    if write_back {
        let _ = write_sidecar_for_text(path, text, &idx);
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
    fn checked_scan_accepts_final_line_without_newline() {
        for n in [1usize, 3] {
            let text = fixture(n);
            let bare = text
                .strip_suffix('\n')
                .expect("fixture frame ends with a newline");
            let parsed = crate::iterators::ConFrameIterator::new(bare)
                .collect::<Result<Vec<_>, _>>()
                .expect("parser accepts the final line");
            assert_eq!(parsed.len(), n);
            let offsets =
                frame_start_offsets_checked(bare).expect("checked scan accepts the final line");
            assert_eq!(offsets, crate::iterators::frame_start_offsets(bare));
            assert_eq!(offsets.len(), n);
            let mut scanner = crate::iterators::ConFrameIterator::new(bare);
            for _ in 0..n {
                scanner
                    .forward_fast()
                    .unwrap()
                    .expect("skip accepts the final line");
            }
            assert!(scanner.forward_fast().is_none());
        }
    }

    #[test]
    fn checked_scan_reports_truncation() {
        let text = fixture(3);
        // Drop the last coordinate line. A final line that is present but
        // has no trailing newline is valid and is covered separately.
        let end = text.strip_suffix('\n').unwrap().rfind('\n').unwrap() + 1;
        let cut = &text[..end];
        assert!(frame_start_offsets_checked(cut).is_err());
        assert!(crate::iterators::ConFrameIterator::new(cut).any(|r| r.is_err()));
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
    fn sliced_utf8_error_offset_matches_std() {
        let mut buf = vec![b'\n'; UTF8_SLICE_MIN * 2 + 64];
        let at = UTF8_SLICE_MIN + UTF8_SLICE_MIN / 2;
        buf[at] = 0xff;
        let err = validate_utf8_sliced(&buf).unwrap_err();
        let std_err = std::str::from_utf8(&buf).unwrap_err();
        assert_eq!(err.valid_up_to(), std_err.valid_up_to());
        assert_eq!(err.error_len(), std_err.error_len());
        assert_eq!(err.valid_up_to(), at);
        assert_eq!(err.error_len(), Some(1));

        buf[at] = b'\n';
        buf.push(0xc2);
        let err = validate_utf8_sliced(&buf).unwrap_err();
        let std_err = std::str::from_utf8(&buf).unwrap_err();
        assert_eq!(err.valid_up_to(), std_err.valid_up_to());
        assert_eq!(err.error_len(), std_err.error_len());
        assert_eq!(err.valid_up_to(), buf.len() - 1);
        assert_eq!(err.error_len(), None);
    }

    #[test]
    fn sliced_utf8_lead_plus_non_continuation_is_not_truncated() {
        // A multi-byte lead followed by a non-continuation is an invalid
        // sequence in the middle of the buffer. `error_len` is `Some`
        // (resume after the lead). `None` would mean the bytes ran out.
        let mut buf = b"head\n".to_vec();
        let at = buf.len();
        buf.push(0xC2);
        buf.extend_from_slice(b"A tail\n");
        let err = validate_utf8_sliced(&buf).unwrap_err();
        let std_err = std::str::from_utf8(&buf).unwrap_err();
        assert_eq!(err.valid_up_to(), at);
        assert_eq!(err.valid_up_to(), std_err.valid_up_to());
        assert_eq!(err.error_len(), Some(1));
        assert_eq!(err.error_len(), std_err.error_len());

        // Same shape for a three-byte lead whose second byte is a
        // continuation and whose third is not. The invalid sequence is
        // two bytes; stopping on those two still looks truncated.
        let mut buf = b"head\n".to_vec();
        let at = buf.len();
        buf.extend_from_slice(&[0xE1, 0x80, b'Z']);
        buf.extend_from_slice(b" tail\n");
        let err = validate_utf8_sliced(&buf).unwrap_err();
        let std_err = std::str::from_utf8(&buf).unwrap_err();
        assert_eq!(err.valid_up_to(), at);
        assert_eq!(err.valid_up_to(), std_err.valid_up_to());
        assert_eq!(err.error_len(), Some(2));
        assert_eq!(err.error_len(), std_err.error_len());
    }

    #[test]
    fn utf8_slice_target_stays_inside_huge_buffers() {
        let len = 20 << 20;
        let n = (len / UTF8_SLICE_MIN).max(1);
        for k in 1..n {
            assert_eq!(utf8_slice_target(len, k, n), k * len / n);
            assert!(utf8_slice_target(len, k, n) <= len);
        }
        let len = usize::MAX - 1024;
        let n_slices = (len / UTF8_SLICE_MIN).max(2);
        let k = n_slices - 1;
        assert!(k.checked_mul(len).is_none());
        let target = utf8_slice_target(len, k, n_slices);
        assert!(target <= len);
        let expected = (k as u128 * len as u128 / n_slices as u128) as usize;
        assert_eq!(target, expected);
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

    #[test]
    fn edge_hash_matches_file_fingerprint() {
        let dir = std::env::temp_dir().join(format!("rcidx-edge-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("t.con");
        let text = fixture(40);
        assert!(text.len() > (EDGE as usize) * 2);
        std::fs::write(&con, &text).unwrap();
        let fp = fingerprint(&con).unwrap();
        assert_eq!(fp.size, text.len() as u64);
        assert_eq!(fp.edges, edge_hash(text.as_bytes()));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn same_length_middle_change_is_not_published() {
        let dir = std::env::temp_dir().join(format!("rcidx-stale-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("t.con");
        let text = fixture(40);
        std::fs::write(&con, &text).unwrap();
        let idx = FrameIndex::scan(&text).unwrap();
        let mut changed = text.as_bytes().to_vec();
        let at = (EDGE as usize..changed.len() - EDGE as usize)
            .find(|&i| changed[i].is_ascii_alphabetic())
            .expect("middle of the file has a letter");
        changed[at] = if changed[at] == b'A' { b'B' } else { b'A' };
        assert_eq!(edge_hash(text.as_bytes()), edge_hash(&changed));
        assert_ne!(text.as_bytes(), changed.as_slice());
        std::fs::write(&con, &changed).unwrap();
        let err = write_sidecar_for_text(&con, &text, &idx).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidInput);
        assert_eq!(read_sidecar(&con).unwrap(), None);
        assert_eq!(
            load_or_build(&con, &text, true).unwrap().offsets,
            idx.offsets
        );
        assert_eq!(read_sidecar(&con).unwrap(), None);
        let new_text = std::str::from_utf8(&changed).unwrap();
        let published = load_or_build(&con, new_text, true).unwrap();
        assert_eq!(published, FrameIndex::scan(new_text).unwrap());
        assert_eq!(read_sidecar(&con).unwrap(), Some(published));
        let _ = std::fs::remove_dir_all(&dir);
    }

    fn rechecksum(bytes: &mut [u8]) {
        let body_len = bytes.len() - 8;
        let sum = fnv1a(FNV_OFFSET, &bytes[..body_len]);
        bytes[body_len..].copy_from_slice(&sum.to_le_bytes());
    }

    #[test]
    fn checksum_valid_short_table_is_rejected() {
        let text = fixture(2);
        let idx = FrameIndex::scan(&text).unwrap();
        let fp = Fingerprint {
            size: text.len() as u64,
            mtime_ns: 0,
            edges: edge_hash(text.as_bytes()),
        };
        let mut bytes = encode(fp, &idx);
        let n = (idx.len() as u64).saturating_add(1);
        bytes[40..48].copy_from_slice(&n.to_le_bytes());
        rechecksum(&mut bytes);
        assert_eq!(decode(&bytes, fp), None);
    }

    #[test]
    fn wrapping_frame_count_is_rejected() {
        let text = fixture(2);
        let idx = FrameIndex::scan(&text).unwrap();
        let fp = Fingerprint {
            size: text.len() as u64,
            mtime_ns: 0,
            edges: edge_hash(text.as_bytes()),
        };
        let mut bytes = encode(fp, &idx);
        let payload = bytes.len() - 8 - HEADER_LEN;
        let n = (1usize << (usize::BITS - 3)).wrapping_add(payload / 8);
        assert_eq!(8usize.wrapping_mul(n), payload);
        assert!(n > idx.len());
        bytes[40..48].copy_from_slice(&(n as u64).to_le_bytes());
        rechecksum(&mut bytes);
        assert_eq!(decode(&bytes, fp), None);
    }
}
