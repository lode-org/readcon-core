//=============================================================================
// Transparent compression support
//=============================================================================

use std::io::{self, Read, Write};
use std::path::Path;

/// zlib/gzip level used for CON payloads.
///
/// This is [`flate2::Compression::default`] (level 6). The historical
/// campaign median of 0.120 s was this level applied to a frame whose
/// coordinates had already been cleared; the first sample of that run,
/// still holding the lattice, was 0.371 s.
pub const GZIP_LEVEL: u32 = 6;

/// zstd level used for CON payloads. Level 3 is the zstd CLI default.
pub const ZSTD_LEVEL: i32 = 3;

/// Detected compression format based on magic bytes.
///
/// `Zstd` is only constructed when the `zstd` Cargo feature is enabled.
/// Builds without the feature treat `.zst` files as opaque bytes and
/// return an error from [`read_file_contents`] indicating the feature
/// is required.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Compression {
    None,
    Gzip,
    /// zstd data: a frame (`28 b5 2f fd`) or a skippable frame
    /// (`5? 2a 4d 18`, RFC 8878). Build with `--features zstd`.
    Zstd,
}

/// A Zstandard frame or a skippable frame, in the byte order on disk.
///
/// RFC 8878 gives a frame the magic `28 b5 2f fd` and a skippable frame
/// one of `50 2a 4d 18` through `5f 2a 4d 18`. A file from `pzstd` can
/// start with the skippable frame.
fn is_zstd_magic(bytes: &[u8]) -> bool {
    bytes.len() >= 4
        && (bytes[..4] == [0x28, 0xb5, 0x2f, 0xfd]
            || ((0x50..=0x5f).contains(&bytes[0])
                && bytes[1] == 0x2a
                && bytes[2] == 0x4d
                && bytes[3] == 0x18))
}

/// Detect compression format from the first bytes of a file.
///
/// - `1f 8b` = gzip
/// - `28 b5 2f fd` = zstd frame
/// - `5? 2a 4d 18` = zstd skippable frame
/// - Otherwise = uncompressed
pub fn detect_compression(bytes: &[u8]) -> Compression {
    if bytes.len() >= 2 && bytes[0] == 0x1f && bytes[1] == 0x8b {
        return Compression::Gzip;
    }
    if is_zstd_magic(bytes) {
        return Compression::Zstd;
    }
    Compression::None
}

/// Detect compression format from a file extension.
///
/// Returns `Compression::Gzip` for `.gz`, `Compression::Zstd` for
/// `.zst`, `Compression::None` otherwise.
pub fn detect_compression_from_extension(path: &Path) -> Compression {
    match path.extension().and_then(|e| e.to_str()) {
        Some("gz") => Compression::Gzip,
        Some("zst") => Compression::Zstd,
        _ => Compression::None,
    }
}

/// Size in bytes from which [`read_file_contents`] maps an uncompressed file.
/// A smaller one is read into a `String`.
pub const MMAP_THRESHOLD: u64 = 64 * 1024;

/// Reads file contents, decompressing if needed.
///
/// Detection strategy:
/// 1. Read the first 4 bytes to check magic bytes.
/// 2. If gzip or zstd: decompress entire file to a String.
/// 3. If uncompressed and smaller than [`MMAP_THRESHOLD`]: read the rest into a String.
/// 4. If uncompressed and at least [`MMAP_THRESHOLD`]: memory-mapped I/O.
///
/// The path is opened once and every byte comes from that handle, so a
/// pipe works and a file replaced during the call is not mixed in.
pub fn read_file_contents(path: &Path) -> Result<FileContents, Box<dyn std::error::Error>> {
    read_file_contents_detected(path).map(|(contents, _)| contents)
}

/// [`read_file_contents`], also returning the compression it detected.
pub fn read_file_contents_detected(
    path: &Path,
) -> Result<(FileContents, Compression), Box<dyn std::error::Error>> {
    read_contents(path, true)
}

/// [`read_file_contents`] as one owned `String`. An uncompressed file is
/// read into it at any size instead of being mapped, so the text is held
/// once and later changes to the file do not reach it.
pub fn read_file_text(path: &Path) -> Result<String, Box<dyn std::error::Error>> {
    match read_contents(path, false)?.0 {
        FileContents::Owned(text) => Ok(text),
        FileContents::Mapped(_) => unreachable!("read_contents maps only when asked to"),
    }
}

/// Bytes of one file, mapped when a plain file is large enough.
///
/// Compressed input is decoded into a buffer. A plain file under 64 KiB,
/// or anything that is not a regular file, is read into a buffer. A larger
/// plain file stays mapped for the parse and is not copied. The bytes are
/// not checked as UTF-8; the parser reports a bad byte when it reaches it.
pub enum ByteSource {
    Buf(Vec<u8>),
    Map(memmap2::Mmap),
}

impl ByteSource {
    pub fn as_slice(&self) -> &[u8] {
        match self {
            ByteSource::Buf(bytes) => bytes,
            ByteSource::Map(map) => map,
        }
    }
}

