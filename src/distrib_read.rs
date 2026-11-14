//! Distributed read: each rank of a caller-supplied communicator parses
//! only its block of frames (see [`crate::distrib::block_range`]).
//!
//! Two modes:
//!
//! - [`ReadMode::Shared`]: every rank opens the same file (shared file
//!   system). When the frames share one byte length, every rank reads
//!   only its own span and rank 0 does not scan the rest of the file.
//!   Otherwise rank 0 loads or builds the checked `.rcidx` index, and
//!   every rank, including rank 0, then reads only its own span. No
//!   frame bytes move between ranks.
//! - [`ReadMode::Scatter`]: rank 0 reads (and decompresses) the file,
//!   scans offsets, and sends each rank its byte range with
//!   `MPI_Scatterv`. Use it for gzip/zstd input or when the file is not
//!   visible on every rank.
//!
//! [`ReadMode::Auto`] picks `Scatter` for compressed input and `Shared`
//! otherwise. Every failure is collective: all ranks return an error.
//!
//! Frame ownership depends only on `(n_frames, n_ranks, rank)`, so the
//! frames of ranks `0..P` concatenated in rank order equal the serial
//! read for every `P`.

use std::path::Path;

use ::mpi::datatype::Partition;
use ::mpi::traits::*;

use crate::compression::{self, Compression, FileContents};
use crate::distrib::{Comm, block_range};
use crate::frame_index::{self, FrameIndex};
use crate::iterators::parse_frames_at_offsets;
use crate::types::ConFrame;

type BoxErr = Box<dyn std::error::Error>;

/// A frame of the collective read failed to parse on another rank.
///
/// The rank that met the failure returns a [`crate::error::LocatedParseError`]
/// for it; every other rank returns this, so callers on all ranks can tell
/// a parse failure from an I/O failure.
#[derive(Debug)]
pub struct PeerParseError;

impl std::fmt::Display for PeerParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("frame parse failed on another rank")
    }
}

impl std::error::Error for PeerParseError {}

/// How frame bytes reach each rank.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum ReadMode {
    Auto = 0,
    Shared = 1,
    Scatter = 2,
}

impl ReadMode {
    pub fn from_i32(v: i32) -> Option<Self> {
        match v {
            0 => Some(Self::Auto),
            1 => Some(Self::Shared),
            2 => Some(Self::Scatter),
            _ => None,
        }
    }
}

/// This rank's share of a distributed read.
#[derive(Debug)]
pub struct RankFrames {
    /// Global index of `frames[0]`.
    pub first: usize,
    /// Total frame count across all ranks.
    pub n_total: usize,
    pub frames: Vec<ConFrame>,
}

fn bytes_of(fc: &FileContents) -> &[u8] {
    match fc {
        FileContents::Owned(s) => s.as_bytes(),
        FileContents::Mapped(m) => m,
    }
}

/// True on every rank iff `ok` is true on every rank.
pub(crate) fn agree(comm: &Comm, ok: bool) -> bool {
    let mut all = 0i32;
    comm.raw().all_reduce_into(
        &i32::from(ok),
        &mut all,
        ::mpi::collective::SystemOperation::min(),
    );
    all == 1
}

fn encode_u64s(v: &[u64]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}

fn decode_u64s(b: &[u8]) -> Vec<u64> {
    b.as_chunks::<8>()
        .0
        .iter()
        .map(|c| u64::from_le_bytes(*c))
        .collect()
}

/// Broadcast `Ok(payload)` or an error message from rank 0.
fn bcast_result(comm: &Comm, r: Result<Vec<u8>, String>) -> Result<Vec<u8>, BoxErr> {
    let msg = match &r {
        Ok(p) => [&[1u8][..], p].concat(),
        Err(e) => [&[0u8][..], e.as_bytes()].concat(),
    };
    let payload = if comm.rank() == 0 { &msg[..] } else { &[][..] };
    let got = comm.bcast_bytes(0, payload);
    match got.split_first() {
        Some((1, rest)) => Ok(rest.to_vec()),
        Some((_, rest)) => Err(String::from_utf8_lossy(rest).into_owned().into()),
        None => Err("empty broadcast".into()),
    }
}

/// Newlines in `bytes[..at]`.
fn newlines_before(bytes: &[u8], at: usize) -> u32 {
    let end = at.min(bytes.len());
    bytes[..end].iter().filter(|&&b| b == b'\n').count() as u32
}

/// Newlines before byte `at` of `path`.
///
/// Shared-mode ranks hold only their own span, so the file line of that
/// span is the newline count of the prefix. Every rank takes the same
/// branch: a failed prefix read is collective, like the span read.
///
/// The count reads at most [`PREFIX_COUNT_CHUNK`] bytes at a time. A
/// `Vec` of length `at` would sit beside the span the rank already
/// parsed, and the last rank's prefix is almost the whole file.
fn line_offset_before(comm: &Comm, path: &Path, at: usize) -> Result<u32, BoxErr> {
    #[cfg(test)]
    note_prefix_call();
    let counted = count_newlines_before(path, at);
    let ok = agree(comm, counted.is_ok());
    match (counted, ok) {
        (Ok(n), true) => Ok(n),
        (Err(e), _) => Err(format!("rank {}: {e}", comm.rank()).into()),
        (Ok(_), false) => Err("file open failed on another rank".into()),
    }
}

