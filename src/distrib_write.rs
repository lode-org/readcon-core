//! Collective write: every rank of a caller-supplied communicator
//! contributes its frames and the file holds them in rank order.
//!
//! Each rank rebuilds its frames through [`ConFrameBuilder`](crate::types::ConFrameBuilder)
//! and then formats them with the serial [`ConFrameWriter`], so the
//! bytes depend only on the frames and match a binding rewrite
//! (`con_spec_minor` included). One `MPI_Allgather` of the local byte
//! lengths gives every rank its file offset and the total, and the
//! output is byte-identical to a serial write of the rank-ordered
//! frames for any rank count (including ranks with no frames).
//!
//! Modes:
//!
//! - [`WriteMode::MpiIo`]: the same publish as
//!   [`crate::writer::publish_ranked_slices`]. Rank 0 allocates a fresh
//!   file with [`crate::writer::begin_shared_store`]. A multi-frame group
//!   is spelled into that mapping, which removes the second copy. A wide
//!   frame is formatted, then stored. On ext2, ext3, ext4, XFS, and btrfs,
//!   rank 0 pwrites every slice in order, because concurrent pwrites of one
//!   fresh local inode contend. That store is still slower than a warm
//!   overwrite and slower than a plain copy of the same million-atom bytes.
//!   Every other filesystem, including tmpfs, Lustre, GPFS, BeeGFS, and NFS,
//!   keeps a per-rank store so each rank writes its own range.
//!   `READCON_RANKED_WRITE=parallel` or `sequential`, read on rank 0,
//!   overrides the choice.
//!   [`crate::writer::commit_shared_store`] publishes the file. No spare is
//!   left behind. `rewrite` instead fills `path` + `.rewrite`.
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
use ::mpi::point_to_point::send_receive_into;
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
/// `rewrite == false` publishes a fresh file and leaves no `.rewrite`
/// sibling. `rewrite == true` is the spare described on [`write_ranked_bytes`].
pub fn write_block(
    comm: &Comm,
    path: &Path,
    frames: &[ConFrame],
    mode: WriteMode,
    precision: Option<usize>,
    rewrite: bool,
    keep_spare: bool,
) -> Result<u64, BoxErr> {
    let refs: Vec<&ConFrame> = frames.iter().collect();
    write_block_refs(comm, path, &refs, mode, precision, rewrite, keep_spare)
}

/// [`write_block`] over borrowed frames (used by the C ABI).
/// Write each rank's bytes in rank order. Rank 0's buffer is the start
/// of the file. Used when one frame's atom lines are split across ranks.
/// The default (`rewrite == false`) is a fresh file published by
/// [`crate::writer::commit_shared_store`]. `rewrite == true` fills
/// `path` + `.rewrite` and renames that over `path`. `keep_spare` parks
/// the previous inode there, a second copy of the file.
pub fn write_ranked_bytes(
    comm: &Comm,
    path: &Path,
    bytes: &[u8],
    rewrite: bool,
    keep_spare: bool,
) -> Result<u64, BoxErr> {
    let len = bytes.len() as u64;
    let world = comm.raw();
    let mut offset = 0u64;
    world.exclusive_scan_into(&len, &mut offset, ::mpi::collective::SystemOperation::sum());
    if comm.rank() == 0 {
        offset = 0;
    }
    let mut total = 0u64;
    world.all_reduce_into(&len, &mut total, ::mpi::collective::SystemOperation::sum());
    write_pwrite(comm, path, bytes, offset, total, rewrite, keep_spare)?;
    world.barrier();
    Ok(total)
}

fn write_pwrite(
    comm: &Comm,
    path: &Path,
    bytes: &[u8],
    offset: u64,
    total: u64,
    rewrite: bool,
    keep_spare: bool,
) -> Result<(), BoxErr> {
    if rewrite {
        return write_pwrite_spare(comm, path, bytes, offset, total, keep_spare);
    }
    // Rank 0's file is the same unpublished inode `commit_shared_store`
    // renames onto `path`. fallocate of the whole length happens once,
    // inside `begin_shared_store`, before any rank writes.
    let (held, tmp) = stage_store(comm, path, total)?;
    // 0 = each rank writes its slice, 1 = rank 0 writes them in order,
    // 2 = rank 0 rejected READCON_RANKED_WRITE.
    let mut kind = [0u8];
    let mut choice_err = None;
    if comm.rank() == 0 {
        match std::fs::File::open(&tmp) {
            Ok(file) => match crate::writer::choose_ranked_store(&file) {
                Ok(crate::writer::RankedStore::Parallel) => kind[0] = 0,
                Ok(crate::writer::RankedStore::Sequential) => kind[0] = 1,
                Err(err) => {
                    kind[0] = 2;
                    choice_err = Some(err);
                }
            },
            Err(err) => {
                kind[0] = 2;
                choice_err = Some(err.to_string());
            }
        }
    }
    comm.raw().process_at_rank(0).broadcast_into(&mut kind);
    let wrote = match kind[0] {
        0 => (|| -> std::io::Result<()> {
            let file = std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&tmp)?;
            store_ranked_slice(&file, bytes, offset)
        })()
        .map_err(BoxErr::from),
        1 => write_ranked_sequential(comm, &tmp, bytes, total),
        _ => Err(choice_err
            .unwrap_or_else(|| "ranked store failed on rank 0".to_string())
            .into()),
    };
    if let Err(err) = collective(comm, wrote, "pwrite") {
        drop(held);
        return Err(err);
    }
    let published = if let Some(store) = held {
        crate::writer::commit_shared_store(store, path).map_err(BoxErr::from)
    } else {
        Ok(())
    };
    collective(comm, published, "publish")?;
    Ok(())
}

