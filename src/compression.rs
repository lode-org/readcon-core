//=============================================================================
// Transparent compression support
//=============================================================================

use std::io::{self, Read};
use std::path::Path;

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
    /// zstd frame, magic `28 B5 2F FD`. Build with `--features zstd`.
    Zstd,
}

/// Detect compression format from the first bytes of a file.
///
/// - `1f 8b` = gzip
/// - `28 b5 2f fd` = zstd
/// - Otherwise = uncompressed
pub fn detect_compression(bytes: &[u8]) -> Compression {
    if bytes.len() >= 2 && bytes[0] == 0x1f && bytes[1] == 0x8b {
        return Compression::Gzip;
    }
    if bytes.len() >= 4
        && bytes[0] == 0x28
        && bytes[1] == 0xb5
        && bytes[2] == 0x2f
        && bytes[3] == 0xfd
    {
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

/// Size threshold below which we use `read_to_string` instead of mmap.
const MMAP_THRESHOLD: u64 = 64 * 1024;

/// Reads file contents, decompressing if needed.
///
/// Detection strategy:
/// 1. Read the first 4 bytes to check magic bytes.
/// 2. If gzip or zstd: decompress entire file to a String.
/// 3. If uncompressed and < 64 KiB: read the rest into a String.
/// 4. If uncompressed and >= 64 KiB: memory-mapped I/O.
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
            // Every gzip member, in order (CON-compress.1, D16).
            let mut decoder = flate2::read::MultiGzDecoder::new(stream);
            let mut contents = String::new();
            decoder.read_to_string(&mut contents)?;
            FileContents::Owned(contents)
        }
        Compression::Zstd => {
            #[cfg(feature = "zstd")]
            {
                let mut decoder = zstd::stream::read::Decoder::new(stream)?;
                let mut contents = String::new();
                decoder.read_to_string(&mut contents)?;
                FileContents::Owned(contents)
            }
            #[cfg(not(feature = "zstd"))]
            {
                return Err(io::Error::new(
                    io::ErrorKind::Unsupported,
                    "zstd-compressed input detected; rebuild readcon-core with --features zstd",
                )
                .into());
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
        if let FileContents::Mapped(m) = &contents {
            let mut start = 0;
            while start < m.len() {
                let target = (start + RELEASE_STEP).min(m.len());
                let end = memchr::memchr(b'\n', &m[target..]).map_or(m.len(), |p| target + p + 1);
                if crate::frame_index::validate_utf8_sliced(&m[start..end]).is_err() {
                    std::str::from_utf8(m)?;
                }
                release(m, start, end)?;
                start = end;
            }
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
        flate2::Compression::default(),
    ))
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
    let encoder = zstd::stream::write::Encoder::new(file, 3)?;
    Ok(encoder.auto_finish())
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
}
