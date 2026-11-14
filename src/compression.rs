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
    // only, so dropped pages read back from the file. Miri has no
    // `MADV_DONTNEED`; skipping the hint leaves the bytes in place.
    #[cfg(all(unix, not(miri)))]
    unsafe {
        map.unchecked_advise_range(memmap2::UncheckedAdvice::DontNeed, start, end - start)?;
    }
    #[cfg(not(all(unix, not(miri))))]
    let _ = (map, start, end);
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
/// gzip stream. Larger payloads use about 2 MiB of plain text per member,
/// and at least four members per core, so a read can keep every worker
/// busy instead of waiting on one fat member. Capped at 64.
pub fn compression_workers(nbytes: usize) -> usize {
    const MIN_CHUNKED: usize = 1 << 20;
    const PLAIN_PER_MEMBER: usize = 2 << 20;
    if nbytes < MIN_CHUNKED {
        return 1;
    }
    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let by_size = (nbytes / PLAIN_PER_MEMBER).max(1);
    by_size.max(threads.saturating_mul(4)).clamp(1, 64)
}

/// Deflate workers for a write that did not ask for a thread count.
///
/// The member count stays wide so a read can split the file. Running one
/// thread per member oversubscribes an 8-core host once that count hits
/// 32. The cap is `available_parallelism`.
pub fn default_deflate_threads(members: usize) -> usize {
    let cores = std::thread::available_parallelism()
        .map(|count| count.get())
        .unwrap_or(1)
        .max(1);
    members.max(1).min(cores)
}

fn split_chunks(data: &[u8], workers: usize) -> Vec<&[u8]> {
    if data.is_empty() || workers <= 1 {
        return vec![data];
    }
    let workers = workers.max(1);
    let mut cuts = Vec::with_capacity(workers + 1);
    cuts.push(0usize);
    for index in 1..workers {
        let mut at = index * data.len() / workers;
        if at > 0 && at < data.len() && data[at - 1] != b'\n' {
            let forward = memchr::memchr(b'\n', &data[at..]).map(|rel| at + rel + 1);
            let back = memchr::memrchr(b'\n', &data[..at]).map(|rel| rel + 1);
            let previous = *cuts.last().unwrap_or(&0);
            at = match (forward, back) {
                (Some(next), Some(prev))
                    if next < data.len() && (prev <= previous || next - at <= at - prev) =>
                {
                    next
                }
                (Some(next), _) if next < data.len() => next,
                (_, Some(prev)) if prev > previous => prev,
                _ => at,
            };
        }
        if cuts.last().copied() != Some(at) && at < data.len() {
            cuts.push(at);
        }
    }
    if cuts.last().copied() != Some(data.len()) {
        cuts.push(data.len());
    }
    cuts.windows(2)
        .filter(|span| span[1] > span[0])
        .map(|span| &data[span[0]..span[1]])
        .collect()
}

/// `(first coordinate row, row count)` for each plain slice.
///
/// `None` when the text is not one coordinate block after a header, so
/// the reader keeps the full-frame parser. Old indexes omit this table
/// and still decode.
fn coord_member_rows(data: &[u8], parts: &[&[u8]]) -> Option<Vec<(u32, u32)>> {
    if parts.len() < 2 || data.is_empty() {
        return None;
    }
    let mut line_at = Vec::new();
    let mut pos = 0usize;
    while let Some(rel) = memchr::memchr(b'\n', &data[pos..]) {
        line_at.push(pos);
        pos += rel + 1;
        if line_at.len() > 64 && line_at.len() > 9 {
            break;
        }
    }
    if line_at.len() < 9 {
        return None;
    }
    let line = |index: usize| -> Option<&[u8]> {
        let start = *line_at.get(index)?;
        let end = line_at.get(index + 1).copied().unwrap_or(data.len());
        let end = end.saturating_sub(usize::from(end > start && data[end - 1] == b'\n'));
        Some(&data[start..end])
    };
    let types_text = std::str::from_utf8(line(6)?).ok()?;
    let natm_types = crate::parser::parse_count_line(types_text, 1).ok()?[0];
    // Species headers sit between coordinate groups. A member can be one
    // contiguous coordinate run only when the frame has a single species;
    // anything else keeps the full-frame parser.
    if natm_types != 1 {
        return None;
    }
    let counts_text = std::str::from_utf8(line(7)?).ok()?;
    let counts = crate::parser::parse_count_line(counts_text, natm_types).ok()?;
    let natoms: usize = counts.iter().sum();
    if natoms == 0 {
        return None;
    }
    let header_lines = 9 + natm_types * 2;
    // A per-newline callback over a million rows is slower than the
    // deflate it is trying to index. Count bytes in each slice instead.
    let mut counts = Vec::with_capacity(parts.len());
    for part in parts {
        counts.push(count_newlines(part) as u32);
    }
    if counts[0] < header_lines as u32 {
        return None;
    }
    counts[0] -= header_lines as u32;
    let total: u32 = counts.iter().copied().sum();
    if total as usize != natoms {
        return None;
    }
    if let Some(last_nl) = memchr::memrchr(b'\n', data) {
        if data[last_nl + 1..]
            .iter()
            .any(|byte| !byte.is_ascii_whitespace())
        {
            return None;
        }
    }
    let mut row = 0u32;
    let mut table = Vec::with_capacity(parts.len());
    for count in counts {
        table.push((row, count));
        row = row.saturating_add(count);
    }
    if row as usize != natoms {
        return None;
    }
    Some(table)
}

