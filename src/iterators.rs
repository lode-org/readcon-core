//=============================================================================
// The Public API - A clean iterator for users of our library
//=============================================================================

use crate::parser::parse_single_frame;
use crate::{error, types};
use std::iter::Peekable;

/// An iterator that lazily parses simulation frames from a `.con` file's contents.
///
/// This struct wraps an iterator over the lines of a string and, upon each iteration,
/// attempts to parse a complete `ConFrame`. This is the primary interface for reading
/// data from a `.con` file.
///
/// The iterator yields items of type `Result<ConFrame, ParseError>`, allowing for
/// robust error handling for each frame.
pub struct ConFrameIterator<'a> {
    lines: Peekable<std::str::Lines<'a>>,
}

impl<'a> ConFrameIterator<'a> {
    /// Creates a new `ConFrameIterator` from a string slice of the entire file.
    ///
    /// # Arguments
    ///
    /// * `file_contents` - A string slice containing the text of one or more `.con` frames.
    pub fn new(file_contents: &'a str) -> Self {
        ConFrameIterator {
            lines: file_contents.lines().peekable(),
        }
    }

    /// Skips the next frame without fully parsing its atomic data.
    ///
    /// This is more efficient than `next()` if you only need to advance the
    /// iterator. It reads the frame's header to determine how many lines to skip.
    ///
    /// # Returns
    ///
    /// * `Some(Ok(()))` on a successful skip.
    /// * `Some(Err(ParseError::...))` if there's an error parsing the header.
    /// * `None` if the iterator is already at the end.
    pub fn forward(&mut self) -> Option<Result<(), error::ParseError>> {
        self.lines.peek()?;

        // Parse the header to determine the size of the frame.
        let header = match crate::parser::parse_frame_header(&mut self.lines) {
            Ok(header) => header,
            Err(e) => return Some(Err(e)),
        };

        // Calculate the number of lines to skip for the atom data.
        let num_atom_types = header.natm_types;
        let total_atoms: usize = header.natms_per_type.iter().sum();

        // For each atom type, there is one line for the symbol and one "Coordinates..." line.
        let non_atom_lines = num_atom_types * 2;
        let lines_to_skip = total_atoms + non_atom_lines;

        // Advance the iterator by skipping the lines.
        for _ in 0..lines_to_skip {
            if self.lines.next().is_none() {
                return Some(Err(error::ParseError::IncompleteFrame));
            }
        }

        Some(Ok(()))
    }
}

impl<'a> Iterator for ConFrameIterator<'a> {
    /// The type of item yielded by the iterator.
    ///
    /// Each item is a `Result` that contains a successfully parsed `ConFrame` or a
    /// `ParseError` if the frame's data is malformed.
    type Item = Result<types::ConFrame, error::ParseError>;

    /// Advances the iterator and attempts to parse the next frame.
    ///
    /// This method will return `None` only when there are no more lines to consume.
    /// If there are lines but they do not form a complete frame, it will return
    /// `Some(Err(ParseError::...))`.
    fn next(&mut self) -> Option<Self::Item> {
        // If there are no more lines at all, the iterator is exhausted.
        if self.lines.peek().is_none() {
            return None;
        }
        // Otherwise, attempt to parse the next frame from the available lines.
        Some(parse_single_frame(&mut self.lines))
    }
}