/// Newlines in `[0, at)` of `path`, without storing that prefix.
fn count_newlines_before(path: &Path, at: usize) -> Result<u32, String> {
    use std::io::{Read, Seek, SeekFrom};
    if at == 0 {
        return Ok(0);
    }
    let mut file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let len = file.metadata().map_err(|e| e.to_string())?.len() as usize;
    if at > len {
        return Err("byte range is outside the file".into());
    }
    file.seek(SeekFrom::Start(0)).map_err(|e| e.to_string())?;
    let mut left = at;
    let mut count = 0u32;
    let chunk = PREFIX_COUNT_CHUNK.min(at);
    let mut buf = vec![0u8; chunk];
    #[cfg(test)]
    note_prefix_alloc(buf.len());
    while left > 0 {
        let n = chunk.min(left);
        file.read_exact(&mut buf[..n]).map_err(|e| e.to_string())?;
        count = count.saturating_add(newlines_before(&buf, n));
        left -= n;
    }
    Ok(count)
}

/// 1-based file line of a cursor inside a frame whose first line is `frame_line`.
///
/// The iterator counts from 1 inside the frame slice. A cursor that never
/// moved still names the frame's first line, which is what a metadata
/// helper would otherwise pin to line 2 of the file.
fn cursor_file_line(chunk: &str, frame_line: u32) -> u32 {
    let mut iter = crate::iterators::ConFrameIterator::new(chunk);
    let local = match iter.next() {
        Some(Err(_)) => iter.lines.line_no(),
        _ => 0,
    };
    if local == 0 {
        frame_line
    } else {
        frame_line.saturating_add(local - 1)
    }
}

/// Newline count before the block owned by `rank`.
fn block_line_offset(text: &[u8], idx: &FrameIndex, n_ranks: usize, rank: usize) -> u32 {
    let range = block_range(idx.len(), n_ranks, rank);
    if range.is_empty() {
        return 0;
    }
    newlines_before(text, idx.offsets[range.start] as usize)
}

/// Broadcast each rank's block line offset from rank 0, which holds `text`.
fn bcast_line_offsets(comm: &Comm, text: Option<&[u8]>, idx: &FrameIndex) -> Result<u32, BoxErr> {
    let n = comm.size();
    let packed = if comm.rank() == 0 {
        let text = text.ok_or("rank 0 missing file text")?;
        let offsets: Vec<u64> = (0..n)
            .map(|rank| u64::from(block_line_offset(text, idx, n, rank)))
            .collect();
        Ok(encode_u64s(&offsets))
    } else {
        Ok(Vec::new())
    };
    let got = decode_u64s(&bcast_result(comm, packed)?);
    Ok(got.get(comm.rank()).copied().unwrap_or(0) as u32)
}

/// Parse `bytes` (frames starting at `local_offsets`, relative to the
/// slice; the first is global frame `first`) and agree collectively on
/// success. A parse failure keeps its type, global frame index, and
/// 1-based file line. `line_offset` is the number of newlines before
/// `bytes` in the original file.
fn parse_local(
    comm: &Comm,
    bytes: &[u8],
    local_offsets: &[usize],
    line_offset: u32,
    first: usize,
    threads: Option<usize>,
) -> Result<Vec<ConFrame>, BoxErr> {
    let parsed: Result<Vec<ConFrame>, BoxErr> = std::str::from_utf8(bytes)
        .map_err(|e| BoxErr::from(format!("rank {}: {e}", comm.rank())))
        .and_then(|text| {
            parse_frames_at_offsets(text, local_offsets, threads)
                .into_iter()
                .enumerate()
                .map(|(i, r)| {
                    r.map_err(|e| {
                        let start = local_offsets[i];
                        let end = local_offsets.get(i + 1).copied().unwrap_or(text.len());
                        let frame_line = line_offset
                            .saturating_add(1)
                            .saturating_add(newlines_before(text.as_bytes(), start));
                        BoxErr::from(crate::error::LocatedParseError::new(
                            e,
                            cursor_file_line(&text[start..end], frame_line),
                            (first + i) as u64,
                        ))
                    })
                })
                .collect()
        });
    let ok = agree(comm, parsed.is_ok());
    match (parsed, ok) {
        (Ok(f), true) => Ok(f),
        (Err(e), _) => Err(e),
        (Ok(_), false) => Err(Box::new(PeerParseError)),
    }
}

/// Read this rank's block of frames from `path`.
///
/// `threads` sets the rayon pool size within each rank (`None` uses the
/// global pool). In shared mode, equal-length frames skip the full-file
/// index walk. Other files still let rank 0 refresh `path.rcidx` when
/// it is missing or stale, and then every rank reads only its span.
pub fn read_block(
    comm: &Comm,
    path: &Path,
    mode: ReadMode,
    threads: Option<usize>,
) -> Result<RankFrames, BoxErr> {
    // Rank 0 decides the mode so every rank takes the same branch.
    let decided = if comm.rank() == 0 {
        let m = match mode {
            ReadMode::Auto => match sniff(path) {
                Ok(Compression::None) => Ok(ReadMode::Shared),
                Ok(_) => Ok(ReadMode::Scatter),
                Err(e) => Err(e.to_string()),
            },
            m => Ok(m),
        };
        m.map(|m| vec![m as u8])
    } else {
        Ok(Vec::new())
    };
    let mode = match bcast_result(comm, decided)?.first() {
        Some(1) => ReadMode::Shared,
        _ => ReadMode::Scatter,
    };
    match mode {
        ReadMode::Shared => read_shared(comm, path, threads),
        _ => read_scatter(comm, path, threads),
    }
}