fn count_newlines(data: &[u8]) -> usize {
    #[cfg(target_arch = "x86_64")]
    {
        static AVX2: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
        if *AVX2.get_or_init(|| is_x86_feature_detected!("avx2")) {
            return unsafe { count_newlines_avx2(data) };
        }
    }
    data.iter().filter(|byte| **byte == b'\n').count()
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn count_newlines_avx2(data: &[u8]) -> usize {
    use std::arch::x86_64::*;
    unsafe {
        let mut n = 0usize;
        let mut i = 0usize;
        let nl = _mm256_set1_epi8(b'\n' as i8);
        while i + 128 <= data.len() {
            let mut mask_n = 0usize;
            for lane in 0..4 {
                let v = _mm256_loadu_si256(data.as_ptr().add(i + lane * 32) as *const _);
                mask_n += _mm256_movemask_epi8(_mm256_cmpeq_epi8(v, nl)).count_ones() as usize;
            }
            n += mask_n;
            i += 128;
        }
        while i + 32 <= data.len() {
            let v = _mm256_loadu_si256(data.as_ptr().add(i) as *const _);
            n += _mm256_movemask_epi8(_mm256_cmpeq_epi8(v, nl)).count_ones() as usize;
            i += 32;
        }
        while i < data.len() {
            n += usize::from(*data.get_unchecked(i) == b'\n');
            i += 1;
        }
        n
    }
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
/// The member count is also the worker count.
pub fn write_gzip_members_n(path: &Path, data: &[u8], members: usize) -> io::Result<usize> {
    write_gzip_members_limited(path, data, members, members.max(1))
}

/// [`write_gzip_members_n`] with a separate worker count.
///
/// Eight members on two workers compress four slices per worker. The
/// bytes match a one-worker write of the same slices.
/// Format each atom slice and deflate it on that same worker.
///
/// The plain text is the binding header on the first slice plus coordinate
/// lines. One member stays on the streaming encoder so its bytes do not
/// change. `threads == 1` is the caller's problem: this function always
/// uses `threads` workers.
pub fn write_fused_gzip_frame(
    path: &Path,
    frame: &crate::types::ConFrame,
    members: usize,
    threads: usize,
) -> io::Result<usize> {
    write_fused_frame(path, frame, members, threads, true)
}

/// [`write_fused_gzip_frame`] for zstd frames.
#[cfg(feature = "zstd")]
pub fn write_fused_zstd_frame(
    path: &Path,
    frame: &crate::types::ConFrame,
    members: usize,
    threads: usize,
) -> io::Result<usize> {
    write_fused_frame(path, frame, members, threads, false)
}

fn write_fused_frame(
    path: &Path,
    frame: &crate::types::ConFrame,
    members: usize,
    threads: usize,
    gzip: bool,
) -> io::Result<usize> {
    let n = frame.atom_data.len();
    let members = members.max(2).min(n.max(2));
    let mut ranges = Vec::with_capacity(members);
    let mut rows = Vec::with_capacity(members);
    let mut row = 0u32;
    let mut start = 0usize;
    for index in 0..members {
        let end = if index + 1 == members {
            n
        } else {
            (index + 1) * n / members
        };
        if end <= start {
            continue;
        }
        let count = (end - start) as u32;
        rows.push((row, count));
        row += count;
        ranges.push((start, end));
        start = end;
    }
    let header = crate::writer::binding_header_bytes(frame)
        .map_err(|err| io::Error::other(err.to_string()))?;
    let slots: Vec<GzipMemberSlot> = (0..ranges.len())
        .map(|_| std::sync::Mutex::new(None))
        .collect();
    let threads = threads.max(1).min(ranges.len());
    let ranges_ref = &ranges;
    std::thread::scope(|scope| {
        for (begin, end) in worker_ranges(ranges.len(), threads) {
            let slots = &slots;
            let header = &header;
            scope.spawn(move || {
                let mut plain = Vec::new();
                for index in begin..end {
                    let (atom_from, atom_to) = ranges_ref[index];
                    plain.clear();
                    if atom_from == 0 {
                        plain.extend_from_slice(header);
                    }
                    plain.extend(crate::writer::format_coord_range(frame, atom_from, atom_to));
                    let plain_len = plain.len();
                    let encoded = if gzip {
                        gzip_member(&plain)
                    } else {
                        #[cfg(feature = "zstd")]
                        {
                            zstd_compress_part(&plain)
                        }
                        #[cfg(not(feature = "zstd"))]
                        {
                            let _ = &plain;
                            Err(zstd_unsupported())
                        }
                    };
                    *slots[index].lock().unwrap() = Some(encoded.map(|bytes| (bytes, plain_len)));
                }
            });
        }
    });
    let mut encoded = Vec::with_capacity(ranges.len());
    let mut plain_lens = Vec::with_capacity(ranges.len());
    for slot in slots {
        match slot.into_inner().unwrap_or(None) {
            Some(Ok((bytes, plain_len))) => {
                encoded.push(bytes);
                plain_lens.push(plain_len);
            }
            Some(Err(err)) => return Err(err),
            None => return Err(io::Error::other("compress")),
        }
    }
    if gzip {
        if encoded.len() > 1 {
            stamp_gzip_index(&mut encoded, &plain_lens, Some(&rows));
        }
        write_members(path, &encoded)?;
    } else {
        #[cfg(feature = "zstd")]
        {
            let mut file = std::fs::File::create(path)?;
            if encoded.len() > 1 {
                file.write_all(&zstd_index_frame(&encoded, &plain_lens, Some(&rows)))?;
            }
            for part in &encoded {
                file.write_all(part)?;
            }
            file.flush()?;
        }
    }
    Ok(encoded.len())
}

pub fn write_gzip_members_limited(
    path: &Path,
    data: &[u8],
    members: usize,
    threads: usize,
) -> io::Result<usize> {
    let trace = std::env::var_os("READCON_WRITE_TRACE").is_some();
    let t0 = std::time::Instant::now();
    let parts = split_chunks(data, members.max(1));
    let plain: Vec<usize> = parts.iter().map(|part| part.len()).collect();
    let t_split = t0.elapsed().as_secs_f64();
    let t1 = std::time::Instant::now();
    let mut encoded = encode_parts(&parts, threads, gzip_member)?;
    let t_encode = t1.elapsed().as_secs_f64();
    let t2 = std::time::Instant::now();
    if encoded.len() > 1 {
        let rows = coord_member_rows(data, &parts);
        stamp_gzip_index(&mut encoded, &plain, rows.as_deref());
    }
    let t_index = t2.elapsed().as_secs_f64();
    let t3 = std::time::Instant::now();
    let count = encoded.len();
    write_members(path, &encoded)?;
    if trace {
        eprintln!(
            "gzip-write split={t_split:.4} encode={t_encode:.4} index={t_index:.4} io={:.4} members={count} threads={threads}",
            t3.elapsed().as_secs_f64()
        );
    }
    Ok(count)
}

/// `RC` extra-field payload: `RCZ1`, member count, compressed starts,
/// then each member's plain length.
fn row_table(data: &[u8], count: usize) -> Option<Vec<(u32, u32)>> {
    let at = 6 + 16 * count;
    if data.len() < at + 8 * count {
        return None;
    }
    let mut rows = Vec::with_capacity(count);
    for index in 0..count {
        let off = at + 8 * index;
        let base = u32::from_le_bytes(data[off..off + 4].try_into().ok()?);
        let n = u32::from_le_bytes(data[off + 4..off + 8].try_into().ok()?);
        rows.push((base, n));
    }
    Some(rows)
}

fn stamp_gzip_index(members: &mut [Vec<u8>], plain: &[usize], rows: Option<&[(u32, u32)]>) {
    let count = members.len();
    let row_bytes = usize::from(rows.is_some()) * 8 * count;
    let extra_len = 4 + 2 + 16 * count + row_bytes;
    let inserted = 2 + 4 + extra_len;
    let mut starts = Vec::with_capacity(count);
    let mut offset = inserted;
    for member in members.iter() {
        starts.push(offset as u64);
        offset += member.len();
    }
    starts[0] = 0;
    let mut payload = Vec::with_capacity(extra_len);
    payload.extend_from_slice(b"RCZ1");
    payload.extend_from_slice(&(count as u16).to_le_bytes());
    for start in &starts {
        payload.extend_from_slice(&start.to_le_bytes());
    }
    for len in plain {
        payload.extend_from_slice(&(*len as u64).to_le_bytes());
    }
    if let Some(rows) = rows {
        for (base, n) in rows {
            payload.extend_from_slice(&base.to_le_bytes());
            payload.extend_from_slice(&n.to_le_bytes());
        }
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

struct MemberPlan {
    starts: Vec<usize>,
    plain: Option<Vec<usize>>,
    /// `(first coordinate row, row count)` per member, when the payload is
    /// one coordinate block after a single header.
    rows: Option<Vec<(u32, u32)>>,
}

type GzipMemberSlot = std::sync::Mutex<Option<io::Result<(Vec<u8>, usize)>>>;

fn gzip_member_starts(bytes: &[u8]) -> Option<MemberPlan> {
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
            let plain = if data.len() >= 6 + 16 * count {
                let mut lens = Vec::with_capacity(count);
                for index in 0..count {
                    let at = 6 + 8 * count + 8 * index;
                    lens.push(u64::from_le_bytes(data[at..at + 8].try_into().ok()?) as usize);
                }
                Some(lens)
            } else {
                None
            };
            let rows = row_table(data, count);
            return Some(MemberPlan {
                starts,
                plain,
                rows,
            });
        }
        cursor += 4 + len;
    }
    None
}

/// `0` uses one worker per member. `1` stays on the calling thread.
pub(crate) fn decode_thread_budget() -> usize {
    DECODE_THREADS.with(|flag| flag.get())
}

std::thread_local! {
    static DECODE_THREADS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

/// Run `body` with indexed members inflated on at most `threads` workers.
///
/// `threads < 2` is the calling thread. The previous budget is restored
/// when `body` returns, including on unwind.
pub fn with_decode_threads<T>(threads: usize, body: impl FnOnce() -> T) -> T {
    let previous = DECODE_THREADS.with(|flag| flag.replace(threads));
    struct Reset(usize);
    impl Drop for Reset {
        fn drop(&mut self) {
            DECODE_THREADS.with(|flag| flag.set(self.0));
        }
    }
    let _reset = Reset(previous);
    body()
}

/// Run `body` with multi-member inflation forced onto one thread.
pub fn with_serial_decode<T>(body: impl FnOnce() -> T) -> T {
    with_decode_threads(1, body)
}

fn gunzip_member(bytes: &[u8]) -> io::Result<Vec<u8>> {
    let (out, exact) = gzip_one_member(bytes)?;
    if !exact {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "gzip member does not fill its index slice",
        ));
    }
    Ok(out)
}

fn gunzip_all(bytes: &[u8]) -> io::Result<Vec<u8>> {
    let mut out = Vec::new();
    inflate_gzip(bytes, &mut out)?;
    Ok(out)
}

fn worker_limit_from_budget(members: usize) -> usize {
    let members = members.max(1);
    match decode_thread_budget() {
        0 => members,
        budget => budget.min(members).max(1),
    }
}

fn worker_ranges(jobs: usize, threads: usize) -> Vec<(usize, usize)> {
    let threads = threads.max(1).min(jobs.max(1));
    let mut ranges = Vec::with_capacity(threads);
    let mut start = 0usize;
    for worker in 0..threads {
        let end = if worker + 1 == threads {
            jobs
        } else {
            (worker + 1) * jobs / threads
        };
        if end > start {
            ranges.push((start, end));
            start = end;
        }
    }
    ranges
}

fn par_ranges(jobs: usize, threads: usize, work: impl Fn(usize, usize) + Sync + Send) {
    let ranges = worker_ranges(jobs, threads);
    if ranges.len() < 2 {
        for (begin, end) in ranges {
            work(begin, end);
        }
        return;
    }
    #[cfg(feature = "parallel")]
    {
        crate::parser::on_pool(ranges.len(), || {
            use rayon::prelude::*;
            ranges
                .par_iter()
                .for_each(|(begin, end)| work(*begin, *end));
        });
    }
    #[cfg(not(feature = "parallel"))]
    {
        std::thread::scope(|scope| {
            for (worker, (begin, end)) in ranges.into_iter().enumerate() {
                let work = &work;
                scope.spawn(move || {
                    crate::parser::pin_worker(worker);
                    work(begin, end);
                });
            }
        });
    }
}

fn gzip_one_member(src: &[u8]) -> io::Result<(Vec<u8>, bool)> {
    // `read::GzDecoder` wraps a `BufReader` and may pull bytes past the
    // member. The bufread decoder on a cursor reports the member's end.
    let mut decoder = flate2::bufread::GzDecoder::new(std::io::Cursor::new(src));
    let mut out = Vec::new();
    decoder.read_to_end(&mut out)?;
    let consumed = decoder.get_ref().position() as usize;
    Ok((out, consumed == src.len()))
}

fn gzip_into(src: &[u8], dst: &mut [u8]) -> io::Result<()> {
    // Inflate into the caller's slice. A temporary member buffer was a
    // second copy of every slice, and a million-atom CON.gz paid it on
    // top of the serial decoder the older releases use.
    let mut decoder = flate2::bufread::GzDecoder::new(std::io::Cursor::new(src));
    decoder.read_exact(dst)?;
    let mut extra = [0u8; 1];
    match decoder.read(&mut extra) {
        Ok(0) => {}
        Ok(_) => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "gzip member does not fill its index slice",
            ));
        }
        Err(err) if err.kind() == io::ErrorKind::UnexpectedEof => {}
        Err(err) => return Err(err),
    }
    let consumed = decoder.get_ref().position() as usize;
    if consumed != src.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "gzip member does not fill its index slice",
        ));
    }
    Ok(())
}

