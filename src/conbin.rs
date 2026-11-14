//! CON-bin: one page of header, then every frame's positions as one run
//! of little-endian values, then the velocities the same way.
//!
//! [`map_file`] maps that file and faults it in place. The runs are the
//! columns: the caller does not allocate a second buffer, so the read does
//! not take a write fault per destination page. [`read_into_threads`] is the
//! `pread` fill of a caller-owned slice, kept so a measurement can pair the
//! two on the same file.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
#[cfg(unix)]
use std::os::fd::AsRawFd;
use std::path::Path;

use crate::error::ParseError;
use crate::iterators::ConFrameIterator;

const MAGIC: &[u8; 8] = b"CONBIN01";
const VERSION: u32 = 1;
const FLAG_F32: u32 = 1;
const FLAG_VELOCITY: u32 = 2;

/// Magic, version, flags, frame count, atom count, payload offset.
/// 8 + 4 + 4 + 8 + 8 + 8.
const FIELD_BYTES: usize = 40;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConBinHeader {
    pub n_frames: u64,
    pub n_atoms: u64,
    pub binary32: bool,
    pub velocities: bool,
}

impl ConBinHeader {
    pub fn position_len(&self) -> Result<usize, ParseError> {
        (self.n_frames as usize)
            .checked_mul(self.n_atoms as usize)
            .and_then(|n| n.checked_mul(3))
            .ok_or_else(|| ParseError::InvalidCount("CON-bin column length overflows".into()))
    }
}

/// How the mapped pages are made resident before the caller reads them.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Prefetch {
    /// One `MADV_POPULATE_READ` per worker, covering that worker's span.
    Span,
    /// `MADV_POPULATE_READ` in queue-sized pieces of each worker's span.
    ChunkPopulate,
    /// `posix_fadvise(POSIX_FADV_WILLNEED)` of the next queue-sized piece
    /// on a private file descriptor, issued before the caller reads.
    ChunkWillneed,
    /// Will-need the next piece, then `MADV_POPULATE_READ` the current one.
    Hybrid,
}

/// Limits read from the block queue that holds `path`.
///
/// `max_request` is `max_sectors_kb` times 1024, the largest request that
/// queue accepts
/// (<https://docs.kernel.org/admin-guide/abi-stable.html#abi-sys-block-disk-queue-max-sectors-kb>).
/// `nr_requests` is how many requests the queue can hold
/// (<https://docs.kernel.org/admin-guide/abi-stable.html#abi-sys-block-disk-queue-nr-requests>).
/// `read_ahead` is `read_ahead_kb`
/// times 1024, the kernel readahead window. A partition is walked to its
/// parent disk, which is the sysfs node that holds `queue/`. A missing
/// queue file yields the page size, the unit `madvise` accepts, and a
/// missing `nr_requests` yields 1. `rotational` is recorded and does not
/// select the plan.
#[derive(Debug, Clone, Copy)]
pub struct QueueLimits {
    pub page: usize,
    pub logical_block: usize,
    pub max_request: usize,
    pub nr_requests: usize,
    pub read_ahead: usize,
    /// Hardware queues. blk-mq applies `nr_requests` to each one.
    pub nr_hw_queues: usize,
    /// `queue/rotational` is 1 when the queue file says so.
    /// The flag is recorded. It does not select the read plan.
    pub rotational: bool,
}

impl QueueLimits {
    /// Page-sized stand-in used when the file has no block queue.
    ///
    /// btrfs, tmpfs, overlayfs and NFS have no `queue/` directory.
    /// The page is the unit `madvise` accepts, so one request of one
    /// page is the stand-in.
    pub fn page_default(page: usize) -> Self {
        Self {
            page,
            logical_block: page,
            max_request: page,
            nr_requests: 1,
            read_ahead: page,
            nr_hw_queues: 1,
            rotational: false,
        }
    }

    pub fn of(path: &Path) -> Result<Self, ParseError> {
        let page = page_size()?;
        #[cfg(target_os = "linux")]
        {
            let file =
                File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
            let dev = std::os::unix::fs::MetadataExt::dev(
                &file
                    .metadata()
                    .map_err(|err| ParseError::ValidationError(err.to_string()))?,
            );
            Ok(Self::from_sysfs(dev, page))
        }
        #[cfg(not(target_os = "linux"))]
        {
            let _ = path;
            Ok(Self::page_default(page))
        }
    }

    #[cfg(target_os = "linux")]
    fn from_sysfs(dev: u64, page: usize) -> Self {
        let num =
            |name: &str| queue_text(dev, name).and_then(|text| text.trim().parse::<usize>().ok());
        let logical = num("logical_block_size").unwrap_or(page).max(1);
        let max_request = num("max_sectors_kb")
            .map(|kb| kb.saturating_mul(1024))
            .unwrap_or(page)
            .max(page);
        let nr_requests = num("nr_requests").unwrap_or(1).max(1);
        let read_ahead = num("read_ahead_kb")
            .map(|kb| kb.saturating_mul(1024))
            .unwrap_or(page)
            .max(page);
        let rotational = num("rotational").unwrap_or(0) != 0;
        Self {
            page,
            logical_block: logical,
            max_request,
            nr_requests,
            read_ahead,
            nr_hw_queues: hw_queue_count(dev),
            rotational,
        }
    }

    /// Bytes one worker submits while the others share the same queue.
    ///
    /// The queue holds `nr_requests` requests of `max_request` bytes.
    /// `workers` share it, so each gets `nr_requests / workers` requests,
    /// or one request when the queue is shorter than the worker count.
    /// The span is at least the kernel readahead window, because a shorter
    /// hint still pulls that window, and it is aligned down to the page.
    pub fn worker_span(&self, workers: usize) -> usize {
        let workers = workers.max(1);
        let requests = (self.nr_requests / workers).max(1);
        let queued = requests.saturating_mul(self.max_request);
        let span = queued.max(self.read_ahead).max(self.page);
        let aligned = span & !(self.page - 1);
        aligned.max(self.page)
    }
}

#[cfg(target_os = "linux")]
pub(crate) fn dev_nums(dev: u64) -> (u64, u64) {
    // glibc `sys/sysmacros.h`, the encoding major(3) documents.
    let major = ((dev >> 32) & 0xffff_f000) | ((dev >> 8) & 0xfff);
    let minor = ((dev >> 12) & 0xffff_ff00) | (dev & 0xff);
    (major, minor)
}

/// `queue/nr_hw_queues` when the file exists. Otherwise the number of
/// directories under `mq/`, which blk-mq creates, one per hardware queue.
/// A missing tree means one queue.
#[cfg(target_os = "linux")]
fn hw_queue_count(dev: u64) -> usize {
    if let Some(text) = queue_text(dev, "nr_hw_queues")
        && let Ok(count) = text.trim().parse::<usize>()
    {
        return count.max(1);
    }
    let (major, minor) = dev_nums(dev);
    let mut dir = std::path::PathBuf::from(format!("/sys/dev/block/{major}:{minor}"));
    if dir.join("partition").is_file() {
        dir.push("..");
    }
    let mq = dir.join("mq");
    let count = std::fs::read_dir(&mq)
        .ok()
        .map(|entries| entries.filter_map(|entry| entry.ok()).count())
        .unwrap_or(0);
    count.max(1)
}

/// Read one queue file. A partition node has `partition` and no `queue`.
/// Its parent is the disk, and that directory holds `queue/`.
/// `Documentation/admin-guide/devices.rst` describes the block sysfs tree.
#[cfg(target_os = "linux")]
fn queue_text(dev: u64, name: &str) -> Option<String> {
    let (major, minor) = dev_nums(dev);
    let dir = std::path::PathBuf::from(format!("/sys/dev/block/{major}:{minor}"));
    let own = dir.join("queue").join(name);
    if let Ok(text) = std::fs::read_to_string(&own) {
        return Some(text);
    }
    if dir.join("partition").is_file() {
        let parent = dir.join("..").join("queue").join(name);
        if let Ok(text) = std::fs::read_to_string(&parent) {
            return Some(text);
        }
    }
    None
}

/// Host page size. `madvise` rejects an address that is not a multiple of it.
fn page_size() -> Result<usize, ParseError> {
    #[cfg(unix)]
    let page = {
        let page = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
        if page <= 0 {
            return Err(ParseError::ValidationError(
                "sysconf(SC_PAGESIZE) failed".into(),
            ));
        }
        page as usize
    };
    #[cfg(windows)]
    let page = {
        // dwPageSize is the DWORD after the 4-byte architecture union in
        // SYSTEM_INFO, on both 32-bit and 64-bit Windows.
        // https://learn.microsoft.com/windows/win32/api/sysinfoapi/ns-sysinfoapi-system_info
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GetSystemInfo(info: *mut std::ffi::c_void);
        }
        let mut info = [0u8; 64];
        unsafe { GetSystemInfo(info.as_mut_ptr().cast()) };
        u32::from_ne_bytes(info[4..8].try_into().unwrap()) as usize
    };
    if !page.is_power_of_two() || page == 0 {
        return Err(ParseError::ValidationError(
            "the host page size is not a power of two".into(),
        ));
    }
    Ok(page)
}