fn sniff(path: &Path) -> std::io::Result<Compression> {
    use std::io::Read;
    let mut m = [0u8; 4];
    let n = std::fs::File::open(path)?.read(&mut m)?;
    Ok(compression::detect_compression(&m[..n]))
}

/// Rank 0: read the file and scan or load its index.
fn root_index(path: &Path, write_sidecar: bool) -> Result<(FileContents, FrameIndex), String> {
    let fc = compression::read_file_contents(path).map_err(|e| e.to_string())?;
    let idx = {
        let text = fc.as_str_sliced().map_err(|e| e.to_string())?;
        let mapped = matches!(fc, FileContents::Mapped(_));
        frame_index::load_or_build(path, text, write_sidecar && mapped)
            .map_err(|e| e.to_string())?
    };
    Ok((fc, idx))
}

fn pack_index(idx: &FrameIndex) -> Vec<u8> {
    let mut v = vec![idx.data_len];
    v.extend_from_slice(&idx.offsets);
    encode_u64s(&v)
}

fn unpack_index(b: &[u8]) -> FrameIndex {
    let v = decode_u64s(b);
    FrameIndex {
        data_len: v[0],
        offsets: v[1..].to_vec(),
    }
}

/// Byte range of frames `r` and their offsets relative to its start.
fn block_bytes(idx: &FrameIndex, r: &std::ops::Range<usize>) -> (usize, usize, Vec<usize>) {
    if r.is_empty() {
        return (0, 0, Vec::new());
    }
    let lo = idx.offsets[r.start] as usize;
    let hi = idx.range(r.end - 1).unwrap().end;
    let offs = idx.offsets[r.clone()]
        .iter()
        .map(|&o| o as usize - lo)
        .collect();
    (lo, hi, offs)
}

/// Read only `[lo, hi)` so a rank does not pull bytes another rank parses.
fn read_span(path: &Path, lo: usize, hi: usize) -> Result<Vec<u8>, String> {
    use std::io::{Read, Seek, SeekFrom};
    let mut file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let len = file.metadata().map_err(|e| e.to_string())?.len() as usize;
    if lo > hi || hi > len {
        return Err("byte range is outside the file".into());
    }
    file.seek(SeekFrom::Start(lo as u64))
        .map_err(|e| e.to_string())?;
    let mut buf = vec![0u8; hi - lo];
    #[cfg(test)]
    if lo == 0 {
        note_prefix_alloc(buf.len());
    }
    file.read_exact(&mut buf).map_err(|e| e.to_string())?;
    Ok(buf)
}

/// Largest buffer a shared-mode newline count may allocate.
///
/// The count used to `read_span` `[0, lo)` into one `Vec`. A later rank
/// then held its frame span and almost the whole file.
const PREFIX_COUNT_CHUNK: usize = 64 * 1024;

#[cfg(test)]
thread_local! {
    static PREFIX_ALLOCS: std::cell::RefCell<Vec<usize>> = const { std::cell::RefCell::new(Vec::new()) };
}

#[cfg(test)]
fn note_prefix_alloc(n: usize) {
    if n > 0 {
        PREFIX_ALLOCS.with(|slot| slot.borrow_mut().push(n));
    }
}

#[cfg(test)]
fn take_prefix_allocs() -> Vec<usize> {
    PREFIX_ALLOCS.with(|slot| std::mem::take(&mut *slot.borrow_mut()))
}