fn inflate_gzip(bytes: &[u8], out: &mut Vec<u8>) -> io::Result<()> {
    if decode_thread_budget() != 1 {
        if let Some(plan) = gzip_member_starts(bytes) {
            if plan.starts.len() > 1 {
                let threads = worker_limit_from_budget(plan.starts.len());
                let indexed = if let Some(plain) = plan.plain.as_deref() {
                    if plain.len() == plan.starts.len() {
                        inflate_sized(bytes, &plan.starts, plain, threads, gzip_into, out)
                    } else {
                        Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "gzip index has no plain length for every member",
                        ))
                    }
                } else {
                    let parts = inflate_unknown(bytes, &plan.starts, threads, gunzip_member)?;
                    out.clear();
                    for part in parts {
                        out.extend_from_slice(&part);
                    }
                    Ok(())
                };
                if indexed.is_ok() {
                    return indexed;
                }
                // A stale or partial index must not hide a later member.
                // The serial decoder is what a file without our index uses.
                out.clear();
            }
        }
    }
    let mut decoder = flate2::read::MultiGzDecoder::new(bytes);
    out.clear();
    decoder.read_to_end(out)?;
    Ok(())
}

/// Largest plain length an index may claim for a file of `file_len` bytes.
///
/// The index is attacker-controlled. A flipped high bit must fail the
/// decode instead of reserving that many bytes.
fn plain_length_budget(file_len: usize) -> usize {
    file_len.saturating_mul(8192).saturating_add(1024 * 1024)
}

