//=============================================================================
// The Public API - A clean iterator for users of our library
//=============================================================================

use crate::parser::{parse_declared_sections, parse_single_frame};
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
    pub(crate) lines: Peekable<std::str::Lines<'a>>,
    /// Raw bytes of the source string, alongside a cursor. Used by
    /// [`Self::forward_fast`] to skip frames via direct memchr-bulk
    /// `\n` lookup instead of advancing the line iterator one call at
    /// a time. The cursor is only nudged forward from `forward_fast`;
    /// callers that mix `next()` / `forward()` with `forward_fast`
    /// will see the cursor reset to whatever the line iterator's
    /// current view of the slice is.
    bytes: &'a [u8],
    cursor: usize,
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
            bytes: file_contents.as_bytes(),
            cursor: 0,
        }
    }

    /// Bulk-skips `n` lines starting at `self.cursor` using memchr to
    /// find each `\n`. Returns `Ok(())` when `n` lines were consumed,
    /// `Err(IncompleteFrame)` when the byte slice ran out first.
    ///
    /// Used by [`Self::forward_fast`] to avoid the per-line iterator
    /// overhead of `Peekable<Lines>::next()` on workloads that only
    /// want to skip past the current frame.
    fn advance_lines(&mut self, n: usize) -> Result<(), error::ParseError> {
        for _ in 0..n {
            let rest = &self.bytes[self.cursor..];
            match memchr::memchr(b'\n', rest) {
                Some(pos) => self.cursor += pos + 1,
                None => {
                    if rest.is_empty() {
                        return Err(error::ParseError::IncompleteFrame);
                    }
                    self.cursor = self.bytes.len();
                    return Err(error::ParseError::IncompleteFrame);
                }
            }
        }
        Ok(())
    }

    /// Returns the bytes of the current line at `self.cursor` (without
    /// the trailing `\n`) as a `&str`, advancing the cursor past the
    /// newline.
    fn read_line_str(&mut self) -> Option<&'a str> {
        let rest = &self.bytes[self.cursor..];
        if rest.is_empty() {
            return None;
        }
        let (line_bytes, advance) = match memchr::memchr(b'\n', rest) {
            Some(pos) => (&rest[..pos], pos + 1),
            None => (rest, rest.len()),
        };
        // Strip optional trailing \r for Windows line endings.
        let trimmed = if line_bytes.last() == Some(&b'\r') {
            &line_bytes[..line_bytes.len() - 1]
        } else {
            line_bytes
        };
        // SAFETY: source was a `&str` so any UTF-8 prefix terminated by
        // an ASCII byte (`\n`, `\r`) remains valid UTF-8.
        let line = unsafe { std::str::from_utf8_unchecked(trimmed) };
        self.cursor += advance;
        Some(line)
    }

    /// memchr-backed equivalent of [`Self::forward`]. Skips the next
    /// frame without fully parsing its atom data, walking the
    /// underlying byte slice with `memchr` directly instead of the
    /// peekable line iterator. The two methods are not interleavable:
    /// once the caller starts using `forward_fast`, switching to
    /// `next()` or `forward()` resets to the line iterator's view and
    /// loses any progress the cursor made.
    pub fn forward_fast(&mut self) -> Option<Result<(), error::ParseError>> {
        if self.cursor >= self.bytes.len() {
            return None;
        }
        // Lines 1..=6 of the header are skipped wholesale.
        if let Err(e) = self.advance_lines(6) {
            return Some(Err(e));
        }
        // Line 7: natm_types.
        let natm_types: usize = match self.read_line_str() {
            Some(line) => match crate::parser::parse_line_of_n::<usize>(line, 1) {
                Ok(v) => v[0],
                Err(e) => return Some(Err(e)),
            },
            None => return Some(Err(error::ParseError::IncompleteHeader)),
        };
        // Line 8: natms_per_type.
        let natms_per_type: Vec<usize> = match self.read_line_str() {
            Some(line) => match crate::parser::parse_line_of_n(line, natm_types) {
                Ok(v) => v,
                Err(e) => return Some(Err(e)),
            },
            None => return Some(Err(error::ParseError::IncompleteHeader)),
        };
        // Line 9: masses_per_type, consumed.
        if let Err(e) = self.advance_lines(1) {
            return Some(Err(e));
        }
        let total_atoms: usize = natms_per_type.iter().sum();
        let coord_block_lines = total_atoms + natm_types * 2;
        if let Err(e) = self.advance_lines(coord_block_lines) {
            return Some(Err(e));
        }
        // Optional sections: blank line + same-shape block, repeated.
        loop {
            let rest = &self.bytes[self.cursor..];
            // Peek the next line without advancing the cursor.
            let next_eol = memchr::memchr(b'\n', rest);
            let line = match next_eol {
                Some(pos) => &rest[..pos],
                None => rest,
            };
            let is_blank = line
                .iter()
                .all(|b| matches!(b, b' ' | b'\t' | b'\r'));
            if !is_blank || line.is_empty() && self.cursor >= self.bytes.len() {
                break;
            }
            if !is_blank {
                break;
            }
            // Consume the blank separator and the section block.
            self.cursor += next_eol.map(|p| p + 1).unwrap_or(rest.len());
            if let Err(e) = self.advance_lines(coord_block_lines) {
                return Some(Err(e));
            }
        }
        Some(Ok(()))
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
        self.lines.peek()?;

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

        // Skip additional sections (velocities, forces).
        // Each section has: blank separator + same structure as coordinate blocks.
        // We don't have access to the parsed sections list here (we only parsed
        // the header minimally), so we detect sections by peeking for blank separators.
        loop {
            match self.lines.peek() {
                Some(line) if line.trim().is_empty() => {
                    self.lines.next(); // consume blank separator
                    let section_lines = total_atoms + non_atom_lines;
                    for _ in 0..section_lines {
                        if self.lines.next().is_none() {
                            return Some(Err(error::ParseError::IncompleteFrame));
                        }
                    }
                }
                _ => break,
            }
        }

        Some(Ok(()))
    }

    /// Next frame plus the exact substring of the buffer passed to [`Self::new`].
    ///
    /// **Corpus ingest contract:** successive successful spans from the same
    /// `file_contents` are contiguous (`end` of frame *i* equals `start` of frame
    /// *i+1*) and, for a buffer that is only multi-frame CON (no prefix garbage),
    /// concatenating all spans reproduces the trajectory text. Campaign stores
    /// (`readcon-db`) must persist these spans as authoritative blobs—do not
    /// re-serialize on the hot ingest path unless the caller supplied in-memory
    /// [`types::ConFrame`] values without source text.
    ///
    /// See also [`crate::index_proj::frame_byte_spans`] and
    /// [`crate::index_proj::spans_cover_buffer`].
    pub fn next_with_raw_span(
        &mut self,
        file_contents: &'a str,
    ) -> Option<Result<(types::ConFrame, &'a str), error::ParseError>> {
        let base = file_contents.as_ptr() as usize;
        let start = {
            let line = self.lines.peek()?;
            line.as_ptr() as usize - base
        };
        let frame = match self.next()? {
            Ok(f) => f,
            Err(e) => return Some(Err(e)),
        };
        let end = match self.lines.peek() {
            Some(line) => line.as_ptr() as usize - base,
            None => file_contents.len(),
        };
        debug_assert!(end >= start && end <= file_contents.len());
        // frame already went through next() → sync_arrays_from_atom_data
        Some(Ok((frame, &file_contents[start..end])))
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
        self.lines.peek()?;
        // Otherwise, attempt to parse the next frame from the available lines.
        let mut frame = match parse_single_frame(&mut self.lines) {
            Ok(f) => f,
            Err(e) => return Some(Err(e)),
        };
        // Parse declared sections (velocities, forces) or fall back to legacy velocity detection
        // (mutates AoS only; SoA sections filled below).
        match parse_declared_sections(&mut self.lines, &mut frame.header, &mut frame.atom_data) {
            Ok(_) => {}
            Err(e) => return Some(Err(e)),
        }
        frame.sync_arrays_from_atom_data();
        Some(Ok(frame))
    }
}