/// Load `path` for a parse. See [`ByteSource`].
pub fn read_bytes_owned(path: &Path) -> Result<ByteSource, Box<dyn std::error::Error>> {
    let mut file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;
    let mut magic = [0u8; 4];
    let n = (&mut file).take(4).read(&mut magic)?;
    match detect_compression(&magic[..n]) {
        Compression::None if metadata.is_file() && metadata.len() >= MMAP_THRESHOLD => {
            let map = unsafe { memmap2::Mmap::map(&file)? };
            Ok(ByteSource::Map(map))
        }
        Compression::None => {
            let mut bytes = Vec::with_capacity(metadata.len().saturating_add(4) as usize);
            bytes.extend_from_slice(&magic[..n]);
            file.read_to_end(&mut bytes)?;
            Ok(ByteSource::Buf(bytes))
        }
        Compression::Gzip | Compression::Zstd => {
            drop(file);
            Ok(ByteSource::Buf(read_file_bytes(path)?))
        }
    }
}

/// File bytes in one read when the file is not compressed.
///
/// Gzip and zstd still go through the decoder. Plain text skips the
/// four-byte probe and the UTF-8 `String` allocation.
pub fn read_file_bytes(path: &Path) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    let bytes = std::fs::read(path)?;
    let magic = &bytes[..bytes.len().min(4)];
    match detect_compression(magic) {
        Compression::None => Ok(bytes),
        Compression::Gzip => gunzip_all(&bytes).map_err(Into::into),
        Compression::Zstd => {
            #[cfg(feature = "zstd")]
            {
                zstd_decode_all(&bytes).map_err(Into::into)
            }
            #[cfg(not(feature = "zstd"))]
            {
                let _ = bytes;
                Err(zstd_unsupported().into())
            }
        }
    }
}

fn read_contents(
    path: &Path,
    map_large: bool,
) -> Result<(FileContents, Compression), Box<dyn std::error::Error>> {
    let file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;

    // gzip needs 2 magic bytes and zstd needs 4. They stay in front of the
    // rest of the stream, since a pipe cannot seek back.
    let mut magic = Vec::with_capacity(4);
    (&file).take(4).read_to_end(&mut magic)?;
    let compression = detect_compression(&magic);
    let mut stream = magic.as_slice().chain(&file);

    let contents = match compression {
        Compression::Gzip => {
            // Every gzip member, in order (CON-compress.1, D16). A file
            // this crate wrote stores member starts in the first extra
            // field and those slices are inflated together. Any other
            // gzip stream, including one member and a foreign multi-member
            // file, stays on the serial decoder.
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes)?;
            let plain = gunzip_all(&bytes)?;
            let contents = String::from_utf8(plain).map_err(|err| {
                io::Error::new(io::ErrorKind::InvalidData, err.utf8_error().to_string())
            })?;
            FileContents::Owned(contents)
        }
        Compression::Zstd => {
            #[cfg(feature = "zstd")]
            {
                let mut bytes = Vec::new();
                stream.read_to_end(&mut bytes)?;
                let plain = zstd_decode_all(&bytes)?;
                let contents = String::from_utf8(plain).map_err(|err| {
                    io::Error::new(io::ErrorKind::InvalidData, err.utf8_error().to_string())
                })?;
                FileContents::Owned(contents)
            }
            #[cfg(not(feature = "zstd"))]
            {
                return Err(zstd_unsupported().into());
            }
        }
        Compression::None if metadata.len() < MMAP_THRESHOLD => {
            let mut bytes = Vec::with_capacity(metadata.len() as usize);
            stream.read_to_end(&mut bytes)?;
            let contents = String::from_utf8(bytes).map_err(|_| {
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "stream did not contain valid UTF-8",
                )
            })?;
            FileContents::Owned(contents)
        }
        Compression::None if map_large => {
            let mmap = unsafe { memmap2::Mmap::map(&file)? };
            FileContents::Mapped(mmap)
        }
        Compression::None => {
            let mut bytes = Vec::with_capacity(metadata.len() as usize);
            stream.read_to_end(&mut bytes)?;
            // The message `as_str` gives for the same bytes when mapped.
            FileContents::Owned(String::from_utf8(bytes).map_err(|e| e.utf8_error())?)
        }
    };
    Ok((contents, compression))
}

#[cfg(not(feature = "zstd"))]
fn zstd_unsupported() -> io::Error {
    io::Error::new(
        io::ErrorKind::Unsupported,
        "zstd-compressed input detected; rebuild readcon-core with --features zstd",
    )
}

/// The bytes of `path` as one stream, decompressed while it is read.
///
/// Compression is detected by magic bytes, as in [`read_file_contents`],
/// and every gzip member is read in order.
/// The only memory used is the decoder's own buffers, so it does not grow
/// with the file.
pub fn open_decoded(path: &Path) -> Result<Box<dyn Read + Send>, Box<dyn std::error::Error>> {
    let mut file = std::fs::File::open(path)?;
    let mut magic = Vec::with_capacity(4);
    (&mut file).take(4).read_to_end(&mut magic)?;
    let compression = detect_compression(&magic);
    let stream = io::Cursor::new(magic).chain(file);
    Ok(match compression {
        Compression::Gzip => Box::new(flate2::read::MultiGzDecoder::new(stream)),
        #[cfg(feature = "zstd")]
        Compression::Zstd => Box::new(zstd::stream::read::Decoder::new(stream)?),
        #[cfg(not(feature = "zstd"))]
        Compression::Zstd => return Err(zstd_unsupported().into()),
        Compression::None => Box::new(stream),
    })
}

