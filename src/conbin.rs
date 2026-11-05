//! CON-bin: a fixed header block, then every frame's positions as one run
//! of little-endian values, then the velocities the same way.
//!
//! [`map_file`] maps that file and faults it in place. The runs are the
//! columns: the caller does not allocate a second buffer, so the read does
//! not take a write fault per destination page. [`read_into_threads`] is the
//! `pread` fill of a caller-owned slice, kept so a measurement can pair the
//! two on the same file. The header block is [`PAYLOAD_ALIGN`] bytes, which
//! does not follow the page size of the host.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::fd::AsRawFd;
use std::path::Path;

use crate::error::ParseError;
use crate::iterators::ConFrameIterator;

/// Coordinates stored for one atom.
pub const COORDS_PER_ATOM: usize = 3;

/// One kibibyte. [`PAYLOAD_ALIGN`] is a whole number of these.
const KIBIBYTE: usize = 1024;

/// Bytes of header a writer emits before the payload.
///
/// 64 KiB is a multiple of a 4 KiB page, a 16 KiB page and a 64 KiB page,
/// so a span of this length is a valid `madvise` range on those hosts.
/// Readers still accept a payload offset from a file whose header was only
/// one 4 KiB page.
pub const PAYLOAD_ALIGN: usize = 64 * KIBIBYTE;

const MAGIC: &[u8] = b"CONBIN01";
const VERSION: u32 = 1;
/// Bit 0 of the flags field. Set when each value is binary32.
const FLAG_BINARY32: u32 = 1 << 0;
/// Bit 1 of the flags field. Set when a velocity run follows positions.
const FLAG_VELOCITY: u32 = 1 << 1;

const VERSION_BYTES: usize = (u32::BITS / u8::BITS) as usize;
const FLAGS_BYTES: usize = (u32::BITS / u8::BITS) as usize;
const COUNT_BYTES: usize = (u64::BITS / u8::BITS) as usize;
const OFFSET_BYTES: usize = (u64::BITS / u8::BITS) as usize;

const MAGIC_START: usize = 0;
const VERSION_START: usize = MAGIC_START + MAGIC.len();
const FLAGS_START: usize = VERSION_START + VERSION_BYTES;
const FRAMES_START: usize = FLAGS_START + FLAGS_BYTES;
const ATOMS_START: usize = FRAMES_START + COUNT_BYTES;
const OFFSET_START: usize = ATOMS_START + COUNT_BYTES;
/// Magic, version, flags, frame count, atom count and payload offset.
pub const HEADER_BYTES: usize = OFFSET_START + OFFSET_BYTES;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConBinHeader {
    pub n_frames: u64,
    pub n_atoms: u64,
    pub binary32: bool,
    pub velocities: bool,
}

impl ConBinHeader {
    pub fn position_len(&self) -> Result<usize, ParseError> {
        let frames = usize::try_from(self.n_frames)
            .map_err(|_| ParseError::InvalidCount("CON-bin frame count overflows".into()))?;
        let atoms = usize::try_from(self.n_atoms)
            .map_err(|_| ParseError::InvalidCount("CON-bin atom count overflows".into()))?;
        frames
            .checked_mul(atoms)
            .and_then(|n| n.checked_mul(COORDS_PER_ATOM))
            .ok_or_else(|| ParseError::InvalidCount("CON-bin column length overflows".into()))
    }
}

fn header_fields(header: &ConBinHeader, payload_off: u64) -> [u8; HEADER_BYTES] {
    let mut out = [0u8; HEADER_BYTES];
    out[MAGIC_START..VERSION_START].copy_from_slice(MAGIC);
    out[VERSION_START..FLAGS_START].copy_from_slice(&VERSION.to_le_bytes());
    let mut flags = 0u32;
    if header.binary32 {
        flags |= FLAG_BINARY32;
    }
    if header.velocities {
        flags |= FLAG_VELOCITY;
    }
    out[FLAGS_START..FRAMES_START].copy_from_slice(&flags.to_le_bytes());
    out[FRAMES_START..ATOMS_START].copy_from_slice(&header.n_frames.to_le_bytes());
    out[ATOMS_START..OFFSET_START].copy_from_slice(&header.n_atoms.to_le_bytes());
    out[OFFSET_START..HEADER_BYTES].copy_from_slice(&payload_off.to_le_bytes());
    out
}

fn parse_fields(bytes: &[u8]) -> Result<(ConBinHeader, u64), ParseError> {
    if bytes.len() < HEADER_BYTES || &bytes[MAGIC_START..VERSION_START] != MAGIC {
        return Err(ParseError::ValidationError(
            "CON-bin header is not CONBIN01".into(),
        ));
    }
    let version = u32::from_le_bytes(
        bytes[VERSION_START..FLAGS_START]
            .try_into()
            .expect("version field is 4 bytes"),
    );
    if version != VERSION {
        return Err(ParseError::ValidationError(format!(
            "CON-bin version {version} is not {VERSION}"
        )));
    }
    let flags = u32::from_le_bytes(
        bytes[FLAGS_START..FRAMES_START]
            .try_into()
            .expect("flags field is 4 bytes"),
    );
    let offset = u64::from_le_bytes(
        bytes[OFFSET_START..HEADER_BYTES]
            .try_into()
            .expect("offset field is 8 bytes"),
    );
    Ok((
        ConBinHeader {
            n_frames: u64::from_le_bytes(
                bytes[FRAMES_START..ATOMS_START]
                    .try_into()
                    .expect("frame count is 8 bytes"),
            ),
            n_atoms: u64::from_le_bytes(
                bytes[ATOMS_START..OFFSET_START]
                    .try_into()
                    .expect("atom count is 8 bytes"),
            ),
            binary32: flags & FLAG_BINARY32 != 0,
            velocities: flags & FLAG_VELOCITY != 0,
        },
        offset,
    ))
}