pub(crate) fn trusted_plain_total(file_len: usize, plain: &[usize]) -> Option<usize> {
    let cap = plain_length_budget(file_len);
    let mut total = 0usize;
    for len in plain {
        if *len > cap {
            return None;
        }
        total = total.checked_add(*len).filter(|sum| *sum <= cap)?;
    }
    Some(total)
}

/// Atom count implied by a row table, when every span fits in `plain_total`.
#[cfg(feature = "parallel")]
pub(crate) fn trusted_row_total(plain_total: usize, rows: &[(u32, u32)]) -> Option<usize> {
    let cap = plain_total / 8 + 16;
    let mut total = 0usize;
    let mut spans = Vec::with_capacity(rows.len());
    for (base, count) in rows {
        let base = *base as usize;
        let count = *count as usize;
        total = total.checked_add(count).filter(|sum| *sum <= cap)?;
        let end = base.checked_add(count)?;
        spans.push((base, end));
    }
    // The spans must cover every atom once. A gap leaves an uninitialized
    // atom, and dropping that atom reads a dangling pointer.
    spans.sort_unstable();
    let mut cursor = 0usize;
    for (base, end) in spans {
        if base != cursor || end > total {
            return None;
        }
        cursor = end;
    }
    if cursor != total {
        return None;
    }
    Some(total)
}

fn inflate_sized(
    bytes: &[u8],
    starts: &[usize],
    plain: &[usize],
    threads: usize,
    decode: impl Fn(&[u8], &mut [u8]) -> io::Result<()> + Sync + Send,
    out: &mut Vec<u8>,
) -> io::Result<()> {
    let Some(total) = trusted_plain_total(bytes.len(), plain) else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "member plain length exceeds the compressed file",
        ));
    };
    // `reserve(n)` grows until `capacity >= len + n`, not `capacity >= old + n`.
    // A reused buffer whose length was cleared still has its old capacity, so
    // reserving only the shortfall against that capacity leaves `set_len` past
    // the end.
    out.clear();
    if out.capacity() < total {
        let extra = total - out.len();
        out.reserve(extra);
    }
    // `u8` has no destructor. `set_len(0)` on the error path drops nothing
    // unread. Every successful return overwrites `0..total`.
    unsafe { out.set_len(total) };
    let mut offsets = Vec::with_capacity(plain.len());
    let mut cursor = 0usize;
    for len in plain {
        offsets.push(cursor);
        cursor += *len;
    }
    let mut ends = Vec::with_capacity(starts.len());
    ends.extend_from_slice(&starts[1..]);
    ends.push(bytes.len());
    let error = std::sync::Mutex::new(None);
    let base = out.as_mut_ptr() as usize;
    par_ranges(starts.len(), threads, |begin, end| {
        for index in begin..end {
            if ends[index] < starts[index] || ends[index] > bytes.len() {
                *error.lock().unwrap() = Some(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "member range is outside the file",
                ));
                return;
            }
            let src = &bytes[starts[index]..ends[index]];
            let dst = unsafe {
                std::slice::from_raw_parts_mut((base as *mut u8).add(offsets[index]), plain[index])
            };
            if let Err(err) = decode(src, dst) {
                *error.lock().unwrap() = Some(err);
                return;
            }
        }
    });
    if let Some(err) = error.into_inner().unwrap_or(None) {
        unsafe { out.set_len(0) };
        return Err(err);
    }
    Ok(())
}

fn inflate_unknown(
    bytes: &[u8],
    starts: &[usize],
    threads: usize,
    decode: impl Fn(&[u8]) -> io::Result<Vec<u8>> + Sync + Send,
) -> io::Result<Vec<Vec<u8>>> {
    let mut ends = Vec::with_capacity(starts.len());
    ends.extend_from_slice(&starts[1..]);
    ends.push(bytes.len());
    let slots: Vec<std::sync::Mutex<Option<io::Result<Vec<u8>>>>> = (0..starts.len())
        .map(|_| std::sync::Mutex::new(None))
        .collect();
    par_ranges(starts.len(), threads, |begin, end| {
        for index in begin..end {
            let part = if ends[index] < starts[index] || ends[index] > bytes.len() {
                Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "member range is outside the file",
                ))
            } else {
                decode(&bytes[starts[index]..ends[index]])
            };
            *slots[index].lock().unwrap() = Some(part);
        }
    });
    let mut out = Vec::with_capacity(starts.len());
    for slot in slots {
        match slot.into_inner().unwrap_or(None) {
            Some(Ok(part)) => out.push(part),
            Some(Err(err)) => return Err(err),
            None => return Err(io::Error::other("inflate")),
        }
    }
    Ok(out)
}

fn encode_parts<F>(parts: &[&[u8]], threads: usize, encode: F) -> io::Result<Vec<Vec<u8>>>
where
    F: Fn(&[u8]) -> io::Result<Vec<u8>> + Sync,
{
    if parts.len() < 2 || threads <= 1 {
        let mut out = Vec::with_capacity(parts.len().max(1));
        if parts.is_empty() {
            out.push(encode(b"")?);
            return Ok(out);
        }
        for part in parts {
            out.push(encode(part)?);
        }
        return Ok(out);
    }
    let slots: Vec<std::sync::Mutex<Option<io::Result<Vec<u8>>>>> = (0..parts.len())
        .map(|_| std::sync::Mutex::new(None))
        .collect();
    // One OS thread per worker, as the original member writer did. The
    // pinned pool is the parser's; sharing it with deflate left the
    // eight-thread gzip write slower than four.
    let ranges = worker_ranges(parts.len(), threads);
    std::thread::scope(|scope| {
        for (begin, end) in ranges {
            let slots = &slots;
            let parts = &parts;
            let encode = &encode;
            scope.spawn(move || {
                for index in begin..end {
                    *slots[index].lock().unwrap() = Some(encode(parts[index]));
                }
            });
        }
    });
    let mut out = Vec::with_capacity(parts.len());
    for slot in slots {
        match slot.into_inner().unwrap_or(None) {
            Some(Ok(part)) => out.push(part),
            Some(Err(err)) => return Err(err),
            None => return Err(io::Error::other("compress")),
        }
    }
    Ok(out)
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
    write_zstd_members_limited(path, data, members, members.max(1))
}