fn header_fields(header: &ConBinHeader, payload_off: u64) -> [u8; FIELD_BYTES] {
    let mut out = [0u8; FIELD_BYTES];
    out[..8].copy_from_slice(MAGIC);
    out[8..12].copy_from_slice(&VERSION.to_le_bytes());
    let mut flags = 0u32;
    if header.binary32 {
        flags |= FLAG_F32;
    }
    if header.velocities {
        flags |= FLAG_VELOCITY;
    }
    out[12..16].copy_from_slice(&flags.to_le_bytes());
    out[16..24].copy_from_slice(&header.n_frames.to_le_bytes());
    out[24..32].copy_from_slice(&header.n_atoms.to_le_bytes());
    out[32..40].copy_from_slice(&payload_off.to_le_bytes());
    out
}

fn parse_fields(bytes: &[u8]) -> Result<(ConBinHeader, u64), ParseError> {
    if bytes.len() < FIELD_BYTES || &bytes[..8] != MAGIC {
        return Err(ParseError::ValidationError(
            "CON-bin header is not CONBIN01".into(),
        ));
    }
    let version = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
    if version != VERSION {
        return Err(ParseError::ValidationError(format!(
            "CON-bin version {version} is not {VERSION}"
        )));
    }
    let flags = u32::from_le_bytes(bytes[12..16].try_into().unwrap());
    let offset = u64::from_le_bytes(bytes[32..40].try_into().unwrap());
    Ok((
        ConBinHeader {
            n_frames: u64::from_le_bytes(bytes[16..24].try_into().unwrap()),
            n_atoms: u64::from_le_bytes(bytes[24..32].try_into().unwrap()),
            binary32: flags & FLAG_F32 != 0,
            velocities: flags & FLAG_VELOCITY != 0,
        },
        offset,
    ))
}

/// Payload start stored in the header. Any 8-byte alignment inside the
/// file is accepted, so a file written on a 4 KiB host still opens when
/// the host page is 16 KiB or 64 KiB. An offset of 0 is not a stand-in
/// for the host page.
fn checked_payload_offset(stored: u64, file_len: usize) -> Result<usize, ParseError> {
    let off = usize::try_from(stored)
        .map_err(|_| ParseError::ValidationError("CON-bin payload offset does not fit".into()))?;
    if off < FIELD_BYTES || off > file_len || off % 8 != 0 {
        return Err(ParseError::ValidationError(
            "CON-bin payload offset is not an 8-byte aligned address inside the file".into(),
        ));
    }
    Ok(off)
}

#[derive(Clone, Copy)]
struct F64Payload {
    offset: usize,
    end: usize,
}

/// Binary64 columns with a velocity run. Binary32 and a missing velocity
/// run are errors: `sum_mapped` reads those two binary64 runs.
fn f64_payload(header_bytes: &[u8], file_len: usize) -> Result<F64Payload, ParseError> {
    let (header, stored) = parse_fields(header_bytes)?;
    if header.binary32 {
        return Err(ParseError::ValidationError(
            "CON-bin file is binary32; sum_mapped reads binary64".into(),
        ));
    }
    if !header.velocities {
        return Err(ParseError::ValidationError(
            "CON-bin file has no velocity run".into(),
        ));
    }
    let offset = checked_payload_offset(stored, file_len)?;
    let values = header
        .position_len()?
        .checked_mul(2)
        .ok_or_else(|| ParseError::InvalidCount("CON-bin column length overflows".into()))?;
    let nbytes = values
        .checked_mul(8)
        .ok_or_else(|| ParseError::InvalidCount("CON-bin column byte length overflows".into()))?;
    let end = offset
        .checked_add(nbytes)
        .ok_or_else(|| ParseError::InvalidCount("CON-bin payload offset overflows".into()))?;
    if end > file_len {
        return Err(ParseError::IncompleteFrame);
    }
    Ok(F64Payload { offset, end })
}

/// A mapped CON-bin. The position run and the velocity run are the file.
pub struct ConBinMap {
    /// `MAP_PRIVATE` copy-on-write (`MmapOptions::map_copy`). A store copies
    /// the page and does not write the file.
    pub map: memmap2::MmapMut,
    pub header: ConBinHeader,
    pub payload_off: usize,
}

impl ConBinMap {
    pub fn positions_f64(&self) -> Result<&[f64], ParseError> {
        self.run(std::mem::size_of::<f64>(), 0)
    }

    pub fn positions_f64_mut(&mut self) -> Result<&mut [f64], ParseError> {
        self.run_mut(std::mem::size_of::<f64>(), 0)
    }

    pub fn velocities_f64(&self) -> Result<&[f64], ParseError> {
        let n = self.header.position_len()?;
        self.run(std::mem::size_of::<f64>(), n)
    }

    pub fn positions_f32(&self) -> Result<&[f32], ParseError> {
        self.run(std::mem::size_of::<f32>(), 0)
    }

    pub fn velocities_f32(&self) -> Result<&[f32], ParseError> {
        let n = self.header.position_len()?;
        self.run(std::mem::size_of::<f32>(), n)
    }

    fn run<T>(&self, width: usize, column: usize) -> Result<&[T], ParseError> {
        let n = self.header.position_len()?;
        let start = self
            .payload_off
            .checked_add(column.checked_mul(width).ok_or_else(|| {
                ParseError::InvalidCount("CON-bin column byte length overflows".into())
            })?)
            .ok_or_else(|| ParseError::InvalidCount("CON-bin payload offset overflows".into()))?;
        let nbytes = n.checked_mul(width).ok_or_else(|| {
            ParseError::InvalidCount("CON-bin column byte length overflows".into())
        })?;
        let end = start.checked_add(nbytes).ok_or_else(|| {
            ParseError::InvalidCount("CON-bin column extends past the file".into())
        })?;
        if end > self.map.len() {
            return Err(ParseError::IncompleteFrame);
        }
        let bytes = &self.map[start..end];
        if !cfg!(target_endian = "little") {
            return Err(ParseError::ValidationError(
                "CON-bin is little-endian; this host cannot view it in place".into(),
            ));
        }
        if bytes.as_ptr().align_offset(std::mem::align_of::<T>()) != 0 {
            return Err(ParseError::ValidationError(
                "CON-bin payload is not aligned for its element type".into(),
            ));
        }
        // SAFETY: `bytes` is inside the map, its length is a multiple of `T`,
        // and the pointer is aligned for `T`. The file is little-endian and
        // the host is little-endian, so the bit pattern is the value.
        // The map stays borrowed for the returned slice.
        Ok(unsafe { std::slice::from_raw_parts(bytes.as_ptr().cast::<T>(), n) })
    }

    fn run_mut<T>(&mut self, width: usize, column: usize) -> Result<&mut [T], ParseError> {
        let n = self.header.position_len()?;
        let start = self
            .payload_off
            .checked_add(column.checked_mul(width).ok_or_else(|| {
                ParseError::InvalidCount("CON-bin column byte length overflows".into())
            })?)
            .ok_or_else(|| ParseError::InvalidCount("CON-bin payload offset overflows".into()))?;
        let nbytes = n.checked_mul(width).ok_or_else(|| {
            ParseError::InvalidCount("CON-bin column byte length overflows".into())
        })?;
        let end = start.checked_add(nbytes).ok_or_else(|| {
            ParseError::InvalidCount("CON-bin column extends past the file".into())
        })?;
        if end > self.map.len() {
            return Err(ParseError::IncompleteFrame);
        }
        if !cfg!(target_endian = "little") {
            return Err(ParseError::ValidationError(
                "CON-bin is little-endian; this host cannot view it in place".into(),
            ));
        }
        let ptr = self.map[start..end].as_mut_ptr();
        if ptr.align_offset(std::mem::align_of::<T>()) != 0 {
            return Err(ParseError::ValidationError(
                "CON-bin payload is not aligned for its element type".into(),
            ));
        }
        // SAFETY: same alignment and length rules as `run`. The map is
        // `MAP_PRIVATE`, so stores copy a page and do not write the file.
        Ok(unsafe { std::slice::from_raw_parts_mut(ptr.cast::<T>(), n) })
    }
}

/// Sum both binary64 columns of `path`.
///
/// The default is one `readahead` stream.
/// Two sessions on one boot compared one stream with a stream per span.
/// Neither plan won at every thread count in both.
/// The host cache was not controlled.
/// The default stays one stream, the simpler plan.
/// `nr_requests` is the depth of each hardware queue (`nr_hw_queues`
/// of them, blk-mq), not one device-wide pool.
/// Workers sum a piece after that piece is faulted in, and the piece
/// sums are added in file order. The header's payload offset, length
/// and dtype select the bytes. Binary32 and a missing velocity run are
/// errors. Other platforms map the file and sum it with no `readahead`.
pub fn sum_mapped(path: &Path, threads: usize) -> Result<f64, ParseError> {
    #[cfg(target_os = "linux")]
    {
        let limits = QueueLimits::of(path)?;
        sequential_resident_sum(path, threads.max(1), &limits)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = threads;
        plain_sum(path)
    }
}

