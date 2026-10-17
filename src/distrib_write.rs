//! Collective write: every rank of a caller-supplied communicator
//! contributes its frames and the file holds them in rank order.
//!
//! Each rank formats its frames with the serial [`ConFrameWriter`], so
//! the bytes depend only on the frames. `MPI_Exscan` of the local byte
//! lengths gives each rank's file offset, and the output is
//! byte-identical to a serial write of the rank-ordered frames for any
//! rank count (including ranks with no frames).
//!
//! Modes:
//!
//! - [`WriteMode::MpiIo`]: `MPI_File_open`, `MPI_File_set_size` to the
//!   exact total (so rewriting a longer file leaves no tail) and
//!   `MPI_File_write_at_all` in rounds of at most 1 GiB per rank.
//! - [`WriteMode::Gather`]: for file systems without MPI-IO. Rank 0
//!   collects every block (`MPI_Gatherv` up to 2 GiB in total,
//!   point-to-point chunks above that) and writes the file itself.
//!
//! After the data is written rank 0 writes the checked `.rcidx` sidecar
//! from the known frame offsets (best effort). Every failure is
//! collective: all ranks return an error.

use std::path::Path;

use ::mpi::datatype::PartitionMut;
use ::mpi::ffi;
use ::mpi::traits::*;

use crate::distrib::Comm;
use crate::distrib_read::agree;
use crate::frame_index::{self, FrameIndex};
use crate::types::ConFrame;
use crate::writer::ConFrameWriter;

type BoxErr = Box<dyn std::error::Error>;

/// Largest byte count passed to one MPI call (1 GiB).
///
/// `READCON_MPI_TEST_CHUNK=<bytes>` lowers this and the Gatherv limit so
/// tests exercise the multi-round and point-to-point paths on small
/// files. Every rank must see the same value.
fn chunk() -> usize {
    std::env::var("READCON_MPI_TEST_CHUNK")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|&c: &usize| c > 0)
        .unwrap_or(1 << 30)
}

/// Totals above this skip `MPI_Gatherv` (C int counts and displacements).
fn gatherv_max() -> u64 {
    (i32::MAX as u64).min(chunk() as u64)
}

/// How bytes reach the file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum WriteMode {
    /// Same as `MpiIo` (kept separate so a later heuristic can choose).
    Auto = 0,
    MpiIo = 1,
    Gather = 2,
}

impl WriteMode {
    pub fn from_i32(v: i32) -> Option<Self> {
        match v {
            0 => Some(Self::Auto),
            1 => Some(Self::MpiIo),
            2 => Some(Self::Gather),
            _ => None,
        }
    }
}

/// Format `frames` exactly as the serial writer would, returning the
/// bytes and each frame's start offset within them.
pub fn format_frames(
    frames: &[&ConFrame],
    precision: Option<usize>,
) -> Result<(Vec<u8>, Vec<u64>), BoxErr> {
    let mut out = Vec::new();
    let mut starts = Vec::with_capacity(frames.len());
    for f in frames {
        starts.push(out.len() as u64);
        let mut one = Vec::new();
        {
            let mut w = match precision {
                Some(p) => ConFrameWriter::with_precision(&mut one, p),
                None => ConFrameWriter::new(&mut one),
            };
            w.write_frame(f)?;
            w.flush()?;
        }
        out.extend_from_slice(&one);
    }
    Ok((out, starts))
}

fn collective<T>(comm: &Comm, r: Result<T, BoxErr>, what: &str) -> Result<T, BoxErr> {
    let ok = agree(comm, r.is_ok());
    match (r, ok) {
        (Ok(v), true) => Ok(v),
        (Err(e), _) => Err(format!("rank {}: {what}: {e}", comm.rank()).into()),
        (Ok(_), false) => Err(format!("{what} failed on another rank").into()),
    }
}

fn mpi_rc(rc: i32, call: &str) -> Result<(), BoxErr> {
    if rc == 0 {
        Ok(())
    } else {
        Err(format!("{call} returned MPI error {rc}").into())
    }
}

/// Write the frames of every rank, in rank order, to `path`.
///
/// Collective over `comm`. Returns the total file size in bytes.
pub fn write_block(
    comm: &Comm,
    path: &Path,
    frames: &[ConFrame],
    mode: WriteMode,
    precision: Option<usize>,
) -> Result<u64, BoxErr> {
    let refs: Vec<&ConFrame> = frames.iter().collect();
    write_block_refs(comm, path, &refs, mode, precision)
}