/// Column element. Sealed so only `f32` and `f64` can satisfy it.
///
/// Stored values are little-endian. `write_le` and `read_le` name that
/// order, so a host of either endian writes and reads the same bytes.
trait ConBinFloat: Copy + float_seal::Sealed {
    fn write_le(self, out: &mut Vec<u8>);
    fn read_le(bytes: &[u8]) -> Self;
}

mod float_seal {
    pub trait Sealed {}
    impl Sealed for f32 {}
    impl Sealed for f64 {}
}

impl ConBinFloat for f32 {
    fn write_le(self, out: &mut Vec<u8>) {
        out.extend_from_slice(&self.to_le_bytes());
    }

    fn read_le(bytes: &[u8]) -> Self {
        let mut buf = [0u8; 4];
        buf.copy_from_slice(bytes);
        f32::from_le_bytes(buf)
    }
}

impl ConBinFloat for f64 {
    fn write_le(self, out: &mut Vec<u8>) {
        out.extend_from_slice(&self.to_le_bytes());
    }

    fn read_le(bytes: &[u8]) -> Self {
        let mut buf = [0u8; 8];
        buf.copy_from_slice(bytes);
        f64::from_le_bytes(buf)
    }
}

/// The file is little-endian. A big-endian host must not treat those bytes as values.
fn require_little_endian() -> Result<(), ParseError> {
    if cfg!(target_endian = "little") {
        Ok(())
    } else {
        Err(ParseError::ValidationError(
            "CON-bin is little-endian; this host cannot view it in place".into(),
        ))
    }
}

/// Payload start shared by the mapped reader and the copy path.
///
/// An offset of 0 means the payload begins at [`PAYLOAD_ALIGN`], which is
/// where [`write_from_con`] puts it. Any other offset has to begin at or
/// after the header fields, lie inside the file, and be aligned for the
/// value width. A binary64 payload aligns to `f64`. A binary32 payload
/// aligns to `f32`. It does not have to be a multiple of the host page or
/// of [`PAYLOAD_ALIGN`], so a file written on a 4 KiB page still opens on
/// a 16 KiB or 64 KiB host. Offsets 1 through [`HEADER_BYTES`] - 1 are rejected.
fn payload_start(offset: u64, file_len: u64, binary32: bool) -> Result<u64, ParseError> {
    let start = if offset == 0 {
        PAYLOAD_ALIGN as u64
    } else {
        offset
    };
    let align = if binary32 {
        std::mem::align_of::<f32>() as u64
    } else {
        std::mem::align_of::<f64>() as u64
    };
    if start < HEADER_BYTES as u64 || start > file_len || start % align != 0 {
        return Err(ParseError::ValidationError(
            "CON-bin payload offset is not an aligned boundary inside the file".into(),
        ));
    }
    Ok(start)
}

/// A mapped CON-bin. The position run and the velocity run are the file.
///
/// The map, the header and the payload offset stay private. Callers use
/// [`ConBinMap::header`], [`ConBinMap::payload_offset`] and the column accessors.
pub struct ConBinMap {
    map: memmap2::Mmap,
    header: ConBinHeader,
    payload_off: usize,
}

impl ConBinMap {
    /// Header fields of the mapped file.
    pub fn header(&self) -> &ConBinHeader {
        &self.header
    }

    /// Byte offset of the first payload value.
    pub fn payload_offset(&self) -> usize {
        self.payload_off
    }

    /// Hand the mapping to the Python module in this crate.
    #[cfg(feature = "python")]
    pub(crate) fn into_map(self) -> memmap2::Mmap {
        self.map
    }

    pub fn positions_f64(&self) -> Result<&[f64], ParseError> {
        self.require_storage(false)?;
        self.run(0)
    }

    pub fn velocities_f64(&self) -> Result<&[f64], ParseError> {
        self.require_storage(false)?;
        self.require_velocities()?;
        let n = self.header.position_len()?;
        self.run(n)
    }

    pub fn positions_f32(&self) -> Result<&[f32], ParseError> {
        self.require_storage(true)?;
        self.run(0)
    }

    pub fn velocities_f32(&self) -> Result<&[f32], ParseError> {
        self.require_storage(true)?;
        self.require_velocities()?;
        let n = self.header.position_len()?;
        self.run(n)
    }

    fn require_storage(&self, binary32: bool) -> Result<(), ParseError> {
        if self.header.binary32 == binary32 {
            return Ok(());
        }
        Err(ParseError::ValidationError(if binary32 {
            "CON-bin file is binary64; use the binary64 readers".into()
        } else {
            "CON-bin file is binary32; use the binary32 readers".into()
        }))
    }