#[cfg(test)]
thread_local! {
    static PREFIX_CALLS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

#[cfg(test)]
fn note_prefix_call() {
    PREFIX_CALLS.with(|slot| slot.set(slot.get() + 1));
}

#[cfg(test)]
fn take_prefix_calls() -> usize {
    PREFIX_CALLS.with(|slot| slot.replace(0))
}

/// Span and frame count when the first two frames share one length and
/// that length tiles the file. Later frames are checked by the parse of
/// each rank's own span, not by a walk of the whole file on rank 0.
fn tiled_span(path: &Path) -> Option<(usize, usize)> {
    let file = std::fs::File::open(path).ok()?;
    let len = file.metadata().ok()?.len() as usize;
    if len < 2 {
        return None;
    }
    // SAFETY: the file is not truncated while this map is alive.
    let map = unsafe { memmap2::Mmap::map(&file).ok()? };
    let mut iter = crate::iterators::ConFrameIterator::from_bytes(&map);
    if !matches!(iter.forward_fast(), Some(Ok(()))) {
        return None;
    }
    let span = iter.byte_pos();
    if span < 2 {
        return None;
    }
    let n = len / span;
    if n == 0 {
        return None;
    }
    // A trailing newline is not another frame. Ranking the whole file
    // for that byte made rank 0 index every read.
    if !map[n * span..]
        .iter()
        .all(|byte| byte.is_ascii_whitespace())
    {
        return None;
    }
    if n >= 2 {
        let mut next = crate::iterators::ConFrameIterator::from_bytes(&map[span..span * 2]);
        if !matches!(next.forward_fast(), Some(Ok(()))) || next.byte_pos() != span {
            return None;
        }
    }
    Some((span, n))
}

/// True when `path` is `n` frames of `span` bytes plus optional whitespace.
fn tiled_length_matches(path: &Path, span: usize, n: usize) -> bool {
    if span < 2 || n == 0 {
        return false;
    }
    let Ok(file) = std::fs::File::open(path) else {
        return false;
    };
    let Ok(meta) = file.metadata() else {
        return false;
    };
    let len = meta.len() as usize;
    let body = n.saturating_mul(span);
    if len < body {
        return false;
    }
    let tail = len - body;
    if tail == 0 {
        return true;
    }
    use std::io::{Read, Seek, SeekFrom};
    let mut file = file;
    if file.seek(SeekFrom::Start(body as u64)).is_err() {
        return false;
    }
    let mut buf = vec![0u8; tail];
    file.read_exact(&mut buf).is_ok() && buf.iter().all(|byte| byte.is_ascii_whitespace())
}

/// Equal-length frames: every rank, including rank 0, reads only its span.
///
/// `Ok(None)` means the file is not one frame length and the caller keeps
/// the index path. Every rank takes the same branch.
fn read_tiled(
    comm: &Comm,
    path: &Path,
    threads: Option<usize>,
) -> Result<Option<RankFrames>, BoxErr> {
    // Only rank 0 maps the file to learn the frame length. The other
    // ranks used to map it too, which made an 8-rank read of a long
    // equal-frame file slower than four ranks.
    let packed = if comm.rank() == 0 {
        match tiled_span(path) {
            Some((span, n)) => {
                let mut bytes = Vec::with_capacity(16);
                bytes.extend_from_slice(&(span as u64).to_le_bytes());
                bytes.extend_from_slice(&(n as u64).to_le_bytes());
                Ok(bytes)
            }
            None => Err("frames do not share one length".into()),
        }
    } else {
        Ok(Vec::new())
    };
    let decided = match bcast_result(comm, packed) {
        Ok(bytes) if bytes.len() == 16 => Some((
            u64::from_le_bytes(bytes[0..8].try_into().unwrap()) as usize,
            u64::from_le_bytes(bytes[8..16].try_into().unwrap()) as usize,
        )),
        _ => None,
    };
    let Some((span, n)) = decided else {
        return Ok(None);
    };
    let same = tiled_length_matches(path, span, n);
    if !agree(comm, same) {
        return Ok(None);
    }
    let r = comm.my_frames(n);
    let lo = r.start.saturating_mul(span);
    let hi = r.end.saturating_mul(span);
    let opened = read_span(path, lo, hi);
    let ok = agree(comm, opened.is_ok());
    let bytes = match (opened, ok) {
        (Ok(bytes), true) => bytes,
        (Err(e), _) => return Err(format!("rank {}: {e}", comm.rank()).into()),
        (Ok(_), false) => return Err("file open failed on another rank".into()),
    };
    let offs: Vec<usize> = (0..r.len()).map(|i| i * span).collect();
    let frames = parse_ranked(comm, path, &bytes, &offs, r.start, threads, lo)?;
    Ok(Some(RankFrames {
        first: r.start,
        n_total: n,
        frames,
    }))
}

/// Parse the span. The prefix newline count runs only when a frame fails,
/// because a successful read does not report a file line.
fn parse_ranked(
    comm: &Comm,
    path: &Path,
    bytes: &[u8],
    offs: &[usize],
    first: usize,
    threads: Option<usize>,
    lo: usize,
) -> Result<Vec<ConFrame>, BoxErr> {
    let attempt = parse_local(comm, bytes, offs, 0, first, threads);
    if attempt.is_ok() {
        return attempt;
    }
    let line_offset = line_offset_before(comm, path, lo)?;
    parse_local(comm, bytes, offs, line_offset, first, threads)
}

fn read_shared(comm: &Comm, path: &Path, threads: Option<usize>) -> Result<RankFrames, BoxErr> {
    if let Some(done) = read_tiled(comm, path, threads)? {
        return Ok(done);
    }
    // Unequal frames: rank 0 builds the index, then every rank, including
    // rank 0, reads only its own byte range. The full buffer is not kept
    // for the parse.
    let packed = if comm.rank() == 0 {
        match root_index(path, true) {
            Ok((_fc, idx)) => Ok(pack_index(&idx)),
            Err(e) => Err(e),
        }
    } else {
        Ok(Vec::new())
    };
    let idx = unpack_index(&bcast_result(comm, packed)?);
    let r = comm.my_frames(idx.len());
    let (lo, hi, offs) = block_bytes(&idx, &r);
    let len = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    let opened = if len == idx.data_len {
        read_span(path, lo, hi)
    } else {
        Err("file differs from rank 0's copy; use ReadMode::Scatter".to_string())
    };
    let ok = agree(comm, opened.is_ok());
    let bytes = match (opened, ok) {
        (Ok(bytes), true) => bytes,
        (Err(e), _) => return Err(format!("rank {}: {e}", comm.rank()).into()),
        (Ok(_), false) => return Err("file open failed on another rank".into()),
    };
    let frames = parse_ranked(comm, path, &bytes, &offs, r.start, threads, lo)?;
    Ok(RankFrames {
        first: r.start,
        n_total: idx.len(),
        frames,
    })
}

fn flock_wait(fd: std::os::fd::RawFd, op: i32) -> bool {
    loop {
        if unsafe { libc::flock(fd, op) } == 0 {
            return true;
        }
        if std::io::Error::last_os_error().kind() != std::io::ErrorKind::Interrupted {
            return false;
        }
    }
}

/// True when a non-blocking shared lock fails because another holder has
/// the exclusive lock. A successful lock means `flock` did not see that
/// holder, so the caller releases it and reports the lock as not coherent.
fn flock_sees_exclusive(fd: std::os::fd::RawFd) -> bool {
    loop {
        if unsafe { libc::flock(fd, libc::LOCK_SH | libc::LOCK_NB) } == 0 {
            let _ = unsafe { libc::flock(fd, libc::LOCK_UN) };
            return false;
        }
        let err = std::io::Error::last_os_error();
        if err.kind() == std::io::ErrorKind::Interrupted {
            continue;
        }
        return err.kind() == std::io::ErrorKind::WouldBlock;
    }
}

/// Block in the kernel until rank 0 has finished the file scan.
///
/// The other ranks sleep on a shared file lock while rank 0 holds the
/// exclusive lock. That lock has to be coherent across the ranks. Where
/// it is not, rank 0 still scans and every rank then uses the blocking
/// broadcast.
fn wait_until_root_scanned(comm: &Comm, path: &Path, scan: impl FnOnce()) {
    let visible = std::fs::File::open(path).is_ok();
    if !agree(comm, visible) {
        if comm.rank() == 0 {
            scan();
        }
        return;
    }
    let file = match std::fs::File::open(path) {
        Ok(file) => file,
        Err(_) => {
            if comm.rank() == 0 {
                scan();
            }
            return;
        }
    };
    let fd = std::os::fd::AsRawFd::as_raw_fd(&file);
    let root_holds = if comm.rank() == 0 {
        flock_wait(fd, libc::LOCK_EX)
    } else {
        false
    };
    comm.raw().barrier();
    let sees = if comm.rank() == 0 {
        root_holds
    } else {
        flock_sees_exclusive(fd)
    };
    if !agree(comm, sees) {
        if comm.rank() == 0 {
            let _ = unsafe { libc::flock(fd, libc::LOCK_UN) };
            scan();
        }
        return;
    }
    if comm.rank() == 0 {
        scan();
        let _ = unsafe { libc::flock(fd, libc::LOCK_UN) };
    } else {
        flock_wait(fd, libc::LOCK_SH);
        let _ = unsafe { libc::flock(fd, libc::LOCK_UN) };
    }
}

fn read_scatter(comm: &Comm, path: &Path, threads: Option<usize>) -> Result<RankFrames, BoxErr> {
    let p = comm.size();
    let mut root_data = None;
    let mut packed_slot = None;
    wait_until_root_scanned(comm, path, || {
        packed_slot = Some(root_index(path, false).and_then(|(fc, idx)| {
            // Scatterv counts are C ints.
            let too_big = (0..p).any(|k| {
                let (lo, hi, _) = block_bytes(&idx, &block_range(idx.len(), p, k));
                hi - lo > i32::MAX as usize
            });
            if too_big {
                return Err("a rank's block exceeds 2 GiB; use more ranks".into());
            }
            let b = pack_index(&idx);
            root_data = Some((fc, idx));
            Ok(b)
        }));
    });
    let packed = packed_slot.unwrap_or(Ok(Vec::new()));
    let idx = unpack_index(&bcast_result(comm, packed)?);
    let r = comm.my_frames(idx.len());
    let (lo, hi, offs) = block_bytes(&idx, &r);
    let line_offset =
        bcast_line_offsets(comm, root_data.as_ref().map(|(fc, _)| bytes_of(fc)), &idx)?;
    // Keep a real allocation even for an empty block: Open MPI rejects
    // the dangling pointer of an empty Vec as a receive buffer.
    let mut store = vec![0u8; (hi - lo).max(1)];
    let buf = &mut store[..hi - lo];

    let root = comm.raw().process_at_rank(0);
    if let Some((fc, _)) = &root_data {
        let mut counts = Vec::with_capacity(p);
        let mut displs = Vec::with_capacity(p);
        for k in 0..p {
            let (l, h, _) = block_bytes(&idx, &block_range(idx.len(), p, k));
            counts.push((h - l) as i32);
            displs.push(l.min(i32::MAX as usize) as i32);
        }
        // Displacements are C ints too, so files over 2 GiB use
        // point-to-point sends instead (same decision on every rank).
        let all = bytes_of(fc);
        if idx.data_len <= i32::MAX as u64 {
            let part = Partition::new(all, &counts[..], &displs[..]);
            root.scatter_varcount_into_root(&part, buf);
        } else {
            for k in 1..p {
                let (l, h, _) = block_bytes(&idx, &block_range(idx.len(), p, k));
                comm.raw().process_at_rank(k as i32).send(&all[l..h]);
            }
            buf.copy_from_slice(&all[lo..hi]);
        }
    } else {
        let big = idx.data_len > i32::MAX as u64;
        if big {
            comm.raw().process_at_rank(0).receive_into(buf);
        } else {
            root.scatter_varcount_into(buf);
        }
    }
    drop(root_data);
    let frames = parse_local(comm, buf, &offs, line_offset, r.start, threads)?;
    Ok(RankFrames {
        first: r.start,
        n_total: idx.len(),
        frames,
    })
}

/// C ABI: read this rank's block of frames on a Fortran communicator.
///
/// `mode` is 0 (auto), 1 (shared file system) or 2 (scatter from rank
/// 0). `n_threads == 0` uses the global rayon pool. On success returns
/// the frame array (free with `free_rkr_frame_array`) and writes the
/// local count, the global index of the first local frame and the total
/// frame count. Returns NULL on every rank if any rank fails.
///
/// # Safety
/// MPI must be initialized; `comm_f` must be a live intra-communicator;
/// `path_c` must be a NUL-terminated string; the out pointers must be
/// valid for writes. Every rank of the communicator must call this.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_mpi_read_block_f(
    comm_f: ::mpi::ffi::RSMPI_Fint,
    path_c: *const std::ffi::c_char,
    mode: i32,
    n_threads: usize,
    num_frames: *mut usize,
    first_frame: *mut u64,
    total_frames: *mut u64,
) -> *mut *mut crate::ffi::RKRConFrame {
    let comm = match unsafe { Comm::dup_fint(comm_f) } {
        Ok(c) => c,
        Err(e) => {
            crate::ffi::record_status_message(
                crate::ffi::RKRStatus::RKR_STATUS_IO_ERROR,
                &format!("MPI_Comm_dup failed with MPI error {e}"),
            );
            return std::ptr::null_mut();
        }
    };
    // Argument checks are agreed collectively so no rank is left waiting.
    let args = (!path_c.is_null()
        && !num_frames.is_null()
        && !first_frame.is_null()
        && !total_frames.is_null())
    .then(|| unsafe { std::ffi::CStr::from_ptr(path_c) }.to_str().ok())
    .flatten()
    .zip(ReadMode::from_i32(mode));
    if !agree(&comm, args.is_some()) {
        crate::ffi::record_status_message(
            crate::ffi::RKRStatus::RKR_STATUS_NULL_POINTER,
            "null argument",
        );
        return std::ptr::null_mut();
    }
    let (path, mode) = args.unwrap();
    let threads = (n_threads > 0).then_some(n_threads);
    match read_block(&comm, Path::new(path), mode, threads) {
        Ok(rf) => unsafe {
            *first_frame = rf.first as u64;
            *total_frames = rf.n_total as u64;
            crate::ffi::pack_frame_handles(rf.frames, num_frames)
        },
        Err(err) => {
            crate::ffi::record_mpi_failure(err.as_ref());
            std::ptr::null_mut()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn two_frames() -> String {
        let good = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        let bad = "seed\n{not-json\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        format!("{good}{bad}")
    }

    fn second_frame_at(text: &str) -> usize {
        text[1..].find("seed\n").expect("second frame") + 1
    }

    /// The second frame starts after 12 lines. Its metadata line is file line 14.
    #[test]
    fn later_frame_line_offset_is_past_the_first_frame() {
        let text = two_frames();
        let second = second_frame_at(&text);
        let idx = FrameIndex {
            offsets: vec![0, second as u64],
            data_len: text.len() as u64,
        };
        assert_eq!(block_line_offset(text.as_bytes(), &idx, 1, 0), 0);
        assert_eq!(block_line_offset(text.as_bytes(), &idx, 2, 1), 12);
        assert_eq!(cursor_file_line(&text[second..], 13), 14);
    }

    /// A prefix newline count must not allocate a `Vec` of length `lo`.
    ///
    /// Shared mode asks every rank for the newlines before its span.
    /// `read_span(0, lo)` is that allocation. The chunk cap is the
    /// largest buffer the count may hold.
    #[test]
    fn shared_prefix_count_does_not_allocate_a_vec_of_size_lo() {
        let _scratch = tempfile::tempdir().unwrap();
        with_comm(|comm| {
            let at = PREFIX_COUNT_CHUNK * 2 + 7;
            let path = _scratch.path().join(format!(
                "readcon-mpi-prefix-count-{}.con",
                std::process::id()
            ));
            std::fs::write(&path, vec![b'\n'; at]).unwrap();
            let _ = take_prefix_allocs();
            let n = line_offset_before(comm, &path, at).unwrap();
            let sizes = take_prefix_allocs();
            let _ = std::fs::remove_file(&path);
            assert_eq!(n, at as u32);
            assert!(!sizes.is_empty(), "prefix count did not record its buffer");
            assert!(
                sizes.iter().all(|&n| n <= PREFIX_COUNT_CHUNK && n < at),
                "shared-mode prefix count allocated a Vec of size lo={at}: {sizes:?}"
            );
        });
    }

    /// MPI can be initialized once per process. Later tests reuse that
    /// universe; dropping it would finalize MPI and the next init fails.
    fn with_comm(body: impl FnOnce(&crate::distrib::Comm)) {
        let _hold = mpi_test_lock();
        let world = shared_universe().world();
        let comm = crate::distrib::Comm::dup_of(&world);
        body(&comm);
    }

    fn shared_universe() -> &'static ::mpi::environment::Universe {
        use std::sync::OnceLock;
        static SLOT: OnceLock<usize> = OnceLock::new();
        let ptr = *SLOT.get_or_init(|| {
            let universe = ::mpi::initialize().expect("MPI_Init");
            Box::into_raw(Box::new(universe)) as usize
        });
        unsafe { &*(ptr as *const ::mpi::environment::Universe) }
    }

    fn mpi_test_lock() -> std::sync::MutexGuard<'static, ()> {
        static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        LOCK.lock().unwrap_or_else(|err| err.into_inner())
    }

    /// A successful shared read does not count newlines before the span.
    ///
    /// That count is the file line of a later error. The success path
    /// used to read it on every rank, including a rank whose span starts
    /// at byte 0.
    #[test]
    fn successful_shared_read_does_not_count_the_prefix() {
        let _scratch = tempfile::tempdir().unwrap();
        with_comm(|comm| {
            let frame = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
            let path = _scratch.path().join(format!(
                "readcon-mpi-prefix-success-{}.con",
                std::process::id()
            ));
            std::fs::write(&path, frame.repeat(4)).unwrap();
            let _ = take_prefix_calls();
            let got = read_block(comm, &path, ReadMode::Shared, Some(1)).expect("read");
            let calls = take_prefix_calls();
            let _ = std::fs::remove_file(&path);
            assert_eq!(got.n_total, 4);
            assert_eq!(
                calls, 0,
                "a successful read counted newlines before the span"
            );
        });
    }

    /// Collective read of the same file. The owning rank reports line 14.
    /// The serial reader covers this text when the MPI feature is off.
    #[test]
    fn distrib_later_frame_metadata_reports_its_file_line() {
        let _scratch = tempfile::tempdir().unwrap();
        with_comm(|comm| {
            let owned = if comm.rank() == 0 {
                let path = _scratch
                    .path()
                    .join(format!("readcon-mpi-later-line-{}.con", std::process::id()));
                std::fs::write(&path, two_frames()).unwrap();
                path.to_string_lossy().into_owned().into_bytes()
            } else {
                Vec::new()
            };
            let path =
                PathBuf::from(String::from_utf8(bcast_result(comm, Ok(owned)).unwrap()).unwrap());
            for mode in [ReadMode::Shared, ReadMode::Scatter] {
                let err = read_block(comm, &path, mode, Some(1)).expect_err("malformed frame");
                match err.downcast::<crate::error::LocatedParseError>() {
                    Ok(located) => {
                        assert_eq!(located.error.class_name(), "InvalidMetadataJson");
                        assert_eq!(located.frame_index, 1, "{mode:?} {located}");
                        assert_eq!(located.line, 14, "{mode:?} {located}");
                    }
                    Err(err) if err.is::<PeerParseError>() => {}
                    Err(err) => panic!("mode {mode:?}: {err}"),
                }
            }
            if comm.rank() == 0 {
                let _ = std::fs::remove_file(&path);
            }
        });
    }
}