/// [`write_block`] over borrowed frames (used by the C ABI).
pub fn write_block_refs(
    comm: &Comm,
    path: &Path,
    frames: &[&ConFrame],
    mode: WriteMode,
    precision: Option<usize>,
) -> Result<u64, BoxErr> {
    let (bytes, starts) = collective(comm, format_frames(frames, precision), "format")?;
    let len = bytes.len() as u64;
    let world = comm.raw();

    let mut offset = 0u64;
    world.exclusive_scan_into(&len, &mut offset, ::mpi::collective::SystemOperation::sum());
    if comm.rank() == 0 {
        offset = 0; // MPI leaves rank 0's Exscan result undefined.
    }
    let mut total = 0u64;
    world.all_reduce_into(&len, &mut total, ::mpi::collective::SystemOperation::sum());

    match mode {
        WriteMode::Auto | WriteMode::MpiIo => write_mpiio(comm, path, &bytes, offset, total)?,
        WriteMode::Gather => write_gather(comm, path, &bytes, total)?,
    }

    // Sidecar from the offsets every rank already knows (best effort,
    // so a read-only sidecar location never fails the write).
    let global: Vec<u64> = starts.iter().map(|s| s + offset).collect();
    let all = gather_u64s(comm, &global);
    if let Some(offsets) = all {
        let idx = FrameIndex {
            offsets,
            data_len: total,
        };
        if !idx.is_empty() {
            let _ = frame_index::write_sidecar(path, &idx);
        } else {
            let _ = std::fs::remove_file(frame_index::sidecar_path(path));
        }
    }
    world.barrier();
    Ok(total)
}

/// Gather variable-length u64 lists to rank 0 in rank order.
fn gather_u64s(comm: &Comm, mine: &[u64]) -> Option<Vec<u64>> {
    let world = comm.raw();
    let root = world.process_at_rank(0);
    let n = mine.len() as i32;
    if comm.rank() == 0 {
        let mut counts = vec![0i32; comm.size()];
        root.gather_into_root(&n, &mut counts[..]);
        let displs: Vec<i32> = counts
            .iter()
            .scan(0i32, |acc, &c| {
                let d = *acc;
                *acc += c;
                Some(d)
            })
            .collect();
        let sum: usize = counts.iter().map(|&c| c as usize).sum();
        let mut store = vec![0u64; sum.max(1)];
        {
            let mut part = PartitionMut::new(&mut store[..sum], &counts[..], &displs[..]);
            root.gather_varcount_into_root(&mine[..], &mut part);
        }
        store.truncate(sum);
        Some(store)
    } else {
        root.gather_into(&n);
        root.gather_varcount_into(&mine[..]);
        None
    }
}

fn write_mpiio(
    comm: &Comm,
    path: &Path,
    bytes: &[u8],
    offset: u64,
    total: u64,
) -> Result<(), BoxErr> {
    let cpath = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())
        .map_err(|e| BoxErr::from(e.to_string()));
    let cpath = collective(comm, cpath, "path")?;
    let mut fh: ffi::MPI_File = unsafe { ffi::RSMPI_FILE_NULL };
    // MPI_MODE_CREATE | MPI_MODE_WRONLY (1 | 4 in MPICH and Open MPI).
    let amode = (ffi::MPI_MODE_CREATE | ffi::MPI_MODE_WRONLY) as i32;
    let rc = unsafe {
        ffi::MPI_File_open(
            comm.raw().as_raw(),
            cpath.as_ptr(),
            amode,
            ffi::RSMPI_INFO_NULL,
            &mut fh,
        )
    };
    collective(comm, mpi_rc(rc, "MPI_File_open"), "open")?;

    let result = (|| -> Result<(), BoxErr> {
        let rc = unsafe { ffi::MPI_File_set_size(fh, total as ffi::MPI_Offset) };
        collective(comm, mpi_rc(rc, "MPI_File_set_size"), "set_size")?;
        // write_at_all is collective, so every rank joins every round.
        let ch = chunk();
        let mine = bytes.len().div_ceil(ch) as u64;
        let mut rounds = 0u64;
        comm.raw().all_reduce_into(
            &mine,
            &mut rounds,
            ::mpi::collective::SystemOperation::max(),
        );
        let mut keep = [0u8; 1];
        let mut res = Ok(());
        for k in 0..rounds as usize {
            let lo = (k * ch).min(bytes.len());
            let hi = ((k + 1) * ch).min(bytes.len());
            // Empty rounds still pass a live pointer.
            let ptr = if hi > lo {
                bytes[lo..].as_ptr()
            } else {
                keep.as_mut_ptr() as *const u8
            };
            let rc = unsafe {
                ffi::MPI_File_write_at_all(
                    fh,
                    (offset + lo as u64) as ffi::MPI_Offset,
                    ptr as *const std::ffi::c_void,
                    (hi - lo) as i32,
                    ffi::RSMPI_UINT8_T,
                    ffi::RSMPI_STATUS_IGNORE,
                )
            };
            if res.is_ok() {
                res = mpi_rc(rc, "MPI_File_write_at_all");
            }
        }
        collective(comm, res, "write_at_all")
    })();
    let rc = unsafe { ffi::MPI_File_close(&mut fh) };
    result?;
    collective(comm, mpi_rc(rc, "MPI_File_close"), "close")?;
    Ok(())
}

