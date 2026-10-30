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

    fn large_text() -> Vec<u8> {
        let frame = include_bytes!("../resources/test/tiny_cuh2.con");
        let copies = MMAP_THRESHOLD as usize / frame.len() + 2;
        frame.repeat(copies)
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
}
