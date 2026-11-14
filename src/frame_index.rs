//! Frame offset index and its checked `.rcidx` sidecar.
//!
//! The sidecar stores the byte offset of every frame start in an
//! uncompressed CON file, so later reads skip the offset scan.
//! A sidecar is only used when its checksum is intact, its stored size
//! matches the data, and its offsets are the ones a scan finds: the frame
//! skip from each offset must end at the next. A table that passes is the
//! scan of the data however old the sidecar is, so neither the mtime nor
//! a content hash is compared. The check runs per frame, in parallel with
//! the `parallel` feature, and a table that fails it is rebuilt.
//!
//! Layout (all integers little-endian):
//!
//! | bytes | field                                  |
//! |-------|----------------------------------------|
//! | 8     | magic `RCIDX\0\0\0`                    |
//! | 4     | format version (2)                     |
//! | 4     | reserved (0)                           |
//! | 8     | data file size in bytes                |
//! | 8     | content hash of every data byte, written for earlier version 2 readers and not read here |
//! | 8     | frame count `n`                        |
//! | 8 n   | frame start offsets                    |
//! | 8     | FNV-1a 64 of every preceding byte      |

use std::io::{self, Write};
use std::path::{Path, PathBuf};

use crate::error::ParseError;
use crate::iterators::ConFrameIterator;