fn write_gather(comm: &Comm, path: &Path, bytes: &[u8], total: u64) -> Result<(), BoxErr> {
    use std::io::Write;
    let world = comm.raw();
    let root = world.process_at_rank(0);
    let len = bytes.len() as u64;
    let status: Result<(), BoxErr> = if comm.rank() == 0 {
        let mut lens = vec![0u64; comm.size()];
        root.gather_into_root(&len, &mut lens[..]);
        let mut file_err: Option<String> = None;
        let mut file = match std::fs::File::create(path) {
            Ok(f) => Some(f),
            Err(e) => {
                file_err = Some(e.to_string());
                None
            }
        };
        let mut sink = |chunk: &[u8], file: &mut Option<std::fs::File>| {
            if let Some(f) = file.as_mut() {
                if let Err(e) = f.write_all(chunk) {
                    file_err.get_or_insert(e.to_string());
                }
            }
        };
        // Ranks always send so nobody blocks, even if the file failed.
        if total <= gatherv_max() {
            let counts: Vec<i32> = lens.iter().map(|&l| l as i32).collect();
            let displs: Vec<i32> = counts
                .iter()
                .scan(0i32, |a, &c| {
                    let d = *a;
                    *a += c;
                    Some(d)
                })
                .collect();
            let mut store = vec![0u8; (total as usize).max(1)];
            {
                let mut part =
                    PartitionMut::new(&mut store[..total as usize], &counts[..], &displs[..]);
                root.gather_varcount_into_root(bytes, &mut part);
            }
            sink(&store[..total as usize], &mut file);
        } else {
            sink(bytes, &mut file);
            for (k, &l) in lens.iter().enumerate().skip(1) {
                let mut left = l as usize;
                while left > 0 {
                    let (chunk, _) = world.process_at_rank(k as i32).receive_vec::<u8>();
                    left -= chunk.len();
                    sink(&chunk, &mut file);
                }
            }
        }
        drop(sink);
        if let Some(f) = file.as_mut() {
            if let Err(e) = f.sync_all() {
                file_err.get_or_insert(e.to_string());
            }
        }
        match file_err {
            Some(e) => Err(e.into()),
            None => Ok(()),
        }
    } else {
        root.gather_into(&len);
        if total <= gatherv_max() {
            let keep = [0u8; 1];
            root.gather_varcount_into(if bytes.is_empty() { &keep[..0] } else { bytes });
        } else {
            for c in bytes.chunks(chunk()) {
                root.send(c);
            }
        }
        Ok(())
    };
    // Rank 0 alone knows whether the file write worked.
    let msg = match &status {
        Ok(()) => vec![1u8],
        Err(e) => [&[0u8][..], e.to_string().as_bytes()].concat(),
    };
    let got = comm.bcast_bytes(0, if comm.rank() == 0 { &msg } else { &[] });
    match got.split_first() {
        Some((1, _)) => Ok(()),
        Some((_, m)) => Err(format!("rank 0 write: {}", String::from_utf8_lossy(m)).into()),
        None => Err("empty broadcast".into()),
    }
}

/// C ABI: write this rank's frames collectively on a Fortran communicator.
///
/// `mode` is 0 (auto), 1 (MPI-IO) or 2 (gather to rank 0).
/// `precision < 0` uses the writer default. Writes the total file size
/// to `*total_bytes`. Returns 0 on every rank, or -1 on every rank if
/// any rank fails. `frames` may be NULL when `num_frames` is 0.
///
/// # Safety
/// MPI must be initialized; `comm_f` must be a live intra-communicator;
/// `path_c` must be a NUL-terminated string; `frames` must hold
/// `num_frames` live frame handles. Every rank must call this.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_mpi_write_block_f(
    comm_f: ffi::RSMPI_Fint,
    path_c: *const std::ffi::c_char,
    frames: *const *const crate::ffi::RKRConFrame,
    num_frames: usize,
    mode: i32,
    precision: i32,
    total_bytes: *mut u64,
) -> i32 {
    let comm = match unsafe { Comm::dup_fint(comm_f) } {
        Ok(c) => c,
        Err(_) => return -1,
    };
    let args =
        (!path_c.is_null() && !total_bytes.is_null() && (num_frames == 0 || !frames.is_null()))
            .then(|| unsafe { std::ffi::CStr::from_ptr(path_c) }.to_str().ok())
            .flatten()
            .zip(WriteMode::from_i32(mode));
    if !agree(&comm, args.is_some()) {
        return -1;
    }
    let (path, mode) = args.unwrap();
    let refs: Option<Vec<&ConFrame>> = (0..num_frames)
        .map(|i| unsafe { (*frames.add(i) as *const ConFrame).as_ref() })
        .collect();
    if !agree(&comm, refs.is_some()) {
        return -1;
    }
    let refs = refs.unwrap();
    let prec = (precision >= 0).then_some(precision as usize);
    match write_block_refs(&comm, Path::new(path), &refs, mode, prec) {
        Ok(t) => {
            unsafe { *total_bytes = t };
            0
        }
        Err(_) => -1,
    }
}
