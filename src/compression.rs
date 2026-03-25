//=============================================================================
// Transparent compression support
//=============================================================================

use std::io::{self, Read};
use std::path::Path;

/// Detected compression format based on magic bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Compression {
    None,
    Gzip,
}

/// Detect compression format from the first bytes of a file.
///
/// - `1f 8b` = gzip
/// - Otherwise = uncompressed
pub fn detect_compression(bytes: &[u8]) -> Compression {
    if bytes.len() >= 2 && bytes[0] == 0x1f && bytes[1] == 0x8b {
        return Compression::Gzip;
    }
    Compression::None
}

/// Detect compression format from a file extension.
///
/// Returns `Compression::Gzip` for `.gz` extension, `Compression::None` otherwise.
pub fn detect_compression_from_extension(path: &Path) -> Compression {
    match path.extension().and_then(|e| e.to_str()) {
        Some("gz") => Compression::Gzip,
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

    // Read first 2 bytes for magic detection
    let mut magic = [0u8; 2];
    let bytes_read = {
        let mut f = &file;
        f.read(&mut magic)?
    };

    let compression = if bytes_read >= 2 {
        detect_compression(&magic)
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
pub fn gzip_writer(
    path: &Path,
) -> io::Result<flate2::write::GzEncoder<std::fs::File>> {
    let file = std::fs::File::create(path)?;
    Ok(flate2::write::GzEncoder::new(
        file,
        flate2::Compression::default(),
    ))
}
