//! Random access to the frames of one CON file.

use std::io::Read;
use std::path::Path;

use crate::compression::{self, Compression, FileContents};
use crate::error::ParseError;
use crate::frame_index::{self, FrameIndex};
use crate::iterators::ConFrameIterator;
use crate::types::ConFrame;

/// The contents of one file and its checked [`FrameIndex`], kept for
/// repeated reads by frame number.
///
/// Uncompressed input reuses `path.rcidx` when it matches the file and
/// scans otherwise; `write_index` writes a fresh scan back. gzip and zstd
/// input is decompressed once and indexed in memory only, with no sidecar.
pub struct ConTrajectory {
    contents: FileContents,
    index: FrameIndex,
}

impl ConTrajectory {
    pub fn open(path: &Path, write_index: bool) -> Result<Self, Box<dyn std::error::Error>> {
        let contents = compression::read_file_contents(path)?;
        let text = contents.as_str_sliced()?;
        let index = if is_compressed(path)? {
            FrameIndex::scan(text)?
        } else {
            frame_index::load_or_build(path, text, write_index)?
        };
        Ok(Self { contents, index })
    }

    pub fn len(&self) -> usize {
        self.index.len()
    }

    pub fn is_empty(&self) -> bool {
        self.index.is_empty()
    }

    /// Parse frame `i`. An index past the end is
    /// [`ParseError::IndexOutOfBounds`].
    pub fn frame(&self, i: usize) -> Result<ConFrame, ParseError> {
        let out_of_range = ParseError::IndexOutOfBounds {
            index: i,
            len: self.len(),
        };
        let range = self.index.range(i).ok_or(out_of_range)?;
        let bytes = self
            .contents
            .as_bytes()
            .get(range)
            .ok_or(ParseError::IncompleteFrame)?;
        let text = std::str::from_utf8(bytes)
            .map_err(|e| ParseError::ValidationError(format!("invalid UTF-8 in frame {i}: {e}")))?;
        ConFrameIterator::new(text)
            .next()
            .unwrap_or(Err(ParseError::IncompleteFrame))
    }
}

fn is_compressed(path: &Path) -> std::io::Result<bool> {
    let mut magic = Vec::with_capacity(4);
    std::fs::File::open(path)?.take(4).read_to_end(&mut magic)?;
    Ok(compression::detect_compression(&magic) != Compression::None)
}