/// One sequential pwrite of the whole file. Slices arrive in rank order,
/// so the write starts at offset 0. Used on ext2, ext3, ext4, XFS, and btrfs.
fn write_ranked_sequential(
    comm: &Comm,
    tmp: &Path,
    bytes: &[u8],
    total: u64,
) -> Result<(), BoxErr> {
    let world = comm.raw();
    if comm.rank() == 0 {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(tmp)
            .map_err(|err| err.to_string())?;
        let mut at = 0u64;
        if !bytes.is_empty() {
            pwrite_all(&file, bytes, at).map_err(|err| err.to_string())?;
        }
        at += bytes.len() as u64;
        for src in 1..comm.size() {
            let (chunk, _) = world.process_at_rank(src as i32).receive_vec::<u8>();
            if !chunk.is_empty() {
                pwrite_all(&file, &chunk, at).map_err(|err| err.to_string())?;
            }
            at += chunk.len() as u64;
        }
        if at != total {
            return Err(format!("ranked store wrote {at} bytes of {total}").into());
        }
        Ok(())
    } else {
        world.process_at_rank(0).send(bytes);
        Ok(())
    }
}

fn write_spelled(
    comm: &Comm,
    path: &Path,
    frames: &[&ConFrame],
    frame_lens: &[usize],
) -> Result<u64, BoxErr> {
    let local: usize = frame_lens.iter().sum();
    let share = [local as u64, frames.len() as u64];
    let mut gathered = vec![0u64; comm.size() * 2];
    comm.raw().all_gather_into(&share[..], &mut gathered[..]);
    let mut offset = 0u64;
    for rank in 0..comm.rank() {
        offset += gathered[rank * 2];
    }
    let total: u64 = gathered.iter().step_by(2).copied().sum();
    let lengths: Vec<u64> = gathered.iter().step_by(2).copied().collect();
    let frame_counts: Vec<u64> = gathered.iter().skip(1).step_by(2).copied().collect();
    let mut starts = Vec::with_capacity(frame_lens.len());
    let mut at = 0u64;
    for len in frame_lens {
        starts.push(at);
        at += *len as u64;
    }
    let (mut held, tmp) = stage_store(comm, path, total)?;
    let page = 4096u64;
    let aligned = offset & !(page - 1);
    let delta = (offset - aligned) as usize;
    let mapped = (|| -> Result<Option<memmap2::MmapMut>, BoxErr> {
        if local == 0 {
            return Ok(None);
        }
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&tmp)
            .map_err(|err| err.to_string())?;
        // SAFETY: `aligned` is a multiple of the page, and the span stays
        // inside the file rank 0 allocated.
        let mut map = unsafe {
            memmap2::MmapOptions::new()
                .offset(aligned)
                .len(delta + local)
                .map_mut(&file)
                .map_err(|err| err.to_string())?
        };
        crate::writer::advise_shared_store(&file, map.as_mut_ptr(), map.len());
        crate::writer::format_group_into(frames, &mut map[delta..delta + local], None, false, true)
            .map_err(|err| err.to_string())?;
        Ok(Some(map))
    })();
    let map = match collective(comm, mapped, "spell") {
        Ok(map) => map,
        Err(err) => {
            drop(held);
            return Err(err);
        }
    };
    let bytes: &[u8] = map
        .as_ref()
        .map(|mapped| &mapped[delta..delta + local])
        .unwrap_or(&[]);
    let ready = local_ready(offset, bytes, total);
    let published = if let Some(store) = held.take() {
        crate::writer::commit_shared_store(store, path).map_err(BoxErr::from)
    } else {
        Ok(())
    };
    collective(comm, published, "publish")?;
    publish_index(
        comm,
        path,
        &lengths,
        &frame_counts,
        offset,
        &starts,
        bytes,
        total,
        ready,
    )?;
    Ok(total)
}

/// Rank 0 fallocates one fresh file of `total` bytes and every rank
/// receives the path of that inode.
fn stage_store(
    comm: &Comm,
    path: &Path,
    total: u64,
) -> Result<(Option<crate::writer::SharedStore>, std::path::PathBuf), BoxErr> {
    let mut held = None;
    let mut create_err = None;
    let encoded = if comm.rank() == 0 {
        match crate::writer::begin_shared_store(path, total) {
            Ok(store) => {
                let encoded = store.path().as_os_str().as_encoded_bytes().to_vec();
                held = Some(store);
                encoded
            }
            Err(err) => {
                create_err = Some(err.to_string());
                Vec::new()
            }
        }
    } else {
        Vec::new()
    };
    let raw = bcast_short(comm, &encoded);
    if raw.is_empty() {
        return Err(create_err
            .unwrap_or_else(|| "create failed on rank 0".to_string())
            .into());
    }
    // SAFETY: `raw` is the path rank 0 just exposed for this inode.
    let tmp =
        std::path::PathBuf::from(unsafe { std::ffi::OsString::from_encoded_bytes_unchecked(raw) });
    Ok((held, tmp))
}

