//=============================================================================
// The Public API - A clean iterator for users of our library
//=============================================================================

use crate::parser::{
    parse_declared_sections, parse_single_frame, parse_single_frame_positions, LineStream,
};
use crate::{error, types};
use std::path::Path;

/// memchr-backed line cursor for the full parse path (not only frame skip).
///
/// Profile note: `str::Lines` + `Peekable` showed up under
/// `ConFrameIterator::next` on multi-atom multi-frame workloads. One cursor
/// serves `next` / `peek` / `forward_fast` so skip and full parse share the
/// same O(1) newline scan rather than two desynchronized views of the buffer.
pub struct MemchrLines<'a> {
    bytes: &'a [u8],
    pos: usize,
    peeked: Option<&'a str>,
}

impl<'a> MemchrLines<'a> {
    pub fn new(text: &'a str) -> Self {
        Self {
            bytes: text.as_bytes(),
            pos: 0,
            peeked: None,
        }
    }

    #[inline]
    fn read_one(&mut self) -> Option<&'a str> {
        if self.pos >= self.bytes.len() {
            return None;
        }
        let rest = &self.bytes[self.pos..];
        let (line_bytes, advance) = match memchr::memchr(b'\n', rest) {
            Some(i) => (&rest[..i], i + 1),
            None => (rest, rest.len()),
        };
        self.pos += advance;
        let trimmed = if line_bytes.last() == Some(&b'\r') {
            &line_bytes[..line_bytes.len() - 1]
        } else {
            line_bytes
        };
        // SAFETY: source was `&str`; line is a UTF-8 prefix cut on ASCII `\n`/`\r`.
        Some(unsafe { std::str::from_utf8_unchecked(trimmed) })
    }

    #[inline]
    pub fn next_line(&mut self) -> Option<&'a str> {
        if let Some(p) = self.peeked.take() {
            return Some(p);
        }
        self.read_one()
    }

    #[inline]
    pub fn peek_line(&mut self) -> Option<&'a str> {
        if self.peeked.is_none() {
            self.peeked = self.read_one();
        }
        self.peeked
    }

    /// Drop any peek buffer (required before bulk cursor advances).
    fn clear_peek(&mut self) {
        if let Some(p) = self.peeked.take() {
            // Rewind pos to the start of the peeked line.
            let start = p.as_ptr() as usize - self.bytes.as_ptr() as usize;
            self.pos = start;
        }
    }
}

impl<'a> Iterator for MemchrLines<'a> {
    type Item = &'a str;
    fn next(&mut self) -> Option<&'a str> {
        self.next_line()
    }
}

impl<'a> LineStream<'a> for MemchrLines<'a> {
    #[inline]
    fn next_line(&mut self) -> Option<&'a str> {
        MemchrLines::next_line(self)
    }
    #[inline]
    fn peek_line(&mut self) -> Option<&'a str> {
        MemchrLines::peek_line(self)
    }
}

/// An iterator that lazily parses simulation frames from a `.con` or `.convel`
/// file's contents.
///
/// This struct wraps a memchr line cursor over the file buffer and, upon each
/// iteration, attempts to parse a complete `ConFrame`. Velocity sections are
/// detected automatically: if a blank line follows the coordinate blocks, the
/// velocity data is parsed into the atoms.
///
/// The iterator yields items of type `Result<ConFrame, ParseError>`, allowing for
/// robust error handling for each frame.
pub struct ConFrameIterator<'a> {
    pub(crate) lines: MemchrLines<'a>,
}

impl<'a> ConFrameIterator<'a> {
    /// Creates a new `ConFrameIterator` from a string slice of the entire file.
    ///
    /// # Arguments
    ///
    /// * `file_contents` - A string slice containing the text of one or more `.con` frames.
    pub fn new(file_contents: &'a str) -> Self {
        ConFrameIterator {
            lines: MemchrLines::new(file_contents),
        }
    }

    /// Bulk-skips `n` lines from the shared memchr cursor.
    fn advance_lines(&mut self, n: usize) -> Result<(), error::ParseError> {
        self.lines.clear_peek();
        for _ in 0..n {
            let rest = &self.lines.bytes[self.lines.pos..];
            match memchr::memchr(b'\n', rest) {
                Some(pos) => self.lines.pos += pos + 1,
                None => {
                    if rest.is_empty() {
                        return Err(error::ParseError::IncompleteFrame);
                    }
                    self.lines.pos = self.lines.bytes.len();
                    return Err(error::ParseError::IncompleteFrame);
                }
            }
        }
        Ok(())
    }