/// Holds file contents either as an owned String or a memory-mapped region.
pub enum FileContents {
    Owned(String),
    Mapped(memmap2::Mmap),
}

impl FileContents {
    pub fn as_str(&self) -> Result<&str, std::str::Utf8Error> {
        match self {
            FileContents::Owned(s) => Ok(s.as_str()),
            FileContents::Mapped(m) => std::str::from_utf8(m),
        }
    }

    pub fn as_bytes(&self) -> &[u8] {
        match self {
            FileContents::Owned(s) => s.as_bytes(),
            FileContents::Mapped(m) => m,
        }
    }

    /// Like [`Self::as_str`], but validates mapped files in newline-aligned
    /// slices (in parallel with the `parallel` feature).
    pub fn as_str_sliced(&self) -> Result<&str, std::str::Utf8Error> {
        match self {
            FileContents::Owned(s) => Ok(s.as_str()),
            FileContents::Mapped(m) => crate::frame_index::validate_utf8_sliced(m),
        }
    }
}

/// Mapped bytes between two releases of the pages already read.
const RELEASE_STEP: usize = 32 << 20;

/// The text of one file, read from the front.
///
/// With `map`, an uncompressed file of 64 KiB or more stays mapped, and
/// [`Self::release_before`] advises `MADV_DONTNEED` for the pages before the
/// read position. On Linux that drops the file pages, so resident memory
/// stays near [`RELEASE_STEP`] instead of the file size. macOS gets the same
/// call, but its `MADV_DONTNEED` does not discard pages. Outside Unix the
/// release is a no-op. On those systems the whole file can become resident.
/// A mapped file is not a snapshot and must not change while it is read; a
/// truncation can end the process with `SIGBUS`.
pub struct ForwardText {
    contents: FileContents,
    released: usize,
}

impl ForwardText {
    /// The text of `path`. Without `map` it is [`read_file_text`].
    pub fn open(path: &Path, map: bool) -> Result<Self, Box<dyn std::error::Error>> {
        let contents = if map {
            read_file_contents(path)?
        } else {
            FileContents::Owned(read_file_text(path)?)
        };
        // One sequential check. Discarding the pages here would fault
        // them back in during the parse, and a parallel check would
        // start a worker pool for a single slice.
        if let FileContents::Mapped(m) = &contents {
            std::str::from_utf8(m)?;
        }
        Ok(Self {
            contents,
            released: 0,
        })
    }

    pub fn as_str(&self) -> &str {
        match &self.contents {
            FileContents::Owned(s) => s,
            // SAFETY: `open` checked every byte, in slices that end after a
            // newline. A mapped file must not change while mapped, as for
            // every mapped reader in this crate.
            FileContents::Mapped(m) => unsafe { std::str::from_utf8_unchecked(m) },
        }
    }

    /// Release the mapped pages before byte `pos` once [`RELEASE_STEP`]
    /// bytes have been read since the last release. A later read of them
    /// maps them in again. A `pos` past the end counts as the end.
    pub fn release_before(&mut self, pos: usize) -> io::Result<()> {
        if let FileContents::Mapped(m) = &self.contents
            && pos >= self.released + RELEASE_STEP
        {
            let pos = pos.min(m.len());
            release(m, self.released, pos)?;
            self.released = pos;
        }
        Ok(())
    }
}

/// Drop resident pages of `map` on `workers` threads, then the caller
/// unmaps. Each thread advises a disjoint byte range. The page size is
/// `sysconf(SC_PAGESIZE)`, not a host-tuned cutoff.
pub fn advise_dontneed_parallel(map: &memmap2::Mmap, workers: usize) {
    let len = map.len();
    if len == 0 {
        return;
    }
    let workers = workers.max(1);
    if workers == 1 {
        let _ = release(map, 0, len);
        return;
    }
    let step = len.div_ceil(workers);
    let advise_one = |worker: usize| {
        let start = worker.saturating_mul(step);
        if start >= len {
            return;
        }
        let end = (start + step).min(len);
        let _ = release(map, start, end);
    };
    // Inside the read's pool this stays on those workers. Outside it,
    // a private scope avoids the global pool.
    #[cfg(feature = "parallel")]
    if rayon::current_thread_index().is_some() {
        use rayon::prelude::*;
        (0..workers).into_par_iter().for_each(advise_one);
        return;
    }
    std::thread::scope(|scope| {
        for worker in 0..workers {
            scope.spawn(move || advise_one(worker));
        }
    });
}

/// Advise `MADV_DONTNEED` for the whole 64 KiB blocks of the map that
/// `start..end` reaches, cut at the map end.
fn release(map: &memmap2::Mmap, start: usize, end: usize) -> io::Result<()> {
    // A multiple of every Linux page size. The map starts on a page, so the
    // range stays inside it, and the page that contains `end` stays mapped.
    const BLOCK: usize = 64 * 1024;
    let start = start & !(BLOCK - 1);
    let end = end.min(map.len()) & !(BLOCK - 1);
    if end <= start {
        return Ok(());
    }
    // SAFETY: `start..end` lies inside the map, which is shared and read
    // only, so dropped pages read back from the file.
    #[cfg(unix)]
    unsafe {
        map.unchecked_advise_range(memmap2::UncheckedAdvice::DontNeed, start, end - start)?;
    }
    #[cfg(not(unix))]
    let _ = map;
    Ok(())
}