    fn require_velocities(&self) -> Result<(), ParseError> {
        if self.header.velocities {
            Ok(())
        } else {
            Err(ParseError::ValidationError(
                "CON-bin file has no velocities".into(),
            ))
        }
    }

    fn run<T: ConBinFloat>(&self, column: usize) -> Result<&[T], ParseError> {
        let width = std::mem::size_of::<T>();
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
        require_little_endian()?;
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
}

/// Map `path` and fault the pages in before returning.
///
/// `MADV_HUGEPAGE` is applied before the fault. `MAP_POPULATE` would fault
/// inside `mmap`, before that advice, so the faults would be base pages.
/// `MADV_POPULATE_READ` (Linux 5.14) waits until the pages are resident.
/// A kernel older than that, and some filesystems, reject the hint.
/// The hint is not required. A failure leaves the mapping in place, and
/// the pages fault when the caller reads them.
/// `MADV_SEQUENTIAL` and `MADV_WILLNEED` are the other access hints.
/// `threads` workers fault spans of [`PAYLOAD_ALIGN`] bytes. A file shorter
/// than one such span per worker stays on one worker. That span is a multiple
/// of a 4 KiB, 16 KiB or 64 KiB page, which is what `madvise` requires.
///
/// When `mmap` itself fails, the file is read into a private mapping.
/// That mapping holds the same bytes, so the accessors return the same values.
///
/// A file-backed map covers the file as it is at this call. A later truncation
/// can raise `SIGBUS` on the next fault and end the process. Do not shrink the
/// file while a [`ConBinMap`], or a slice borrowed from it, is still in use.
pub fn map_file(path: &Path, threads: usize) -> Result<ConBinMap, ParseError> {
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let map = map_or_read(&file)?;
    if map.len() < HEADER_BYTES {
        return Err(ParseError::ValidationError(
            "CON-bin header is not CONBIN01".into(),
        ));
    }
    let (header, offset) = parse_fields(&map[..HEADER_BYTES])?;
    let payload_off = payload_start(offset, map.len() as u64, header.binary32)? as usize;
    fault_in(&map, threads, PAYLOAD_ALIGN)?;
    Ok(ConBinMap {
        map,
        header,
        payload_off,
    })
}

/// File-backed map, or a private map filled by `read` when `mmap` fails.
fn map_or_read(file: &File) -> Result<memmap2::Mmap, ParseError> {
    #[cfg(test)]
    if MAP_FAILS.with(|flag| flag.get()) {
        return private_map(file);
    }
    // SAFETY: `file` is open for reading and `Mmap::map` maps its current
    // length read-only. The mapping does not stop a later truncation. A fault
    // on a page that is no longer in the file raises SIGBUS.
    match unsafe { memmap2::Mmap::map(file) } {
        Ok(map) => Ok(map),
        Err(_) => private_map(file),
    }
}

fn private_map(file: &File) -> Result<memmap2::Mmap, ParseError> {
    let len = usize::try_from(
        file.metadata()
            .map_err(|err| ParseError::ValidationError(err.to_string()))?
            .len(),
    )
    .map_err(|_| ParseError::InvalidCount("CON-bin file length overflows".into()))?;
    if len < HEADER_BYTES {
        return Err(ParseError::ValidationError(
            "CON-bin header is not CONBIN01".into(),
        ));
    }
    let mut anon = memmap2::MmapOptions::new()
        .len(len)
        .map_anon()
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut reader = file
        .try_clone()
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    reader
        .read_exact(&mut anon)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    anon.make_read_only()
        .map_err(|err| ParseError::ValidationError(err.to_string()))
}

#[cfg(test)]
thread_local! {
    static POPULATE_FAILS: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
    static MAP_FAILS: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

fn fault_in(map: &memmap2::Mmap, threads: usize, page: usize) -> Result<(), ParseError> {
    // Hints. A kernel without transparent huge pages rejects HUGEPAGE.
    // A rejected populate hint falls through to a plain touch below.
    let _ = map.advise(memmap2::Advice::Sequential);
    #[cfg(target_os = "linux")]
    let _ = map.advise(memmap2::Advice::HugePage);
    let _ = map.advise(memmap2::Advice::WillNeed);
    if try_populate(map, threads, page).is_err() {
        touch_pages(map, page);
    }
    Ok(())
}

/// `MADV_POPULATE_READ` where the host has it. Failure is a hint failure.
fn try_populate(map: &memmap2::Mmap, threads: usize, page: usize) -> Result<(), ParseError> {
    #[cfg(test)]
    if POPULATE_FAILS.with(|flag| flag.get()) {
        return Err(ParseError::ValidationError(
            "CON-bin populate hint failed".into(),
        ));
    }
    #[cfg(target_os = "linux")]
    {
        advise_spans(map, memmap2::Advice::PopulateRead, threads, page)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (map, threads, page);
        Err(ParseError::ValidationError(
            "CON-bin populate hint is absent".into(),
        ))
    }
}

fn touch_pages(map: &memmap2::Mmap, page: usize) {
    let page = page.max(1);
    for chunk in map.chunks(page) {
        std::hint::black_box(chunk.first().copied());
    }
}

#[cfg(target_os = "linux")]
fn advise_spans(
    map: &memmap2::Mmap,
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
    let mut bytes = [0u8; HEADER_BYTES];
    file.read_exact(&mut bytes)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    parse_fields(&bytes).map(|(header, _)| header)
}

fn bytes_of<T: ConBinFloat>(values: &mut [T]) -> &mut [u8] {
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

/// [`read_into`] with `threads` workers. Each worker reads a span of
/// [`PAYLOAD_ALIGN`] bytes. A shorter span stays on one worker.
pub fn read_into_threads(
    path: &Path,
    positions: &mut [f64],
    velocities: Option<&mut [f64]>,
    threads: usize,
) -> Result<ConBinHeader, ParseError> {
    read_columns_into(path, positions, velocities, threads, false)
}

/// Copy a binary32 CON-bin into caller-owned columns. One thread issues the reads.
pub fn read_into_f32(
    path: &Path,
    positions: &mut [f32],
    velocities: Option<&mut [f32]>,
) -> Result<ConBinHeader, ParseError> {
    read_into_f32_threads(path, positions, velocities, 1)
}

/// [`read_into_f32`] with `threads` workers. The split is the same
/// [`PAYLOAD_ALIGN`] rule as [`read_into_threads`].
pub fn read_into_f32_threads(
    path: &Path,
    positions: &mut [f32],
    velocities: Option<&mut [f32]>,
    threads: usize,
) -> Result<ConBinHeader, ParseError> {
    read_columns_into(path, positions, velocities, threads, true)
}

fn read_columns_into<T: ConBinFloat>(
    path: &Path,
    positions: &mut [T],
    velocities: Option<&mut [T]>,
    threads: usize,
    binary32: bool,
) -> Result<ConBinHeader, ParseError> {
    require_little_endian()?;
    let file = File::open(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut raw = [0u8; HEADER_BYTES];
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
    let file_len = file
        .metadata()
        .map_err(|err| ParseError::ValidationError(err.to_string()))?
        .len();
    let pos_off = payload_start(offset, file_len, header.binary32)?;
    if std::mem::size_of_val(positions) != expect {
        return Err(ParseError::InvalidCount(format!(
            "position slice has {} bytes, the file has {expect}",
            std::mem::size_of_val(positions)
        )));
    }
    let pos_end = run_end(pos_off, expect, file_len)?;
    let fd = file.as_raw_fd();
    // Sequential advice matches one pass over the payload. WILLNEED is not
    // used here: it starts a second readahead beside the reads themselves.
    // `posix_fadvise` is a Linux call. Other Unix hosts just read.
    // SAFETY: `fd` is the open file. Offset 0 and length 0 advise the whole
    // file. The call does not write bytes and does not move the cursor.
    #[cfg(target_os = "linux")]
    unsafe {
        libc::posix_fadvise(fd, 0, 0, libc::POSIX_FADV_SEQUENTIAL);
    }
    // Linux read returns at most MAX_RW_COUNT bytes (INT_MAX aligned down to
    // the page, include/linux/fs.h). `pread_all` continues until the span is full.
    {
        let pos_bytes = bytes_of(positions);
        pread_parallel(fd, pos_bytes, pos_off, threads, PAYLOAD_ALIGN)?;
    }
    decode_le(positions);
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
        run_end(pos_end, expect, file_len)?;
        {
            let vel_bytes = bytes_of(vel);
            pread_parallel(fd, vel_bytes, pos_end, threads, PAYLOAD_ALIGN)?;
        }
        decode_le(vel);
    } else if velocities.is_some() {
        return Err(ParseError::ValidationError(
            "CON-bin file has no velocities".into(),
        ));
    }
    Ok(header)
}

/// End of the run of `len` bytes at `start`. The run must end inside the
/// file, which keeps the offsets that `pread_parallel` computes in `off_t`.
fn run_end(start: u64, len: usize, file_len: u64) -> Result<u64, ParseError> {
    start
        .checked_add(len as u64)
        .filter(|&end| end <= file_len)
        .ok_or(ParseError::IncompleteFrame)
}

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

fn pread_all(fd: i32, dest: &mut [u8], mut offset: u64) -> Result<(), ParseError> {
    let mut done = 0;
    while done < dest.len() {
        // SAFETY: `dest[done..]` is the unread tail of the caller buffer.
        // `fd` is open for reading. `offset` is the file position of that
        // tail. `pread` writes at most the tail length and leaves the cursor.
        let n = unsafe {
            libc::pread(
                fd,
                dest[done..].as_mut_ptr().cast(),
                dest.len() - done,
                offset as libc::off_t,
            )
        };
        if n < 0 {
            return Err(ParseError::ValidationError(
                std::io::Error::last_os_error().to_string(),
            ));
        }
        if n == 0 {
            return Err(ParseError::IncompleteFrame);
        }
        done += n as usize;
        offset += n as u64;
    }
    Ok(())
}

fn write_values<T: ConBinFloat>(file: &mut File, values: &[T]) -> Result<(), ParseError> {
    let mut bytes = Vec::with_capacity(std::mem::size_of_val(values));
    for value in values {
        value.write_le(&mut bytes);
    }
    file.write_all(&bytes)
        .map_err(|err| ParseError::ValidationError(err.to_string()))
}

/// Turn the little-endian bytes `pread` stored into host values.
fn decode_le<T: ConBinFloat>(values: &mut [T]) {
    let width = std::mem::size_of::<T>();
    let nbytes = std::mem::size_of_val(values);
    let mut raw = vec![0u8; nbytes];
    // SAFETY: `values` is initialized. The copy is the bytes `pread` wrote,
    // which are little-endian elements of `T`.
    unsafe {
        std::ptr::copy_nonoverlapping(values.as_ptr().cast::<u8>(), raw.as_mut_ptr(), nbytes);
    }
    for (slot, chunk) in values.iter_mut().zip(raw.chunks_exact(width)) {
        *slot = T::read_le(chunk);
    }
}

fn write_header_page(file: &mut File, header: &ConBinHeader) -> Result<(), ParseError> {
    let mut header_page = vec![0u8; PAYLOAD_ALIGN];
    let prefix = header_fields(header, PAYLOAD_ALIGN as u64);
    header_page[..HEADER_BYTES].copy_from_slice(&prefix);
    file.write_all(&header_page)
        .map_err(|err| ParseError::ValidationError(err.to_string()))
}

/// Write one binary64 file whose columns come from `seed`.
///
/// The header page and both runs match what [`map_file`] and [`read_into`] read.
/// `seed` is mixed with each value index, so the same triple writes the same file.
pub fn write_uniform(
    path: &Path,
    frames: u64,
    atoms: u64,
    seed: u64,
) -> Result<ConBinHeader, ParseError> {
    let header = ConBinHeader {
        n_frames: frames,
        n_atoms: atoms,
        binary32: false,
        velocities: true,
    };
    let n = header.position_len()?;
    let mut file =
        File::create(path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    write_header_page(&mut file, &header)?;
    let pos: Vec<f64> = (0..n).map(|i| mix_unit(seed, i as u64)).collect();
    let vel: Vec<f64> = (0..n)
        .map(|i| mix_unit(seed, (n as u64) + i as u64))
        .collect();
    write_values(&mut file, &pos)?;
    write_values(&mut file, &vel)?;
    Ok(header)
}

/// SplitMix64 finalizer, then a unit interval.
/// The multipliers and shift distances are the ones in Steele, Lea and Flood, 2014.
const SPLITMIX_MUL_1: u64 = 0x9E37_79B9_7F4A_7C15;
const SPLITMIX_MUL_2: u64 = 0xBF58_476D_1CE4_E5B9;
const SPLITMIX_MUL_3: u64 = 0x94D0_49BB_1331_11EB;
const SPLITMIX_SHIFT_1: u32 = 30;
const SPLITMIX_SHIFT_2: u32 = 27;
const SPLITMIX_SHIFT_3: u32 = 31;
const SPLITMIX_FLOAT_SHIFT: u32 = 11;
const SPLITMIX_FLOAT_BITS: u32 = 53;

fn mix_unit(seed: u64, index: u64) -> f64 {
    let mut z = seed.wrapping_add(index).wrapping_mul(SPLITMIX_MUL_1);
    z = (z ^ (z >> SPLITMIX_SHIFT_1)).wrapping_mul(SPLITMIX_MUL_2);
    z = (z ^ (z >> SPLITMIX_SHIFT_2)).wrapping_mul(SPLITMIX_MUL_3);
    z ^= z >> SPLITMIX_SHIFT_3;
    (z >> SPLITMIX_FLOAT_SHIFT) as f64 / ((1u64 << SPLITMIX_FLOAT_BITS) as f64)
}

/// Read a CON text file and write a CON-bin of the same frames.
///
/// The header occupies [`PAYLOAD_ALIGN`] bytes, so the payload starts on that
/// boundary. The parser reads every frame into the position column before the
/// file is written. The velocity column is written only when every frame has
/// velocities. A file that mixes frames with and without velocities is an error.
pub fn write_from_con(
    con_path: &Path,
    out_path: &Path,
    binary32: bool,
) -> Result<ConBinHeader, ParseError> {
    let text = std::fs::read_to_string(con_path)
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    let mut file =
        File::create(out_path).map_err(|err| ParseError::ValidationError(err.to_string()))?;
    write_header_page(
        &mut file,
        &ConBinHeader {
            n_frames: 0,
            n_atoms: 0,
            binary32,
            velocities: false,
        },
    )?;

    let mut n_frames = 0u64;
    let mut n_atoms = 0u64;
    let mut positions: Vec<f64> = Vec::new();
    let mut velocities: Vec<f64> = Vec::new();
    // None until the first atom decides. After that every atom must agree.
    let mut with_velocities: Option<bool> = None;
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
            positions.extend_from_slice(&[atom.x, atom.y, atom.z]);
            match (atom.velocity(), with_velocities) {
                (Some(value), None) => {
                    with_velocities = Some(true);
                    velocities.extend_from_slice(&value);
                }
                (Some(value), Some(true)) => velocities.extend_from_slice(&value),
                (None, None) => with_velocities = Some(false),
                (None, Some(false)) => {}
                _ => {
                    return Err(ParseError::ValidationError(
                        "CON-bin needs velocities on every frame, or on none".into(),
                    ));
                }
            }
        }
        n_frames += 1;
    }
    if binary32 {
        let pos32: Vec<f32> = positions.iter().map(|v| *v as f32).collect();
        write_values(&mut file, &pos32)?;
        if with_velocities == Some(true) {
            let vel32: Vec<f32> = velocities.iter().map(|v| *v as f32).collect();
            write_values(&mut file, &vel32)?;
        }
    } else {
        write_values(&mut file, &positions)?;
        if with_velocities == Some(true) {
            write_values(&mut file, &velocities)?;
        }
    }
    let header = ConBinHeader {
        n_frames,
        n_atoms,
        binary32,
        velocities: with_velocities == Some(true),
    };
    file.seek(SeekFrom::Start(0))
        .map_err(|err| ParseError::ValidationError(err.to_string()))?;
    write_header_page(&mut file, &header)?;
    Ok(header)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_columns(path: &Path, frames: usize, atoms: usize, binary32: bool, velocities: bool) {
        let mut file = File::create(path).unwrap();
        let header = ConBinHeader {
            n_frames: frames as u64,
            n_atoms: atoms as u64,
            binary32,
            velocities,
        };
        write_header_page(&mut file, &header).unwrap();
        let n = frames * atoms * COORDS_PER_ATOM;
        if binary32 {
            let pos: Vec<f32> = (0..n).map(|i| i as f32).collect();
            write_values(&mut file, &pos).unwrap();
            if velocities {
                let vel: Vec<f32> = (0..n).map(|i| -(i as f32)).collect();
                write_values(&mut file, &vel).unwrap();
            }
        } else {
            let pos: Vec<f64> = (0..n).map(|i| i as f64 * 0.25).collect();
            write_values(&mut file, &pos).unwrap();
            if velocities {
                let vel: Vec<f64> = (0..n).map(|i| i as f64 * -0.5).collect();
                write_values(&mut file, &vel).unwrap();
            }
        }
    }

    fn write_known(path: &Path, frames: usize, atoms: usize) {
        write_columns(path, frames, atoms, false, true);
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
        assert_eq!(pos.len(), 4 * 3 * COORDS_PER_ATOM);
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

    struct HookGuard {
        slot: &'static std::thread::LocalKey<std::cell::Cell<bool>>,
    }

    impl HookGuard {
        fn arm(slot: &'static std::thread::LocalKey<std::cell::Cell<bool>>) -> Self {
            slot.with(|flag| flag.set(true));
            Self { slot }
        }
    }

    impl Drop for HookGuard {
        fn drop(&mut self) {
            self.slot.with(|flag| flag.set(false));
        }
    }

    #[test]
    fn populate_failure_still_reads_the_same_values() {
        let dir = std::env::temp_dir().join(format!("conbin-populate-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        write_known(&path, 4, 3);
        let plain = map_file(&path, 2).unwrap();
        let expect_pos = plain.positions_f64().unwrap().to_vec();
        let expect_vel = plain.velocities_f64().unwrap().to_vec();
        drop(plain);
        let _guard = HookGuard::arm(&POPULATE_FAILS);
        let mapped = map_file(&path, 2).unwrap();
        assert_eq!(mapped.positions_f64().unwrap(), expect_pos.as_slice());
        assert_eq!(mapped.velocities_f64().unwrap(), expect_vel.as_slice());
        let mut got_pos = vec![0.0; expect_pos.len()];
        let mut got_vel = vec![0.0; expect_vel.len()];
        read_into_threads(&path, &mut got_pos, Some(&mut got_vel), 2).unwrap();
        assert_eq!(got_pos, expect_pos);
        assert_eq!(got_vel, expect_vel);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn mmap_failure_still_reads_the_same_values() {
        let dir = std::env::temp_dir().join(format!("conbin-mmap-fail-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("known.conbin");
        write_known(&path, 4, 3);
        let plain = map_file(&path, 1).unwrap();
        let expect_pos = plain.positions_f64().unwrap().to_vec();
        let expect_vel = plain.velocities_f64().unwrap().to_vec();
        drop(plain);
        let _guard = HookGuard::arm(&MAP_FAILS);
        let mapped = map_file(&path, 1).unwrap();
        assert_eq!(mapped.positions_f64().unwrap(), expect_pos.as_slice());
        assert_eq!(mapped.velocities_f64().unwrap(), expect_vel.as_slice());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn writer_stores_one_known_value_little_endian() {
        let dir = std::env::temp_dir().join(format!("conbin-le-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("one.conbin");
        // Second position is 0.25. Its little-endian bytes are fixed.
        write_known(&path, 1, 1);
        let known = 0.25f64;
        let bytes = std::fs::read(&path).unwrap();
        let at = PAYLOAD_ALIGN + std::mem::size_of::<f64>();
        assert_eq!(&bytes[at..at + 8], known.to_le_bytes().as_slice());
        let mapped = map_file(&path, 1).unwrap();
        assert_eq!(mapped.positions_f64().unwrap()[1], known);
        let mut got = vec![0.0; mapped.header().position_len().unwrap()];
        let mut vel = vec![0.0; got.len()];
        read_into_threads(&path, &mut got, Some(&mut vel), 1).unwrap();
        assert_eq!(got[1], known);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn copied_reads_fail_on_a_payload_offset_past_the_file() {
        let dir = std::env::temp_dir().join(format!("conbin-offset-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("far.conbin");
        // Two payload blocks of positions, so that two workers split the run.
        let atoms = (2 * PAYLOAD_ALIGN).div_ceil(COORDS_PER_ATOM * std::mem::size_of::<f64>());
        write_known(&path, 1, atoms);
        let header = read_header(&path).unwrap();
        let n = header.position_len().unwrap();
        let mut bytes = std::fs::read(&path).unwrap();
        // An offset past the file fails the shared check.
        bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, u64::MAX));
        std::fs::write(&path, &bytes).unwrap();
        for threads in [1, 2] {
            let mut pos = vec![0.0; n];
            let mut vel = vec![0.0; n];
            let got = read_into_threads(&path, &mut pos, Some(&mut vel), threads);
            assert!(
                matches!(got, Err(ParseError::ValidationError(_))),
                "offset past the file, {threads} threads: {got:?}"
            );
        }
        // An aligned offset at the end of the file passes that check.
        // The run then ends past the file.
        let at_end = bytes.len() as u64;
        bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, at_end));
        std::fs::write(&path, &bytes).unwrap();
        for threads in [1, 2] {
            let mut pos = vec![0.0; n];
            let mut vel = vec![0.0; n];
            let got = read_into_threads(&path, &mut pos, Some(&mut vel), threads);
            assert!(
                matches!(got, Err(ParseError::IncompleteFrame)),
                "offset at end of file, {threads} threads: {got:?}"
            );
        }
        // An aligned offset at the end of a header-only file lets the shared
        // check pass, and the run then ends past the file.
        bytes.truncate(PAYLOAD_ALIGN);
        bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, PAYLOAD_ALIGN as u64));
        std::fs::write(&path, &bytes).unwrap();
        for threads in [1, 2] {
            let mut pos = vec![0.0; n];
            let mut vel = vec![0.0; n];
            let got = read_into_threads(&path, &mut pos, Some(&mut vel), threads);
            assert!(
                matches!(got, Err(ParseError::IncompleteFrame)),
                "{threads} threads: {got:?}"
            );
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn mapped_readers_honour_storage_and_velocity_flags() {
        let dir = std::env::temp_dir().join(format!("conbin-flags-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("f32.conbin");
        write_columns(&path, 1, 2, true, false);
        let mapped = map_file(&path, 1).unwrap();
        assert!(mapped.positions_f64().is_err());
        assert!(mapped.velocities_f64().is_err());
        assert!(mapped.positions_f32().is_ok());
        assert!(mapped.velocities_f32().is_err());
        let n = mapped.header().position_len().unwrap();
        let mut pos = vec![0.0f32; n];
        let mut vel = vec![0.0f32; n];
        assert!(read_into_f32_threads(&path, &mut pos, Some(&mut vel), 1).is_err());
        read_into_f32_threads(&path, &mut pos, None, 1).unwrap();
        assert_eq!(pos[1], 1.0);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn four_kib_page_file_reads_when_the_host_page_is_wider() {
        // Header length of a file written on a host with 4 KiB pages.
        const FOUR_KIB: usize = 4 * KIBIBYTE;
        let dir = std::env::temp_dir().join(format!("conbin-4k-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("narrow.conbin");
        let frames = 2u64;
        let atoms = 3u64;
        let header = ConBinHeader {
            n_frames: frames,
            n_atoms: atoms,
            binary32: false,
            velocities: true,
        };
        let n = header.position_len().unwrap();
        let mut bytes = vec![0u8; FOUR_KIB];
        bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, FOUR_KIB as u64));
        let pos: Vec<f64> = (0..n).map(|i| i as f64 * 0.25).collect();
        let vel: Vec<f64> = (0..n).map(|i| i as f64 * -0.5).collect();
        for value in pos.iter().chain(&vel) {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        std::fs::write(&path, &bytes).unwrap();
        let mapped = map_file(&path, 2).unwrap();
        assert_eq!(mapped.payload_offset(), FOUR_KIB);
        assert_eq!(mapped.positions_f64().unwrap(), pos.as_slice());
        assert_eq!(mapped.velocities_f64().unwrap(), vel.as_slice());
        let mut got_pos = vec![0.0; n];
        let mut got_vel = vec![0.0; n];
        read_into_threads(&path, &mut got_pos, Some(&mut got_vel), 2).unwrap();
        assert_eq!(got_pos, pos);
        assert_eq!(got_vel, vel);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn offsets_off_a_page_still_read() {
        // 40, just after the header fields, and 4104, eight bytes past 4 KiB.
        const VALUE_BYTES: usize = std::mem::size_of::<f64>();
        const OFFSETS: [usize; 2] = [HEADER_BYTES, 4 * KIBIBYTE + VALUE_BYTES];
        let dir = std::env::temp_dir().join(format!("conbin-offpage-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let header = ConBinHeader {
            n_frames: 2,
            n_atoms: 3,
            binary32: false,
            velocities: true,
        };
        let n = header.position_len().unwrap();
        let pos: Vec<f64> = (0..n).map(|i| i as f64 * 0.25).collect();
        let vel: Vec<f64> = (0..n).map(|i| i as f64 * -0.5).collect();
        for offset in OFFSETS {
            let path = dir.join(format!("{offset}.conbin"));
            let mut bytes = vec![0u8; offset];
            bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, offset as u64));
            for value in pos.iter().chain(&vel) {
                bytes.extend_from_slice(&value.to_le_bytes());
            }
            std::fs::write(&path, &bytes).unwrap();
            let mapped = map_file(&path, 2).unwrap();
            assert_eq!(mapped.payload_offset(), offset);
            assert_eq!(mapped.positions_f64().unwrap(), pos.as_slice());
            assert_eq!(mapped.velocities_f64().unwrap(), vel.as_slice());
            let mut got_pos = vec![0.0; n];
            let mut got_vel = vec![0.0; n];
            read_into_threads(&path, &mut got_pos, Some(&mut got_vel), 2).unwrap();
            assert_eq!(got_pos, pos);
            assert_eq!(got_vel, vel);
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn copy_path_rejects_offsets_inside_the_header() {
        let dir = std::env::temp_dir().join(format!("conbin-off-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("hdr.conbin");
        write_known(&path, 1, 2);
        let header = read_header(&path).unwrap();
        let n = header.position_len().unwrap();
        let mut bytes = std::fs::read(&path).unwrap();
        for offset in 1..HEADER_BYTES as u64 {
            bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, offset));
            std::fs::write(&path, &bytes).unwrap();
            let mut pos = vec![0.0; n];
            let mut vel = vec![0.0; n];
            let copied = read_into_threads(&path, &mut pos, Some(&mut vel), 1);
            assert!(copied.is_err(), "copy offset {offset}");
            assert!(map_file(&path, 1).is_err(), "map offset {offset}");
        }
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
        let text = include_str!("../resources/test/tiny_cuh2.con").repeat(2);
        let mut expected = Vec::new();
        for frame in ConFrameIterator::new(&text) {
            let frame = frame.unwrap();
            for atom in &frame.atom_data {
                expected.extend_from_slice(&[atom.x, atom.y, atom.z]);
                assert!(atom.velocity().is_none());
            }
        }
        let header = write_from_con(&con, &bin, false).unwrap();
        assert_eq!(header.n_frames, 2);
        assert_eq!(header.n_atoms, 4);
        assert!(!header.velocities);
        let mapped = map_file(&bin, 1).unwrap();
        assert_eq!(mapped.positions_f64().unwrap(), expected.as_slice());
        assert!(mapped.velocities_f64().is_err());
        let mut got = vec![0.0; expected.len()];
        read_into_threads(&bin, &mut got, None, 1).unwrap();
        assert_eq!(got, expected);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn write_from_con_keeps_a_velocity_run_when_every_frame_has_one() {
        let dir = std::env::temp_dir().join(format!("conbin-vel-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("vel.convel");
        let text = include_str!("../resources/test/tiny_cuh2.convel");
        std::fs::write(&con, text).unwrap();
        let mut expected_pos = Vec::new();
        let mut expected_vel = Vec::new();
        for frame in ConFrameIterator::new(text) {
            let frame = frame.unwrap();
            for atom in &frame.atom_data {
                expected_pos.extend_from_slice(&[atom.x, atom.y, atom.z]);
                expected_vel.extend_from_slice(&atom.velocity().unwrap());
            }
        }
        let bin = dir.join("vel.conbin");
        let header = write_from_con(&con, &bin, false).unwrap();
        assert!(header.velocities);
        let mapped = map_file(&bin, 1).unwrap();
        assert_eq!(mapped.positions_f64().unwrap(), expected_pos.as_slice());
        assert_eq!(mapped.velocities_f64().unwrap(), expected_vel.as_slice());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn write_from_con_rejects_a_mix_of_velocity_frames() {
        let dir = std::env::temp_dir().join(format!("conbin-mix-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let con = dir.join("mix.con");
        let mixed = format!(
            "{}{}",
            include_str!("../resources/test/tiny_cuh2.con"),
            include_str!("../resources/test/tiny_cuh2.convel")
        );
        std::fs::write(&con, mixed).unwrap();
        let bin = dir.join("mix.conbin");
        let got = write_from_con(&con, &bin, false);
        assert!(
            matches!(got, Err(ParseError::ValidationError(_))),
            "{got:?}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn f64_payload_offset_must_be_aligned_when_the_file_opens() {
        let dir = std::env::temp_dir().join(format!("conbin-align-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("odd.conbin");
        // One f32 past the header fields: aligned for binary32, not for binary64.
        let offset = HEADER_BYTES + std::mem::align_of::<f32>();
        let header = ConBinHeader {
            n_frames: 1,
            n_atoms: 1,
            binary32: false,
            velocities: false,
        };
        let n = header.position_len().unwrap();
        let mut bytes = vec![0u8; offset];
        bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&header, offset as u64));
        let pos: Vec<f64> = (0..n).map(|i| i as f64).collect();
        for value in &pos {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        std::fs::write(&path, &bytes).unwrap();
        assert!(map_file(&path, 1).is_err());
        let mut got = vec![0.0; n];
        assert!(read_into_threads(&path, &mut got, None, 1).is_err());
        let narrow = ConBinHeader {
            binary32: true,
            ..header
        };
        bytes[..HEADER_BYTES].copy_from_slice(&header_fields(&narrow, offset as u64));
        bytes.truncate(offset);
        let pos32: Vec<f32> = (0..n).map(|i| i as f32).collect();
        for value in &pos32 {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        std::fs::write(&path, &bytes).unwrap();
        let mapped = map_file(&path, 1).unwrap();
        assert_eq!(mapped.payload_offset(), offset);
        assert_eq!(mapped.positions_f32().unwrap(), pos32.as_slice());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