const MAGIC: &[u8; 8] = b"RCIDX\0\0\0";
const VERSION: u32 = 2;
const HEADER_LEN: usize = 8 + 4 + 4 + 8 + 8 + 8;
const COUNT_AT: usize = HEADER_LEN - 8;

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
        if no_frame_at(text, start) {
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

/// True when the scan ends at `pos`: nothing or only whitespace follows.
fn no_frame_at(text: &str, pos: usize) -> bool {
    crate::iterators::no_frame_at(text.as_bytes(), pos)
}

/// True when `offsets` is exactly what [`frame_start_offsets_checked`]
/// returns for `text`.
///
/// The first offset must be 0, and the skip from each offset must end at
/// the next one, or at the end of the data for the last. A skip reads no
/// state from earlier frames, so the frames are checked independently.
/// The skip gets the next offset as a hint, which changes only its speed.
fn offsets_match_scan(text: &str, offsets: &[u64]) -> bool {
    let Some(&first) = offsets.first() else {
        return no_frame_at(text, 0);
    };
    let frame_ok = |i: usize| {
        let start = offsets[i] as usize;
        // Also starts the skip on a character boundary.
        let starts_line = start == 0 || text.as_bytes().get(start - 1) == Some(&b'\n');
        if !starts_line || no_frame_at(text, start) {
            return false;
        }
        let end = offsets.get(i + 1).map_or(text.len(), |&o| o as usize);
        let mut skip = ConFrameIterator::starting_at(text, start);
        if !matches!(skip.forward_fast_to(Some(end)), Some(Ok(()))) {
            return false;
        }
        match offsets.get(i + 1) {
            Some(&next) => skip.byte_pos() as u64 == next,
            None => no_frame_at(text, skip.byte_pos()),
        }
    };
    if first != 0 {
        return false;
    }
    #[cfg(feature = "parallel")]
    {
        use rayon::prelude::*;
        (0..offsets.len()).into_par_iter().all(frame_ok)
    }
    #[cfg(not(feature = "parallel"))]
    {
        (0..offsets.len()).all(frame_ok)
    }
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
    std::str::from_utf8(&bytes[..end])?;
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
    let windows: Vec<&[usize]> = cuts.windows(2).collect();
    #[cfg(feature = "parallel")]
    {
        use rayon::prelude::*;
        // One window has no second slice to run beside it. `par_iter`
        // would still start the global pool.
        if windows.len() >= 2 {
            windows.par_iter().try_for_each(|w| check(w))?;
        } else {
            for w in &windows {
                check(w)?;
            }
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        for w in &windows {
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

/// Bytes per block of [`content_hash`]. Blocks are hashed on their own and
/// folded in order, so the value does not depend on the thread count.
pub(crate) const HASH_BLOCK: usize = 1 << 20;

/// Eight independent multiply and rotate lanes over 64-byte strides.
///
/// Each step is a bijection of its lane for a fixed word, so changing any
/// one word of a block always changes that lane.
pub(crate) fn block_hash(block: &[u8]) -> u64 {
    let mut cursor = BlockCursor::new();
    cursor.feed(block);
    cursor.finish()
}

/// A [`block_hash`] that can stop at a rank boundary and continue on the
/// next rank. The finished value matches hashing the concatenated bytes.
pub(crate) struct BlockCursor {
    lanes: [u64; 8],
    pending: [u8; 64],
    pending_len: usize,
}

impl BlockCursor {
    pub(crate) fn new() -> Self {
        Self {
            lanes: std::array::from_fn(|k| FNV_OFFSET ^ k as u64),
            pending: [0; 64],
            pending_len: 0,
        }
    }

    pub(crate) fn feed(&mut self, mut data: &[u8]) {
        const K: u64 = 0x9e37_79b9_7f4a_7c15;
        if self.pending_len > 0 {
            let need = 64 - self.pending_len;
            let n = need.min(data.len());
            self.pending[self.pending_len..self.pending_len + n].copy_from_slice(&data[..n]);
            self.pending_len += n;
            data = &data[n..];
            if self.pending_len == 64 {
                Self::mix(&mut self.lanes, &self.pending, K);
                self.pending_len = 0;
            }
        }
        if data.is_empty() {
            // A short feed only filled `pending`. Falling through would
            // reset `pending_len` from an empty remainder and drop those
            // bytes on the next rank.
            return;
        }
        let (strides, rest) = data.as_chunks::<64>();
        for stride in strides {
            Self::mix(&mut self.lanes, stride, K);
        }
        self.pending[..rest.len()].copy_from_slice(rest);
        self.pending_len = rest.len();
    }

    fn mix(lanes: &mut [u64; 8], stride: &[u8], k: u64) {
        for (lane, word) in lanes.iter_mut().zip(stride.as_chunks::<8>().0) {
            *lane = (*lane ^ u64::from_le_bytes(*word))
                .wrapping_mul(k)
                .rotate_left(31);
        }
    }

    pub(crate) fn finish(&self) -> u64 {
        let tail = fnv1a(FNV_OFFSET, &self.pending[..self.pending_len]);
        self.lanes
            .iter()
            .fold(tail, |hash, lane| fnv1a(hash, &lane.to_le_bytes()))
    }

    /// Snapshot the lanes so the next rank can continue a partial block.
    pub(crate) fn to_bytes(&self) -> [u8; 129] {
        let mut out = [0u8; 129];
        for (index, lane) in self.lanes.iter().enumerate() {
            out[index * 8..index * 8 + 8].copy_from_slice(&lane.to_le_bytes());
        }
        out[64..128].copy_from_slice(&self.pending);
        out[128] = self.pending_len as u8;
        out
    }

    /// Restore a snapshot from the previous rank's partial block.
    pub(crate) fn from_bytes(bytes: &[u8]) -> Self {
        let mut lanes = [0u64; 8];
        for (index, lane) in lanes.iter_mut().enumerate() {
            let mut word = [0u8; 8];
            word.copy_from_slice(&bytes[index * 8..index * 8 + 8]);
            *lane = u64::from_le_bytes(word);
        }
        let mut pending = [0u8; 64];
        pending.copy_from_slice(&bytes[64..128]);
        Self {
            lanes,
            pending,
            pending_len: bytes[128] as usize,
        }
    }
}

/// Hash of every byte: [`block_hash`] per [`HASH_BLOCK`], folded with the
/// length by FNV-1a. Not cryptographic; it detects edits, not attacks.
pub fn content_hash(bytes: &[u8]) -> u64 {
    #[cfg(feature = "parallel")]
    let blocks: Vec<u64> = {
        use rayon::prelude::*;
        bytes.par_chunks(HASH_BLOCK).map(block_hash).collect()
    };
    #[cfg(not(feature = "parallel"))]
    let blocks: Vec<u64> = bytes.chunks(HASH_BLOCK).map(block_hash).collect();
    fold_block_hashes(bytes.len() as u64, &blocks)
}

/// Fold per-block hashes in file order. `blocks` is one hash per
/// [`HASH_BLOCK`], and the last block may be short.
pub(crate) fn fold_block_hashes(total: u64, blocks: &[u64]) -> u64 {
    let seed = fnv1a(FNV_OFFSET, &total.to_le_bytes());
    blocks.iter().fold(seed, |h, b| fnv1a(h, &b.to_le_bytes()))
}

/// Hashes one rank can finish without a neighbour's cursor.
pub(crate) struct LocalReady {
    pub hashes: Vec<(u64, u64)>,
    pub tail: Option<[u8; 129]>,
}

pub(crate) enum Lead {
    Hash((u64, u64)),
    Forward([u8; 129]),
}

/// Full blocks owned by the slice at `start`, plus a cursor when a
/// partial block continues on a later rank.
pub(crate) fn local_ready(start: u64, bytes: &[u8], total: u64) -> LocalReady {
    let block = HASH_BLOCK as u64;
    let end = start + bytes.len() as u64;
    let mut hashes = Vec::new();
    let mut pos = if start % block == 0 {
        start
    } else {
        (start / block + 1) * block
    };
    if pos > end {
        pos = end;
    }
    let mut local = (pos - start) as usize;
    while pos < end {
        let take_end = (pos + block).min(end);
        let full = take_end - pos == block;
        let owned_tail = take_end == total;
        if !(full || owned_tail) {
            break;
        }
        let n = (take_end - pos) as usize;
        hashes.push((pos / block, block_hash(&bytes[local..local + n])));
        local += n;
        pos = take_end;
    }
    let tail = if pos < end && pos % block == 0 && pos != total {
        let mut cursor = BlockCursor::new();
        cursor.feed(&bytes[(pos - start) as usize..]);
        Some(cursor.to_bytes())
    } else {
        None
    };
    LocalReady { hashes, tail }
}

/// Continue `cursor` across this rank's leading partial block.
pub(crate) fn finish_lead(start: u64, bytes: &[u8], total: u64, cursor_bytes: [u8; 129]) -> Lead {
    let block = HASH_BLOCK as u64;
    let end = start + bytes.len() as u64;
    let block_end = (start / block + 1) * block;
    let lead_end = block_end.min(end);
    let n = (lead_end - start) as usize;
    let mut cursor = BlockCursor::from_bytes(&cursor_bytes);
    cursor.feed(&bytes[..n]);
    if end >= block_end || end == total {
        Lead::Hash((start / block, cursor.finish()))
    } else {
        Lead::Forward(cursor.to_bytes())
    }
}

/// Hash of ordered rank slices, including empty ranks and splits inside a
/// block. This is the gather used by a ranked write, with no MPI. It
/// matches [`content_hash`] of the concatenation.
pub fn ranked_content_hash(parts: &[&[u8]]) -> u64 {
    let total: u64 = parts.iter().map(|part| part.len() as u64).sum();
    if total == 0 {
        return fold_block_hashes(0, &[]);
    }
    let mut blocks = vec![0u64; total.div_ceil(HASH_BLOCK as u64) as usize];
    let mut pending: Option<[u8; 129]> = None;
    let mut offset = 0u64;
    for part in parts {
        if part.is_empty() {
            continue;
        }
        let ready = local_ready(offset, part, total);
        if let Some(cursor) = pending.take() {
            match finish_lead(offset, part, total, cursor) {
                Lead::Hash((index, hash)) => blocks[index as usize] = hash,
                Lead::Forward(next) => pending = Some(next),
            }
        }
        for (index, hash) in ready.hashes {
            blocks[index as usize] = hash;
        }
        if let Some(tail) = ready.tail {
            pending = Some(tail);
        }
        offset += part.len() as u64;
    }
    fold_block_hashes(total, &blocks)
}

/// Block hashes this slice can finish, plus the bytes that share a
/// block with a neighbour. `offset` is the slice's position in the file.
#[cfg(any(test, feature = "mpi"))]
pub(crate) struct SliceParts {
    pub hashed: Vec<(u64, u64)>,
    pub fragments: Vec<(u64, Vec<u8>)>,
}

#[cfg(any(test, feature = "mpi"))]
pub(crate) fn slice_block_parts(offset: u64, data: &[u8]) -> SliceParts {
    let mut hashed = Vec::new();
    let mut fragments = Vec::new();
    if data.is_empty() {
        return SliceParts { hashed, fragments };
    }
    let block = HASH_BLOCK as u64;
    let end = offset + data.len() as u64;
    let mut pos = offset;
    while pos < end {
        let block_start = (pos / block) * block;
        let block_limit = block_start + block;
        let take_end = block_limit.min(end);
        let local = (pos - offset) as usize;
        let n = (take_end - pos) as usize;
        let chunk = &data[local..local + n];
        if pos == block_start && take_end == block_limit {
            hashed.push((pos / block, block_hash(chunk)));
        } else {
            fragments.push((pos, chunk.to_vec()));
        }
        pos = take_end;
    }
    SliceParts { hashed, fragments }
}

/// Content hash of a file split into ordered pieces. The pieces may
/// start mid-block. The result matches [`content_hash`] of the
/// concatenation.
#[cfg(test)]
pub(crate) fn fold_slice_parts(total: u64, parts: &[SliceParts]) -> u64 {
    if total == 0 {
        return fold_block_hashes(0, &[]);
    }
    let nblocks = total.div_ceil(HASH_BLOCK as u64) as usize;
    let mut hashes = vec![0u64; nblocks];
    let mut frags: Vec<(u64, &[u8])> = Vec::new();
    for part in parts {
        for &(idx, hash) in &part.hashed {
            hashes[idx as usize] = hash;
        }
        for (off, bytes) in &part.fragments {
            frags.push((*off, bytes.as_slice()));
        }
    }
    frags.sort_by_key(|(off, _)| *off);
    let mut i = 0;
    while i < frags.len() {
        let block = (frags[i].0 / HASH_BLOCK as u64) as usize;
        let mut buf = Vec::new();
        while i < frags.len() && (frags[i].0 / HASH_BLOCK as u64) as usize == block {
            buf.extend_from_slice(frags[i].1);
            i += 1;
        }
        hashes[block] = block_hash(&buf);
    }
    fold_block_hashes(total, &hashes)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Fingerprint {
    size: u64,
    content: u64,
}

impl Fingerprint {
    fn of(data: &[u8]) -> Self {
        Fingerprint {
            size: data.len() as u64,
            content: content_hash(data),
        }
    }
}

/// Call `f` on the bytes now at `path`.
fn with_mapped<T>(path: &Path, f: impl FnOnce(&[u8]) -> T) -> io::Result<T> {
    let file = std::fs::File::open(path)?;
    if file.metadata()?.len() == 0 {
        return Ok(f(&[]));
    }
    // SAFETY: as for every mapped reader in this crate, the file must not
    // be truncated or rewritten while the map is alive.
    let map = unsafe { memmap2::Mmap::map(&file)? };
    Ok(f(&map))
}

fn fingerprint(path: &Path) -> io::Result<Fingerprint> {
    with_mapped(path, Fingerprint::of)
}

fn encode(fp: Fingerprint, idx: &FrameIndex) -> Vec<u8> {
    let mut out = Vec::with_capacity(HEADER_LEN + 8 * idx.offsets.len() + 8);
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&VERSION.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes());
    out.extend_from_slice(&fp.size.to_le_bytes());
    out.extend_from_slice(&fp.content.to_le_bytes());
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

/// Decode a sidecar and check it against `text`; `None` means stale or
/// corrupt. The stored size is a fast reject and the content hash is not
/// read, since [`offsets_match_scan`] alone decides the table.
fn decode(bytes: &[u8], text: &str) -> Option<FrameIndex> {
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
    let size = u64_at(bytes, 16);
    if size != text.len() as u64 {
        return None;
    }
    let n = usize::try_from(u64_at(bytes, COUNT_AT)).ok()?;
    let table = n.checked_mul(8)?;
    let expected = HEADER_LEN.checked_add(table)?;
    if body.len() != expected {
        return None;
    }
    let offsets: Vec<u64> = (0..n).map(|i| u64_at(bytes, HEADER_LEN + i * 8)).collect();
    let ordered = offsets.windows(2).all(|w| w[0] < w[1]);
    if !ordered || offsets.last().is_some_and(|&o| o >= size) {
        return None;
    }
    // A checksum cannot catch a table that was written whole but wrong.
    // Readers also slice the text here without a new UTF-8 check.
    if !offsets_match_scan(text, &offsets) {
        return None;
    }
    Some(FrameIndex {
        offsets,
        data_len: size,
    })
}

/// Read the sidecar for `path` if it exists and matches the data file.
pub fn read_sidecar(path: &Path) -> io::Result<Option<FrameIndex>> {
    let bytes = match std::fs::read(sidecar_path(path)) {
        Ok(b) => b,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e),
    };
    with_mapped(path, |data| {
        decode(&bytes, validate_utf8_sliced(data).ok()?)
    })
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
/// The size and content hash describe `path` as it exists at this call.
/// Scanning an earlier buffer and then calling this can store them with
/// stale offsets. Readers then reject the table, since it is not a scan
/// of the data, and rescan.
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

/// Write the sidecar from a content hash the caller already has.
///
/// [`write_sidecar`] reads `path` to hash it. A ranked write already
/// holds those bytes, so reading the file again is a serial pass over
/// the whole trajectory. `content` is the hash of the bytes just written,
/// and `idx.data_len` is their length.
#[cfg(any(test, feature = "mpi"))]
pub(crate) fn write_sidecar_known(path: &Path, idx: &FrameIndex, content: u64) -> io::Result<()> {
    let fp = Fingerprint {
        size: idx.data_len,
        content,
    };
    write_encoded(path, &encode(fp, idx))
}

/// Return a trusted index for `text` (the contents of `path`).
///
/// Uses the sidecar when its table is the scan of `text`; otherwise scans
/// and, when `write_back` is set, refreshes the sidecar. The data file is
/// not read again, and the hash for a write is taken from `text`.
/// Write errors are ignored, so read-only directories still work.
pub fn load_or_build(path: &Path, text: &str, write_back: bool) -> Result<FrameIndex, ParseError> {
    if let Ok(bytes) = std::fs::read(sidecar_path(path))
        && let Some(idx) = decode(&bytes, text)
    {
        return Ok(idx);
    }
    let idx = FrameIndex::scan(text)?;
    if write_back {
        let fp = Fingerprint::of(text.as_bytes());
        let _ = write_encoded(path, &encode(fp, &idx));
    }
    Ok(idx)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resumed_block_hash_matches_one_shot() {
        let data: Vec<u8> = (0..200_000).map(|index| (index % 251) as u8).collect();
        for split in [0usize, 1, 63, 64, 65, 1000, 199_999] {
            let mut cursor = BlockCursor::new();
            cursor.feed(&data[..split]);
            cursor.feed(&data[split..]);
            assert_eq!(cursor.finish(), block_hash(&data), "split {split}");
            let mut cursor = BlockCursor::new();
            cursor.feed(&data[..split]);
            let saved = cursor.to_bytes();
            let mut cursor = BlockCursor::from_bytes(&saved);
            let mid = split + (data.len() - split) / 3;
            cursor.feed(&data[split..mid.max(split)]);
            let saved = cursor.to_bytes();
            let mut cursor = BlockCursor::from_bytes(&saved);
            cursor.feed(&data[mid.max(split)..]);
            assert_eq!(
                cursor.finish(),
                block_hash(&data),
                "serialized split {split}"
            );
        }
    }

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
        // Change the data file: the size check must reject the old sidecar.
        write_sidecar(&con, &idx).unwrap();
        let text2 = fixture(6);
        std::fs::write(&con, &text2).unwrap();
        assert_eq!(read_sidecar(&con).unwrap(), None);
        assert_eq!(load_or_build(&con, &text2, true).unwrap().len(), 6);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn content_hash_matches_file_fingerprint() {
        let dir = std::env::temp_dir().join(format!("rcidx-hash-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("t.con");
        for text in [String::new(), fixture(40)] {
            std::fs::write(&con, &text).unwrap();
            assert_eq!(fingerprint(&con).unwrap(), Fingerprint::of(text.as_bytes()));
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn content_hash_sees_every_byte_and_block_order() {
        let base: Vec<u8> = (0..HASH_BLOCK * 3 + 77).map(|i| (i % 251) as u8).collect();
        let h = content_hash(&base);
        for at in [
            0,
            63,
            64,
            HASH_BLOCK - 1,
            HASH_BLOCK,
            2 * HASH_BLOCK + 5,
            base.len() - 1,
        ] {
            let mut b = base.clone();
            b[at] ^= 0x20;
            assert_ne!(content_hash(&b), h, "byte {at}");
        }
        let mut swapped = base.clone();
        swapped[..2 * HASH_BLOCK].rotate_left(HASH_BLOCK);
        assert_ne!(content_hash(&swapped), h);
        assert_ne!(content_hash(&base[..base.len() - 1]), h);
        let serial = base.chunks(HASH_BLOCK).map(block_hash).fold(
            fnv1a(FNV_OFFSET, &(base.len() as u64).to_le_bytes()),
            |acc, b| fnv1a(acc, &b.to_le_bytes()),
        );
        assert_eq!(serial, h);
    }

    #[test]
    fn split_blocks_match_the_whole_buffer() {
        let data: Vec<u8> = (0..HASH_BLOCK * 2 + 100).map(|i| (i % 251) as u8).collect();
        let whole = content_hash(&data);
        let cuts = [
            vec![0, data.len()],
            vec![0, 1, data.len()],
            vec![
                0,
                10,
                HASH_BLOCK - 3,
                HASH_BLOCK,
                HASH_BLOCK + 1,
                HASH_BLOCK + 50,
                data.len() - 1,
                data.len(),
            ],
            vec![0, HASH_BLOCK, 2 * HASH_BLOCK, data.len()],
        ];
        for cut in cuts {
            let parts: Vec<super::SliceParts> = cut
                .windows(2)
                .map(|span| super::slice_block_parts(span[0] as u64, &data[span[0]..span[1]]))
                .collect();
            assert_eq!(
                super::fold_slice_parts(data.len() as u64, &parts),
                whole,
                "{cut:?}"
            );
        }
        assert_eq!(super::fold_slice_parts(0, &[]), content_hash(&[]));
    }

    proptest::proptest! {
        #![proptest_config(proptest::prelude::ProptestConfig {
            cases: 48,
            failure_persistence: None,
            ..proptest::prelude::ProptestConfig::default()
        })]
        #[test]
        fn folded_rank_slices_match_the_full_file_hash(
            bytes in proptest::collection::vec(proptest::prelude::any::<u8>(), 0..2048),
            raw_cuts in proptest::collection::vec(proptest::prelude::any::<u16>(), 0..10),
        ) {
            let mut points = vec![0usize];
            let n = bytes.len();
            for cut in raw_cuts {
                points.push((cut as usize) % (n + 1));
            }
            points.push(n);
            points.sort_unstable();
            let parts: Vec<super::SliceParts> = points
                .windows(2)
                .map(|span| super::slice_block_parts(span[0] as u64, &bytes[span[0]..span[1]]))
                .collect();
            proptest::prop_assert_eq!(
                super::fold_slice_parts(n as u64, &parts),
                content_hash(&bytes)
            );
        }
    }

    /// Cuts that land inside a block and on a block boundary, including
    /// an empty rank, still fold to the hash of the whole buffer.
    #[test]
    fn folded_blocks_match_across_an_empty_rank() {
        let data: Vec<u8> = (0..HASH_BLOCK * 2 + 80).map(|i| (i % 251) as u8).collect();
        let whole = content_hash(&data);
        let mut cuts = vec![
            0usize,
            1,
            7,
            HASH_BLOCK - 1,
            HASH_BLOCK,
            HASH_BLOCK,
            HASH_BLOCK + 3,
        ];
        cuts.push(data.len());
        let parts: Vec<super::SliceParts> = cuts
            .windows(2)
            .map(|span| super::slice_block_parts(span[0] as u64, &data[span[0]..span[1]]))
            .collect();
        assert_eq!(super::fold_slice_parts(data.len() as u64, &parts), whole);
    }

    /// Rank slices, including an empty rank and a one-byte rank, fold to
    /// the hash of the whole buffer. The sidecar written from that hash
    /// matches a sidecar fingerprinted from the file.
    #[test]
    fn rank_slices_hash_matches_the_full_file() {
        let data: Vec<u8> = (0..HASH_BLOCK * 2 + 64).map(|i| (i % 251) as u8).collect();
        let whole = content_hash(&data);
        let layouts: [&[usize]; 4] = [
            &[0, data.len()],
            &[0, 1, data.len()],
            &[0, 1, 1, HASH_BLOCK - 1, HASH_BLOCK, data.len()],
            &[
                0,
                3,
                HASH_BLOCK / 2,
                HASH_BLOCK,
                HASH_BLOCK + 7,
                2 * HASH_BLOCK,
                data.len(),
            ],
        ];
        for cuts in layouts {
            let mut parts = Vec::new();
            for span in cuts.windows(2) {
                parts.push(super::slice_block_parts(
                    span[0] as u64,
                    &data[span[0]..span[1]],
                ));
                // An empty rank at this offset contributes nothing.
                parts.push(super::slice_block_parts(span[1] as u64, &[]));
            }
            assert_eq!(
                super::fold_slice_parts(data.len() as u64, &parts),
                whole,
                "cuts {cuts:?}"
            );
        }

        let dir = std::env::temp_dir().join(format!("rcidx-ranks-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("t.con");
        std::fs::write(&path, &data).unwrap();
        let idx = FrameIndex {
            offsets: vec![0],
            data_len: data.len() as u64,
        };
        let mut rank_parts = Vec::new();
        let mid = HASH_BLOCK + 3;
        rank_parts.push(super::slice_block_parts(0, &data[..mid]));
        rank_parts.push(super::slice_block_parts(mid as u64, &[]));
        rank_parts.push(super::slice_block_parts(mid as u64, &data[mid..]));
        let folded = super::fold_slice_parts(data.len() as u64, &rank_parts);
        assert_eq!(folded, whole);
        super::write_sidecar_known(&path, &idx, folded).unwrap();
        let from_ranks = std::fs::read(sidecar_path(&path)).unwrap();
        write_sidecar(&path, &idx).unwrap();
        let from_file = std::fs::read(sidecar_path(&path)).unwrap();
        assert_eq!(from_ranks, from_file);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn known_hash_sidecar_matches_a_file_fingerprint() {
        let dir = std::env::temp_dir().join(format!("rcidx-known-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("t.con");
        let text = fixture(4);
        std::fs::write(&con, &text).unwrap();
        let idx = load_or_build(&con, &text, false).unwrap();
        super::write_sidecar_known(&con, &idx, content_hash(text.as_bytes())).unwrap();
        let known = std::fs::read(sidecar_path(&con)).unwrap();
        write_sidecar(&con, &idx).unwrap();
        let fingerprinted = std::fs::read(sidecar_path(&con)).unwrap();
        assert_eq!(known, fingerprinted);
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Frames parsed from the ranges of `idx`, in order.
    fn frames_via(idx: &FrameIndex, text: &str) -> Vec<crate::types::ConFrame> {
        (0..idx.len())
            .map(|i| {
                let r = idx.range(i).unwrap();
                ConFrameIterator::new(&text[r]).next().unwrap().unwrap()
            })
            .collect()
    }

    fn scanned_frames(text: &str) -> Vec<crate::types::ConFrame> {
        ConFrameIterator::new(text)
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
    }

    /// Publish a sidecar scanned from `old`, then put `new` (same length)
    /// on disk and open it with and without write-back.
    fn reopen_after_edit(name: &str, old: &str, new: &str) -> Vec<FrameIndex> {
        assert_eq!(old.len(), new.len());
        let dir = std::env::temp_dir().join(format!("rcidx-{name}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("t.con");
        std::fs::write(&con, old).unwrap();
        load_or_build(&con, old, true).unwrap();
        assert!(read_sidecar(&con).unwrap().is_some());
        std::fs::write(&con, new).unwrap();
        let opened = vec![
            load_or_build(&con, new, false).unwrap(),
            load_or_build(&con, new, true).unwrap(),
            load_or_build(&con, new, true).unwrap(),
        ];
        let _ = std::fs::remove_dir_all(&dir);
        opened
    }

    #[test]
    fn same_length_middle_change_reads_match_a_scan() {
        let text = fixture(40);
        let mut changed = text.as_bytes().to_vec();
        let at = (4096..changed.len() - 4096)
            .find(|&i| changed[i].is_ascii_alphabetic())
            .expect("middle of the file has a letter");
        changed[at] = if changed[at] == b'A' { b'B' } else { b'A' };
        let new_text = std::str::from_utf8(&changed).unwrap();
        let scan = FrameIndex::scan(new_text).unwrap();
        let expected = scanned_frames(new_text);
        assert_ne!(expected, scanned_frames(&text));
        for idx in reopen_after_edit("letter", &text, new_text) {
            assert_eq!(idx, scan);
            assert_eq!(frames_via(&idx, new_text), expected);
        }
    }

    #[test]
    fn same_length_change_that_moves_a_boundary_is_rescanned() {
        let text = fixture(40);
        let old = FrameIndex::scan(&text).unwrap();
        let frame = |i: usize| &text[old.range(i).unwrap()];
        // Move the first H row of frame 21 to the end of frame 20 and fix
        // both H counts. The length and the line starts stay the same.
        let row_at = frame(21).find("Coordinates of Component 2\n").unwrap()
            + "Coordinates of Component 2\n".len();
        let row_len = frame(21)[row_at..].find('\n').unwrap() + 1;
        let row = &frame(21)[row_at..row_at + row_len];
        let mut moved = String::new();
        for i in 0..old.len() {
            let f = frame(i);
            match i {
                20 => {
                    moved.push_str(&f.replacen("\n2 2\n", "\n2 3\n", 1));
                    moved.push_str(row);
                }
                21 => {
                    let f = f.replacen("\n2 2\n", "\n2 1\n", 1);
                    let at = f.find(row).unwrap();
                    moved.push_str(&f[..at]);
                    moved.push_str(&f[at + row_len..]);
                }
                _ => moved.push_str(f),
            }
        }
        let scan = FrameIndex::scan(&moved).unwrap();
        assert_eq!(scan.len(), old.len());
        assert_ne!(scan, old);
        assert!(
            old.offsets
                .iter()
                .all(|&o| o == 0 || moved.as_bytes()[o as usize - 1] == b'\n')
        );
        assert!(!offsets_match_scan(&moved, &old.offsets));
        let fp = Fingerprint::of(moved.as_bytes());
        assert_eq!(decode(&encode(fp, &old), &moved), None);
        let expected = scanned_frames(&moved);
        assert_eq!(expected[20].atom_data.len(), 5);
        assert_eq!(expected[21].atom_data.len(), 3);
        for idx in reopen_after_edit("moved", &text, &moved) {
            assert_eq!(idx, scan);
            assert_eq!(frames_via(&idx, &moved), expected);
        }
    }

    #[test]
    fn only_the_scanned_table_matches() {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/resources/test");
        let mut checked = 0;
        for entry in std::fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            let Ok(one) = std::fs::read_to_string(&path) else {
                continue;
            };
            let text = one.repeat(3);
            let Ok(scan) = frame_start_offsets_checked(&text) else {
                continue;
            };
            let good: Vec<u64> = scan.iter().map(|&o| o as u64).collect();
            assert!(offsets_match_scan(&text, &good), "{}", path.display());
            for drop in 0..good.len() {
                let mut t = good.clone();
                t.remove(drop);
                assert!(
                    !offsets_match_scan(&text, &t),
                    "{} drop {drop}",
                    path.display()
                );
            }
            let mut longer = good.clone();
            longer.push(text.len() as u64);
            assert!(!offsets_match_scan(&text, &longer), "{}", path.display());
            checked += 1;
        }
        assert!(checked >= 10, "{checked} fixtures");
        assert!(offsets_match_scan(" \n\n", &[]));
        assert!(!offsets_match_scan(&fixture(1), &[]));
    }

    #[test]
    fn end_hint_never_changes_the_skip() {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/resources/test");
        let mut checked = 0;
        for entry in std::fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            let Ok(one) = std::fs::read_to_string(&path) else {
                continue;
            };
            let text = one.repeat(3);
            let line_starts: Vec<usize> = std::iter::once(0)
                .chain(text.match_indices('\n').map(|(i, _)| i + 1))
                .collect();
            let mut starts = crate::iterators::frame_start_offsets(&text);
            starts.extend(line_starts.iter().copied().take(40));
            starts.retain(|&s| s < text.len());
            for start in starts {
                let mut plain = ConFrameIterator::starting_at(&text, start);
                let want = format!("{:?}", plain.forward_fast());
                let end = plain.byte_pos();
                let mut hints = vec![None, Some(0), Some(text.len() + 1)];
                hints.extend([end.saturating_sub(1), end + 1].map(Some));
                hints.extend(line_starts.iter().map(|&s| Some(s)));
                for &hint in &hints {
                    let mut hinted = ConFrameIterator::starting_at(&text, start);
                    let got = format!("{:?}", hinted.forward_fast_to(hint));
                    assert_eq!(got, want, "{} at {start}, hint {hint:?}", path.display());
                    assert_eq!(hinted.byte_pos(), plain.byte_pos());
                }
            }
            checked += 1;
        }
        assert!(checked >= 10, "{checked} fixtures");
    }

    #[test]
    fn version_1_sidecar_is_rebuilt() {
        let text = fixture(2);
        let idx = FrameIndex::scan(&text).unwrap();
        let fp = Fingerprint::of(text.as_bytes());
        let mut bytes = encode(fp, &idx);
        assert_eq!(decode(&bytes, &text), Some(idx.clone()));
        bytes[8..12].copy_from_slice(&1u32.to_le_bytes());
        rechecksum(&mut bytes);
        assert_eq!(decode(&bytes, &text), None);
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
        let fp = Fingerprint::of(text.as_bytes());
        let mut bytes = encode(fp, &idx);
        let n = (idx.len() as u64).saturating_add(1);
        bytes[COUNT_AT..COUNT_AT + 8].copy_from_slice(&n.to_le_bytes());
        rechecksum(&mut bytes);
        assert_eq!(decode(&bytes, &text), None);
    }

    #[test]
    fn wrapping_frame_count_is_rejected() {
        let text = fixture(2);
        let idx = FrameIndex::scan(&text).unwrap();
        let fp = Fingerprint::of(text.as_bytes());
        let mut bytes = encode(fp, &idx);
        let payload = bytes.len() - 8 - HEADER_LEN;
        let n = (1usize << (usize::BITS - 3)).wrapping_add(payload / 8);
        assert_eq!(8usize.wrapping_mul(n), payload);
        assert!(n > idx.len());
        bytes[COUNT_AT..COUNT_AT + 8].copy_from_slice(&(n as u64).to_le_bytes());
        rechecksum(&mut bytes);
        assert_eq!(decode(&bytes, &text), None);
    }
}