    /// One line from the shared cursor (same as full-parse path).
    fn read_line_str(&mut self) -> Option<&'a str> {
        self.lines.clear_peek();
        self.lines.next_line()
    }

    /// memchr-backed equivalent of [`Self::forward`]. Skips the next
    /// frame without fully parsing its atom data. Shares the same line
    /// cursor as [`Iterator::next`], so skip and full parse interleave safely.
    pub fn forward_fast(&mut self) -> Option<Result<(), error::ParseError>> {
        self.lines.clear_peek();
        if self.lines.pos >= self.lines.bytes.len() {
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
        self.lines.clear_peek();
        loop {
            let rest = &self.lines.bytes[self.lines.pos..];
            if rest.is_empty() {
                break;
            }
            let next_eol = memchr::memchr(b'\n', rest);
            let line = match next_eol {
                Some(pos) => &rest[..pos],
                None => rest,
            };
            let is_blank = line.iter().all(|b| matches!(b, b' ' | b'\t' | b'\r'));
            if !is_blank {
                break;
            }
            // Consume the blank separator and the section block.
            self.lines.pos += next_eol.map(|p| p + 1).unwrap_or(rest.len());
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
        // Prefer the shared memchr skip path (same cursor as full parse).
        self.forward_fast()
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
            let line = self.lines.peek_line()?;
            line.as_ptr() as usize - base
        };
        let frame = match self.next()? {
            Ok(f) => f,
            Err(e) => return Some(Err(e)),
        };
        let end = match self.lines.peek_line() {
            Some(line) => line.as_ptr() as usize - base,
            None => file_contents.len(),
        };
        debug_assert!(end >= start && end <= file_contents.len());
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
        self.lines.peek_line()?;
        // Otherwise, attempt to parse the next frame from the available lines.
        let mut frame = match parse_single_frame(&mut self.lines) {
            Ok(f) => f,
            Err(e) => return Some(Err(e)),
        };
        // Optional sections mutate AoS; only re-sync section SoA when needed.
        // Coords-only frames already have positions/ids/masses fully assembled
        // (no O(N) post-scan for absent velocities).
        let sections = match parse_declared_sections(
            &mut self.lines,
            &mut frame.header,
            &mut frame.atom_data,
        ) {
            Ok(n) => n,
            Err(e) => return Some(Err(e)),
        };
        if sections > 0 {
            frame.sync_arrays_from_atom_data();
        }
        Some(Ok(frame))
    }
}

#[cfg(test)]
mod lean_positions_tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn lean_positions_match_full_frame_on_fixtures() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/test");
        for name in ["cuh2.con", "tiny_cuh2.con", "tiny_multi_cuh2.con"] {
            let p = root.join(name);
            let text = std::fs::read_to_string(&p).unwrap_or_else(|_| panic!("fixture {name}"));
            let full: Vec<_> = ConFrameIterator::new(&text)
                .map(|r| r.expect("full"))
                .collect();
            let coords = read_frame_coordinates_str(&text).expect("coords-only");
            assert_eq!(coords.len(), full.len(), "{name} frame count");
            for (i, (pos, fr)) in coords.iter().zip(full.iter()).enumerate() {
                assert_eq!(pos.nrows(), fr.positions.nrows(), "{name} f{i} nrows");
                assert_eq!(pos.ncols(), 3);
                for r in 0..pos.nrows() {
                    let want = fr.positions.as_f64_row(r);
                    assert_eq!(
                        [pos[[r, 0]], pos[[r, 1]], pos[[r, 2]]],
                        want,
                        "{name} f{i} atom {r}"
                    );
                }
            }
        }
    }

    #[test]
    fn lean_positions_skips_vel_section_and_matches_coords() {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test/tiny_cuh2_vel_forces.con");
        let text = std::fs::read_to_string(&p).expect("fixture");
        let full = ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        let coords = read_frame_coordinates_str(&text).expect("coords-only");
        assert_eq!(coords.len(), 1);
        let pos = &coords[0];
        assert_eq!(pos.nrows(), full.atom_data.len());
        for r in 0..pos.nrows() {
            let want = full.positions.as_f64_row(r);
            assert_eq!([pos[[r, 0]], pos[[r, 1]], pos[[r, 2]]], want);
        }
        // full frame still has section data; coords-only path returns matrices only
        assert!(full.atom_data.iter().any(|a| a.force.is_some() || a.velocity.is_some()));
    }

    #[test]
    fn read_all_positions_alias_matches_read_frame_coordinates() {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/test/tiny_cuh2.con");
        let a = read_frame_coordinates(&p).expect("canonical");
        let b = read_all_positions(&p).expect("alias");
        assert_eq!(a, b);
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
/// Byte-size gate for Rayon multi-frame parse. Avoids an extra O(n) frame-count
/// scan: phase-1 of [`parse_frames_parallel`] already walks boundaries when we
/// choose parallel. Below this size, sequential parse wins on small multi-frame
/// files (pool scheduling overhead).
#[cfg(feature = "parallel")]
pub const PARALLEL_BYTES_THRESHOLD: usize = 48 * 1024;

pub fn read_all_frames(path: &Path) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str()?;
    #[cfg(feature = "parallel")]
    {
        if text.len() >= PARALLEL_BYTES_THRESHOLD {
            let parts = parse_frames_parallel(text);
            let mut frames = Vec::with_capacity(parts.len());
            for r in parts {
                frames.push(r?);
            }
            return Ok(frames);
        }
    }
    let iter = ConFrameIterator::new(text);
    let frames: Result<Vec<_>, _> = iter.collect();
    Ok(frames?)
}

