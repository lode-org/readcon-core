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
/// 1. Read first 2 bytes to check magic bytes.
/// 2. If gzip: decompress entire file to a String.
/// 3. If uncompressed and < 64 KiB: `read_to_string`.
/// 4. If uncompressed and >= 64 KiB: memory-mapped I/O.
pub fn read_file_contents(path: &Path) -> Result<FileContents, Box<dyn std::error::Error>> {
    let file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;

    // Read first 4 bytes for magic detection (gzip needs 2, zstd needs 4)
    let mut magic = [0u8; 4];
    let bytes_read = {
        let mut f = &file;
        f.read(&mut magic)?
    };

    let compression = if bytes_read > 0 {
        detect_compression(&magic[..bytes_read])
    } else {
        Compression::None
    };

    match compression {
        Compression::Gzip => {
            // Re-open and decompress the entire file
            let file = std::fs::File::open(path)?;
            let mut decoder = flate2::read::GzDecoder::new(file);
            let mut contents = String::new();
            decoder.read_to_string(&mut contents)?;
            Ok(FileContents::Owned(contents))
        }
        Compression::Zstd => {
            #[cfg(feature = "zstd")]
            {
                let file = std::fs::File::open(path)?;
                let mut decoder = zstd::stream::read::Decoder::new(file)?;
                let mut contents = String::new();
                decoder.read_to_string(&mut contents)?;
                Ok(FileContents::Owned(contents))
            }
            #[cfg(not(feature = "zstd"))]
            {
                Err(io::Error::new(
                    io::ErrorKind::Unsupported,
                    "zstd-compressed input detected; rebuild readcon-core with --features zstd",
                )
                .into())
            }
        }
        Compression::None => {
            if metadata.len() < MMAP_THRESHOLD {
                let contents = std::fs::read_to_string(path)?;
                Ok(FileContents::Owned(contents))
            } else {
                let file = std::fs::File::open(path)?;
                let mmap = unsafe { memmap2::Mmap::map(&file)? };
                Ok(FileContents::Mapped(mmap))
            }
        }
    }
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