fn write_pwrite_spare(
    comm: &Comm,
    path: &Path,
    bytes: &[u8],
    offset: u64,
    total: u64,
    keep_spare: bool,
) -> Result<(), BoxErr> {
    let spare = crate::writer::rewrite_names(path)
        .map(|(spare, _hold)| spare)
        .map_err(BoxErr::from);
    let spare = collective(comm, spare, "spare")?;
    let prepared = if comm.rank() == 0 {
        if let Some(parent) = path.parent().filter(|dir| !dir.as_os_str().is_empty()) {
            let _ = std::fs::create_dir_all(parent);
        }
        open_ranked_spare(path, total).map(|_| ())
    } else {
        Ok(())
    };
    if let Err(err) = collective(comm, prepared.map_err(BoxErr::from), "create") {
        return Err(err);
    }
    let wrote = (|| -> std::io::Result<()> {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&spare)?;
        store_ranked_slice(&file, bytes, offset)
    })();
    if let Err(err) = collective(comm, wrote.map_err(BoxErr::from), "pwrite") {
        return Err(err);
    }
    let published = if comm.rank() == 0 {
        crate::writer::publish_rewrite(&spare, path, keep_spare).map_err(BoxErr::from)
    } else {
        Ok(())
    };
    collective(comm, published, "publish")?;
    Ok(())
}

fn store_ranked_slice(file: &std::fs::File, bytes: &[u8], offset: u64) -> std::io::Result<()> {
    if bytes.is_empty() {
        return Ok(());
    }
    if crate::writer::file_is_tmpfs(file) {
        copy_mapped(file, bytes, offset)
    } else {
        pwrite_all(file, bytes, offset)
    }
}

fn open_ranked_spare(path: &Path, total: u64) -> std::io::Result<std::path::PathBuf> {
    let spare = crate::writer::prepare_rewrite_spare(path)?;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(&spare)?;
    if file.metadata()?.len() != total {
        file.set_len(total)?;
    }
    Ok(spare)
}

/// One broadcast of a short blob. `0xffff` in the length slot means the
/// blob did not fit and the two-step broadcast follows.
fn bcast_short(comm: &Comm, data: &[u8]) -> Vec<u8> {
    let mut buf = [0u8; 1024];
    if comm.rank() == 0 {
        if data.len() + 2 > buf.len() {
            buf[0] = 0xff;
            buf[1] = 0xff;
        } else {
            let n = data.len() as u16;
            buf[..2].copy_from_slice(&n.to_le_bytes());
            buf[2..2 + data.len()].copy_from_slice(data);
        }
    }
    comm.raw().process_at_rank(0).broadcast_into(&mut buf[..]);
    let n = u16::from_le_bytes([buf[0], buf[1]]) as usize;
    if n == 0xffff {
        return comm.bcast_bytes(0, if comm.rank() == 0 { data } else { &[] });
    }
    buf[2..2 + n].to_vec()
}

/// Create `path` at `total` bytes, or leave it when it is already that long.
///
/// Truncating a file we are about to fill frees every page and faults
/// them back. Rank 0 did that alone, so eight ranks waited on one
/// free of the whole trajectory. A same-length rewrite keeps the pages.
fn prepare_ranked_file(path: &Path, total: u64) -> std::io::Result<()> {
    if let Ok(meta) = std::fs::metadata(path)
        && meta.len() == total
    {
        return Ok(());
    }
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)?;
    file.set_len(total)?;
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
    crate::writer::advise_shared_store(file, map.as_mut_ptr(), map.len());
    map[delta..delta + body.len()].copy_from_slice(body);
    Ok(())
}

fn pwrite_all(file: &std::fs::File, buf: &[u8], mut offset: u64) -> std::io::Result<()> {
    if buf.is_empty() {
        return Ok(());
    }
    #[cfg(unix)]
    {
        use std::os::unix::io::AsRawFd;
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
    #[cfg(windows)]
    {
        use std::os::windows::fs::FileExt;
        let mut written = 0usize;
        while written < buf.len() {
            let n = file.seek_write(&buf[written..], offset)?;
            if n == 0 {
                return Err(std::io::Error::new(std::io::ErrorKind::WriteZero, "pwrite"));
            }
            written += n;
            offset += n as u64;
        }
        Ok(())
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (file, buf, offset);
        Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "ranked pwrite",
        ))
    }
}

pub fn write_block_refs(
    comm: &Comm,
    path: &Path,
    frames: &[&ConFrame],
    mode: WriteMode,
    precision: Option<usize>,
    rewrite: bool,
    keep_spare: bool,
) -> Result<u64, BoxErr> {
    // Every rank takes the same branch. An empty rank can join a priced
    // group; a rank whose frames do not price falls the whole group back
    // to format-then-store.
    let can_spell =
        !rewrite && precision.is_none() && matches!(mode, WriteMode::Auto | WriteMode::MpiIo);
    let priced = if can_spell && frames.len() >= 2 {
        crate::writer::cached_packed_lengths(frames, 1, None, false, true)
    } else {
        None
    };
    if can_spell && agree(comm, priced.is_some() || frames.is_empty()) {
        return write_spelled(comm, path, frames, &priced.unwrap_or_default());
    }
    // One allgather replaces the exclusive scan, the length reduction,
    // and the format agree. `u64::MAX` is a format error; a real block
    // cannot be that long.
    let formatted = format_frames(frames, precision);
    let share = match &formatted {
        Ok((bytes, starts)) => [bytes.len() as u64, starts.len() as u64],
        Err(_) => [u64::MAX, 0],
    };
    let mut gathered = vec![0u64; comm.size() * 2];
    comm.raw().all_gather_into(&share[..], &mut gathered[..]);
    if gathered.iter().step_by(2).any(|&len| len == u64::MAX) {
        return Err(match formatted {
            Err(err) => format!("rank {}: format: {err}", comm.rank()).into(),
            Ok(_) => "format failed on another rank".into(),
        });
    }
    let (bytes, starts) = formatted?;
    let mut offset = 0u64;
    for rank in 0..comm.rank() {
        offset += gathered[rank * 2];
    }
    let total: u64 = gathered.iter().step_by(2).copied().sum();
    let lengths: Vec<u64> = gathered.iter().step_by(2).copied().collect();
    let frame_counts: Vec<u64> = gathered.iter().skip(1).step_by(2).copied().collect();

    match mode {
        WriteMode::Auto | WriteMode::MpiIo => {
            // The block hash reads the formatted bytes and does not call
            // MPI, so it runs beside the store. Page faults leave the
            // core idle; the hash uses that time instead of adding a
            // pass after the file is published.
            let ready = std::thread::scope(|scope| {
                let job = scope.spawn(|| local_ready(offset, &bytes, total));
                let stored = write_pwrite(comm, path, &bytes, offset, total, rewrite, keep_spare);
                let ready = job.join().unwrap_or_else(|_| LocalReady {
                    hashes: Vec::new(),
                    tail: None,
                });
                stored.map(|()| ready)
            })?;
            publish_index(
                comm,
                path,
                &lengths,
                &frame_counts,
                offset,
                &starts,
                &bytes,
                total,
                ready,
            )?;
        }
        WriteMode::Gather => {
            write_gather(comm, path, &bytes, total)?;
            let ready = local_ready(offset, &bytes, total);
            publish_index(
                comm,
                path,
                &lengths,
                &frame_counts,
                offset,
                &starts,
                &bytes,
                total,
                ready,
            )?;
        }
    }
    Ok(total)
}