/// Creates a gzip-compressed writer wrapping a file at the given path.
pub fn gzip_writer(path: &Path) -> io::Result<flate2::write::GzEncoder<std::fs::File>> {
    let file = std::fs::File::create(path)?;
    Ok(flate2::write::GzEncoder::new(
        file,
        flate2::Compression::new(GZIP_LEVEL),
    ))
}

/// How many independent compression members a payload of `nbytes` uses.
///
/// Below 1 MiB the file stays one member, so small fixtures keep a single
/// gzip stream. Larger payloads use one member per core, capped at 8.
pub fn compression_workers(nbytes: usize) -> usize {
    const MIN_CHUNKED: usize = 1 << 20;
    if nbytes < MIN_CHUNKED {
        return 1;
    }
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1)
        .clamp(1, 8)
}

fn split_chunks(data: &[u8], workers: usize) -> Vec<&[u8]> {
    if data.is_empty() || workers <= 1 {
        return vec![data];
    }
    let chunk = data.len().div_ceil(workers);
    let mut parts = Vec::new();
    let mut start = 0;
    while start < data.len() {
        let end = (start + chunk).min(data.len());
        parts.push(&data[start..end]);
        start = end;
    }
    parts
}

fn gzip_member(data: &[u8]) -> io::Result<Vec<u8>> {
    let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::new(GZIP_LEVEL));
    enc.write_all(data)?;
    enc.finish()
}

/// Writes `data` as gzip members at [`GZIP_LEVEL`].
///
/// One member when the payload is small. Otherwise each core compresses a
/// slice. A wide file stores the member starts in the first member's extra
/// field so the reader can inflate those slices together. A one-member file
/// is an ordinary gzip stream.
pub fn write_gzip_members(path: &Path, data: &[u8]) -> io::Result<usize> {
    write_gzip_members_n(path, data, compression_workers(data.len()))
}

/// [`write_gzip_members`] with an explicit member count.
///
/// `members == 1` is one gzip stream and does not use another core.
pub fn write_gzip_members_n(path: &Path, data: &[u8], members: usize) -> io::Result<usize> {
    let parts = split_chunks(data, members.max(1));
    let mut encoded = encode_parts(&parts, gzip_member)?;
    if encoded.len() > 1 {
        stamp_gzip_index(&mut encoded);
    }
    let count = encoded.len();
    write_members(path, &encoded)?;
    Ok(count)
}

/// `RC` extra-field payload: `RCZ1`, member count, then each member's start.
fn stamp_gzip_index(members: &mut [Vec<u8>]) {
    let extra_len = 4 + 2 + 8 * members.len();
    let inserted = 2 + 4 + extra_len;
    let mut starts = Vec::with_capacity(members.len());
    let mut offset = inserted;
    for member in members.iter() {
        starts.push(offset as u64);
        offset += member.len();
    }
    starts[0] = 0;
    let mut payload = Vec::with_capacity(extra_len);
    payload.extend_from_slice(b"RCZ1");
    payload.extend_from_slice(&(members.len() as u16).to_le_bytes());
    for start in &starts {
        payload.extend_from_slice(&start.to_le_bytes());
    }
    let mut extra = Vec::with_capacity(inserted);
    extra.extend_from_slice(&((4 + payload.len()) as u16).to_le_bytes());
    extra.extend_from_slice(b"RC");
    extra.extend_from_slice(&(payload.len() as u16).to_le_bytes());
    extra.extend_from_slice(&payload);
    let first = &mut members[0];
    debug_assert_eq!(&first[0..2], b"\x1f\x8b");
    first[3] |= 0x04;
    first.splice(10..10, extra);
}

fn gzip_member_starts(bytes: &[u8]) -> Option<Vec<usize>> {
    if bytes.len() < 16 || bytes[0] != 0x1f || bytes[1] != 0x8b || bytes[3] & 0x04 == 0 {
        return None;
    }
    let xlen = u16::from_le_bytes([bytes[10], bytes[11]]) as usize;
    let extra = bytes.get(12..12 + xlen)?;
    let mut cursor = 0;
    while cursor + 4 <= extra.len() {
        let len = u16::from_le_bytes([extra[cursor + 2], extra[cursor + 3]]) as usize;
        let data = extra.get(cursor + 4..cursor + 4 + len)?;
        if &extra[cursor..cursor + 2] == b"RC" && data.starts_with(b"RCZ1") && data.len() >= 6 {
            let count = u16::from_le_bytes([data[4], data[5]]) as usize;
            if data.len() < 6 + 8 * count || count == 0 {
                return None;
            }
            let mut starts = Vec::with_capacity(count);
            for index in 0..count {
                let at = 6 + 8 * index;
                let start = u64::from_le_bytes(data[at..at + 8].try_into().ok()?) as usize;
                if start > bytes.len() || (index > 0 && start <= starts[index - 1]) {
                    return None;
                }
                starts.push(start);
            }
            return Some(starts);
        }
        cursor += 4 + len;
    }
    None
}