#[cfg(test)]
mod aos_soa_agreement_tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn iterator_vel_forces_soa_matches_aos() {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test/tiny_cuh2_vel_forces.con");
        let text = std::fs::read_to_string(&p).expect("fixture");
        let fr = ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        let n = fr.atom_data.len();
        assert!(n > 0);
        assert_eq!(fr.positions.nrows(), n);
        let has_vel = fr.atom_data.iter().any(|a| a.velocity.is_some());
        let has_frc = fr.atom_data.iter().any(|a| a.force.is_some());
        if has_vel {
            assert_eq!(
                fr.velocities.nrows(),
                n,
                "SoA velocities must match AoS after section parse"
            );
        }
        if has_frc {
            assert_eq!(fr.forces.nrows(), n, "SoA forces must match AoS");
        }
        for (i, a) in fr.atom_data.iter().enumerate() {
            let p = fr.positions.as_f64_row(i);
            assert_eq!([a.x, a.y, a.z], p);
            if let Some(v) = a.velocity {
                assert_eq!(v, fr.velocities.as_f64_row(i));
            }
            if let Some(f) = a.force {
                assert_eq!(f, fr.forces.as_f64_row(i));
            }
        }
    }

    /// After SoA-primary parse, section sync must not require rewriting positions
    /// (nrows already equals N); forces SoA still filled from AoS.
    #[test]
    fn sync_skips_pos_when_nrows_matches_keeps_force_soa() {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test/tiny_cuh2_forces.con");
        let text = std::fs::read_to_string(&p).expect("fixture");
        let fr = ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        let n = fr.atom_data.len();
        assert_eq!(fr.positions.nrows(), n);
        assert_eq!(fr.forces.nrows(), n);
        // Snapshot first position SoA row then re-sync; coords must stay bit-identical
        // (no needless rewrite would change nothing but we still require agreement).
        let p0 = fr.positions.as_f64_row(0);
        let mut fr2 = fr.clone();
        fr2.sync_arrays_from_atom_data();
        assert_eq!(fr2.positions.as_f64_row(0), p0);
        assert_eq!(fr2.forces.nrows(), n);
        assert_eq!(
            fr2.forces.as_f64_row(0),
            fr2.atom_data[0].force.expect("force")
        );
    }
}