fn pack_slice_parts(parts: &frame_index::SliceParts) -> Vec<u8> {
    let mut out =
        Vec::with_capacity(16 + parts.fragments.iter().map(|(_, b)| b.len()).sum::<usize>());
    out.extend_from_slice(&(parts.hashed.len() as u64).to_le_bytes());
    for &(idx, hash) in &parts.hashed {
        out.extend_from_slice(&idx.to_le_bytes());
        out.extend_from_slice(&hash.to_le_bytes());
    }
    out.extend_from_slice(&(parts.fragments.len() as u64).to_le_bytes());
    for (off, bytes) in &parts.fragments {
        out.extend_from_slice(&off.to_le_bytes());
        out.extend_from_slice(&(bytes.len() as u64).to_le_bytes());
        out.extend_from_slice(bytes);
    }
    out
}

fn unpack_slice_parts(mut buf: &[u8]) -> Result<frame_index::SliceParts, String> {
    fn take<'a>(buf: &mut &'a [u8], n: usize) -> Result<&'a [u8], String> {
        if buf.len() < n {
            return Err("short slice-part payload".into());
        }
        let (head, rest) = buf.split_at(n);
        *buf = rest;
        Ok(head)
    }
    fn u64_le(buf: &mut &[u8]) -> Result<u64, String> {
        let bytes = take(buf, 8)?;
        Ok(u64::from_le_bytes(bytes.try_into().unwrap()))
    }
    let n_hashed = usize::try_from(u64_le(&mut buf)?).map_err(|err| err.to_string())?;
    let mut hashed = Vec::with_capacity(n_hashed);
    for _ in 0..n_hashed {
        hashed.push((u64_le(&mut buf)?, u64_le(&mut buf)?));
    }
    let n_frags = usize::try_from(u64_le(&mut buf)?).map_err(|err| err.to_string())?;
    let mut fragments = Vec::with_capacity(n_frags);
    for _ in 0..n_frags {
        let off = u64_le(&mut buf)?;
        let len = usize::try_from(u64_le(&mut buf)?).map_err(|err| err.to_string())?;
        fragments.push((off, take(&mut buf, len)?.to_vec()));
    }
    if !buf.is_empty() {
        return Err("trailing slice-part payload".into());
    }
    Ok(frame_index::SliceParts { hashed, fragments })
}

use frame_index::{Lead, LocalReady};

fn local_ready(start: u64, bytes: &[u8], total: u64) -> LocalReady {
    frame_index::local_ready(start, bytes, total)
}

fn finish_lead(start: u64, bytes: &[u8], total: u64, cursor_bytes: [u8; 129]) -> Lead {
    frame_index::finish_lead(start, bytes, total, cursor_bytes)
}

/// Block hashes this rank will own. Every rank can compute this from the
/// byte ranges, so the gather's counts do not need their own collective.
fn planned_hashes(start: u64, end: u64, total: u64) -> usize {
    let block = frame_index::HASH_BLOCK as u64;
    let mut count = 0usize;
    let mut pos = if start % block == 0 {
        start
    } else {
        (start / block + 1) * block
    };
    if pos > end {
        pos = end;
    }
    while pos < end {
        let take_end = (pos + block).min(end);
        let full = take_end - pos == block;
        let owned_tail = take_end == total;
        if !(full || owned_tail) {
            break;
        }
        count += 1;
        pos = take_end;
    }
    let has_lead = start % block != 0 && start < end;
    let finishes_lead = has_lead && {
        let block_end = (start / block + 1) * block;
        end >= block_end || end == total
    };
    count + usize::from(finishes_lead)
}

fn rank_has_lead(start: u64, end: u64) -> bool {
    let block = frame_index::HASH_BLOCK as u64;
    start % block != 0 && start < end
}

fn rank_has_tail(start: u64, end: u64, total: u64) -> bool {
    let block = frame_index::HASH_BLOCK as u64;
    let mut pos = if start % block == 0 {
        start
    } else {
        (start / block + 1) * block
    };
    if pos > end {
        pos = end;
    }
    while pos < end {
        let take_end = (pos + block).min(end);
        let full = take_end - pos == block;
        let owned_tail = take_end == total;
        if !(full || owned_tail) {
            break;
        }
        pos = take_end;
    }
    pos < end && pos % block == 0 && pos != total
}

fn next_nonempty(lengths: &[u64], rank: usize) -> Option<usize> {
    lengths
        .iter()
        .skip(rank + 1)
        .position(|&len| len > 0)
        .map(|step| rank + 1 + step)
}