/// Byte span of the coordinate lines in one CON frame.
///
/// The span starts after `Coordinates of Component 1` and stops at the
/// blank line that ends the block, or at the end of the file.
pub fn frame_coord_span(bytes: &[u8]) -> Option<(usize, usize)> {
    let marker = b"Coordinates of Component 1\n";
    let at = memchr::memmem::find(bytes, marker)?;
    let start = at + marker.len();
    let mut end = start;
    while end < bytes.len() {
        if bytes[end] == b'\n' && end + 1 < bytes.len() && bytes[end + 1] == b'\n' {
            return Some((start, end + 1));
        }
        end += 1;
    }
    Some((start, bytes.len()))
}

/// Newline-aligned slice of `[start, end)` for `rank` of `size`.
///
/// Rank 0 starts at `start` and the last rank ends at `end`. A cut that
/// lands mid-line moves forward to the next newline so every line belongs
/// to one rank.
pub fn rank_line_range(
    bytes: &[u8],
    start: usize,
    end: usize,
    rank: usize,
    size: usize,
) -> std::ops::Range<usize> {
    if size == 0 || rank >= size || start >= end {
        return start..start;
    }
    let mut cuts = Vec::with_capacity(size + 1);
    cuts.push(start);
    let span = end - start;
    for index in 1..size {
        let mut at = start + span * index / size;
        if at > start && at < end && bytes[at - 1] != b'\n' {
            while at < end && bytes[at] != b'\n' {
                at += 1;
            }
            if at < end {
                at += 1;
            }
        }
        if at < *cuts.last().unwrap_or(&start) {
            at = *cuts.last().unwrap_or(&start);
        }
        cuts.push(at.min(end));
    }
    cuts.push(end);
    cuts[rank]..cuts[rank + 1]
}

