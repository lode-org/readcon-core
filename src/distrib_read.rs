//! Distributed read: each rank of a caller-supplied communicator parses
//! only its block of frames (see [`crate::distrib::block_range`]).
//!
//! Two modes:
//!
//! - [`ReadMode::Shared`]: every rank opens the same file (shared file
//!   system). Rank 0 loads or builds the checked `.rcidx` index and
//!   broadcasts the offsets; each rank then maps the file, checks UTF-8
//!   on its own byte range only, and parses its frames with rayon. No
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
    b.chunks_exact(8)
        .map(|c| u64::from_le_bytes(c.try_into().unwrap()))
        .collect()
}

/// Broadcast `Ok(payload)` or an error message from rank 0.
fn bcast_result(comm: &Comm, r: Result<Vec<u8>, String>) -> Result<Vec<u8>, BoxErr> {
    let msg = match &r {
        Ok(p) => [&[1u8][..], p].concat(),
        Err(e) => [&[0u8][..], e.as_bytes()].concat(),
    };
    let got = comm.bcast_bytes(0, if comm.rank() == 0 { &msg } else { &[] });
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
/// global pool). In shared mode rank 0 refreshes `path.rcidx` when it
/// is missing or stale.
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

fn read_shared(comm: &Comm, path: &Path, threads: Option<usize>) -> Result<RankFrames, BoxErr> {
    let packed = if comm.rank() == 0 {
        root_index(path, true).map(|(_, idx)| pack_index(&idx))
    } else {
        Ok(Vec::new())
    };
    let idx = unpack_index(&bcast_result(comm, packed)?);
    let r = comm.my_frames(idx.len());

    // Every rank maps the file itself; a size mismatch means it is not
    // the same file (or not shared), which is an error for all.
    let opened = compression::read_file_contents(path)
        .map_err(|e| e.to_string())
        .and_then(|fc| {
            if bytes_of(&fc).len() as u64 == idx.data_len {
                Ok(fc)
            } else {
                Err("file differs from rank 0's copy; use ReadMode::Scatter".to_string())
            }
        });
    let ok = agree(comm, opened.is_ok());
    let fc = match (opened, ok) {
        (Ok(fc), true) => fc,
        (Err(e), _) => return Err(format!("rank {}: {e}", comm.rank()).into()),
        (Ok(_), false) => return Err("file open failed on another rank".into()),
    };
    let (lo, hi, offs) = block_bytes(&idx, &r);
    let line_offset = newlines_before(bytes_of(&fc), lo);
    let frames = parse_local(
        comm,
        &bytes_of(&fc)[lo..hi],
        &offs,
        line_offset,
        r.start,
        threads,
    )?;
    Ok(RankFrames {
        first: r.start,
        n_total: idx.len(),
        frames,
    })
}

fn read_scatter(comm: &Comm, path: &Path, threads: Option<usize>) -> Result<RankFrames, BoxErr> {
    let p = comm.size();
    let mut root_data = None;
    let packed = if comm.rank() == 0 {
        root_index(path, false).and_then(|(fc, idx)| {
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
        })
    } else {
        Ok(Vec::new())
    };
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
            let part = Partition::new(&all[..], &counts[..], &displs[..]);
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
        Err(_) => return std::ptr::null_mut(),
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
        Err(_) => std::ptr::null_mut(),
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

    /// Collective read of the same file. The owning rank reports line 14.
    /// The serial reader covers this text when the MPI feature is off.
    #[test]
    fn distrib_later_frame_metadata_reports_its_file_line() {
        let universe = ::mpi::initialize().expect("MPI_Init");
        let comm = crate::distrib::Comm::dup_of(&universe.world());
        let owned = if comm.rank() == 0 {
            let path = std::env::temp_dir()
                .join(format!("readcon-mpi-later-line-{}.con", std::process::id()));
            std::fs::write(&path, two_frames()).unwrap();
            path.to_string_lossy().into_owned().into_bytes()
        } else {
            Vec::new()
        };
        let path =
            PathBuf::from(String::from_utf8(bcast_result(&comm, Ok(owned)).unwrap()).unwrap());
        for mode in [ReadMode::Shared, ReadMode::Scatter] {
            let err = read_block(&comm, &path, mode, Some(1)).expect_err("malformed frame");
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
    }
}