fn prev_nonempty(lengths: &[u64], rank: usize) -> Option<usize> {
    lengths.iter().take(rank).rposition(|&len| len > 0)
}

fn rank_offset(lengths: &[u64], rank: usize) -> u64 {
    lengths.iter().take(rank).sum()
}

/// Fold per-rank slices the way the collective exchange does, with no MPI.
#[cfg(test)]
fn fold_ranked_slices(parts: &[&[u8]]) -> u64 {
    frame_index::ranked_content_hash(parts)
}

fn recv_cursor(world: &::mpi::topology::SimpleCommunicator, src: usize) -> [u8; 129] {
    let mut buf = [0u8; 129];
    world.process_at_rank(src as i32).receive_into(&mut buf[..]);
    buf
}

fn sendrecv_cursor(
    world: &::mpi::topology::SimpleCommunicator,
    dest: usize,
    src: usize,
    msg: [u8; 129],
) -> [u8; 129] {
    let mut buf = [0u8; 129];
    send_receive_into(
        &msg[..],
        &world.process_at_rank(dest as i32),
        &mut buf[..],
        &world.process_at_rank(src as i32),
    );
    buf
}

fn absorb_lead(
    offset: u64,
    bytes: &[u8],
    total: u64,
    cursor: [u8; 129],
    outgoing: &mut Option<[u8; 129]>,
) -> Option<(u64, u64)> {
    match finish_lead(offset, bytes, total, cursor) {
        Lead::Hash(pair) => Some(pair),
        Lead::Forward(next) => {
            *outgoing = Some(next);
            None
        }
    }
}

/// Move 129-byte block cursors to the rank that finishes each split block.
/// Large ranks send a tail and receive a lead in one step. A rank that
/// owns less than the rest of a block forwards the cursor afterwards.
fn exchange_cursors(
    comm: &Comm,
    lengths: &[u64],
    offset: u64,
    bytes: &[u8],
    total: u64,
    mut outgoing: Option<[u8; 129]>,
) -> Vec<(u64, u64)> {
    let world = comm.raw();
    let rank = comm.rank();
    let end = offset + bytes.len() as u64;
    let mut extra = Vec::new();
    let mut waiting = rank_has_lead(offset, end) && prev_nonempty(lengths, rank).is_some();
    let pred_ready = prev_nonempty(lengths, rank).is_some_and(|pred| {
        let start = rank_offset(lengths, pred);
        rank_has_tail(start, start + lengths[pred], total)
    });
    for hop in 0..comm.size() {
        if outgoing.is_none() && !waiting {
            break;
        }
        let dest = next_nonempty(lengths, rank);
        let src = prev_nonempty(lengths, rank);
        let can_recv = waiting && src.is_some() && (hop > 0 || pred_ready);
        let can_send = outgoing.is_some() && dest.is_some() && (!waiting || can_recv);
        if !can_recv && !can_send {
            if hop + 1 == comm.size() {
                waiting = false;
                outgoing = None;
            }
            continue;
        }
        match (outgoing.take(), can_recv, dest, src) {
            (Some(msg), true, Some(dest), Some(src)) => {
                let buf = sendrecv_cursor(world, dest, src, msg);
                if let Some(pair) = absorb_lead(offset, bytes, total, buf, &mut outgoing) {
                    extra.push(pair);
                }
                waiting = false;
            }
            (Some(msg), false, Some(dest), _) => {
                world.process_at_rank(dest as i32).send(&msg[..]);
                waiting = false;
            }
            (None, true, _, Some(src)) => {
                let buf = recv_cursor(world, src);
                if let Some(pair) = absorb_lead(offset, bytes, total, buf, &mut outgoing) {
                    extra.push(pair);
                }
                waiting = false;
            }
            _ => {
                waiting = false;
            }
        }
    }
    extra
}

fn pack_index_share(offsets: &[u64], hashes: &[(u64, u64)]) -> Vec<u8> {
    // Eight header bytes keep a rank that owns nothing off the empty
    // gather MPI rejects.
    let mut out = Vec::with_capacity(8 + offsets.len() * 8 + hashes.len() * 16);
    out.extend_from_slice(&(offsets.len() as u32).to_le_bytes());
    out.extend_from_slice(&(hashes.len() as u32).to_le_bytes());
    for offset in offsets {
        out.extend_from_slice(&offset.to_le_bytes());
    }
    for &(index, hash) in hashes {
        out.extend_from_slice(&index.to_le_bytes());
        out.extend_from_slice(&hash.to_le_bytes());
    }
    out
}

fn share_len(n_offsets: u64, n_hashes: usize) -> usize {
    8 + n_offsets as usize * 8 + n_hashes * 16
}

fn share_counts(lengths: &[u64], frame_counts: &[u64], total: u64) -> Vec<i32> {
    lengths
        .iter()
        .enumerate()
        .map(|(rank, &len)| {
            let start = rank_offset(lengths, rank);
            share_len(
                frame_counts[rank],
                planned_hashes(start, start + len, total),
            ) as i32
        })
        .collect()
}