/// Parse `x y z` from each non-empty line. The returned buffer is three
/// floats per line, in file order.
/// Atoms whose coordinates alias `coords`.
///
/// `coords` is the return value's buffer. Moving that `Vec` does not move
/// the allocation, so the atoms stay valid. Reallocating it, or dropping
/// it before the atoms, does not.
pub fn slab_atoms(
    slice: &[u8],
    symbol: &std::sync::Arc<str>,
) -> Result<(Vec<f64>, Vec<crate::types::AtomDatum>), String> {
    let coords = parse_coord_lines(slice)?;
    let n = coords.len() / 3;
    let mut atoms = Vec::with_capacity(n);
    let base = coords.as_ptr() as *mut f64;
    let mut cursor = 0usize;
    let mut index = 0usize;
    while cursor < slice.len() && index < n {
        let start = cursor;
        while cursor < slice.len() && slice[cursor] != b'\n' {
            cursor += 1;
        }
        let line = &slice[start..cursor];
        if cursor < slice.len() {
            cursor += 1;
        }
        if line.iter().all(|byte| byte.is_ascii_whitespace()) {
            continue;
        }
        let mut at = 0usize;
        for _ in 0..3 {
            while at < line.len() && line[at].is_ascii_whitespace() {
                at += 1;
            }
            let Some((_, next)) = crate::fast_dec::parse_f64_hot(line, at) else {
                return Err("float".into());
            };
            at = next;
        }
        while at < line.len() && line[at].is_ascii_whitespace() {
            at += 1;
        }
        let (fixed, id) = if at < line.len() {
            let (value, used) = take_u64(line, at);
            let bits = value as u8;
            at += used;
            while at < line.len() && line[at].is_ascii_whitespace() {
                at += 1;
            }
            let id = if at < line.len() {
                take_u64(line, at).0
            } else {
                index as u64
            };
            ([bits & 1 != 0, bits & 2 != 0, bits & 4 != 0], id)
        } else {
            ([false, false, false], index as u64)
        };
        atoms.push(crate::types::AtomDatum::at_slot(
            std::sync::Arc::clone(symbol),
            unsafe { base.add(index * 3) },
            fixed,
            id,
        ));
        index += 1;
    }
    Ok((coords, atoms))
}

