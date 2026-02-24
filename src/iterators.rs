//=============================================================================
// The Public API - A clean iterator for users of our library
//=============================================================================

use crate::parser::{parse_single_frame, parse_velocity_section};
use crate::{error, types};
use std::iter::Peekable;
use std::path::Path;

/// An iterator that lazily parses simulation frames from a `.con` or `.convel`
/// file's contents.
///
/// This struct wraps an iterator over the lines of a string and, upon each iteration,
/// attempts to parse a complete `ConFrame`. Velocity sections are detected
/// automatically: if a blank line follows the coordinate blocks, the velocity
/// data is parsed into the atoms.
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
    /// iterator. It reads the frame's header to determine how many lines to skip,
    /// including any velocity section if present.
    ///
    /// # Returns
    ///
    /// * `Some(Ok(()))` on a successful skip.
    /// * `Some(Err(ParseError::...))` if there's an error parsing the header.
    /// * `None` if the iterator is already at the end.
    pub fn forward(&mut self) -> Option<Result<(), error::ParseError>> {
        // Skip frame by parsing only required header fields to avoid full parsing overhead
        if self.lines.peek().is_none() {
            return None;
        }

        // Manually consume the first 6 lines of the header, which we don't need for skipping.
        for _ in 0..6 {
            if self.lines.next().is_none() {
                return Some(Err(error::ParseError::IncompleteHeader));
            }
        }

        // Line 7: natm_types. We need to parse this.
        let natm_types: usize = match self.lines.next() {
            Some(line) => match crate::parser::parse_line_of_n::<usize>(line, 1) {
                Ok(v) => v[0],
                Err(e) => return Some(Err(e)),
            },
            None => return Some(Err(error::ParseError::IncompleteHeader)),
        };

        // Line 8: natms_per_type. We need this to sum the total number of atoms.
        let natms_per_type: Vec<usize> = match self.lines.next() {
            Some(line) => match crate::parser::parse_line_of_n(line, natm_types) {
                Ok(v) => v,
                Err(e) => return Some(Err(e)),
            },
            None => return Some(Err(error::ParseError::IncompleteHeader)),
        };

        // Line 9: masses_per_type. We just need to consume this line.
        if self.lines.next().is_none() {
            return Some(Err(error::ParseError::IncompleteHeader));
        }

        // Calculate how many more lines to skip for coordinate blocks.
        let total_atoms: usize = natms_per_type.iter().sum();
        // For each atom type, there is a symbol line and a "Coordinates..." line.
        let non_atom_lines = natm_types * 2;
        let lines_to_skip = total_atoms + non_atom_lines;

        // Advance the iterator by skipping the coordinate block lines.
        for _ in 0..lines_to_skip {
            if self.lines.next().is_none() {
                // The file ended before the header's promise was fulfilled.
                return Some(Err(error::ParseError::IncompleteFrame));
            }
        }

        // Check for an optional velocity section (blank separator followed by
        // velocity blocks with the same structure as coordinate blocks).
        if let Some(line) = self.lines.peek() {
            if line.trim().is_empty() {
                // Consume the blank separator
                self.lines.next();
                // Skip the velocity blocks: same structure as coordinate blocks
                let vel_lines_to_skip = total_atoms + non_atom_lines;
                for _ in 0..vel_lines_to_skip {
                    if self.lines.next().is_none() {
                        return Some(Err(error::ParseError::IncompleteVelocitySection));
                    }
                }
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
        let mut frame = match parse_single_frame(&mut self.lines) {
            Ok(f) => f,
            Err(e) => return Some(Err(e)),
        };
        // Attempt to parse optional velocity section
        match parse_velocity_section(&mut self.lines, &frame.header, &mut frame.atom_data) {
            Ok(_) => {}
            Err(e) => return Some(Err(e)),
        }
        Some(Ok(frame))
    }
}

/// Reads all frames from a file using memory-mapped I/O.
///
/// This avoids the `read_to_string` allocation for large trajectory files by
/// letting the OS page cache handle the data. The mmap is read-only and the
/// file contents are validated as UTF-8 before parsing.
pub fn read_all_frames(path: &Path) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    let file = std::fs::File::open(path)?;
    let mmap = unsafe { memmap2::Mmap::map(&file)? };
    let contents = std::str::from_utf8(&mmap)?;
    let iter = ConFrameIterator::new(contents);
    let frames: Result<Vec<_>, _> = iter.collect();
    Ok(frames?)
}