/// [`write_zstd_members_n`] with a separate worker count.
#[cfg(feature = "zstd")]
pub fn write_zstd_members_limited(
    path: &Path,
    data: &[u8],
    members: usize,
    threads: usize,
) -> io::Result<usize> {
    let trace = std::env::var_os("READCON_WRITE_TRACE").is_some();
    let t0 = std::time::Instant::now();
    let parts = split_chunks(data, members.max(1));
    let plain: Vec<usize> = parts.iter().map(|part| part.len()).collect();
    let t_split = t0.elapsed().as_secs_f64();
    let t1 = std::time::Instant::now();
    // One frame keeps the `bulk::compress` bytes. Several frames reuse a
    // context; the plaintext is what callers compare.
    let encoded = if parts.len() < 2 {
        encode_parts(&parts, 1, |part| {
            zstd::bulk::compress(part, ZSTD_LEVEL).map_err(|err| io::Error::other(err.to_string()))
        })?
    } else {
        encode_parts(&parts, threads, zstd_compress_part)?
    };
    let t_encode = t1.elapsed().as_secs_f64();
    let t2 = std::time::Instant::now();
    let count = encoded.len();
    let mut file = std::fs::File::create(path)?;
    if count > 1 {
        let rows = coord_member_rows(data, &parts);
        file.write_all(&zstd_index_frame(&encoded, &plain, rows.as_deref()))?;
    }
    let t_index = t2.elapsed().as_secs_f64();
    let t3 = std::time::Instant::now();
    for frame in &encoded {
        file.write_all(frame)?;
    }
    file.flush()?;
    if trace {
        eprintln!(
            "zstd-write split={t_split:.4} encode={t_encode:.4} index={t_index:.4} io={:.4} members={count} threads={threads}",
            t3.elapsed().as_secs_f64()
        );
    }
    Ok(count)
}

#[cfg(feature = "zstd")]
fn zstd_compress_part(part: &[u8]) -> io::Result<Vec<u8>> {
    // One member stays on `bulk::compress`, which is the single-frame
    // byte image. Several members reuse a context on the worker.
    if part.is_empty() {
        return zstd::bulk::compress(part, ZSTD_LEVEL)
            .map_err(|err| io::Error::other(err.to_string()));
    }
    std::thread_local! {
        static COMPRESSOR: std::cell::RefCell<Option<zstd::bulk::Compressor<'static>>> =
            const { std::cell::RefCell::new(None) };
    }
    COMPRESSOR.with(|cell| {
        let mut slot = cell.borrow_mut();
        if slot.is_none() {
            *slot = Some(
                zstd::bulk::Compressor::new(ZSTD_LEVEL)
                    .map_err(|err| io::Error::other(err.to_string()))?,
            );
        }
        slot.as_mut()
            .expect("compressor")
            .compress(part)
            .map_err(|err| io::Error::other(err.to_string()))
    })
}

#[cfg(feature = "zstd")]
fn zstd_index_frame(frames: &[Vec<u8>], plain: &[usize], rows: Option<&[(u32, u32)]>) -> Vec<u8> {
    let row_bytes = usize::from(rows.is_some()) * 8 * frames.len();
    let payload_len = 4 + 2 + 16 * frames.len() + row_bytes;
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
    for len in plain {
        payload.extend_from_slice(&(*len as u64).to_le_bytes());
    }
    if let Some(rows) = rows {
        for (base, n) in rows {
            payload.extend_from_slice(&base.to_le_bytes());
            payload.extend_from_slice(&n.to_le_bytes());
        }
    }
    let mut bytes = Vec::with_capacity(8 + payload.len());
    bytes.extend_from_slice(&0x184D_2A50u32.to_le_bytes());
    bytes.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&payload);
    bytes
}

#[cfg(feature = "zstd")]
fn zstd_frame_starts(bytes: &[u8]) -> Option<MemberPlan> {
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
    let plain = if payload.len() >= 6 + 16 * count {
        let mut lens = Vec::with_capacity(count);
        for index in 0..count {
            let at = 6 + 8 * count + 8 * index;
            lens.push(u64::from_le_bytes(payload[at..at + 8].try_into().ok()?) as usize);
        }
        Some(lens)
    } else {
        None
    };
    let rows = row_table(payload, count);
    Some(MemberPlan {
        starts,
        plain,
        rows,
    })
}

#[cfg(feature = "zstd")]
fn zstd_into(src: &[u8], dst: &mut [u8]) -> io::Result<()> {
    std::thread_local! {
        static DECODER: std::cell::RefCell<Option<zstd::bulk::Decompressor<'static>>> =
            const { std::cell::RefCell::new(None) };
    }
    DECODER.with(|cell| {
        let mut slot = cell.borrow_mut();
        if slot.is_none() {
            *slot = Some(
                zstd::bulk::Decompressor::new().map_err(|err| io::Error::other(err.to_string()))?,
            );
        }
        let n = slot
            .as_mut()
            .expect("decoder")
            .decompress_to_buffer(src, dst)
            .map_err(|err| io::Error::other(err.to_string()))?;
        if n != dst.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "zstd frame length does not match the index",
            ));
        }
        let frame = zstd::zstd_safe::find_frame_compressed_size(src).map_err(|_| {
            io::Error::new(io::ErrorKind::InvalidData, "zstd frame size is not known")
        })?;
        if frame != src.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "zstd frame does not fill its index slice",
            ));
        }
        Ok(())
    })
}

#[cfg(feature = "zstd")]
fn zstd_decode_all(bytes: &[u8]) -> io::Result<Vec<u8>> {
    let mut out = Vec::new();
    inflate_zstd(bytes, &mut out)?;
    Ok(out)
}

#[cfg(feature = "zstd")]
fn inflate_zstd(bytes: &[u8], out: &mut Vec<u8>) -> io::Result<()> {
    if decode_thread_budget() != 1 {
        if let Some(plan) = zstd_frame_starts(bytes) {
            if plan.starts.len() > 1 {
                let threads = worker_limit_from_budget(plan.starts.len());
                let indexed = if let Some(plain) = plan.plain.as_deref() {
                    if plain.len() == plan.starts.len() {
                        inflate_sized(bytes, &plan.starts, plain, threads, zstd_into, out)
                    } else {
                        Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "zstd index has no plain length for every frame",
                        ))
                    }
                } else {
                    let parts = inflate_unknown(bytes, &plan.starts, threads, |part| {
                        zstd::stream::decode_all(part)
                            .map_err(|err| io::Error::other(err.to_string()))
                    })?;
                    out.clear();
                    for part in parts {
                        out.extend_from_slice(&part);
                    }
                    Ok(())
                };
                if indexed.is_ok() {
                    return indexed;
                }
                out.clear();
            }
        }
    }
    let mut decoder = zstd::stream::read::Decoder::new(bytes)?;
    out.clear();
    decoder.read_to_end(out)?;
    Ok(())
}

/// Inflate a gzip or zstd buffer with `threads` workers and no CON parse.
pub fn codec_inflate(bytes: &[u8], threads: usize) -> io::Result<Vec<u8>> {
    with_decode_threads(threads.max(1), || {
        if bytes.len() >= 2 && bytes[0] == 0x1f && bytes[1] == 0x8b {
            gunzip_all(bytes)
        } else if is_zstd_magic(bytes) {
            #[cfg(feature = "zstd")]
            {
                zstd_decode_all(bytes)
            }
            #[cfg(not(feature = "zstd"))]
            {
                Err(zstd_unsupported())
            }
        } else {
            Ok(bytes.to_vec())
        }
    })
}