/// Reads all frames from a file.
///
/// For files smaller than 64 KiB, uses a simple `read_to_string` to avoid
/// the fixed overhead of mmap (VMA creation, page fault, munmap). For larger
/// trajectory files, uses memory-mapped I/O to let the OS page cache handle
/// the data.
pub fn read_all_frames(path: &Path) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str()?;
    let iter = ConFrameIterator::new(text);
    let frames: Result<Vec<_>, _> = iter.collect();
    Ok(frames?)
}

/// Reads only the first frame from a file.
///
/// More efficient than `read_all_frames` for single-frame access because it
/// stops parsing after the first frame rather than collecting all of them.
pub fn read_first_frame(path: &Path) -> Result<types::ConFrame, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str()?;
    let mut iter = ConFrameIterator::new(text);
    match iter.next() {
        Some(Ok(frame)) => Ok(frame),
        Some(Err(e)) => Err(Box::new(e)),
        None => Err("No frames found in file".into()),
    }
}

/// Parses frames in parallel using rayon, splitting on frame boundaries.
///
/// Phase 1: sequential O(N) scan via memchr-backed
/// [`ConFrameIterator::forward_fast`] to find byte offsets of every
/// frame's start. The previous implementation built a `Vec<&str>` of
/// every line and called `lines[..i].iter().map(|l| l.len() +
/// 1).sum()` on every frame, which is O(N^2) in line count and
/// dominated runtime on multi-frame trajectories.
///
/// Phase 2: parallel parse of each frame slice using rayon on the
/// **global** Rayon pool (see also [`parse_frames_parallel_with_threads`]
/// for strong-scaling control of the worker count).
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_parallel(
    file_contents: &str,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    parse_frames_parallel_with_threads(file_contents, None)
}

/// Like [`parse_frames_parallel`], but runs phase-2 on an explicit Rayon
/// pool with `num_threads` workers when `Some(n)` (`n` is clamped to at
/// least 1). `None` uses the global pool (same as [`parse_frames_parallel`]).
///
/// Strong-scaling tests pin worker counts without racing the global pool.
/// Results are ordered by frame index (stable vs sequential iterator order).
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_parallel_with_threads(
    file_contents: &str,
    num_threads: Option<usize>,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    use rayon::prelude::*;

    // Phase 1: walk the file once with forward_fast and snapshot the
    // cursor before each frame.
    let mut boundaries: Vec<usize> = Vec::new();
    let mut scanner = ConFrameIterator::new(file_contents);
    loop {
        let start = scanner.cursor;
        if start >= scanner.bytes.len() {
            break;
        }
        boundaries.push(start);
        match scanner.forward_fast() {
            Some(Ok(())) => {}
            Some(Err(_)) | None => break,
        }
    }

    let parse_chunks = || {
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
    };

    match num_threads {
        None => parse_chunks(),
        Some(n) => {
            let n = n.max(1);
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(n)
                .build()
                .expect("rayon pool");
            pool.install(parse_chunks)
        }
    }
}

#[cfg(all(test, feature = "parallel"))]
mod parallel_strong_scale_tests {
    use super::*;
    use std::path::PathBuf;

    fn multi_frame_fixture() -> String {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test/tiny_cuh2.con");
        let one = std::fs::read_to_string(p).expect("fixture");
        // Enough frames for >1 worker to exercise the pool.
        one.repeat(8)
    }

    fn sequential_frames(text: &str) -> Vec<types::ConFrame> {
        ConFrameIterator::new(text)
            .map(|r| r.expect("seq frame"))
            .collect()
    }

    fn frames_payload_key(f: &types::ConFrame) -> (usize, Vec<(String, f64, f64, f64)>) {
        let atoms: Vec<_> = f
            .atom_data
            .iter()
            .map(|a| (a.symbol.to_string(), a.x, a.y, a.z))
            .collect();
        (f.atom_data.len(), atoms)
    }

    #[test]
    fn parallel_workers_match_sequential_payloads() {
        let text = multi_frame_fixture();
        let seq = sequential_frames(&text);
        assert!(seq.len() >= 8);
        let seq_keys: Vec<_> = seq.iter().map(frames_payload_key).collect();

        for workers in [1usize, 2, 4] {
            let par = parse_frames_parallel_with_threads(&text, Some(workers));
            assert_eq!(par.len(), seq.len(), "workers={workers}");
            let par_keys: Vec<_> = par
                .into_iter()
                .map(|r| frames_payload_key(&r.expect("par frame")))
                .collect();
            assert_eq!(par_keys, seq_keys, "workers={workers} frame payloads");
        }

        // Global pool path agrees too.
        let par_default = parse_frames_parallel(&text);
        let def_keys: Vec<_> = par_default
            .into_iter()
            .map(|r| frames_payload_key(&r.expect("par")))
            .collect();
        assert_eq!(def_keys, seq_keys);
    }
}