fn serial_decode() -> bool {
    SERIAL_DECODE.with(|flag| flag.get())
}

std::thread_local! {
    static SERIAL_DECODE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// Run `body` with multi-member inflation forced onto one thread.
pub fn with_serial_decode<T>(body: impl FnOnce() -> T) -> T {
    SERIAL_DECODE.with(|flag| flag.set(true));
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            SERIAL_DECODE.with(|flag| flag.set(false));
        }
    }
    let _reset = Reset;
    body()
}

fn gunzip_member(bytes: &[u8]) -> io::Result<Vec<u8>> {
    let mut decoder = flate2::read::GzDecoder::new(bytes);
    let mut out = Vec::new();
    decoder.read_to_end(&mut out)?;
    Ok(out)
}

fn gunzip_all(bytes: &[u8]) -> io::Result<Vec<u8>> {
    if !serial_decode() {
        if let Some(starts) = gzip_member_starts(bytes) {
            if starts.len() > 1 {
                return gunzip_parallel(bytes, &starts);
            }
        }
    }
    let mut decoder = flate2::read::MultiGzDecoder::new(bytes);
    let mut out = Vec::new();
    decoder.read_to_end(&mut out)?;
    Ok(out)
}

fn gunzip_parallel(bytes: &[u8], starts: &[usize]) -> io::Result<Vec<u8>> {
    let mut ends = starts[1..].to_vec();
    ends.push(bytes.len());
    let parts: Vec<&[u8]> = starts
        .iter()
        .zip(ends)
        .map(|(start, end)| &bytes[*start..end])
        .collect();
    let decoded = std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(parts.len());
        for part in parts {
            handles.push(scope.spawn(move || gunzip_member(part)));
        }
        handles
            .into_iter()
            .map(|handle| {
                handle
                    .join()
                    .unwrap_or_else(|_| Err(io::Error::other("gzip")))
            })
            .collect::<io::Result<Vec<_>>>()
    })?;
    let mut out = Vec::new();
    for part in decoded {
        out.extend(part);
    }
    Ok(out)
}

fn encode_parts<F>(parts: &[&[u8]], encode: F) -> io::Result<Vec<Vec<u8>>>
where
    F: Fn(&[u8]) -> io::Result<Vec<u8>> + Sync,
{
    if parts.len() < 2 {
        return Ok(vec![encode(parts.first().copied().unwrap_or(b""))?]);
    }
    std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(parts.len());
        for part in parts {
            handles.push(scope.spawn(|| encode(part)));
        }
        handles
            .into_iter()
            .map(|handle| {
                handle
                    .join()
                    .unwrap_or_else(|_| Err(io::Error::other("compress")))
            })
            .collect()
    })
}

fn write_members(path: &Path, members: &[Vec<u8>]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    for member in members {
        file.write_all(member)?;
    }
    file.flush()
}

/// Creates a zstd-compressed writer wrapping a file at the given path.
///
/// Returns a finished writer ready for streaming line writes; the caller
/// is responsible for dropping the writer to flush the final frame.
/// Available only when the `zstd` Cargo feature is enabled.
#[cfg(feature = "zstd")]
pub fn zstd_writer(
    path: &Path,
) -> io::Result<zstd::stream::write::AutoFinishEncoder<'static, std::fs::File>> {
    let file = std::fs::File::create(path)?;
    // Level 3 is the zstd CLI default; balances ratio against speed.
    let encoder = zstd::stream::write::Encoder::new(file, ZSTD_LEVEL)?;
    Ok(encoder.auto_finish())
}

/// Writes `data` as concatenated zstd frames at [`ZSTD_LEVEL`].
///
/// One frame when the payload is small. A wide file leads with a skippable
/// frame that lists the data-frame starts, which the serial decoder ignores.
#[cfg(feature = "zstd")]
pub fn write_zstd_members(path: &Path, data: &[u8]) -> io::Result<usize> {
    write_zstd_members_n(path, data, compression_workers(data.len()))
}

/// [`write_zstd_members`] with an explicit frame count.
#[cfg(feature = "zstd")]
pub fn write_zstd_members_n(path: &Path, data: &[u8], members: usize) -> io::Result<usize> {
    let parts = split_chunks(data, members.max(1));
    let encoded = encode_parts(&parts, |part| {
        zstd::bulk::compress(part, ZSTD_LEVEL).map_err(|err| io::Error::other(err.to_string()))
    })?;
    let count = encoded.len();
    let mut file = std::fs::File::create(path)?;
    if count > 1 {
        file.write_all(&zstd_index_frame(&encoded))?;
    }
    for frame in &encoded {
        file.write_all(frame)?;
    }
    file.flush()?;
    Ok(count)
}

#[cfg(feature = "zstd")]
fn zstd_index_frame(frames: &[Vec<u8>]) -> Vec<u8> {
    let payload_len = 4 + 2 + 8 * frames.len();
    let mut starts = Vec::with_capacity(frames.len());
    let mut offset = 8 + payload_len;
    for frame in frames {
        starts.push(offset as u64);
        offset += frame.len();
    }
    let mut payload = Vec::with_capacity(payload_len);
    payload.extend_from_slice(b"RCZ1");
    payload.extend_from_slice(&(frames.len() as u16).to_le_bytes());
    for start in starts {
        payload.extend_from_slice(&start.to_le_bytes());
    }
    let mut bytes = Vec::with_capacity(8 + payload.len());
    bytes.extend_from_slice(&0x184D_2A50u32.to_le_bytes());
    bytes.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&payload);
    bytes
}