fn unpack_index_shares(buf: &[u8], counts: &[i32]) -> (Vec<u64>, Vec<(u64, u64)>) {
    let mut offsets = Vec::new();
    let mut hashes = Vec::new();
    let mut at = 0usize;
    for &count in counts {
        let n = count as usize;
        if n < 8 || at + n > buf.len() {
            at += n;
            continue;
        }
        let piece = &buf[at..at + n];
        let n_off = u32::from_le_bytes(piece[..4].try_into().unwrap()) as usize;
        let n_hash = u32::from_le_bytes(piece[4..8].try_into().unwrap()) as usize;
        let mut cursor = 8usize;
        for _ in 0..n_off {
            if cursor + 8 > piece.len() {
                break;
            }
            offsets.push(u64::from_le_bytes(
                piece[cursor..cursor + 8].try_into().unwrap(),
            ));
            cursor += 8;
        }
        for _ in 0..n_hash {
            if cursor + 16 > piece.len() {
                break;
            }
            let index = u64::from_le_bytes(piece[cursor..cursor + 8].try_into().unwrap());
            let hash = u64::from_le_bytes(piece[cursor + 8..cursor + 16].try_into().unwrap());
            if index != u64::MAX {
                hashes.push((index, hash));
            }
            cursor += 16;
        }
        at += n;
    }
    (offsets, hashes)
}

/// One gather of the frame offsets each rank already has and the block
/// hashes of its bytes. Rank 0 writes the sidecar. Those bytes match a
/// fresh fingerprint of the file.
fn publish_index(
    comm: &Comm,
    path: &Path,
    lengths: &[u64],
    frame_counts: &[u64],
    offset: u64,
    starts: &[u64],
    bytes: &[u8],
    total: u64,
    ready: LocalReady,
) -> Result<(), BoxErr> {
    let mut hashes = ready.hashes;
    hashes.extend(exchange_cursors(
        comm, lengths, offset, bytes, total, ready.tail,
    ));
    let planned = planned_hashes(offset, offset + bytes.len() as u64, total);
    if hashes.len() > planned {
        hashes.truncate(planned);
    }
    while hashes.len() < planned {
        // A missing block stays out of the fold. The plan and the bytes
        // agree in the split-hash test; this only keeps the gather sized.
        hashes.push((u64::MAX, 0));
    }
    let global: Vec<u64> = starts.iter().map(|start| start + offset).collect();
    let payload = pack_index_share(&global, &hashes);
    let counts = share_counts(lengths, frame_counts, total);
    let world = comm.raw();
    let root = world.process_at_rank(0);
    if comm.rank() == 0 {
        let displs: Vec<i32> = counts
            .iter()
            .scan(0i32, |acc, &count| {
                let at = *acc;
                *acc += count;
                Some(at)
            })
            .collect();
        let sum: usize = counts.iter().map(|&count| count as usize).sum();
        let mut store = vec![0u8; sum.max(1)];
        {
            let mut part = PartitionMut::new(&mut store[..sum], &counts[..], &displs[..]);
            root.gather_varcount_into_root(&payload[..], &mut part);
        }
        let (offsets, found) = unpack_index_shares(&store[..sum], &counts);
        if offsets.is_empty() {
            let _ = std::fs::remove_file(frame_index::sidecar_path(path));
        } else {
            let mut blocks = vec![0u64; total.div_ceil(frame_index::HASH_BLOCK as u64) as usize];
            for (index, hash) in found {
                if let Some(slot) = blocks.get_mut(index as usize) {
                    *slot = hash;
                }
            }
            let content = frame_index::fold_block_hashes(total, &blocks);
            let idx = FrameIndex {
                offsets,
                data_len: total,
            };
            let _ = frame_index::write_sidecar_known(path, &idx, content);
        }
    } else {
        root.gather_varcount_into(&payload[..]);
    }
    Ok(())
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
    unsafe {
        mpi_write_block(
            comm_f,
            path_c,
            frames,
            num_frames,
            mode,
            precision,
            total_bytes,
            false,
            false,
        )
    }
}

/// Spare form of [`rkr_mpi_write_block_f`]. `keep_spare != 0` parks the
/// previous inode at `path` + `.rewrite`.
///
/// # Safety
/// Same as [`rkr_mpi_write_block_f`]. Every rank must call this.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rkr_mpi_rewrite_block_f(
    comm_f: ffi::RSMPI_Fint,
    path_c: *const std::ffi::c_char,
    frames: *const *const crate::ffi::RKRConFrame,
    num_frames: usize,
    mode: i32,
    precision: i32,
    keep_spare: u8,
    total_bytes: *mut u64,
) -> i32 {
    unsafe {
        mpi_write_block(
            comm_f,
            path_c,
            frames,
            num_frames,
            mode,
            precision,
            total_bytes,
            true,
            keep_spare != 0,
        )
    }
}

unsafe fn mpi_write_block(
    comm_f: ffi::RSMPI_Fint,
    path_c: *const std::ffi::c_char,
    frames: *const *const crate::ffi::RKRConFrame,
    num_frames: usize,
    mode: i32,
    precision: i32,
    total_bytes: *mut u64,
    rewrite: bool,
    keep_spare: bool,
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
    match write_block_refs(
        &comm,
        Path::new(path),
        &refs,
        mode,
        prec,
        rewrite,
        keep_spare,
    ) {
        Ok(t) => {
            unsafe { *total_bytes = t };
            0
        }
        Err(_) => -1,
    }
}

#[cfg(test)]
mod ranked_store_tests {
    use crate::writer::{RankedStore, ranked_store_for_magic, ranked_store_override};

    #[test]
    fn local_block_magics_use_one_sequential_writer() {
        for magic in [0xEF53_i64, 0x5846_5342, 0x9123_683E] {
            assert_eq!(ranked_store_for_magic(magic), RankedStore::Sequential);
        }
        // A 32-bit statfs word sign-extends btrfs. The low 32 bits still match.
        let sign_extended = 0x9123_683E_u32 as i32 as i64;
        assert_eq!(
            ranked_store_for_magic(sign_extended),
            RankedStore::Sequential
        );
    }