#[cfg(not(target_os = "linux"))]
fn plain_sum(path: &Path) -> Result<f64, ParseError> {
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let map = unsafe { memmap2::Mmap::map(&file) }
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    if map.len() < FIELD_BYTES {
        return Err(ParseError::ValidationError(
            "CON-bin header is not CONBIN01".into(),
        ));
    }
    let payload = f64_payload(&map[..FIELD_BYTES], map.len())?;
    if !cfg!(target_endian = "little") {
        return Err(ParseError::ValidationError(
            "CON-bin is little-endian; this host cannot view it in place".into(),
        ));
    }
    let bytes = &map[payload.offset..payload.end];
    let ptr = bytes.as_ptr();
    if ptr.align_offset(std::mem::align_of::<f64>()) != 0 {
        return Err(ParseError::ValidationError(
            "CON-bin payload is not aligned for its element type".into(),
        ));
    }
    let data = unsafe { std::slice::from_raw_parts(ptr.cast::<f64>(), bytes.len() / 8) };
    Ok(data.iter().copied().sum())
}

#[cfg(target_os = "linux")]
fn sequential_resident_sum(
    path: &Path,
    threads: usize,
    limits: &QueueLimits,
) -> Result<f64, ParseError> {
    let owned = open_map(path)?;
    let page = limits.page;
    let len = owned.len;
    let base = owned.ptr as usize;
    let header =
        unsafe { std::slice::from_raw_parts(owned.ptr.cast::<u8>(), FIELD_BYTES.min(len)) };
    let payload = f64_payload(header, len)?;
    let request = (limits.max_request & !(page - 1)).max(page);
    let pieces = piece_list(0, len, request);
    if pages_all_resident(owned.ptr, len, page)? {
        return Ok(sum_pieces_in_order(
            base,
            payload.offset,
            payload.end,
            threads,
            &pieces,
        ));
    }
    // One stream fills the read side of the queue.
    let depth = limits.nr_requests.max(1);
    let (tx, rx) = std::sync::mpsc::sync_channel::<usize>(depth);
    let (err_tx, err_rx) = std::sync::mpsc::channel::<String>();
    let rx = std::sync::Arc::new(std::sync::Mutex::new(rx));
    let addr = owned.ptr as usize;
    let found = std::thread::scope(|scope| {
        let queued = pieces.clone();
        scope.spawn(move || {
            let fd = match File::open(path) {
                Ok(fd) => fd,
                Err(err) => {
                    let _ = err_tx.send(err.to_string());
                    return;
                }
            };
            // Keep `depth` requests in flight. Submit the next piece only
            // after the oldest one has been waited on, so the count does not
            // become depth + 1.
            let mut submitted = 0usize;
            while submitted < depth.min(queued.len()) {
                if let Err(err) = advise_readahead(&fd, queued[submitted].0, queued[submitted].1) {
                    let _ = err_tx.send(err);
                    return;
                }
                submitted += 1;
            }
            for i in 0..queued.len() {
                let (off, n) = queued[i];
                if let Err(err) = wait_resident(addr, off, n, page) {
                    let _ = err_tx.send(err);
                    return;
                }
                let _ = tx.send(i);
                if submitted < queued.len() {
                    if let Err(err) =
                        advise_readahead(&fd, queued[submitted].0, queued[submitted].1)
                    {
                        let _ = err_tx.send(err);
                        return;
                    }
                    submitted += 1;
                }
            }
        });
        let slots = std::sync::Arc::new(std::sync::Mutex::new(vec![0.0f64; pieces.len()]));
        let mut handles = Vec::with_capacity(threads);
        for _ in 0..threads {
            let rx = std::sync::Arc::clone(&rx);
            let slots = std::sync::Arc::clone(&slots);
            let pieces = pieces.clone();
            handles.push(scope.spawn(move || {
                loop {
                    let msg = rx.lock().expect("piece queue").recv();
                    let Ok(index) = msg else { break };
                    let (off, n) = pieces[index];
                    let part = sum_range(base, off, off + n, payload.offset, payload.end);
                    slots.lock().expect("piece sums")[index] = part;
                }
            }));
        }
        for handle in handles {
            handle.join().expect("column sum");
        }
        let slots = slots.lock().expect("piece sums");
        slots.iter().copied().sum::<f64>()
    });
    if let Ok(err) = err_rx.try_recv() {
        return Err(ParseError::ValidationError(err));
    }
    Ok(found)
}

/// One `readahead` stream per worker, each over a disjoint span.
///
/// The piece is `max_sectors_kb` times 1024. `nr_requests` is the depth
/// of each hardware queue, so each worker keeps
/// `max(1, nr_requests / workers)` pieces in flight.
/// Two sessions on one boot compared one stream with a stream per span.
/// Neither plan won at every thread count in both.
/// The host cache was not controlled.
/// The default stays one stream, the simpler plan.
#[cfg(target_os = "linux")]
pub fn sum_split_streams(path: &Path, threads: usize) -> Result<f64, ParseError> {
    let limits = QueueLimits::of(path)?;
    split_stream_sum(path, threads.max(1), &limits)
}

#[cfg(not(target_os = "linux"))]
pub fn sum_split_streams(path: &Path, threads: usize) -> Result<f64, ParseError> {
    let _ = threads;
    plain_sum(path)
}

#[cfg(target_os = "linux")]
fn split_stream_sum(path: &Path, threads: usize, limits: &QueueLimits) -> Result<f64, ParseError> {
    let owned = open_map(path)?;
    let page = limits.page;
    let len = owned.len;
    let base = owned.ptr as usize;
    let header =
        unsafe { std::slice::from_raw_parts(owned.ptr.cast::<u8>(), FIELD_BYTES.min(len)) };
    let payload = f64_payload(header, len)?;
    let request = (limits.max_request & !(page - 1)).max(page);
    let ranges = worker_ranges(len, threads, page);
    if pages_all_resident(owned.ptr, len, page)? {
        let pieces = piece_list(0, len, request);
        return Ok(sum_pieces_in_order(
            base,
            payload.offset,
            payload.end,
            threads,
            &pieces,
        ));
    }
    let depth = (limits.nr_requests / ranges.len()).max(1);
    let (err_tx, err_rx) = std::sync::mpsc::channel::<String>();
    let sum = std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(ranges.len());
        for (span, end) in ranges {
            let err_tx = err_tx.clone();
            handles.push(scope.spawn(move || {
                match stream_one_span(
                    path,
                    SpanGeom {
                        base,
                        span,
                        end,
                        page,
                        payload_off: payload.offset,
                        payload_end: payload.end,
                        request,
                        depth,
                    },
                ) {
                    Ok(part) => part,
                    Err(err) => {
                        let _ = err_tx.send(err);
                        0.0
                    }
                }
            }));
        }
        drop(err_tx);
        handles
            .into_iter()
            .map(|handle| handle.join().expect("split stream"))
            .sum::<f64>()
    });
    if let Ok(err) = err_rx.try_recv() {
        return Err(ParseError::ValidationError(err));
    }
    Ok(sum)
}

#[cfg(target_os = "linux")]
struct SpanGeom {
    base: usize,
    span: usize,
    end: usize,
    page: usize,
    payload_off: usize,
    payload_end: usize,
    request: usize,
    depth: usize,
}

#[cfg(target_os = "linux")]
fn stream_one_span(path: &Path, geom: SpanGeom) -> Result<f64, String> {
    let SpanGeom {
        base,
        span,
        end,
        page,
        payload_off,
        payload_end,
        request,
        depth,
    } = geom;
    let fd = File::open(path).map_err(|err| err.to_string())?;
    let pieces = piece_list(span, end, request);
    let depth = depth.max(1);
    let mut next_submit = 0usize;
    let mut next_sum = 0usize;
    let mut acc = 0.0f64;
    while next_sum < pieces.len() {
        while next_submit < pieces.len() && next_submit - next_sum < depth {
            let (off, n) = pieces[next_submit];
            advise_readahead(&fd, off, n)?;
            next_submit += 1;
        }
        let (off, n) = pieces[next_sum];
        wait_resident(base, off, n, page)?;
        acc += sum_range(base, off, off + n, payload_off, payload_end);
        next_sum += 1;
    }
    Ok(acc)
}

#[cfg(target_os = "linux")]
fn sum_pieces_in_order(
    base: usize,
    payload_off: usize,
    payload_end: usize,
    threads: usize,
    pieces: &[(usize, usize)],
) -> f64 {
    let mut slots = vec![0.0f64; pieces.len()];
    let next = std::sync::atomic::AtomicUsize::new(0);
    std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(threads);
        for _ in 0..threads {
            handles.push(scope.spawn(|| {
                let mut local = Vec::new();
                loop {
                    let index = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= pieces.len() {
                        break;
                    }
                    let (off, n) = pieces[index];
                    local.push((
                        index,
                        sum_range(base, off, off + n, payload_off, payload_end),
                    ));
                }
                local
            }));
        }
        for handle in handles {
            for (index, part) in handle.join().expect("column sum") {
                slots[index] = part;
            }
        }
    });
    slots.iter().copied().sum()
}