/// Deflate `plain` into `members` slices on `threads` workers.
///
/// The returned bytes are the concatenated members, including the index
/// a reader needs. The timed work is the codec, not a CON parse.
pub fn codec_deflate(
    plain: &[u8],
    members: usize,
    threads: usize,
    gzip: bool,
) -> io::Result<Vec<u8>> {
    if gzip {
        let parts = split_chunks(plain, members.max(1));
        let lens: Vec<usize> = parts.iter().map(|part| part.len()).collect();
        let mut encoded = encode_parts(&parts, threads, gzip_member)?;
        if encoded.len() > 1 {
            let rows = coord_member_rows(plain, &parts);
            stamp_gzip_index(&mut encoded, &lens, rows.as_deref());
        }
        let mut out = Vec::new();
        for part in encoded {
            out.extend(part);
        }
        return Ok(out);
    }
    #[cfg(feature = "zstd")]
    {
        let parts = split_chunks(plain, members.max(1));
        let lens: Vec<usize> = parts.iter().map(|part| part.len()).collect();
        let encoded = encode_parts(&parts, threads, zstd_compress_part)?;
        let mut out = Vec::new();
        if encoded.len() > 1 {
            let rows = coord_member_rows(plain, &parts);
            out.extend(zstd_index_frame(&encoded, &lens, rows.as_deref()));
        }
        for part in encoded {
            out.extend(part);
        }
        Ok(out)
    }
    #[cfg(not(feature = "zstd"))]
    {
        let _ = (plain, members, threads);
        Err(zstd_unsupported())
    }
}

/// Indexed members whose plain lengths and coordinate-row spans are known.
pub(crate) struct IndexedMembers {
    pub starts: Vec<usize>,
    pub plain: Vec<usize>,
    pub rows: Vec<(u32, u32)>,
    pub gzip: bool,
}

pub(crate) fn indexed_members(bytes: &[u8]) -> Option<IndexedMembers> {
    if bytes.len() >= 2 && bytes[0] == 0x1f && bytes[1] == 0x8b {
        let plan = gzip_member_starts(bytes)?;
        let plain = plan.plain?;
        let rows = plan.rows?;
        if plain.len() != plan.starts.len() || rows.len() != plan.starts.len() || plain.len() < 2 {
            return None;
        }
        return Some(IndexedMembers {
            starts: plan.starts,
            plain,
            rows,
            gzip: true,
        });
    }
    #[cfg(feature = "zstd")]
    if is_zstd_magic(bytes) {
        let plan = zstd_frame_starts(bytes)?;
        let plain = plan.plain?;
        let rows = plan.rows?;
        if plain.len() != plan.starts.len() || rows.len() != plan.starts.len() || plain.len() < 2 {
            return None;
        }
        return Some(IndexedMembers {
            starts: plan.starts,
            plain,
            rows,
            gzip: false,
        });
    }
    None
}

pub(crate) fn inflate_member(gzip: bool, src: &[u8], dst: &mut [u8]) -> io::Result<()> {
    if gzip {
        gzip_into(src, dst)
    } else {
        #[cfg(feature = "zstd")]
        {
            zstd_into(src, dst)
        }
        #[cfg(not(feature = "zstd"))]
        {
            let _ = (src, dst);
            Err(zstd_unsupported())
        }
    }
}

std::thread_local! {
    static PLAIN_BUF: std::cell::RefCell<Vec<u8>> = const { std::cell::RefCell::new(Vec::new()) };
}