    #[test]
    fn other_magics_keep_a_write_per_rank() {
        for magic in [0_i64, -1, 0x0102_1994, 0x6969, 0x0BD0_0BD0, 0xFF53_4642] {
            assert_eq!(
                ranked_store_for_magic(magic),
                RankedStore::Parallel,
                "magic {magic:#x}"
            );
        }
    }

    #[test]
    fn the_env_override_names_the_two_paths() {
        assert_eq!(
            ranked_store_override("parallel").unwrap(),
            RankedStore::Parallel
        );
        assert_eq!(
            ranked_store_override("sequential").unwrap(),
            RankedStore::Sequential
        );
        assert!(ranked_store_override("ext4").is_err());
        assert!(ranked_store_override("").is_err());
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

    /// Resident pages of `path`. `mincore` does not fault.
    fn resident_pages(path: &std::path::Path) -> usize {
        let file = std::fs::File::open(path).unwrap();
        let len = file.metadata().unwrap().len() as usize;
        assert!(len > 0);
        let map = unsafe { memmap2::Mmap::map(&file).unwrap() };
        let pages = len.div_ceil(4096);
        let mut present = vec![0u8; pages];
        let rc =
            unsafe { libc::mincore(map.as_ptr() as *mut libc::c_void, len, present.as_mut_ptr()) };
        assert_eq!(rc, 0, "mincore: {}", std::io::Error::last_os_error());
        present.iter().filter(|byte| *byte & 1 == 1).count()
    }

    /// A same-length ranked rewrite used to truncate the file on rank 0.
    /// That dropped every page, then the ranks faulted them back. The
    /// bytes of the previous write have to stay until the new bytes land,
    /// and a shorter file still truncates.
    #[test]
    fn a_same_length_rewrite_keeps_pages_and_bytes() {
        let path =
            std::path::PathBuf::from(format!("/dev/shm/readcon-reuse-{}", std::process::id()));
        let first = vec![0xABu8; 8192];
        std::fs::write(&path, &first).unwrap();
        // Fault the pages. A later mincore then sees the resident set.
        assert_eq!(std::fs::read(&path).unwrap(), first);
        let resident = resident_pages(&path);
        assert_eq!(resident, 2, "the first write should be fully resident");

        super::prepare_ranked_file(&path, first.len() as u64).unwrap();
        assert_eq!(
            resident_pages(&path),
            resident,
            "a same-length prepare must not drop the pages"
        );
        assert_eq!(
            std::fs::read(&path).unwrap(),
            first,
            "the previous bytes stay until the rewrite stores new ones"
        );

        let second = vec![0xCDu8; first.len()];
        {
            let file = std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .unwrap();
            copy_mapped(&file, &second, 0).unwrap();
        }
        assert_eq!(std::fs::read(&path).unwrap(), second);
        assert_eq!(resident_pages(&path), resident);

        super::prepare_ranked_file(&path, 8).unwrap();
        assert_eq!(std::fs::read(&path).unwrap().len(), 8);
        let _ = std::fs::remove_file(&path);
    }

    /// A same-length file keeps its pages, and the ranked writes still
    /// have to replace every byte. A hole, an empty rank, or a page
    /// boundary must not leave the previous contents in place.
    #[test]
    fn a_same_length_rewrite_replaces_every_byte() {
        let splits: &[&[usize]] = &[&[16], &[10, 6], &[1, 0, 15], &[4090, 20], &[3, 5, 0, 8]];
        for (case, split) in splits.iter().enumerate() {
            let total: usize = split.iter().sum();
            let path = std::path::PathBuf::from(format!(
                "/dev/shm/readcon-rewrite-{}-{case}",
                std::process::id()
            ));
            if std::fs::write(&path, vec![b'x'; total]).is_err() {
                let path = std::env::temp_dir()
                    .join(format!("readcon-rewrite-{}-{case}", std::process::id()));
                rewrite_same_length(&path, split);
                let _ = std::fs::remove_file(&path);
            } else {
                rewrite_same_length(&path, split);
                let _ = std::fs::remove_file(&path);
            }
        }
    }

    fn rewrite_same_length(path: &std::path::Path, split: &[usize]) {
        let total: usize = split.iter().sum();
        std::fs::write(path, vec![b'x'; total]).unwrap();
        super::prepare_ranked_file(path, total as u64).unwrap();
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .unwrap();
        let tmpfs = crate::writer::file_is_tmpfs(&file);
        let mut expect = Vec::with_capacity(total);
        let mut offset = 0u64;
        for (rank, &len) in split.iter().enumerate() {
            let bytes: Vec<u8> = (0..len).map(|i| b'A' + ((rank + i) % 26) as u8).collect();
            if !bytes.is_empty() && tmpfs {
                super::copy_mapped(&file, &bytes, offset).unwrap();
            } else {
                super::pwrite_all(&file, &bytes, offset).unwrap();
            }
            expect.extend_from_slice(&bytes);
            offset += len as u64;
        }
        drop(file);
        let got = std::fs::read(path).unwrap();
        assert_eq!(got, expect, "stale bytes after a same-length rewrite");
    }

    /// The default store is the shared publisher. It leaves no `.rewrite` file.
    #[test]
    fn a_fresh_ranked_file_leaves_no_rewrite_sibling() {
        let path =
            std::env::temp_dir().join(format!("readcon-fresh-rank-{}.con", std::process::id()));
        let spare = path.with_file_name(format!(
            "{}.rewrite",
            path.file_name().unwrap().to_string_lossy()
        ));
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(&spare);
        let bytes = vec![4u8; 8192];
        let store = crate::writer::begin_shared_store(&path, bytes.len() as u64).unwrap();
        let exposed = store.path().to_path_buf();
        assert!(
            !exposed
                .file_name()
                .unwrap()
                .to_string_lossy()
                .ends_with(".rewrite"),
            "the fresh store is not the spare"
        );
        {
            let file = std::fs::OpenOptions::new()
                .write(true)
                .open(&exposed)
                .unwrap();
            super::pwrite_all(&file, &bytes, 0).unwrap();
        }
        crate::writer::commit_shared_store(store, &path).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        assert!(!exposed.exists(), "the scratch name is not left behind");
        assert!(
            !spare.exists(),
            "a default ranked write leaves no .rewrite file"
        );
        let _ = std::fs::remove_file(&path);
    }

    /// Opt-in spare: the published file stays whole until rename, and the
    /// third same-length store fills the first inode.
    #[test]
    fn a_ranked_spare_reuses_the_inode_and_leaves_the_published_file() {
        use std::os::unix::fs::MetadataExt;
        let path =
            std::env::temp_dir().join(format!("readcon-rank-spare-{}.con", std::process::id()));
        let spare_name = path.with_file_name(format!(
            "{}.rewrite",
            path.file_name().unwrap().to_string_lossy()
        ));
        let hold_name = path.with_file_name(format!(
            "{}.rewrite-hold",
            path.file_name().unwrap().to_string_lossy()
        ));
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(&spare_name);
        let _ = std::fs::remove_file(&hold_name);
        let store = |bytes: &[u8]| {
            let spare = super::open_ranked_spare(&path, bytes.len() as u64).unwrap();
            let file = std::fs::OpenOptions::new()
                .write(true)
                .open(&spare)
                .unwrap();
            super::pwrite_all(&file, bytes, 0).unwrap();
            spare
        };
        let first = vec![1u8; 8192];
        let spare = store(&first);
        assert!(!path.exists());
        crate::writer::publish_rewrite(&spare, &path, true).unwrap();
        let first_ino = std::fs::metadata(&path).unwrap().ino();
        assert_eq!(std::fs::read(&path).unwrap(), first);
        let second = vec![2u8; 8192];
        let spare = store(&second);
        assert_eq!(std::fs::read(&path).unwrap(), first);
        crate::writer::publish_rewrite(&spare, &path, true).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), second);
        let third = vec![3u8; 8192];
        let spare = store(&third);
        assert_eq!(std::fs::metadata(&spare).unwrap().ino(), first_ino);
        assert_eq!(std::fs::read(&path).unwrap(), second);
        crate::writer::publish_rewrite(&spare, &path, true).unwrap();
        assert_eq!(std::fs::metadata(&path).unwrap().ino(), first_ino);
        assert_eq!(std::fs::read(&path).unwrap(), third);
        let _ = store(&vec![9u8; 8192]);
        assert_eq!(std::fs::read(&path).unwrap(), third);
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(&spare_name);
        let _ = std::fs::remove_file(&hold_name);
    }
}