fn take_u64(bytes: &[u8], mut at: usize) -> (u64, usize) {
    let start = at;
    let mut value = 0u64;
    while at < bytes.len() && bytes[at].is_ascii_digit() {
        value = value * 10 + u64::from(bytes[at] - b'0');
        at += 1;
    }
    (value, at - start)
}

pub fn parse_coord_lines(slice: &[u8]) -> Result<Vec<f64>, String> {
    let lines = memchr::memchr_iter(b'\n', slice).count();
    let mut out = Vec::with_capacity(lines.saturating_mul(3));
    let mut cursor = 0usize;
    while cursor < slice.len() {
        let start = cursor;
        while cursor < slice.len() && slice[cursor] != b'\n' {
            cursor += 1;
        }
        let mut line = &slice[start..cursor];
        if cursor < slice.len() {
            cursor += 1;
        }
        if line.last() == Some(&b'\r') {
            line = &line[..line.len() - 1];
        }
        if line.iter().all(|byte| byte.is_ascii_whitespace()) {
            continue;
        }
        let mut index = 0usize;
        for _ in 0..3 {
            while index < line.len() && line[index].is_ascii_whitespace() {
                index += 1;
            }
            let (value, next) =
                crate::fast_dec::parse_f64_hot(line, index).ok_or_else(|| "float".to_string())?;
            out.push(value);
            index = next;
        }
    }
    Ok(out)
}

