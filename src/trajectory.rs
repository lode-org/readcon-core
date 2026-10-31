//! Random access to the frames of one CON file.

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
    /// Read `path` once, check it as UTF-8 and load or scan its index.
    pub fn open(path: &Path, write_index: bool) -> Result<Self, Box<dyn std::error::Error>> {
        let (contents, compression) = compression::read_file_contents_detected(path)?;
        let text = contents.as_str_sliced()?;
        let index = if compression == Compression::None {
            frame_index::load_or_build(path, text, write_index)?
        } else {
            FrameIndex::scan(text)?
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
        let text = self.text().get(range).ok_or(ParseError::IncompleteFrame)?;
        ConFrameIterator::new(text)
            .next()
            .unwrap_or(Err(ParseError::IncompleteFrame))
    }

    fn text(&self) -> &str {
        // SAFETY: `open` checked every byte with `as_str_sliced` and the
        // contents are never written. A mapped file must not change while
        // mapped, as for every mapped reader in this crate.
        unsafe { std::str::from_utf8_unchecked(self.contents.as_bytes()) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn offset_inside_a_character_is_an_error() {
        let text = "é\n".repeat(4);
        let traj = ConTrajectory {
            contents: FileContents::Owned(text.clone()),
            index: FrameIndex {
                offsets: vec![0, 1],
                data_len: text.len() as u64,
            },
        };
        assert!(matches!(traj.frame(0), Err(ParseError::IncompleteFrame)));
        assert!(matches!(traj.frame(1), Err(ParseError::IncompleteFrame)));
    }
}