/// Parses frames in parallel using rayon, splitting on frame boundaries.
///
/// Phase 1: sequential scan to find byte offsets of each frame's start.
/// Phase 2: parallel parse of each frame slice using rayon.
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_parallel(
    file_contents: &str,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    use rayon::prelude::*;

    // Phase 1: find frame byte boundaries by scanning for header patterns.
    // Each frame starts with a header: 2 comment lines, then a line with 3 floats (box).
    // We identify boundaries by walking through the file with a ConFrameIterator
    // and recording byte positions.
    let mut boundaries: Vec<usize> = Vec::new();
    let mut offset = 0;
    boundaries.push(0);

    // Walk through the file using the forward() method to find frame boundaries
    let mut scanner = ConFrameIterator::new(file_contents);
    while scanner.forward().is_some() {
        // After forward(), the internal iterator is positioned right after the frame.
        // We need to figure out the byte offset of the next frame start.
        // Since Peekable<Lines> doesn't expose byte offsets, we use a different approach:
        // count lines consumed per frame and convert to byte offsets.
    }

    // Simpler approach: split into frame text chunks by parsing sequentially,
    // recording where each frame starts and ends in the string.
    boundaries.clear();
    let lines: Vec<&str> = file_contents.lines().collect();
    let mut line_idx = 0;
    let total_lines = lines.len();

    while line_idx < total_lines {
        // Record the byte offset of this frame's start
        let byte_offset: usize = lines[..line_idx]
            .iter()
            .map(|l| l.len() + 1) // +1 for newline
            .sum();
        boundaries.push(byte_offset);

        // Skip 6 header lines (prebox1, prebox2, boxl, angles, postbox1, postbox2)
        if line_idx + 6 >= total_lines {
            break;
        }
        line_idx += 6;

        // Line 7: natm_types
        let natm_types: usize = match lines.get(line_idx) {
            Some(l) => match crate::parser::parse_line_of_n::<usize>(l, 1) {
                Ok(v) => v[0],
                Err(_) => break,
            },
            None => break,
        };
        line_idx += 1;

        // Line 8: natms_per_type
        let natms_per_type: Vec<usize> = match lines.get(line_idx) {
            Some(l) => match crate::parser::parse_line_of_n(l, natm_types) {
                Ok(v) => v,
                Err(_) => break,
            },
            None => break,
        };
        line_idx += 1;

        // Line 9: masses (just skip)
        line_idx += 1;

        // Skip coordinate blocks
        let total_atoms: usize = natms_per_type.iter().sum();
        let coord_lines = total_atoms + natm_types * 2;
        line_idx += coord_lines;

        // Check for velocity section (blank separator)
        if line_idx < total_lines {
            if let Some(l) = lines.get(line_idx) {
                if l.trim().is_empty() {
                    line_idx += 1; // blank separator
                    line_idx += coord_lines; // velocity blocks same size
                }
            }
        }
    }

    // Phase 2: parallel parse each frame chunk
    let num_frames = boundaries.len();
    (0..num_frames)
        .into_par_iter()
        .map(|i| {
            let start = boundaries[i];
            let end = if i + 1 < num_frames {
                boundaries[i + 1]
            } else {
                file_contents.len()
            };
            let chunk = &file_contents[start..end];
            let mut iter = ConFrameIterator::new(chunk);
            match iter.next() {
                Some(result) => result,
                None => Err(error::ParseError::IncompleteFrame),
            }
        })
        .collect()
}