#[cfg(feature = "zstd")]
fn zstd_frame_starts(bytes: &[u8]) -> Option<Vec<usize>> {
    if bytes.len() < 12 || bytes[0..4] != [0x50, 0x2a, 0x4d, 0x18] {
        return None;
    }
    let size = u32::from_le_bytes(bytes[4..8].try_into().ok()?) as usize;
    let payload = bytes.get(8..8 + size)?;
    if !payload.starts_with(b"RCZ1") || payload.len() < 6 {
        return None;
    }
    let count = u16::from_le_bytes([payload[4], payload[5]]) as usize;
    if payload.len() < 6 + 8 * count || count == 0 {
        return None;
    }
    let mut starts = Vec::with_capacity(count);
    for index in 0..count {
        let at = 6 + 8 * index;
        let start = u64::from_le_bytes(payload[at..at + 8].try_into().ok()?) as usize;
        if start > bytes.len() || (index > 0 && start <= starts[index - 1]) {
            return None;
        }
        starts.push(start);
    }
    Some(starts)
}

#[cfg(feature = "zstd")]
fn zstd_decode_all(bytes: &[u8]) -> io::Result<Vec<u8>> {
    if !serial_decode() {
        if let Some(starts) = zstd_frame_starts(bytes) {
            if starts.len() > 1 {
                return zstd_parallel(bytes, &starts);
            }
        }
    }
    let mut decoder = zstd::stream::read::Decoder::new(bytes)?;
    let mut out = Vec::new();
    decoder.read_to_end(&mut out)?;
    Ok(out)
}