/// Inflate `file` into a buffer and hand that slice to `body`.
///
/// The plain text is dropped before this returns. A read that then copies
/// coordinates must not keep the inflated file beside those copies.
pub(crate) fn with_inflated_plain<T>(
    file: &[u8],
    body: impl FnOnce(&[u8]) -> Result<T, Box<dyn std::error::Error>>,
) -> Result<T, Box<dyn std::error::Error>> {
    PLAIN_BUF.with(|cell| {
        let mut buf = cell.borrow_mut();
        if file.len() >= 2 && file[0] == 0x1f && file[1] == 0x8b {
            inflate_gzip(file, &mut buf)
                .map_err(|err| Box::new(err) as Box<dyn std::error::Error>)?;
        } else if is_zstd_magic(file) {
            #[cfg(feature = "zstd")]
            {
                inflate_zstd(file, &mut buf)
                    .map_err(|err| Box::new(err) as Box<dyn std::error::Error>)?;
            }
            #[cfg(not(feature = "zstd"))]
            {
                return Err(Box::new(zstd_unsupported()) as Box<dyn std::error::Error>);
            }
        } else {
            buf.clear();
            buf.extend_from_slice(file);
        }
        let result = body(buf.as_slice())?;
        *buf = Vec::new();
        Ok(result)
    })
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

    /// Independent members inflate back to the same bytes. One member stays
    /// a single frame; several members carry the index a parallel read uses.
    #[test]
    fn codec_deflate_round_trips_one_member_and_several() {
        let plain = b"aaaa\nbbbb\ncccc\ndddd\neeee\nffff\n".repeat(80);
        for members in [1usize, 4] {
            let gzip = codec_deflate(&plain, members, 2, true).unwrap();
            assert!(gzip.starts_with(&[0x1f, 0x8b]));
            assert_eq!(codec_inflate(&gzip, 2).unwrap(), plain);
            #[cfg(feature = "zstd")]
            {
                let zstd_bytes = codec_deflate(&plain, members, 2, false).unwrap();
                assert_eq!(codec_inflate(&zstd_bytes, 2).unwrap(), plain);
            }
        }
        let raw = b"not a compressed buffer";
        assert_eq!(codec_inflate(raw, 1).unwrap(), raw);
    }

    /// A one-thread read stays on the serial decoder. Several decode
    /// threads inflate each member straight into its output slice. Both
    /// return the same plain text.
    #[test]
    fn a_one_thread_inflate_matches_the_slice_inflate() {
        let plain = b"0123456789\n".repeat(200);
        let gzip = codec_deflate(&plain, 4, 4, true).unwrap();
        let serial = with_serial_decode(|| codec_inflate(&gzip, 1)).unwrap();
        let sliced = codec_inflate(&gzip, 4).unwrap();
        assert_eq!(serial, plain);
        assert_eq!(sliced, plain);
        assert_eq!(decode_thread_budget(), 0);

        let member = {
            let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            enc.write_all(&plain).unwrap();
            enc.finish().unwrap()
        };
        let mut exact = vec![0u8; plain.len()];
        gzip_into(&member, &mut exact).unwrap();
        assert_eq!(exact, plain);
        let mut short = vec![0u8; plain.len() - 1];
        assert!(gzip_into(&member, &mut short).is_err());
    }

    /// A member concatenated after an indexed stream is part of the file.
    /// The parallel reader used to stop at the index and drop it.
    #[test]
    fn a_trailing_member_is_not_dropped() {
        let plain = b"frame-one\n".repeat(40);
        let extra = b"frame-two\n".repeat(20);
        let mut expect = plain.clone();
        expect.extend_from_slice(&extra);

        let indexed = codec_deflate(&plain, 2, 2, true).unwrap();
        let extra_gzip = {
            let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            enc.write_all(&extra).unwrap();
            enc.finish().unwrap()
        };
        assert_eq!(
            with_serial_decode(|| codec_inflate(&extra_gzip, 1)).unwrap(),
            extra
        );
        let mut gzip = indexed.clone();
        gzip.extend_from_slice(&extra_gzip);
        let serial = with_serial_decode(|| codec_inflate(&gzip, 1)).unwrap();
        let markers = |bytes: &[u8]| bytes.windows(2).filter(|w| *w == b"\x1f\x8b").count();
        assert_eq!(
            (
                markers(&indexed),
                markers(&gzip),
                serial.len(),
                plain.len(),
                extra.len()
            ),
            (2, 3, expect.len(), plain.len(), extra.len()),
            "member scan"
        );
        assert!(
            serial.starts_with(&plain) && serial.ends_with(&extra),
            "len {} plain {} extra {} tail {}",
            serial.len(),
            plain.len(),
            extra.len(),
            String::from_utf8_lossy(&serial[serial.len().saturating_sub(24)..])
        );
        assert_eq!(codec_inflate(&gzip, 4).unwrap(), expect);
        let mut truncated = indexed;
        truncated.extend_from_slice(&extra_gzip[..8]);
        assert!(with_serial_decode(|| codec_inflate(&truncated, 1)).is_err());
        assert!(codec_inflate(&truncated, 4).is_err());

        #[cfg(feature = "zstd")]
        {
            let indexed = codec_deflate(&plain, 2, 2, false).unwrap();
            let extra_zstd = zstd::stream::encode_all(extra.as_slice(), 3).unwrap();
            let mut zstd_bytes = indexed.clone();
            zstd_bytes.extend_from_slice(&extra_zstd);
            assert_eq!(
                with_serial_decode(|| codec_inflate(&zstd_bytes, 1)).unwrap(),
                expect
            );
            assert_eq!(codec_inflate(&zstd_bytes, 4).unwrap(), expect);
            let mut truncated = indexed;
            truncated.extend_from_slice(&extra_zstd[..8]);
            assert!(with_serial_decode(|| codec_inflate(&truncated, 1)).is_err());
            assert!(codec_inflate(&truncated, 4).is_err());
        }
    }

    fn mapped_text(path: &Path) -> Result<String, String> {
        let contents = read_file_contents(path).map_err(|e| e.to_string())?;
        contents
            .as_str()
            .map(str::to_owned)
            .map_err(|e| e.to_string())
    }

    #[test]
    fn compressed_text_that_is_not_utf8_is_rejected() {
        let dir = tempfile::tempdir().unwrap();
        let raw = b"Cu \xff";
        let gz = dir.path().join("bad.con.gz");
        {
            let mut enc = flate2::write::GzEncoder::new(
                std::fs::File::create(&gz).unwrap(),
                flate2::Compression::default(),
            );
            enc.write_all(raw).unwrap();
            enc.finish().unwrap();
        }
        let err = read_file_text(&gz).unwrap_err().to_string();
        assert!(err.contains("invalid utf-8"), "{err}");
        #[cfg(feature = "zstd")]
        {
            let zst = dir.path().join("bad.con.zst");
            std::fs::write(&zst, zstd::stream::encode_all(&raw[..], 3).unwrap()).unwrap();
            let err = read_file_text(&zst).unwrap_err().to_string();
            assert!(err.contains("invalid utf-8"), "{err}");
        }
    }

    /// File-backed maps are not available under Miri.
    #[test]
    #[cfg(not(miri))]
    fn dontneed_outside_a_rayon_pool_keeps_the_bytes() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.con");
        let bytes = large_text();
        std::fs::write(&path, &bytes).unwrap();
        let file = std::fs::File::open(&path).unwrap();
        let map = unsafe { memmap2::Mmap::map(&file).unwrap() };
        advise_dontneed_parallel(&map, 4);
        assert_eq!(&map[..bytes.len()], bytes.as_slice());
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
    fn indexed_gzip_members_are_cut_on_newlines() {
        let mut data = Vec::new();
        for i in 0..50_000 {
            writeln!(data, "Cu {i}.0 2.0 3.0 0 {i}").unwrap();
        }
        assert!(data.len() > (1 << 20));
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.con.gz");
        let members = write_gzip_members_n(&path, &data, 8).unwrap();
        assert!(members > 1, "a wide payload is more than one gzip member");
        let bytes = std::fs::read(&path).unwrap();
        let starts = gzip_member_starts(&bytes).expect("index").starts;
        assert_eq!(starts.len(), members);
        let mut plain = Vec::new();
        for (index, start) in starts.iter().copied().enumerate() {
            let end = starts.get(index + 1).copied().unwrap_or(bytes.len());
            let part = gunzip_member(&bytes[start..end]).unwrap();
            assert!(
                part.ends_with(b"\n"),
                "member {index} ends mid-line ({} bytes)",
                part.len()
            );
            plain.extend_from_slice(&part);
        }
        assert_eq!(plain, data);
    }

    #[test]
    fn a_short_indexed_plain_length_uses_the_serial_decoder() {
        let data = b"Cu 1.0 2.0 3.0 0 1\nH 4.0 5.0 6.0 0 2\n".repeat(8);
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("short-index.con.gz");
        assert!(write_gzip_members_n(&path, &data, 2).unwrap() > 1);
        let mut bytes = std::fs::read(&path).unwrap();
        assert_eq!(gunzip_all(&bytes).unwrap(), data);
        let at = bytes
            .windows(4)
            .position(|window| window == b"RCZ1")
            .expect("index");
        let count = u16::from_le_bytes([bytes[at + 4], bytes[at + 5]]) as usize;
        let len_at = at + 6 + 8 * count;
        let len = u64::from_le_bytes(bytes[len_at..len_at + 8].try_into().unwrap());
        assert!(len > 1);
        bytes[len_at..len_at + 8].copy_from_slice(&(len - 1).to_le_bytes());
        // A short plain length fails the indexed slice, then the serial
        // decoder still returns the member. A truncated tail does not.
        assert_eq!(gunzip_all(&bytes).unwrap(), data);
        bytes.truncate(bytes.len().saturating_sub(8).max(1));
        assert!(gunzip_all(&bytes).is_err());
    }

    #[test]
    fn one_member_gzip_matches_the_streaming_encoder() {
        let data = b"Cu 1.0 2.0 3.0 0 1\n".repeat(32);
        let direct = gzip_member(&data).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("one.con.gz");
        assert_eq!(write_gzip_members_n(&path, &data, 1).unwrap(), 1);
        assert_eq!(std::fs::read(&path).unwrap(), direct);
        let auto = dir.path().join("auto.con.gz");
        assert_eq!(write_gzip_members(&auto, &data).unwrap(), 1);
        assert_eq!(std::fs::read(&auto).unwrap(), direct);
    }

    #[test]
    fn default_deflate_threads_stay_within_the_machine() {
        let cores = std::thread::available_parallelism()
            .map(|count| count.get())
            .unwrap_or(1)
            .max(1);
        assert_eq!(default_deflate_threads(1), 1);
        assert_eq!(default_deflate_threads(cores.saturating_mul(4)), cores);
        assert!(default_deflate_threads(64) <= cores);
    }

    #[test]
    fn gzip_worker_count_does_not_change_the_bytes() {
        let mut data = Vec::new();
        for i in 0..20_000 {
            writeln!(data, "Cu {i}.25 1.5 2.5 0 {i}").unwrap();
        }
        let dir = tempfile::tempdir().unwrap();
        let one = dir.path().join("t1.con.gz");
        let eight = dir.path().join("t8.con.gz");
        write_gzip_members_limited(&one, &data, 8, 1).unwrap();
        write_gzip_members_limited(&eight, &data, 8, 8).unwrap();
        assert_eq!(std::fs::read(&one).unwrap(), std::fs::read(&eight).unwrap());
        assert_eq!(read_file_bytes(&one).unwrap(), data);
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

    fn cli_stdout(program: &str, args: &[&str]) -> std::process::Output {
        std::process::Command::new(program)
            .args(args)
            .output()
            .unwrap_or_else(|err| panic!("{program} failed to start: {err}"))
    }

    #[test]
    fn gzip_cli_decodes_one_member_and_an_indexed_file() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let wide = b"Cu 1.0 2.0 3.0 0 1\n".repeat(80_000);
        let dir = tempfile::tempdir().unwrap();
        let one = dir.path().join("one.con.gz");
        {
            let mut writer = gzip_writer(&one).unwrap();
            writer.write_all(text.as_bytes()).unwrap();
            writer.finish().unwrap();
        }
        let many = dir.path().join("wide.con.gz");
        write_gzip_members(&many, &wide).unwrap();
        for (path, expect) in [(&one, text.as_bytes()), (&many, wide.as_slice())] {
            let out = cli_stdout("gzip", &["-dc", path.to_str().unwrap()]);
            assert!(
                out.status.success(),
                "{}",
                String::from_utf8_lossy(&out.stderr)
            );
            assert_eq!(out.stdout, expect);
        }
    }

    #[cfg(feature = "zstd")]
    #[test]
    fn zstd_cli_decodes_one_frame_and_an_indexed_file() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let wide = b"0.0 1.0 2.0 0 0\n".repeat(80_000);
        let dir = tempfile::tempdir().unwrap();
        let one = dir.path().join("one.con.zst");
        std::fs::write(&one, zstd::stream::encode_all(text.as_bytes(), 3).unwrap()).unwrap();
        let many = dir.path().join("wide.con.zst");
        write_zstd_members(&many, &wide).unwrap();
        for (path, expect) in [(&one, text.as_bytes()), (&many, wide.as_slice())] {
            let out = cli_stdout("zstd", &["-dc", path.to_str().unwrap()]);
            assert!(
                out.status.success(),
                "{}",
                String::from_utf8_lossy(&out.stderr)
            );
            assert_eq!(out.stdout, expect);
        }
    }

    fn copper_frame(n: usize) -> crate::types::ConFrame {
        let mut builder =
            crate::types::ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        for i in 0..n {
            builder.add_atom(
                "Cu",
                i as f64,
                0.25,
                0.5,
                [false, false, false],
                i as u64,
                63.546,
            );
        }
        builder.build().unwrap()
    }

    fn coords(frame: &crate::types::ConFrame) -> Vec<f64> {
        frame
            .atom_data
            .iter()
            .flat_map(|atom| [atom.x(), atom.y(), atom.z()])
            .collect()
    }

    #[test]
    fn fused_gzip_round_trips_an_odd_atom_count_on_one_and_many_threads() {
        let frame = copper_frame(5);
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("odd.con.gz");
        let members = write_fused_gzip_frame(&path, &frame, 3, 2).unwrap();
        assert!(members >= 2);
        let one = crate::iterators::read_all_frames_phased(&path, Some(1)).unwrap();
        let many = crate::iterators::read_all_frames_phased(&path, Some(4)).unwrap();
        assert_eq!(one.frames.len(), 1);
        assert_eq!(coords(&one.frames[0]), coords(&frame));
        assert_eq!(coords(&many.frames[0]), coords(&frame));
    }

    #[test]
    fn fused_gzip_round_trips_two_species_on_many_threads() {
        let mut builder =
            crate::types::ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        for i in 0..4 {
            builder.add_atom("Cu", i as f64, 0.0, 0.0, [false; 3], i as u64, 63.546);
        }
        for i in 0..3 {
            builder.add_atom("H", i as f64, 1.0, 0.0, [false; 3], 4 + i as u64, 1.008);
        }
        let frame = builder.build().unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("alloy.con.gz");
        write_fused_gzip_frame(&path, &frame, 2, 2).unwrap();
        let one = crate::iterators::read_all_frames_phased(&path, Some(1)).unwrap();
        let many = crate::iterators::read_all_frames_phased(&path, Some(4)).unwrap();
        assert_eq!(coords(&one.frames[0]), coords(&frame));
        assert_eq!(coords(&many.frames[0]), coords(&frame));
        assert_eq!(
            many.frames[0].atom_data[0].symbol.as_ref(),
            frame.atom_data[0].symbol.as_ref()
        );
        assert_eq!(
            many.frames[0].atom_data[4].symbol.as_ref(),
            frame.atom_data[4].symbol.as_ref()
        );
    }

    #[test]
    fn fused_worker_count_does_not_change_the_bytes() {
        let frame = copper_frame(4_096);
        let dir = tempfile::tempdir().unwrap();
        let one = dir.path().join("one.con.gz");
        let eight = dir.path().join("eight.con.gz");
        assert!(write_fused_gzip_frame(&one, &frame, 8, 1).unwrap() > 1);
        assert!(write_fused_gzip_frame(&eight, &frame, 8, 8).unwrap() > 1);
        assert_eq!(std::fs::read(&one).unwrap(), std::fs::read(&eight).unwrap());
        let loaded = crate::iterators::read_all_frames_phased(&eight, Some(8)).unwrap();
        assert_eq!(coords(&loaded.frames[0]), coords(&frame));
    }

    #[cfg(feature = "zstd")]
    #[test]
    fn fused_zstd_worker_count_does_not_change_the_bytes() {
        let frame = copper_frame(4_096);
        let dir = tempfile::tempdir().unwrap();
        let one = dir.path().join("one.con.zst");
        let eight = dir.path().join("eight.con.zst");
        assert!(write_fused_zstd_frame(&one, &frame, 8, 1).unwrap() > 1);
        assert!(write_fused_zstd_frame(&eight, &frame, 8, 8).unwrap() > 1);
        assert_eq!(std::fs::read(&one).unwrap(), std::fs::read(&eight).unwrap());
        let loaded = crate::iterators::read_all_frames_phased(&eight, Some(4)).unwrap();
        assert_eq!(coords(&loaded.frames[0]), coords(&frame));
    }
}