/// Load **only** Cartesian coordinates: one owned `(N, 3)` f64 matrix per frame.
///
/// This is **not** a faster substitute for [`read_all_frames`]. It returns a
/// different product (raw coordinate matrices, no symbols / fixed flags /
/// velocities / Python `Atom` objects). Use it when the pipeline truly needs
/// only `xyz`. For anything else, use [`read_all_frames`] or
/// [`ConFrameIterator`].
///
/// Shares the same coordinate float kernel as full-frame parse; optional
/// sections are structure-skipped (not decoded into memory).
pub fn read_frame_coordinates(
    path: &Path,
) -> Result<Vec<ndarray::Array2<f64>>, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str()?;
    read_frame_coordinates_str(text)
}

/// Like [`read_frame_coordinates`] on an already-loaded UTF-8 buffer.
pub fn read_frame_coordinates_str(
    text: &str,
) -> Result<Vec<ndarray::Array2<f64>>, Box<dyn std::error::Error>> {
    #[cfg(feature = "parallel")]
    {
        if text.len() >= PARALLEL_BYTES_THRESHOLD {
            let parts = parse_positions_parallel(text);
            let mut out = Vec::with_capacity(parts.len());
            for r in parts {
                out.push(r?);
            }
            return Ok(out);
        }
    }
    let mut lines = MemchrLines::new(text);
    let mut out = Vec::new();
    while lines.peek_line().is_some() {
        out.push(parse_single_frame_positions(&mut lines)?);
    }
    Ok(out)
}

/// Compatibility alias for [`read_frame_coordinates`]. Prefer the clearer name.
#[inline]
pub fn read_all_positions(
    path: &Path,
) -> Result<Vec<ndarray::Array2<f64>>, Box<dyn std::error::Error>> {
    read_frame_coordinates(path)
}

/// Compatibility alias for [`read_frame_coordinates_str`].
#[inline]
pub fn read_all_positions_str(
    text: &str,
) -> Result<Vec<ndarray::Array2<f64>>, Box<dyn std::error::Error>> {
    read_frame_coordinates_str(text)
}

/// Parallel positions-only multi-frame parse (same boundary walk as full-frame).
#[cfg(feature = "parallel")]
pub fn parse_positions_parallel(
    file_contents: &str,
) -> Vec<Result<ndarray::Array2<f64>, error::ParseError>> {
    use rayon::prelude::*;
    let mut boundaries: Vec<usize> = Vec::new();
    let mut scanner = ConFrameIterator::new(file_contents);
    loop {
        scanner.lines.clear_peek();
        let start = scanner.lines.pos;
        if start >= scanner.lines.bytes.len() {
            break;
        }
        boundaries.push(start);
        match scanner.forward_fast() {
            Some(Ok(())) => {}
            Some(Err(_)) | None => break,
        }
    }
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
            let mut lines = MemchrLines::new(chunk);
            parse_single_frame_positions(&mut lines)
        })
        .collect()
}

/// Count frames without building atom payloads (uses [`ConFrameIterator::forward_fast`]
/// when possible, else [`ConFrameIterator::forward`]).
///
/// Prefer this over `read_all_frames(...).len()` when only the frame count is needed.
pub fn count_frames(path: &Path) -> Result<usize, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str()?;
    let mut n = 0usize;
    let mut iter = ConFrameIterator::new(text);
    loop {
        match iter.forward_fast() {
            Some(Ok(())) => n += 1,
            Some(Err(e)) => return Err(Box::new(e)),
            None => break,
        }
    }
    Ok(n)
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
        scanner.lines.clear_peek();
        let start = scanner.lines.pos;
        if start >= scanner.lines.bytes.len() {
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