#[cfg(target_os = "linux")]
fn pages_all_resident(ptr: *mut libc::c_void, len: usize, page: usize) -> Result<bool, ParseError> {
    if len == 0 {
        return Ok(true);
    }
    let pages = len.div_ceil(page);
    let mut vec = vec![0u8; pages];
    let rc = unsafe { libc::mincore(ptr, len, vec.as_mut_ptr()) };
    if rc != 0 {
        return Err(ParseError::ValidationError(
            std::io::Error::last_os_error().to_string(),
        ));
    }
    Ok(vec.iter().all(|byte| byte & 1 == 1))
}

/// `Ok` means the range is resident. `Err` is the errno from `madvise`.
/// Only `EINVAL` means this kernel has no `MADV_POPULATE_READ`, so the
/// caller may fault the pages itself. `EFAULT`, `EIO`, `EHWPOISON` and
/// `ENOMEM` are failures (man 2 madvise).
#[cfg(target_os = "linux")]
fn populate_followup(code: i32) -> Result<(), i32> {
    if code == libc::EINVAL {
        Ok(())
    } else {
        Err(code)
    }
}

#[cfg(target_os = "linux")]
fn touch_pages(addr: usize, off: usize, len: usize, page: usize) {
    let pages = len.div_ceil(page);
    for index in 0..pages {
        let at = index * page;
        if at >= len {
            break;
        }
        let byte = (addr + off + at) as *const u8;
        std::hint::black_box(unsafe { std::ptr::read_volatile(byte) });
    }
}

#[cfg(target_os = "linux")]
fn wait_resident(addr: usize, off: usize, len: usize, page: usize) -> Result<(), String> {
    // One readahead has already been submitted. MADV_POPULATE_READ (Linux
    // 5.14) faults this range and waits. The address is checked before the
    // call, so EINVAL is the old-kernel miss and one byte of each page is
    // read. EAGAIN is a transient kernel resource (man 2 madvise) and is
    // retried once per page of the range. Any other errno is returned.
    if page == 0 || !(addr + off).is_multiple_of(page) {
        return Err("madvise address is not page-aligned".into());
    }
    let start = (addr + off) as *mut libc::c_void;
    let pages = len.div_ceil(page).max(1);
    let mut tried = 0usize;
    loop {
        let rc = unsafe { libc::madvise(start, len, libc::MADV_POPULATE_READ) };
        if rc == 0 {
            return Ok(());
        }
        let err = std::io::Error::last_os_error();
        let code = err.raw_os_error().unwrap_or(0);
        if code == libc::EAGAIN && tried < pages {
            tried += 1;
            continue;
        }
        if populate_followup(code).is_ok() {
            touch_pages(addr, off, len, page);
            return Ok(());
        }
        return Err(err.to_string());
    }
}

#[cfg(target_os = "linux")]
fn advise_readahead(file: &File, off: usize, len: usize) -> Result<(), String> {
    let rc = unsafe { libc::readahead(file.as_raw_fd(), off as i64, len) };
    if rc != 0 {
        Err(std::io::Error::last_os_error().to_string())
    } else {
        Ok(())
    }
}

#[cfg(target_os = "linux")]
struct OwnedMap {
    ptr: *mut libc::c_void,
    len: usize,
}

#[cfg(target_os = "linux")]
impl Drop for OwnedMap {
    fn drop(&mut self) {
        unsafe { libc::munmap(self.ptr, self.len) };
    }
}

#[cfg(target_os = "linux")]
fn open_map(path: &Path) -> Result<OwnedMap, ParseError> {
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let len = file
        .metadata()
        .map_err(|err| ParseError::ValidationError(err.to_string()))?
        .len() as usize;
    let ptr = unsafe {
        libc::mmap(
            std::ptr::null_mut(),
            len,
            libc::PROT_READ,
            libc::MAP_PRIVATE,
            file.as_raw_fd(),
            0,
        )
    };
    if ptr == libc::MAP_FAILED {
        return Err(ParseError::ValidationError(
            std::io::Error::last_os_error().to_string(),
        ));
    }
    unsafe {
        libc::madvise(ptr, len, libc::MADV_SEQUENTIAL);
        libc::madvise(ptr, len, libc::MADV_HUGEPAGE);
    }
    Ok(OwnedMap { ptr, len })
}

#[cfg(target_os = "linux")]
fn sum_range(base: usize, start: usize, end: usize, payload_off: usize, payload_end: usize) -> f64 {
    let from = start.max(payload_off);
    let to = end.min(payload_end);
    if to <= from {
        return 0.0;
    }
    let data = unsafe { std::slice::from_raw_parts((base + from) as *const f64, (to - from) / 8) };
    let mut acc = 0.0f64;
    for &value in data {
        acc += value;
    }
    acc
}

/// Map `path` and fault the pages in before returning.
///
/// The map is `MAP_PRIVATE` and writable. A store to a page copies that
/// page. It does not modify the file. `mmap(2)` leaves it unspecified
/// whether a later write to the file by someone else appears in a page
/// the caller has not stored to. Truncation can raise `SIGBUS`.
///
/// `MADV_SEQUENTIAL` and `MADV_WILLNEED` describe one forward pass.
/// `MADV_HUGEPAGE` is the request used when transparent huge pages are in
/// `madvise` mode (`CONFIG_TRANSPARENT_HUGEPAGE_MADVISE`). File-backed
/// huge pages also need `CONFIG_READ_ONLY_THP_FOR_FS`
/// (Documentation/admin-guide/mm/transhuge.rst). This kernel's
/// `/proc/config.gz` has that option unset, and a mapped read showed
/// `FilePmdMapped` 0. The advice stays, because it is the switch the
/// kernel documents, and it is a no-op without that option.
/// `MADV_POPULATE_READ` (Linux 5.14) waits until the pages are resident
/// and reports an error. `MAP_POPULATE` hides errors and cannot be split
/// across the caller's threads after `mmap` returns.
/// `threads` workers fault page-aligned spans. A file shorter than one
/// page per worker stays on one worker. The page is `sysconf(SC_PAGESIZE)`.
pub fn map_file(path: &Path, threads: usize) -> Result<ConBinMap, ParseError> {
    map_file_with(path, threads, Prefetch::Span)
}

/// [`map_file`] with an explicit prefetch. The benchmark pairs these.
pub fn map_file_with(
    path: &Path,
    threads: usize,
    prefetch: Prefetch,
) -> Result<ConBinMap, ParseError> {
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    // MAP_PRIVATE, PROT_READ|PROT_WRITE. Writes copy the page.
    let map = unsafe { memmap2::MmapOptions::new().map_copy(&file) }
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    if map.len() < FIELD_BYTES {
        return Err(ParseError::ValidationError(
            "CON-bin header is not CONBIN01".into(),
        ));
    }
    let (header, offset) = parse_fields(&map[..FIELD_BYTES])?;
    let page = page_size()?;
    let payload_off = checked_payload_offset(offset, map.len())?;
    fault_in(path, &map, threads, page, prefetch)?;
    Ok(ConBinMap {
        map,
        header,
        payload_off,
    })
}