#[cfg(feature = "zstd")]
fn zstd_parallel(bytes: &[u8], starts: &[usize]) -> io::Result<Vec<u8>> {
    let mut ends = starts[1..].to_vec();
    ends.push(bytes.len());
    let parts: Vec<&[u8]> = starts
        .iter()
        .zip(ends)
        .map(|(start, end)| &bytes[*start..end])
        .collect();
    let decoded = std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(parts.len());
        for part in parts {
            handles.push(scope.spawn(move || {
                zstd::stream::decode_all(part).map_err(|err| io::Error::other(err.to_string()))
            }));
        }
        handles
            .into_iter()
            .map(|handle| {
                handle
                    .join()
                    .unwrap_or_else(|_| Err(io::Error::other("zstd")))
            })
            .collect::<io::Result<Vec<_>>>()
    })?;
    let mut out = Vec::new();
    for part in decoded {
        out.extend(part);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn text_of_at_least(len: usize) -> Vec<u8> {
        let frame = include_bytes!("../resources/test/tiny_cuh2.con");
        frame.repeat(len / frame.len() + 2)
    }

    fn large_text() -> Vec<u8> {
        text_of_at_least(MMAP_THRESHOLD as usize)
    }

    fn mapped_text(path: &Path) -> Result<String, String> {
        let contents = read_file_contents(path).map_err(|e| e.to_string())?;
        contents
            .as_str()
            .map(str::to_owned)
            .map_err(|e| e.to_string())
    }

    #[test]
    fn file_text_matches_the_mapped_read() {
        let dir = tempfile::tempdir().unwrap();
        let small = dir.path().join("small.con");
        std::fs::write(&small, include_bytes!("../resources/test/tiny_cuh2.con")).unwrap();
        let large = dir.path().join("large.con");
        std::fs::write(&large, large_text()).unwrap();
        assert!(matches!(
            read_file_contents(&large).unwrap(),
            FileContents::Mapped(_)
        ));
        let gz = dir.path().join("large.con.gz");
        let mut enc = gzip_writer(&gz).unwrap();
        enc.write_all(&large_text()).unwrap();
        enc.finish().unwrap();
        for path in [&small, &large, &gz] {
            let text = read_file_text(path).unwrap();
            assert_eq!(Ok(text), mapped_text(path), "{}", path.display());
        }
    }

    #[test]
    fn file_text_reports_invalid_utf8_as_the_mapped_read() {
        let dir = tempfile::tempdir().unwrap();
        for (name, len) in [("small.con", 100), ("large.con", large_text().len())] {
            let mut bytes = large_text()[..len].to_vec();
            bytes[len - 40] = 0xff;
            let path = dir.path().join(name);
            std::fs::write(&path, &bytes).unwrap();
            let err = read_file_text(&path).unwrap_err().to_string();
            assert_eq!(Err(err), mapped_text(&path), "{name}");
        }
    }

    #[test]
    fn forward_text_reads_back_released_pages() {
        let dir = tempfile::tempdir().unwrap();
        let bytes = text_of_at_least(RELEASE_STEP + (200 << 10));
        let path = dir.path().join("two-steps.con");
        std::fs::write(&path, &bytes).unwrap();
        let mut mapped = ForwardText::open(&path, true).unwrap();
        assert!(matches!(mapped.contents, FileContents::Mapped(_)));
        assert_eq!(mapped.as_str().as_bytes(), bytes.as_slice());
        for pos in (0..=bytes.len()).step_by(1 << 20) {
            mapped.release_before(pos).unwrap();
        }
        assert_eq!(mapped.released, RELEASE_STEP);
        assert_eq!(mapped.as_str().as_bytes(), bytes.as_slice());
        let owned = ForwardText::open(&path, false).unwrap();
        assert!(matches!(owned.contents, FileContents::Owned(_)));
        assert_eq!(owned.as_str(), mapped.as_str());
    }

    /// The guard is private anonymous memory right after the file map, which
    /// `MADV_DONTNEED` would zero.
    ///
    /// The kernel puts a new map at the top of the highest free gap that fits
    /// it. The test frees the space below the guard after it fills every gap
    /// above, so the file map must end at the guard. A map made by another
    /// test thread in between would take that space, so the test body runs
    /// alone in a child process of this test binary.
    #[cfg(target_os = "linux")]
    #[test]
    fn release_before_past_the_end_leaves_the_next_mapping_alone() {
        const NAME: &str =
            "compression::tests::release_before_past_the_end_leaves_the_next_mapping_alone";
        const CHILD: &str = "READCON_RELEASE_TEST_CHILD";
        if std::env::var_os(CHILD).is_none() {
            let out = std::process::Command::new(std::env::current_exe().unwrap())
                .args([NAME, "--exact", "--test-threads=1"])
                .env(CHILD, "1")
                .output()
                .unwrap();
            let stdout = String::from_utf8_lossy(&out.stdout);
            assert!(
                out.status.success() && stdout.contains("test result: ok. 1 passed;"),
                "{stdout}{}",
                String::from_utf8_lossy(&out.stderr)
            );
            return;
        }
        const GUARD: usize = 1 << 20;
        let dir = tempfile::tempdir().unwrap();
        let bytes = text_of_at_least(3 * MMAP_THRESHOLD as usize);
        let path = dir.path().join("short.con");
        std::fs::write(&path, &bytes).unwrap();
        let page = unsafe { libc::sysconf(libc::_SC_PAGESIZE) } as usize;
        let map_len = bytes.len().next_multiple_of(page);
        let anonymous = |len: usize| {
            let map = unsafe {
                libc::mmap(
                    std::ptr::null_mut(),
                    len,
                    libc::PROT_READ | libc::PROT_WRITE,
                    libc::MAP_PRIVATE | libc::MAP_ANONYMOUS,
                    -1,
                    0,
                )
            };
            assert_ne!(map, libc::MAP_FAILED);
            map
        };
        let region = anonymous(map_len + GUARD);
        let guard =
            unsafe { std::slice::from_raw_parts_mut(region.cast::<u8>().add(map_len), GUARD) };
        guard.fill(0xab);
        // Each filler takes the highest gap that fits the file map. The first
        // one below the region shows that no such gap is left above it.
        let mut fillers = Vec::new();
        loop {
            let filler = anonymous(map_len);
            if filler < region {
                unsafe { libc::munmap(filler, map_len) };
                break;
            }
            fillers.push(filler);
        }
        unsafe { libc::munmap(region, map_len) };
        let mut text = ForwardText::open(&path, true).unwrap();
        assert!(
            std::ptr::eq(text.as_str().as_ptr(), region.cast::<u8>()),
            "the file map does not end at the guard"
        );
        for pos in [bytes.len() + RELEASE_STEP, 3 * RELEASE_STEP, usize::MAX] {
            text.release_before(pos).unwrap();
        }
        assert_eq!(text.released, bytes.len());
        assert!(guard.iter().all(|&b| b == 0xab));
        assert_eq!(text.as_str().as_bytes(), bytes.as_slice());
        unsafe { libc::munmap(guard.as_mut_ptr().cast(), GUARD) };
        for filler in fillers {
            unsafe { libc::munmap(filler, map_len) };
        }
    }

    #[test]
    fn forward_text_reports_invalid_utf8_as_the_mapped_read() {
        let dir = tempfile::tempdir().unwrap();
        let mut bytes = text_of_at_least(RELEASE_STEP + (200 << 10));
        let at = bytes.len() - 100;
        bytes[at] = 0xc3;
        let path = dir.path().join("bad.con");
        std::fs::write(&path, &bytes).unwrap();
        for map in [true, false] {
            let err = ForwardText::open(&path, map).err().unwrap().to_string();
            assert_eq!(Err(err), mapped_text(&path), "map {map}");
        }
    }

    #[test]
    fn skippable_frame_magic_is_zstd() {
        assert_eq!(
            detect_compression(&[0x50, 0x2a, 0x4d, 0x18]),
            Compression::Zstd
        );
        assert_eq!(
            detect_compression(&[0x5f, 0x2a, 0x4d, 0x18]),
            Compression::Zstd
        );
        assert_eq!(
            detect_compression(&[0x4f, 0x2a, 0x4d, 0x18]),
            Compression::None
        );
        assert_eq!(detect_compression(&[0x50, 0x2a, 0x4d]), Compression::None);
        assert_eq!(
            detect_compression(&[0x28, 0xb5, 0x2f, 0xfd]),
            Compression::Zstd
        );
    }

    fn skippable_prefix(nibble: u8, payload: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&(0x184D_2A50u32 + u32::from(nibble)).to_le_bytes());
        bytes.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        bytes.extend_from_slice(payload);
        bytes
    }

    #[cfg(not(feature = "zstd"))]
    #[test]
    fn a_leading_skippable_frame_needs_the_zstd_feature() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("skip-first.zst");
        std::fs::write(&path, skippable_prefix(0, b"index")).unwrap();
        let err = read_file_text(&path).unwrap_err().to_string();
        assert!(err.contains("zstd-compressed input detected"), "{err}");
        match open_decoded(&path) {
            Err(err) => {
                assert!(
                    err.to_string().contains("zstd-compressed input detected"),
                    "{err}"
                );
            }
            Ok(_) => panic!("a skippable frame was treated as uncompressed"),
        }
    }

    #[cfg(feature = "zstd")]
    #[test]
    fn a_leading_skippable_frame_decodes_with_the_frames_after_it() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let frame = zstd::stream::encode_all(text.as_bytes(), 1).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let first = dir.path().join("skip-first.con.zst");
        let mut bytes = skippable_prefix(0, b"index");
        bytes.extend_from_slice(&frame);
        std::fs::write(&first, &bytes).unwrap();
        assert_eq!(read_file_text(&first).unwrap(), text);
        let frames = crate::iterators::read_all_frames(&first).unwrap();
        assert_eq!(frames.len(), 1);

        let mut between = frame.clone();
        between.extend(skippable_prefix(0, b"index"));
        between.extend_from_slice(&frame);
        let mid = dir.path().join("skip-between.con.zst");
        std::fs::write(&mid, &between).unwrap();
        assert_eq!(read_file_text(&mid).unwrap(), format!("{text}{text}"));
    }

    fn gzip_member_count(bytes: &[u8]) -> usize {
        let mut rest = bytes;
        let mut count = 0;
        while !rest.is_empty() {
            let mut decoder = flate2::bufread::GzDecoder::new(rest);
            let mut out = Vec::new();
            std::io::Read::read_to_end(&mut decoder, &mut out).unwrap();
            let next = decoder.into_inner();
            assert!(
                next.len() < rest.len() || out.is_empty(),
                "gzip member did not consume input"
            );
            if next.len() == rest.len() {
                break;
            }
            rest = next;
            count += 1;
        }
        count
    }

    #[test]
    fn chunked_gzip_roundtrips_at_level_6_with_one_member_per_slice() {
        // A single gzip member of this payload is the old streaming writer.
        // Four members is the chunked level-6 writer.
        let unit = b"Cu 1.0 2.0 3.0 0 1\n";
        let data = unit.repeat(80_000);
        assert!(data.len() > (1 << 20));
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.con.gz");
        let members = write_gzip_members(&path, &data).unwrap();
        assert!(
            members > 1,
            "a wide payload must be more than one gzip member"
        );
        let bytes = std::fs::read(&path).unwrap();
        assert_eq!(gzip_member_count(&bytes), members);
        assert_eq!(bytes[8], 0, "XFL 0 is gzip level 6, not the fast level");
        assert_eq!(read_file_bytes(&path).unwrap(), data);
    }

    #[cfg(feature = "zstd")]
    #[test]
    fn chunked_zstd_roundtrips_at_level_3() {
        let data = b"0.0 1.0 2.0 0 0\n".repeat(80_000);
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.con.zst");
        let members = write_zstd_members(&path, &data).unwrap();
        assert!(members > 1);
        assert_eq!(read_file_bytes(&path).unwrap(), data);
        assert_eq!(
            with_serial_decode(|| read_file_bytes(&path).unwrap()),
            data,
            "serial decode of an indexed file matches the parallel decode"
        );
    }

    #[test]
    fn a_single_gzip_stream_without_an_index_still_reads() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("one.con.gz");
        {
            let mut writer = gzip_writer(&path).unwrap();
            writer.write_all(text.as_bytes()).unwrap();
            writer.finish().unwrap();
        }
        let bytes = std::fs::read(&path).unwrap();
        assert!(gzip_member_starts(&bytes).is_none());
        assert_eq!(read_file_text(&path).unwrap(), text);
        assert_eq!(read_file_bytes(&path).unwrap(), text.as_bytes());
    }

    #[test]
    fn a_foreign_multi_member_gzip_without_our_index_still_reads() {
        let mut bytes = gzip_member(b"alpha\n").unwrap();
        bytes.extend(gzip_member(b"beta\n").unwrap());
        assert!(gzip_member_starts(&bytes).is_none());
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("foreign.con.gz");
        std::fs::write(&path, &bytes).unwrap();
        assert_eq!(read_file_bytes(&path).unwrap(), b"alpha\nbeta\n");
    }

    #[cfg(feature = "zstd")]
    #[test]
    fn a_single_zstd_frame_without_an_index_still_reads() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("one.con.zst");
        std::fs::write(&path, zstd::stream::encode_all(text.as_bytes(), 3).unwrap()).unwrap();
        assert!(zstd_frame_starts(&std::fs::read(&path).unwrap()).is_none());
        assert_eq!(read_file_text(&path).unwrap(), text);
    }
}