#[cfg(test)]
mod slice_part_codec {
    use super::{pack_slice_parts, unpack_slice_parts};

    #[test]
    fn packed_slice_parts_round_trip() {
        let data: Vec<u8> = (0..3000).map(|i| (i % 251) as u8).collect();
        let parts = crate::frame_index::slice_block_parts(10, &data);
        let back = unpack_slice_parts(&pack_slice_parts(&parts)).unwrap();
        assert_eq!(back.hashed, parts.hashed);
        assert_eq!(back.fragments, parts.fragments);
    }
}

#[cfg(test)]
mod split_hash {
    use super::{fold_ranked_slices, local_ready, planned_hashes};
    use crate::frame_index::{HASH_BLOCK, block_hash, fold_block_hashes};

    fn one_shot(data: &[u8]) -> u64 {
        let blocks: Vec<u64> = data.chunks(HASH_BLOCK).map(block_hash).collect();
        fold_block_hashes(data.len() as u64, &blocks)
    }

    #[test]
    fn ranked_slices_match_a_one_shot_hash() {
        let data: Vec<u8> = (0..HASH_BLOCK * 2 + 3_000)
            .map(|i| (i.wrapping_mul(17)) as u8)
            .collect();
        let expect = one_shot(&data);
        let splits: &[&[usize]] = &[
            &[data.len()],
            &[1, data.len() - 1],
            &[HASH_BLOCK - 1, 1, data.len() - HASH_BLOCK],
            &[HASH_BLOCK, data.len() - HASH_BLOCK],
            &[0, 10, 0, HASH_BLOCK + 5, 0],
            &[3, 0, 8, HASH_BLOCK - 1, 40, HASH_BLOCK, 100],
            &[data.len() / 8; 8],
        ];
        for split in splits {
            let mut parts: Vec<&[u8]> = Vec::new();
            let mut at = 0usize;
            let mut owned = 0usize;
            for &len in *split {
                let end = (at + len).min(data.len());
                parts.push(&data[at..end]);
                let start = at as u64;
                let ready = local_ready(start, &data[at..end], data.len() as u64);
                let lead = if end > at && start % HASH_BLOCK as u64 != 0 {
                    let block_end = (start / HASH_BLOCK as u64 + 1) * HASH_BLOCK as u64;
                    end as u64 >= block_end || end == data.len()
                } else {
                    false
                };
                assert_eq!(
                    ready.hashes.len() + usize::from(lead),
                    planned_hashes(start, end as u64, data.len() as u64),
                    "plan drifted at {start}"
                );
                owned += ready.hashes.len() + usize::from(lead);
                at = end;
                if at == data.len() {
                    break;
                }
            }
            if at < data.len() {
                parts.push(&data[at..]);
            }
            assert!(owned > 0 || data.is_empty(), "no rank owned a block");
            assert_eq!(fold_ranked_slices(&parts), expect, "split {split:?}");
        }
    }
}
