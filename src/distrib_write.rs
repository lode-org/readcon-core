//! Collective write: every rank of a caller-supplied communicator
//! contributes its frames and the file holds them in rank order.
//!
//! Each rank rebuilds its frames through [`ConFrameBuilder`](crate::types::ConFrameBuilder)
//! and then formats them with the serial [`ConFrameWriter`], so the
//! bytes depend only on the frames and match a binding rewrite
//! (`con_spec_minor` included). `MPI_Exscan` of the local byte
//! lengths gives each rank's file offset, and the output is
//! byte-identical to a serial write of the rank-ordered frames for any
//! rank count (including ranks with no frames).
//!
//! Modes:
//!
//! - [`WriteMode::MpiIo`]: rank 0 creates the file and sets its length to
//!   the exclusive-scan total. Every rank then `pwrite`s its own bytes at
//!   that offset. Rewriting a longer file leaves no tail.
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
    let mut one = Vec::new();
    let mut starts = Vec::with_capacity(frames.len());
    for frame in frames {
        starts.push(out.len() as u64);
        one.clear();
        // The binding stamp is the header only. Cloning every atom before
        // formatting it read the frame twice.
        {
            let mut writer = match precision {
                Some(p) => ConFrameWriter::with_precision(&mut one, p),
                None => ConFrameWriter::new(&mut one),
            };
            writer.write_frame_bound(frame)?;
            writer.flush()?;
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
/// Write each rank's bytes in rank order. Rank 0's buffer is the start
/// of the file. Used when one frame's atom lines are split across ranks.
pub fn write_ranked_bytes(comm: &Comm, path: &Path, bytes: &[u8]) -> Result<u64, BoxErr> {
    let len = bytes.len() as u64;
    let world = comm.raw();
    let mut offset = 0u64;
    world.exclusive_scan_into(&len, &mut offset, ::mpi::collective::SystemOperation::sum());
    if comm.rank() == 0 {
        offset = 0;
    }
    let mut total = 0u64;
    world.all_reduce_into(&len, &mut total, ::mpi::collective::SystemOperation::sum());
    write_pwrite(comm, path, bytes, offset, total)?;
    world.barrier();
    Ok(total)
}

/// Each rank writes its own bytes at `offset`. Lengths were already
/// exchanged by an exclusive scan. Nothing is gathered to rank 0.
fn write_pwrite(
    comm: &Comm,
    path: &Path,
    bytes: &[u8],
    offset: u64,
    total: u64,
) -> Result<(), BoxErr> {
    let created = if comm.rank() == 0 {
        std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path)
            .and_then(|file| file.set_len(total))
            .map_err(BoxErr::from)
    } else {
        Ok(())
    };
    collective(comm, created, "create")?;
    comm.raw().barrier();
    // Read is required for the tmpfs shared mapping. A write-only
    // descriptor returns EACCES from mmap.
    let opened = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .map_err(BoxErr::from);
    let file = collective(comm, opened, "open")?;
    // tmpfs page faults dominate a ranked pwrite. A shared mapping of
    // this rank's slice is the same sink the single-frame path uses.
    let wrote = if !bytes.is_empty() && crate::writer::file_is_tmpfs(&file) {
        copy_mapped(&file, bytes, offset).map_err(BoxErr::from)
    } else {
        pwrite_all(&file, bytes, offset).map_err(BoxErr::from)
    };
    collective(comm, wrote, "pwrite")?;
    Ok(())
}

/// Copy `body` into the file at `offset` through a shared mapping.
fn copy_mapped(file: &std::fs::File, body: &[u8], offset: u64) -> std::io::Result<()> {
    let page = 4096u64;
    let aligned = offset & !(page - 1);
    let delta = (offset - aligned) as usize;
    let mut map = unsafe {
        memmap2::MmapOptions::new()
            .offset(aligned)
            .len(delta + body.len())
            .map_mut(file)?
    };
    map[delta..delta + body.len()].copy_from_slice(body);
    Ok(())
}

fn pwrite_all(file: &std::fs::File, buf: &[u8], mut offset: u64) -> std::io::Result<()> {
    use std::os::unix::io::AsRawFd;
    if buf.is_empty() {
        return Ok(());
    }
    let fd = file.as_raw_fd();
    let mut written = 0usize;
    while written < buf.len() {
        let n = unsafe {
            libc::pwrite(
                fd,
                buf[written..].as_ptr() as *const libc::c_void,
                buf.len() - written,
                offset as libc::off_t,
            )
        };
        if n < 0 {
            let err = std::io::Error::last_os_error();
            if err.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(err);
        }
        if n == 0 {
            return Err(std::io::Error::new(std::io::ErrorKind::WriteZero, "pwrite"));
        }
        written += n as usize;
        offset += n as u64;
    }
    Ok(())
}

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
        WriteMode::Auto | WriteMode::MpiIo => write_pwrite(comm, path, &bytes, offset, total)?,
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
            root.gather_varcount_into_root(mine, &mut part);
        }
        store.truncate(sum);
        Some(store)
    } else {
        root.gather_into(&n);
        root.gather_varcount_into(mine);
        None
    }
}

#[allow(dead_code)]
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
            if let Some(f) = file.as_mut()
                && let Err(e) = f.write_all(chunk)
            {
                file_err.get_or_insert(e.to_string());
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
        if let Some(f) = file.as_mut()
            && let Err(e) = f.sync_all()
        {
            file_err.get_or_insert(e.to_string());
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

#[cfg(test)]
mod ranked_sink_tests {
    use super::copy_mapped;

    #[test]
    fn a_tmpfs_ranked_slice_lands_at_its_offset() {
        let path =
            std::path::PathBuf::from(format!("/dev/shm/readcon-rank-map-{}", std::process::id()));
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)
            .unwrap();
        file.set_len(16).unwrap();
        assert!(
            crate::writer::file_is_tmpfs(&file),
            "a shm file is the mapped ranked sink"
        );
        copy_mapped(&file, b"abcd", 0).unwrap();
        copy_mapped(&file, b"WXYZ", 8).unwrap();
        let got = std::fs::read(&path).unwrap();
        assert_eq!(&got[..4], b"abcd");
        assert_eq!(&got[8..12], b"WXYZ");
        let _ = std::fs::remove_file(&path);
    }
}