fn fault_in(
    path: &Path,
    map: &memmap2::MmapMut,
    threads: usize,
    page: usize,
    prefetch: Prefetch,
) -> Result<(), ParseError> {
    #[cfg(unix)]
    let _ = map.advise(memmap2::Advice::Sequential);
    #[cfg(target_os = "linux")]
    let _ = map.advise(memmap2::Advice::HugePage);
    #[cfg(target_os = "linux")]
    {
        match prefetch {
            Prefetch::Span => {
                let _ = map.advise(memmap2::Advice::WillNeed);
                advise_spans(map, memmap2::Advice::PopulateRead, threads, page)?;
            }
            Prefetch::ChunkPopulate => {
                let window = QueueLimits::of(path)?.worker_span(threads);
                chunk_each(map, threads, page, window, ChunkOp::Populate)?;
            }
            Prefetch::ChunkWillneed => {
                let window = QueueLimits::of(path)?.worker_span(threads);
                chunk_each(map, threads, page, window, ChunkOp::Willneed { path })?;
            }
            Prefetch::Hybrid => {
                let window = QueueLimits::of(path)?.worker_span(threads);
                chunk_each(map, threads, page, window, ChunkOp::Hybrid { path })?;
            }
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (path, threads, prefetch);
        for chunk in map.chunks(page) {
            std::hint::black_box(chunk.first().copied());
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
enum ChunkOp<'a> {
    Populate,
    Willneed { path: &'a Path },
    Hybrid { path: &'a Path },
}

#[cfg(target_os = "linux")]
fn chunk_each(
    map: &memmap2::MmapMut,
    threads: usize,
    page: usize,
    window: usize,
    op: ChunkOp<'_>,
) -> Result<(), ParseError> {
    let ranges = worker_ranges(map.len(), threads, page);
    let shared = match op {
        ChunkOp::Populate => ChunkOp::Populate,
        ChunkOp::Willneed { path } => ChunkOp::Willneed { path },
        ChunkOp::Hybrid { path } => ChunkOp::Hybrid { path },
    };
    std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(ranges.len());
        for (start, end) in ranges {
            let op = match shared {
                ChunkOp::Populate => ChunkOp::Populate,
                ChunkOp::Willneed { path } => ChunkOp::Willneed { path },
                ChunkOp::Hybrid { path } => ChunkOp::Hybrid { path },
            };
            handles.push(scope.spawn(move || chunk_worker(map, start, end, window, page, op)));
        }
        handles.into_iter().try_for_each(|handle| {
            handle.join().unwrap_or_else(|_| {
                Err(ParseError::ValidationError(
                    "CON-bin prefetch thread panicked".into(),
                ))
            })
        })
    })
}

#[cfg(target_os = "linux")]
fn chunk_worker(
    map: &memmap2::MmapMut,
    start: usize,
    end: usize,
    window: usize,
    page: usize,
    op: ChunkOp<'_>,
) -> Result<(), ParseError> {
    let window = window.max(page);
    let pieces = piece_list(start, end, window);
    let fd = match op {
        ChunkOp::Willneed { path } | ChunkOp::Hybrid { path } => {
            Some(File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?)
        }
        ChunkOp::Populate => None,
    };
    match op {
        ChunkOp::Populate => {
            for (off, len) in pieces {
                populate_range(map, off, len)?;
            }
        }
        ChunkOp::Willneed { .. } => {
            let fd = fd.as_ref().expect("willneed opens a descriptor");
            for (off, len) in pieces {
                willneed(fd, off, len)?;
            }
        }
        ChunkOp::Hybrid { .. } => {
            let fd = fd.as_ref().expect("hybrid opens a descriptor");
            if let Some((off, len)) = pieces.first().copied() {
                willneed(fd, off, len)?;
            }
            for i in 0..pieces.len() {
                if let Some((off, len)) = pieces.get(i + 1).copied() {
                    willneed(fd, off, len)?;
                }
                let (off, len) = pieces[i];
                populate_range(map, off, len)?;
            }
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn piece_list(start: usize, end: usize, window: usize) -> Vec<(usize, usize)> {
    let mut pieces = Vec::new();
    let mut off = start;
    while off < end {
        let len = window.min(end - off);
        pieces.push((off, len));
        off += len;
    }
    pieces
}

#[cfg(target_os = "linux")]
fn populate_range(map: &memmap2::MmapMut, off: usize, len: usize) -> Result<(), ParseError> {
    let page = page_size()?;
    wait_resident(map.as_ptr() as usize, off, len, page).map_err(ParseError::ValidationError)
}

#[cfg(target_os = "linux")]
fn willneed(file: &File, off: usize, len: usize) -> Result<(), ParseError> {
    let rc = unsafe {
        libc::posix_fadvise(
            file.as_raw_fd(),
            off as libc::off_t,
            len as libc::off_t,
            libc::POSIX_FADV_WILLNEED,
        )
    };
    if rc != 0 {
        return Err(ParseError::ValidationError(format!(
            "posix_fadvise WILLNEED: {rc}"
        )));
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn worker_ranges(len: usize, threads: usize, page: usize) -> Vec<(usize, usize)> {
    if len == 0 {
        return Vec::new();
    }
    let threads = threads.max(1);
    let workers = if len < page.saturating_mul(threads) {
        1
    } else {
        threads
    };
    if workers == 1 {
        return vec![(0, len)];
    }
    let chunk = (len / workers) & !(page - 1);
    let mut ranges = Vec::with_capacity(workers);
    let mut start = 0usize;
    for worker in 0..workers {
        let take = if worker + 1 == workers {
            len - start
        } else {
            chunk
        };
        ranges.push((start, start + take));
        start += take;
    }
    ranges
}

#[cfg(target_os = "linux")]
fn advise_spans(
    map: &memmap2::MmapMut,
    advice: memmap2::Advice,
    threads: usize,
    page: usize,
) -> Result<(), ParseError> {
    let len = map.len();
    if len == 0 {
        return Ok(());
    }
    let threads = threads.max(1);
    let workers = if len < page.saturating_mul(threads) {
        1
    } else {
        threads
    };
    if workers == 1 {
        return map
            .advise(advice)
            .map_err(|err| ParseError::ValidationError(err.to_string()));
    }
    let chunk = (len / workers) & !(page - 1);
    std::thread::scope(|scope| {
        let mut start = 0usize;
        let mut handles = Vec::with_capacity(workers);
        for worker in 0..workers {
            let take = if worker + 1 == workers {
                len - start
            } else {
                chunk
            };
            let off = start;
            start += take;
            handles.push(scope.spawn(move || map.advise_range(advice, off, take)));
        }
        handles.into_iter().try_for_each(|handle| {
            handle
                .join()
                .unwrap_or_else(|_| Err(std::io::Error::other("CON-bin populate thread panicked")))
                .map_err(|err| ParseError::ValidationError(err.to_string()))
        })
    })
}

pub fn read_header(path: &Path) -> Result<ConBinHeader, ParseError> {
    let mut file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut bytes = [0u8; FIELD_BYTES];
    file.read_exact(&mut bytes)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    parse_fields(&bytes).map(|(header, _)| header)
}

fn bytes_of<T>(values: &mut [T]) -> &mut [u8] {
    let len = std::mem::size_of_val(values);
    // SAFETY: `values` is a live slice. The byte view covers exactly those
    // elements and is not used after `values` is borrowed again.
    unsafe { std::slice::from_raw_parts_mut(values.as_mut_ptr().cast::<u8>(), len) }
}

/// Copy a binary64 CON-bin into caller-owned columns. One thread issues the reads.
pub fn read_into(
    path: &Path,
    positions: &mut [f64],
    velocities: Option<&mut [f64]>,
) -> Result<ConBinHeader, ParseError> {
    read_into_threads(path, positions, velocities, 1)
}

/// [`read_into`] with `threads` workers. Each worker reads a page-aligned span.
/// A span shorter than one page stays on one worker.
pub fn read_into_threads(
    path: &Path,
    positions: &mut [f64],
    velocities: Option<&mut [f64]>,
    threads: usize,
) -> Result<ConBinHeader, ParseError> {
    read_columns_into(path, positions, velocities, threads, false)
}

/// Copy both binary64 columns into owned vectors.
///
/// Each vector is `with_capacity`, then `pread` fills `spare_capacity_mut`
/// and `set_len` publishes those slots. The byte view is not a `&mut [f64]`
/// over uninitialised memory. A missing velocity run is an error.
///
/// The header's frame and atom counts are not reserved until both columns
/// fit in the file. A count the file cannot hold is [`ParseError::IncompleteFrame`].
pub fn read_owned_f64(
    path: &Path,
    threads: usize,
) -> Result<(ConBinHeader, Vec<f64>, Vec<f64>), ParseError> {
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut raw = [0u8; FIELD_BYTES];
    (&file)
        .read_exact(&mut raw)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let (header, offset) = parse_fields(&raw)?;
    if header.binary32 {
        return Err(ParseError::ValidationError(
            "CON-bin file is binary32; use read_into_f32".into(),
        ));
    }
    if !header.velocities {
        return Err(ParseError::ValidationError(
            "CON-bin file has no velocity run".into(),
        ));
    }
    let n = header.position_len()?;
    let column = n
        .checked_mul(std::mem::size_of::<f64>())
        .ok_or_else(|| ParseError::InvalidCount("CON-bin column byte length overflows".into()))?;
    let file_len = file
        .metadata()
        .map_err(|err| ParseError::ValidationError(err.to_string()))?
        .len() as usize;
    let pos_off = checked_payload_offset(offset, file_len)?;
    let both = column
        .checked_mul(2)
        .ok_or_else(|| ParseError::InvalidCount("CON-bin column byte length overflows".into()))?;
    let end = pos_off
        .checked_add(both)
        .ok_or_else(|| ParseError::InvalidCount("CON-bin payload offset overflows".into()))?;
    if end > file_len {
        return Err(ParseError::IncompleteFrame);
    }
    drop(file);
    let mut positions = Vec::<f64>::with_capacity(n);
    let mut velocities = Vec::<f64>::with_capacity(n);
    fill_owned_f64(path, &mut positions, &mut velocities, n, threads)?;
    Ok((header, positions, velocities))
}

#[cfg(unix)]
fn spare_prefix_uninit(buf: &mut Vec<f64>, n: usize) -> &mut [std::mem::MaybeUninit<u8>] {
    let spare = buf.spare_capacity_mut();
    assert!(spare.len() >= n);
    let nbytes = n * std::mem::size_of::<f64>();
    let ptr = spare.as_mut_ptr().cast::<std::mem::MaybeUninit<u8>>();
    // SAFETY: `n` uninitialised f64 slots cover `nbytes` bytes. A
    // `MaybeUninit<u8>` slot may be uninitialised, so this slice does not
    // claim the bytes are initialised. `pread` writes through the raw
    // pointer, then `set_len` publishes the f64 slots.
    unsafe { std::slice::from_raw_parts_mut(ptr, nbytes) }
}

fn fill_owned_f64(
    path: &Path,
    positions: &mut Vec<f64>,
    velocities: &mut Vec<f64>,
    n: usize,
    threads: usize,
) -> Result<(), ParseError> {
    #[cfg(not(unix))]
    {
        let _ = (path, positions, velocities, n, threads);
        return Err(ParseError::ValidationError(
            "CON-bin pread fill requires Unix".into(),
        ));
    }
    #[cfg(unix)]
    {
        let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
        let mut raw = [0u8; FIELD_BYTES];
        (&file)
            .read_exact(&mut raw)
            .map_err(|err| ParseError::ValidationError(err.to_string()))?;
        let (_header, offset) = parse_fields(&raw)?;
        let width = std::mem::size_of::<f64>();
        let expect = n.checked_mul(width).ok_or_else(|| {
            ParseError::InvalidCount("CON-bin column byte length overflows".into())
        })?;
        let page = page_size()?;
        let file_len = file
            .metadata()
            .map_err(|err| ParseError::ValidationError(err.to_string()))?
            .len() as usize;
        let pos_off = checked_payload_offset(offset, file_len)? as u64;
        let fd = file.as_raw_fd();
        {
            let bytes = spare_prefix_uninit(positions, n);
            pread_parallel_uninit(fd, bytes, pos_off, threads, page)?;
        }
        // SAFETY: `pread_parallel_uninit` wrote `n` little-endian f64 values or returned.
        unsafe { positions.set_len(n) };
        {
            let bytes = spare_prefix_uninit(velocities, n);
            pread_parallel_uninit(fd, bytes, pos_off + expect as u64, threads, page)?;
        }
        unsafe { velocities.set_len(n) };
        Ok(())
    }
}

/// Copy a binary32 CON-bin into caller-owned columns. One thread issues the reads.
pub fn read_into_f32(
    path: &Path,
    positions: &mut [f32],
    velocities: Option<&mut [f32]>,
) -> Result<ConBinHeader, ParseError> {
    read_into_f32_threads(path, positions, velocities, 1)
}

/// [`read_into_f32`] with `threads` workers. The split is the same page rule
/// as [`read_into_threads`].
pub fn read_into_f32_threads(
    path: &Path,
    positions: &mut [f32],
    velocities: Option<&mut [f32]>,
    threads: usize,
) -> Result<ConBinHeader, ParseError> {
    read_columns_into(path, positions, velocities, threads, true)
}

fn read_columns_into<T>(
    path: &Path,
    positions: &mut [T],
    velocities: Option<&mut [T]>,
    threads: usize,
    binary32: bool,
) -> Result<ConBinHeader, ParseError> {
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut raw = [0u8; FIELD_BYTES];
    (&file)
        .read_exact(&mut raw)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let (header, offset) = parse_fields(&raw)?;
    if header.binary32 != binary32 {
        return Err(ParseError::ValidationError(if binary32 {
            "CON-bin file is binary64; use read_into".into()
        } else {
            "CON-bin file is binary32; use read_into_f32".into()
        }));
    }
    let n = header.position_len()?;
    let width = std::mem::size_of::<T>();
    let expect = n
        .checked_mul(width)
        .ok_or_else(|| ParseError::InvalidCount("CON-bin column byte length overflows".into()))?;
    if positions.len() != n {
        return Err(ParseError::InvalidCount(format!(
            "position slice has {} values, the file has {n}",
            positions.len()
        )));
    }
    let page = page_size()?;
    let file_len = file
        .metadata()
        .map_err(|err| ParseError::ValidationError(err.to_string()))?
        .len() as usize;
    let pos_off = checked_payload_offset(offset, file_len)? as u64;
    let pos_bytes = bytes_of(positions);
    if pos_bytes.len() != expect {
        return Err(ParseError::InvalidCount(format!(
            "position slice has {} bytes, the file has {expect}",
            pos_bytes.len()
        )));
    }
    #[cfg(not(unix))]
    {
        let _ = (pos_bytes, pos_off, threads, page, velocities, header);
        return Err(ParseError::ValidationError(
            "CON-bin pread fill requires Unix".into(),
        ));
    }
    #[cfg(unix)]
    {
        let fd = file.as_raw_fd();
        // Sequential advice matches one pass over the payload. WILLNEED is not
        // used here: it starts a second readahead beside the reads themselves.
        // libc exposes posix_fadvise on Linux. macOS has posix_madvise instead.
        #[cfg(target_os = "linux")]
        unsafe {
            libc::posix_fadvise(fd, 0, 0, libc::POSIX_FADV_SEQUENTIAL);
        }
        // Linux read returns at most MAX_RW_COUNT bytes (INT_MAX aligned down to
        // the page, include/linux/fs.h). `pread_all` continues until the span is full.
        pread_parallel(fd, pos_bytes, pos_off, threads, page)?;
        if header.velocities {
            let Some(vel) = velocities else {
                return Err(ParseError::InvalidCount(
                    "CON-bin has velocities and the caller passed no velocity slice".into(),
                ));
            };
            if vel.len() != n {
                return Err(ParseError::InvalidCount(format!(
                    "velocity slice has {} values, the file has {n}",
                    vel.len()
                )));
            }
            let vel_bytes = bytes_of(vel);
            pread_parallel(fd, vel_bytes, pos_off + expect as u64, threads, page)?;
        }
        Ok(header)
    }
}

#[cfg(unix)]
fn pread_parallel(
    fd: i32,
    dest: &mut [u8],
    offset: u64,
    threads: usize,
    page: usize,
) -> Result<(), ParseError> {
    let threads = threads.max(1);
    let workers = if dest.len() < page.saturating_mul(threads) {
        1
    } else {
        threads
    };
    if workers == 1 {
        return pread_all(fd, dest, offset);
    }
    let chunk = (dest.len() / workers) & !(page - 1);
    std::thread::scope(|scope| {
        let mut rest = dest;
        let mut off = offset;
        let mut handles = Vec::with_capacity(workers);
        for worker in 0..workers {
            let take = if worker + 1 == workers {
                rest.len()
            } else {
                chunk
            };
            let (head, tail) = rest.split_at_mut(take);
            rest = tail;
            let this = off;
            off += take as u64;
            handles.push(scope.spawn(move || pread_all(fd, head, this)));
        }
        handles
            .into_iter()
            .try_for_each(|handle| handle.join().unwrap_or(Err(ParseError::IncompleteFrame)))
    })
}

#[cfg(unix)]
fn pread_raw(fd: i32, ptr: *mut u8, len: usize, mut offset: u64) -> Result<(), ParseError> {
    let mut done = 0;
    while done < len {
        let n = unsafe { libc::pread(fd, ptr.add(done).cast(), len - done, offset as libc::off_t) };
        if n < 0 {
            let err = std::io::Error::last_os_error();
            // POSIX: EINTR means the call was interrupted before a transfer.
            // Restart the same offset. Rust's `read_at` does the same for
            // `ErrorKind::Interrupted`.
            if err.raw_os_error() == Some(libc::EINTR) {
                continue;
            }
            return Err(ParseError::ValidationError(err.to_string()));
        }
        if n == 0 {
            return Err(ParseError::IncompleteFrame);
        }
        done += n as usize;
        offset += n as u64;
    }
    Ok(())
}

#[cfg(unix)]
fn pread_all(fd: i32, dest: &mut [u8], offset: u64) -> Result<(), ParseError> {
    pread_raw(fd, dest.as_mut_ptr(), dest.len(), offset)
}

#[cfg(unix)]
fn pread_uninit(
    fd: i32,
    dest: &mut [std::mem::MaybeUninit<u8>],
    offset: u64,
) -> Result<(), ParseError> {
    // `as_mut_ptr` of `MaybeUninit<u8>` is the address `pread` may write.
    // The slice type does not require the bytes to be initialised.
    pread_raw(fd, dest.as_mut_ptr().cast::<u8>(), dest.len(), offset)
}

#[cfg(unix)]
fn pread_parallel_uninit(
    fd: i32,
    dest: &mut [std::mem::MaybeUninit<u8>],
    offset: u64,
    threads: usize,
    page: usize,
) -> Result<(), ParseError> {
    let threads = threads.max(1);
    let workers = if dest.len() < page.saturating_mul(threads) {
        1
    } else {
        threads
    };
    if workers == 1 {
        return pread_uninit(fd, dest, offset);
    }
    let chunk = (dest.len() / workers) & !(page - 1);
    std::thread::scope(|scope| {
        let mut rest = dest;
        let mut off = offset;
        let mut handles = Vec::with_capacity(workers);
        for worker in 0..workers {
            let take = if worker + 1 == workers {
                rest.len()
            } else {
                chunk
            };
            let (head, tail) = rest.split_at_mut(take);
            rest = tail;
            let this = off;
            off += take as u64;
            handles.push(scope.spawn(move || pread_uninit(fd, head, this)));
        }
        handles
            .into_iter()
            .try_for_each(|handle| handle.join().unwrap_or(Err(ParseError::IncompleteFrame)))
    })
}

fn write_values<T>(file: &mut File, values: &[T]) -> Result<(), ParseError> {
    let bytes = unsafe {
        std::slice::from_raw_parts(values.as_ptr().cast::<u8>(), std::mem::size_of_val(values))
    };
    file.write_all(bytes)
        .map_err(|err| ParseError::ValidationError(err.to_string()))
}

fn write_header_page(
    file: &mut File,
    header: &ConBinHeader,
    page: usize,
) -> Result<(), ParseError> {
    let mut header_page = vec![0u8; page];
    let prefix = header_fields(header, page as u64);
    header_page[..FIELD_BYTES].copy_from_slice(&prefix);
    file.write_all(&header_page)
        .map_err(|err| ParseError::ValidationError(err.to_string()))
}

/// Stream a CON text file into a CON-bin of the same frames.
///
/// The header occupies one host page, so the payload starts on a page
/// boundary. Positions of every frame are written as one run, then velocities.
///
/// ```
/// use readcon_core::conbin::{read_owned_f64, write_from_con};
/// use std::path::Path;
///
/// let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("resources/test/tiny_cuh2.con");
/// let dir = std::env::temp_dir().join(format!("readcon-conbin-doc-{}", std::process::id()));
/// std::fs::create_dir_all(&dir).unwrap();
/// let out = dir.join("tiny.bin");
/// let header = write_from_con(&src, &out, false).unwrap();
/// assert_eq!((header.n_frames, header.n_atoms), (1, 4));
/// let (again, positions, velocities) = read_owned_f64(&out, 1).unwrap();
/// assert_eq!(again.n_frames, 1);
/// assert_eq!(positions.len(), 12);
/// assert!((positions[0] - 0.6394).abs() < 1e-4);
/// assert_eq!(velocities.len(), 12);
/// let _ = std::fs::remove_dir_all(dir);
/// ```
pub fn write_from_con(
    con_path: &Path,
    out_path: &Path,
    binary32: bool,
) -> Result<ConBinHeader, ParseError> {
    let text = std::fs::read_to_string(con_path)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut file =
        File::create(out_path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let page = page_size()?;
    write_header_page(
        &mut file,
        &ConBinHeader {
            n_frames: 0,
            n_atoms: 0,
            binary32,
            velocities: true,
        },
        page,
    )?;

    let mut n_frames = 0u64;
    let mut n_atoms = 0u64;
    let mut positions: Vec<f64> = Vec::new();
    let mut velocities: Vec<f64> = Vec::new();
    for frame in ConFrameIterator::new(&text) {
        let frame = frame?;
        let n = frame.atom_data.len();
        if n_frames == 0 {
            n_atoms = n as u64;
        } else if n as u64 != n_atoms {
            return Err(ParseError::InvalidCount(
                "CON-bin requires the same atom count in every frame".into(),
            ));
        }
        for atom in &frame.atom_data {
            positions.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
            velocities.extend_from_slice(&atom.velocity().unwrap_or([0.0; 3]));
        }
        n_frames += 1;
    }
    if binary32 {
        let pos32: Vec<f32> = positions.iter().map(|v| *v as f32).collect();
        let vel32: Vec<f32> = velocities.iter().map(|v| *v as f32).collect();
        write_values(&mut file, &pos32)?;
        write_values(&mut file, &vel32)?;
    } else {
        write_values(&mut file, &positions)?;
        write_values(&mut file, &velocities)?;
    }
    let header = ConBinHeader {
        n_frames,
        n_atoms,
        binary32,
        velocities: true,
    };
    file.seek(SeekFrom::Start(0))
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    write_header_page(&mut file, &header, page)?;
    Ok(header)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_known(path: &Path, frames: usize, atoms: usize) {
        let page = page_size().unwrap();
        let mut file = File::create(path).unwrap();
        let header = ConBinHeader {
            n_frames: frames as u64,
            n_atoms: atoms as u64,
            binary32: false,
            velocities: true,
        };
        write_header_page(&mut file, &header, page).unwrap();
        let n = frames * atoms * 3;
        let pos: Vec<f64> = (0..n).map(|i| i as f64 * 0.25).collect();
        let vel: Vec<f64> = (0..n).map(|i| i as f64 * -0.5).collect();
        write_values(&mut file, &pos).unwrap();
        write_values(&mut file, &vel).unwrap();
    }

    #[test]
    fn every_prefetch_reads_the_same_columns() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.conbin");
        write_known(&path, 2, 64);
        let span = map_file_with(&path, 2, Prefetch::Span).unwrap();
        let expect_pos = span.positions_f64().unwrap().to_vec();
        let expect_vel = span.velocities_f64().unwrap().to_vec();
        assert_eq!(expect_pos.len(), 2 * 64 * 3);
        for mode in [
            Prefetch::ChunkPopulate,
            Prefetch::ChunkWillneed,
            Prefetch::Hybrid,
        ] {
            let mapped = map_file_with(&path, 2, mode).unwrap();
            assert_eq!(mapped.positions_f64().unwrap(), expect_pos.as_slice());
            assert_eq!(mapped.velocities_f64().unwrap(), expect_vel.as_slice());
        }
        let expect = expect_pos.iter().sum::<f64>() + expect_vel.iter().sum::<f64>();
        assert_eq!(sum_split_streams(&path, 2).unwrap(), expect);
        assert_eq!(sum_mapped(&path, 2).unwrap(), expect);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn worker_span_shares_the_queue() {
        let limits = QueueLimits {
            page: 4096,
            logical_block: 512,
            max_request: 1280 * 1024,
            nr_requests: 256,
            read_ahead: 128 * 1024,
            nr_hw_queues: 1,
            rotational: true,
        };
        assert_eq!(limits.worker_span(8), 32 * 1280 * 1024);
        assert_eq!(limits.worker_span(1), 256 * 1280 * 1024);
        // /dev/shm is tmpfs, so it has no block queue. The sum must still run.
        let dir = std::path::PathBuf::from(format!("/dev/shm/conbin-sum-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        write_known(&path, 4, 8);
        let mapped = map_file(&path, 1).unwrap();
        let expect = mapped.positions_f64().unwrap().iter().sum::<f64>()
            + mapped.velocities_f64().unwrap().iter().sum::<f64>();
        let got = sum_mapped(&path, 2).unwrap();
        let got_split = sum_split_streams(&path, 2).unwrap();
        assert_eq!(got, expect, "parallel sum {got} serial sum {expect}");
        assert_eq!(
            got_split, expect,
            "split sum {got_split} serial sum {expect}"
        );
        let _ = std::fs::remove_dir_all(&dir);
        let short = QueueLimits {
            nr_requests: 2,
            read_ahead: 4096,
            ..limits
        };
        assert_eq!(short.worker_span(8), 1280 * 1024);
        let shm = std::path::PathBuf::from(format!("/dev/shm/conbin-queue-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&shm);
        std::fs::create_dir_all(&shm).unwrap();
        let qpath = shm.join("known.conbin");
        write_known(&qpath, 1, 1);
        let got = QueueLimits::of(&qpath).unwrap();
        assert!(got.page.is_power_of_two());
        assert_eq!(got.max_request, got.page);
        assert_eq!(got.nr_requests, 1);
        assert!(!got.rotational);
        let _ = std::fs::remove_dir_all(&shm);
    }

    #[test]
    fn mapped_runs_match_the_pread_fill() {
        let dir = std::env::temp_dir().join(format!("conbin-map-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        write_known(&path, 4, 3);
        let mapped = map_file(&path, 2).unwrap();
        let pos = mapped.positions_f64().unwrap();
        let vel = mapped.velocities_f64().unwrap();
        assert_eq!(pos.len(), 4 * 3 * 3);
        assert_eq!(pos[0], 0.0);
        assert_eq!(pos[1], 0.25);
        assert_eq!(vel[1], -0.5);
        let mut got_pos = vec![0.0; pos.len()];
        let mut got_vel = vec![0.0; vel.len()];
        read_into_threads(&path, &mut got_pos, Some(&mut got_vel), 2).unwrap();
        assert_eq!(got_pos, pos);
        assert_eq!(got_vel, vel);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn write_from_con_round_trips_text() {
        let dir = std::env::temp_dir().join(format!("conbin-text-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("two.con");
        std::fs::write(
            &con,
            include_str!("../resources/test/tiny_cuh2.con").repeat(2),
        )
        .unwrap();
        let bin = dir.join("two.conbin");
        let header = write_from_con(&con, &bin, false).unwrap();
        assert_eq!(header.n_frames, 2);
        assert_eq!(header.n_atoms, 4);
        let mapped = map_file(&bin, 1).unwrap();
        let pos = mapped.positions_f64().unwrap();
        assert_eq!(pos.len(), 2 * 4 * 3);
        assert!(pos[0].is_finite());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_store_copies_the_page_and_leaves_the_file() {
        let dir = std::env::temp_dir().join(format!("conbin-cow-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        write_known(&path, 2, 4);
        let before = std::fs::read(&path).unwrap();
        let mut mapped = map_file(&path, 1).unwrap();
        {
            let pos = mapped.positions_f64_mut().unwrap();
            let original = pos[0];
            pos[0] = original + 1.0;
            assert_eq!(pos[0], original + 1.0);
        }
        let after = std::fs::read(&path).unwrap();
        assert_eq!(before, after);
        let reread = map_file(&path, 1).unwrap();
        assert_eq!(reread.positions_f64().unwrap()[0], 0.0);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_4k_offset_opens_on_a_16k_or_64k_host() {
        // The stored offset is 4096, and the file is shorter than a 16 KiB
        // or 64 KiB page. The reader keeps 4096. It does not replace that
        // offset with the host page.
        let header = ConBinHeader {
            n_frames: 1,
            n_atoms: 1,
            binary32: false,
            velocities: true,
        };
        let mut bytes = header_fields(&header, 4096).to_vec();
        bytes.resize(4096 + 48, 0);
        bytes[4096..4096 + 8].copy_from_slice(&1.25f64.to_le_bytes());
        bytes[4096 + 24..4096 + 32].copy_from_slice(&(-2.5f64).to_le_bytes());
        assert!(bytes.len() < 16 * 1024);
        assert!(bytes.len() < 64 * 1024);
        let off = checked_payload_offset(4096, bytes.len()).unwrap();
        assert_eq!(off, 4096);
        assert_ne!(off, 16 * 1024);
        assert_ne!(off, 64 * 1024);
        let dir = std::env::temp_dir().join(format!("conbin-off-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        std::fs::write(&path, &bytes).unwrap();
        let mapped = map_file(&path, 1).unwrap();
        assert_eq!(mapped.payload_off, 4096);
        assert_eq!(mapped.positions_f64().unwrap()[0], 1.25);
        assert_eq!(mapped.velocities_f64().unwrap()[0], -2.5);
        let _ = std::fs::remove_dir_all(&dir);
    }

    fn write_typed(path: &Path, binary32: bool, velocities: bool) {
        let header = ConBinHeader {
            n_frames: 1,
            n_atoms: 1,
            binary32,
            velocities,
        };
        let mut bytes = header_fields(&header, 64).to_vec();
        bytes.resize(64 + 48, 0);
        std::fs::write(path, bytes).unwrap();
    }

    #[test]
    fn sum_mapped_rejects_binary32_and_a_missing_velocity_run() {
        let dir = std::env::temp_dir().join(format!("conbin-kind-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let binary32 = dir.join("f32.conbin");
        write_typed(&binary32, true, true);
        let err = sum_mapped(&binary32, 1).unwrap_err();
        assert!(err.to_string().contains("binary32"), "{err}");
        let bare = dir.join("nov.conbin");
        write_typed(&bare, false, false);
        let err = sum_mapped(&bare, 1).unwrap_err();
        assert!(err.to_string().contains("no velocity"), "{err}");
        let err = read_owned_f64(&bare, 1).unwrap_err();
        assert!(err.to_string().contains("no velocity"), "{err}");
        let known = dir.join("known.conbin");
        write_known(&known, 1, 2);
        let (_header, pos, vel) = read_owned_f64(&known, 1).unwrap();
        let mapped = map_file(&known, 1).unwrap();
        assert_eq!(pos.as_slice(), mapped.positions_f64().unwrap());
        assert_eq!(vel.as_slice(), mapped.velocities_f64().unwrap());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(target_os = "linux")]
    fn dir_is_tmpfs(path: &Path) -> bool {
        let text = path.to_string_lossy();
        let Ok(c) = std::ffi::CString::new(text.as_bytes()) else {
            return false;
        };
        let mut stat: libc::statfs = unsafe { std::mem::zeroed() };
        let rc = unsafe { libc::statfs(c.as_ptr(), &mut stat) };
        // include/uapi/linux/magic.h TMPFS_MAGIC
        rc == 0 && stat.f_type == 0x01021994
    }

    #[cfg(target_os = "linux")]
    fn streaming_dir() -> Option<std::path::PathBuf> {
        let mut candidates = vec![std::env::temp_dir()];
        if let Ok(cwd) = std::env::current_dir() {
            candidates.push(cwd);
        }
        candidates.push(std::path::PathBuf::from("/var/tmp"));
        for base in candidates {
            if base.is_dir() && !dir_is_tmpfs(&base) {
                let dir = base.join(format!("conbin-stream-{}", std::process::id()));
                let _ = std::fs::remove_dir_all(&dir);
                if std::fs::create_dir_all(&dir).is_ok() {
                    return Some(dir);
                }
            }
        }
        None
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn sum_mapped_streams_when_pages_are_not_resident() {
        let Some(dir) = streaming_dir() else {
            panic!(
                "sum_mapped_streams_when_pages_are_not_resident: temp, the working directory and /var/tmp are tmpfs, and POSIX_FADV_DONTNEED leaves tmpfs pages resident"
            );
        };
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        write_known(&path, 2, 32);
        let file = File::open(&path).unwrap();
        file.sync_all().unwrap();
        let rc = unsafe { libc::posix_fadvise(file.as_raw_fd(), 0, 0, libc::POSIX_FADV_DONTNEED) };
        assert_eq!(rc, 0);
        let len = file.metadata().unwrap().len() as usize;
        let ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                len,
                libc::PROT_READ,
                libc::MAP_PRIVATE,
                file.as_raw_fd(),
                0,
            )
        };
        assert_ne!(ptr, libc::MAP_FAILED);
        let page = page_size().unwrap();
        let pages = len.div_ceil(page);
        let mut vec = vec![0u8; pages];
        let rc = unsafe { libc::mincore(ptr, len, vec.as_mut_ptr()) };
        assert_eq!(rc, 0);
        assert!(
            vec.iter().any(|byte| byte & 1 == 0),
            "every page stayed resident"
        );
        unsafe { libc::munmap(ptr, len) };
        let got = sum_mapped(&path, 2).unwrap();
        let mapped = map_file(&path, 1).unwrap();
        let expect = mapped.positions_f64().unwrap().iter().sum::<f64>()
            + mapped.velocities_f64().unwrap().iter().sum::<f64>();
        assert_eq!(got, expect, "{got} {expect}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Fills both columns with `pread` into spare capacity.
    /// Miri runs this with `-Zmiri-disable-isolation`.
    /// Miri does not model file-backed mmap, `mincore`, `readahead`
    /// or `MADV_POPULATE_READ`.
    #[cfg(unix)]
    #[test]
    fn read_owned_f64_fills_spare_capacity_by_pread() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("known.conbin");
        write_known(&path, 2, 8);
        for threads in [1usize, 2] {
            let (header, pos, vel) = read_owned_f64(&path, threads).unwrap();
            let n = header.position_len().unwrap();
            assert_eq!(pos.len(), n);
            assert_eq!(vel.len(), n);
            let mut raw = Vec::new();
            std::io::Read::read_to_end(&mut File::open(&path).unwrap(), &mut raw).unwrap();
            let off = raw.len() - 2 * n * 8;
            let want: Vec<f64> = raw[off..]
                .as_chunks::<8>()
                .0
                .iter()
                .map(|chunk| f64::from_le_bytes(*chunk))
                .collect();
            assert_eq!(pos.as_slice(), &want[..n]);
            assert_eq!(vel.as_slice(), &want[n..]);
        }
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn populate_followup_touches_only_after_einval() {
        assert!(populate_followup(libc::EINVAL).is_ok());
        for code in [libc::EFAULT, libc::EIO, libc::EHWPOISON, libc::ENOMEM] {
            assert_eq!(populate_followup(code).unwrap_err(), code);
        }
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn wait_resident_rejects_an_unaligned_address() {
        let page = page_size().unwrap();
        let ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                page,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_PRIVATE | libc::MAP_ANONYMOUS,
                -1,
                0,
            )
        };
        assert_ne!(ptr, libc::MAP_FAILED);
        let err = wait_resident(ptr as usize + 1, 0, 1, page).unwrap_err();
        assert!(err.contains("page-aligned"), "{err}");
        unsafe { libc::munmap(ptr, page) };
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn wait_resident_returns_an_unmapped_populate_error() {
        let page = page_size().unwrap();
        let ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                page,
                libc::PROT_NONE,
                libc::MAP_PRIVATE | libc::MAP_ANONYMOUS,
                -1,
                0,
            )
        };
        assert_ne!(ptr, libc::MAP_FAILED);
        unsafe { libc::munmap(ptr, page) };
        let err = wait_resident(ptr as usize, 0, page, page).unwrap_err();
        assert!(err.contains("os error"), "{err}");
    }
}