#[cfg(test)]
mod atom_range_tests {
    use super::{frame_coord_span, parse_coord_lines, rank_line_range, slab_atoms};

    #[test]
    fn one_frame_splits_across_ranks_without_dropping_a_line() {
        let mut text = String::from(
            "grid\n{\"con_spec_version\":2}\n1 1 1\n90 90 90\n0 0\n0 0\n1\n5\n1.0\nH\nCoordinates of Component 1\n",
        );
        for index in 0..5 {
            text.push_str(&format!("{index}.5 0 1 0 {index}\n"));
        }
        let bytes = text.as_bytes();
        let (start, end) = frame_coord_span(bytes).unwrap();
        let mut coords = Vec::new();
        let mut cursor = start;
        for rank in 0..4 {
            let range = rank_line_range(bytes, start, end, rank, 4);
            assert_eq!(range.start, cursor, "rank {rank} left a gap or an overlap");
            cursor = range.end;
            coords.extend(parse_coord_lines(&bytes[range]).unwrap());
        }
        assert_eq!(cursor, end);
        assert_eq!(coords.len(), 15);
        assert_eq!(coords[0], 0.5);
        assert_eq!(coords[12], 4.5);
    }

    #[test]
    fn a_trailing_newline_still_tiles_equal_frames() {
        let _scratch = tempfile::tempdir().unwrap();
        let frame = "grid\n{\"con_spec_version\":2}\n1 1 1\n90 90 90\n0 0\n0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        let mut bytes = frame.repeat(3);
        bytes.push('\n');
        let path = _scratch
            .path()
            .join(format!("readcon-tail-{}.con", std::process::id()));
        std::fs::write(&path, bytes).unwrap();
        let tiled = super::tiled_span(&path);
        let _ = std::fs::remove_file(&path);
        let (span, n) = tiled.expect("a trailing newline is not another frame");
        assert_eq!(n, 3);
        assert_eq!(span, frame.len());
    }

    /// Rank writes alias one coordinate allocation instead of a box per atom.
    #[test]
    fn slab_atoms_alias_the_parsed_coordinates() {
        let text = b"0.125 0.25 0.5 0 7\n1.5 2.5 3.5 1 8\n";
        let symbol: std::sync::Arc<str> = std::sync::Arc::from("Cu");
        let (coords, atoms) = slab_atoms(text, &symbol).unwrap();
        assert_eq!(coords, vec![0.125, 0.25, 0.5, 1.5, 2.5, 3.5]);
        assert_eq!(atoms[0].x(), 0.125);
        assert_eq!(atoms[0].z(), 0.5);
        assert_eq!(atoms[0].atom_id, 7);
        assert_eq!(atoms[0].fixed(), [false, false, false]);
        assert_eq!(atoms[1].x(), 1.5);
        assert_eq!(atoms[1].atom_id, 8);
        assert_eq!(atoms[1].fixed(), [true, false, false]);
        assert!(std::ptr::eq(atoms[0].coord_ptr(), coords.as_ptr()));
    }
}
