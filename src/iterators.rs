//=============================================================================
// The Public API - A clean iterator for users of our library
//=============================================================================

use crate::parser::{LineStream, parse_declared_sections};
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
    /// When the buffer was not already a `&str`, header lines are checked
    /// as they are tokenized. Coordinate rows stay on the byte parser.
    check_utf8: bool,
    utf8_bad: bool,
    /// 1-based index of the last line produced by [`Self::read_one`], including
    /// a line rejected as UTF-8. 0 before that.
    line_no: u32,
}

impl<'a> MemchrLines<'a> {
    pub fn new(text: &'a str) -> Self {
        Self::from_parts(text.as_bytes(), false)
    }

    /// Cursor over bytes that are not yet known to be UTF-8.
    ///
    /// ASCII coordinate rows are accepted by the numeric scan. Text lines
    /// are validated when they are materialized, so there is no separate
    /// whole-buffer UTF-8 pass.
    pub fn from_bytes(bytes: &'a [u8]) -> Self {
        Self::from_parts(bytes, true)
    }

    fn from_parts(bytes: &'a [u8], check_utf8: bool) -> Self {
        Self {
            bytes,
            pos: 0,
            peeked: None,
            check_utf8,
            utf8_bad: false,
            line_no: 0,
        }
    }

    /// 1-based index of the last line read, including a line that is only peeked.
    #[inline]
    pub fn line_no(&self) -> u32 {
        self.line_no
    }

    #[inline]
    fn read_one(&mut self) -> Option<&'a str> {
        if self.utf8_bad || self.pos >= self.bytes.len() {
            return None;
        }
        let rest = &self.bytes[self.pos..];
        let (line_bytes, advance) = match memchr::memchr(b'\n', rest) {
            Some(i) => (&rest[..i], i + 1),
            None => (rest, rest.len()),
        };
        let trimmed = if line_bytes.last() == Some(&b'\r') {
            &line_bytes[..line_bytes.len() - 1]
        } else {
            line_bytes
        };
        if self.check_utf8 {
            match std::str::from_utf8(trimmed) {
                Ok(s) => {
                    self.accept_line(advance);
                    Some(s)
                }
                Err(_) => {
                    // Stay on the rejected line. Moving past it makes a
                    // whitespace tail look like a clean end of file.
                    // The line number still names this line.
                    self.line_no = self.line_no.saturating_add(1);
                    self.utf8_bad = true;
                    None
                }
            }
        } else {
            self.accept_line(advance);
            // SAFETY: source was `&str`; line is a UTF-8 prefix cut on ASCII `\n`/`\r`.
            Some(unsafe { std::str::from_utf8_unchecked(trimmed) })
        }
    }

    #[inline]
    fn accept_line(&mut self, advance: usize) {
        self.pos += advance;
        self.line_no = self.line_no.saturating_add(1);
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
            self.line_no = self.line_no.saturating_sub(1);
        }
    }

    fn utf8_error(&self) -> Option<error::ParseError> {
        self.utf8_bad.then(invalid_utf8)
    }

    /// Keep `err` unless this cursor already rejected a line as UTF-8.
    fn prefer_utf8(&self, err: error::ParseError) -> error::ParseError {
        if self.utf8_bad { invalid_utf8() } else { err }
    }
}

fn invalid_utf8() -> error::ParseError {
    error::ParseError::ValidationError("invalid UTF-8".into())
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
    #[inline]
    fn next_coord_row(
        &mut self,
        spec_version: u32,
        default_id: u64,
    ) -> Result<([f64; 3], [bool; 3], u64), crate::error::ParseError> {
        if let Some(p) = self.peeked.take() {
            return crate::parser::parse_coord_row_at(p.as_bytes(), 0, spec_version, default_id)
                .map(|(row, _)| row);
        }
        // The failing row is this line even when the numeric scan returns Err
        // before the cursor moves.
        self.line_no = self.line_no.saturating_add(1);
        let (row, pos) =
            crate::parser::parse_coord_row_at(self.bytes, self.pos, spec_version, default_id)?;
        self.pos = pos;
        Ok(row)
    }
    fn remainder_is_whitespace(&mut self) -> bool {
        if self.utf8_bad {
            return false;
        }
        if let Some(line) = self.peek_line()
            && !line.trim().is_empty()
        {
            return false;
        }
        // `peek_line` may have rejected a line. That is a decode error,
        // including when every byte after it is ASCII whitespace.
        if self.utf8_bad {
            return false;
        }
        self.bytes[self.pos..]
            .iter()
            .all(|b| b.is_ascii_whitespace())
    }
    fn blank_line_opens_section(&mut self) -> bool {
        // `peek_line` has already moved `pos` to the line after the peek.
        let Some(peeked) = self.peeked else {
            return false;
        };
        if !peeked.trim().is_empty() {
            return false;
        }
        match probe_section(&self.bytes[self.pos..]) {
            SectionProbe::Opens => true,
            SectionProbe::Closed => false,
            // Leave the rejected bytes on the cursor. `prefer_utf8` then
            // reports the decode error instead of a missing section.
            SectionProbe::InvalidUtf8 => {
                self.utf8_bad = true;
                false
            }
        }
    }

    fn blank_opens_velocity_block(&mut self) -> bool {
        match self.peek_line() {
            Some(line) if line.trim().is_empty() => self.blank_line_opens_section(),
            _ => true,
        }
    }
}

fn split_raw_line(bytes: &[u8]) -> Option<(&[u8], &[u8])> {
    if bytes.is_empty() {
        return None;
    }
    match memchr::memchr(b'\n', bytes) {
        Some(i) => Some((&bytes[..i], &bytes[i + 1..])),
        None => Some((bytes, &[])),
    }
}

fn strip_cr(line: &[u8]) -> &[u8] {
    if line.last() == Some(&b'\r') {
        &line[..line.len() - 1]
    } else {
        line
    }
}

enum SectionProbe {
    Opens,
    Closed,
    InvalidUtf8,
}

/// A blank line opens a section when the next line is a symbol and the
/// line after that is a component label (CON-file.5, CON-header.4).
fn probe_section(after_blank: &[u8]) -> SectionProbe {
    let Some((raw1, after1)) = split_raw_line(after_blank) else {
        return SectionProbe::Closed;
    };
    let line1 = strip_cr(raw1);
    if line1.iter().all(|b| matches!(b, b' ' | b'\t')) {
        return SectionProbe::Closed;
    }
    let Ok(text1) = std::str::from_utf8(line1) else {
        return SectionProbe::InvalidUtf8;
    };
    if text1.trim_start().starts_with('{') {
        return SectionProbe::Closed;
    }
    let Some((raw2, _)) = split_raw_line(after1) else {
        return SectionProbe::Closed;
    };
    let Ok(text2) = std::str::from_utf8(strip_cr(raw2)) else {
        return SectionProbe::InvalidUtf8;
    };
    if crate::parser::line_has_component_label(text2) {
        SectionProbe::Opens
    } else {
        SectionProbe::Closed
    }
}

fn blank_opens_section(after_blank: &[u8]) -> bool {
    matches!(probe_section(after_blank), SectionProbe::Opens)
}

/// An iterator that lazily parses simulation frames from a `.con` or `.convel`
/// file's contents.
///
/// This struct wraps a memchr line cursor over the file buffer and, upon each
/// iteration, attempts to parse a complete `ConFrame`. A blank line after the
/// coordinates is a velocity section only when it begins a complete velocity
/// block. Otherwise that line is line 1 of the next frame, and it may be empty.
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

    /// Like [`Self::new`] for a buffer that has not been UTF-8 validated.
    ///
    /// Text lines are checked as they are tokenized. Numeric rows reject a
    /// non-ASCII byte during the fused parse, which is the UTF-8 check for
    /// those lines.
    pub fn from_bytes(bytes: &'a [u8]) -> Self {
        ConFrameIterator {
            lines: MemchrLines::from_bytes(bytes),
        }
    }

    /// Bulk-skips `n` lines from the shared memchr cursor.
    ///
    /// A final line with no trailing newline still counts when it is the
    /// last line this call needs and its bytes are present. The full
    /// parser accepts that line. Further lines after it are missing.
    fn advance_lines(&mut self, n: usize) -> Result<(), error::ParseError> {
        self.lines.clear_peek();
        for i in 0..n {
            let rest = &self.lines.bytes[self.lines.pos..];
            match memchr::memchr(b'\n', rest) {
                Some(pos) => {
                    self.lines.pos += pos + 1;
                    self.lines.line_no = self.lines.line_no.saturating_add(1);
                }
                None => {
                    if rest.is_empty() {
                        return Err(error::ParseError::IncompleteFrame);
                    }
                    self.lines.pos = self.lines.bytes.len();
                    // Count the unterminated line so a later located error
                    // names it. It satisfies this skip only when it is the
                    // last line still required; the full parser accepts it.
                    self.lines.line_no = self.lines.line_no.saturating_add(1);
                    if i + 1 == n {
                        return Ok(());
                    }
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
            Some(line) => match crate::parser::parse_count_line(line, 1) {
                Ok(v) => v[0],
                Err(e) => return Some(Err(e)),
            },
            None => return Some(Err(error::ParseError::IncompleteHeader)),
        };
        if natm_types == 0 {
            // Lines 8 and 9 are whitespace, or absent at EOF. Do not scan
            // for coordinates or a legacy velocity block (CON-count.1).
            return Some(crate::parser::read_zero_atom_tail(|| self.read_line_str()));
        }
        // Line 8: natms_per_type.
        let natms_per_type: Vec<usize> = match self.read_line_str() {
            Some(line) => match crate::parser::parse_count_line(line, natm_types) {
                Ok(v) => v,
                Err(e) => return Some(Err(e)),
            },
            None => return Some(Err(error::ParseError::IncompleteHeader)),
        };
        if natms_per_type.iter().any(|n| *n == 0) {
            return Some(Err(error::ParseError::InvalidCount(
                "each per-type count must be >= 1".into(),
            )));
        }
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
            let after = match next_eol {
                Some(pos) => &rest[pos + 1..],
                None => &[][..],
            };
            // A blank line and then only whitespace is the end of the file,
            // not a section (CON-frame.5).
            if after.iter().all(|b| b.is_ascii_whitespace()) {
                self.lines.pos = self.lines.bytes.len();
                break;
            }
            // A blank that does not begin a section is line 1 of the next
            // frame, including an empty user line (CON-frame.7, CON-header.4).
            if !blank_opens_section(after) {
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

    /// Byte offset of the next frame start in the buffer passed to [`Self::new`].
    pub fn byte_pos(&self) -> usize {
        self.lines.pos
    }

    /// Skip `n` frames without parsing atom data. Returns how many were skipped.
    /// Named `skip_frames` so it does not collide with [`Iterator::skip`].
    pub fn skip_frames(&mut self, n: usize) -> Result<usize, error::ParseError> {
        self.skip_frames_counted(n).map_err(|(_, err)| err)
    }

    /// Like [`Self::skip_frames`]. The error's first field is how many frames
    /// were skipped before the failure, which is the 0-based index of the
    /// failing frame when the iterator started at frame 0.
    pub(crate) fn skip_frames_counted(
        &mut self,
        n: usize,
    ) -> Result<usize, (usize, error::ParseError)> {
        let mut skipped = 0usize;
        for _ in 0..n {
            match self.forward() {
                None => break,
                Some(Err(e)) => return Err((skipped, e)),
                Some(Ok(())) => skipped += 1,
            }
        }
        Ok(skipped)
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
    /// `Some(Err(ParseError::...))`. Invalid UTF-8 is a validation error, not
    /// the end of the stream.
    fn next(&mut self) -> Option<Self::Item> {
        // A line rejected earlier in this cursor (for example while probing
        // for a velocity block) must not be reported as a clean EOF.
        if let Some(err) = self.lines.utf8_error() {
            return Some(Err(err));
        }
        // Trailing whitespace after the last complete frame is not a frame
        // (CON-frame.1, D2). An empty line that is followed by more text is
        // line 1 of the next frame (CON-frame.7).
        if self.lines.remainder_is_whitespace() {
            if let Some(err) = self.lines.utf8_error() {
                return Some(Err(err));
            }
            while self.lines.next_line().is_some() {}
            return None;
        }
        if let Some(err) = self.lines.utf8_error() {
            return Some(Err(err));
        }
        // Otherwise, attempt to parse the next frame from the available lines.
        let mut frame = match crate::parser::parse_single_frame_ls(&mut self.lines) {
            Ok(f) => f,
            Err(e) => return Some(Err(self.lines.prefer_utf8(e))),
        };
        // Optional sections mutate AoS; only re-sync section SoA when needed.
        // Plain .con assembly already filled positions/ids/masses (no O(N)
        // post-scan when no velocity/force sections were applied).
        let sections =
            match parse_declared_sections(&mut self.lines, &mut frame.header, &mut frame.atom_data)
            {
                Ok(n) => n,
                // A section line that failed UTF-8 makes `next_line` return
                // `None`. That must not surface as `IncompleteSection`.
                Err(e) => return Some(Err(self.lines.prefer_utf8(e))),
            };
        if sections > 0 {
            frame.sync_arrays_from_atom_data();
        }
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
        let has_vel = fr.atom_data.iter().any(|a| a.velocity().is_some());
        let has_frc = fr.atom_data.iter().any(|a| a.force().is_some());
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
            if let Some(v) = a.velocity() {
                assert_eq!(v, fr.velocities.as_f64_row(i));
            }
            if let Some(f) = a.force() {
                assert_eq!(f, fr.forces.as_f64_row(i));
            }
        }
    }

    /// After SoA-primary parse, section sync must not require rewriting positions
    /// (nrows already equals N); forces SoA still filled from AoS.
    #[test]
    fn sync_skips_pos_when_nrows_matches_keeps_force_soa() {
        let p =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/test/tiny_cuh2_forces.con");
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
            fr2.atom_data[0].force().expect("force")
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
pub(crate) const PARALLEL_BYTES_THRESHOLD: usize = 48 * 1024;

pub fn read_all_frames(path: &Path) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    read_all_frames_with_threads(path, None)
}

/// Collect every frame from `text`.
///
/// `num_threads` is `None` for the automatic policy (Rayon when the
/// `parallel` feature is on and the buffer is at least
/// [`PARALLEL_BYTES_THRESHOLD`]), `Some(1)` for a sequential iterator,
/// and `Some(n)` with `n >= 2` for an explicit Rayon pool. Builds
/// without `parallel` always parse sequentially.
pub fn frames_from_text(
    text: &str,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, error::ParseError> {
    #[cfg(feature = "parallel")]
    {
        let use_parallel = match num_threads {
            Some(1) => false,
            Some(n) if n >= 2 => true,
            // None and Some(0): automatic policy.
            _ => text.len() >= PARALLEL_BYTES_THRESHOLD,
        };
        if use_parallel {
            let pool = num_threads.filter(|&n| n >= 2);
            let parts = parse_frames_parallel_with_threads(text, pool);
            let mut frames = Vec::with_capacity(parts.len());
            for r in parts {
                frames.push(r?);
            }
            return Ok(frames);
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = num_threads;
    }
    ConFrameIterator::new(text).collect()
}

/// Like [`read_all_frames`], with an explicit worker count.
///
/// `None` is the automatic policy used by [`read_all_frames`]. `Some(1)`
/// forces sequential parse. `Some(n)` with `n >= 2` pins a Rayon pool
/// (ignored when the `parallel` feature is off).
pub fn read_all_frames_with_threads(
    path: &Path,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    match contents {
        crate::compression::FileContents::Owned(text) => Ok(frames_from_text(&text, num_threads)?),
        // Mapped bytes are not pre-validated. The cursor checks UTF-8 on
        // text lines and the coordinate scan rejects non-ASCII tokens.
        crate::compression::FileContents::Mapped(map) => Ok(frames_from_bytes(&map, num_threads)?),
    }
}

/// [`frames_from_text`] for bytes that may not be UTF-8 yet.
pub fn frames_from_bytes(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, error::ParseError> {
    #[cfg(feature = "parallel")]
    {
        let use_parallel = match num_threads {
            Some(1) => false,
            Some(n) if n >= 2 => true,
            _ => bytes.len() >= PARALLEL_BYTES_THRESHOLD,
        };
        if use_parallel {
            let pool = num_threads.filter(|&n| n >= 2);
            let parts = parse_frames_parallel_bytes(bytes, pool);
            let mut frames = Vec::with_capacity(parts.len());
            for r in parts {
                frames.push(r?);
            }
            return Ok(frames);
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = num_threads;
    }
    let mut frames = Vec::new();
    for r in ConFrameIterator::from_bytes(bytes) {
        frames.push(r?);
    }
    Ok(frames)
}

#[cfg(feature = "parallel")]
fn parse_frames_parallel_bytes(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    use rayon::prelude::*;

    let mut scanner = ConFrameIterator::from_bytes(bytes);
    let mut boundaries = Vec::new();
    loop {
        scanner.lines.clear_peek();
        let start = scanner.lines.pos;
        // Whitespace after the final frame does not open another frame.
        if start >= bytes.len() || bytes[start..].iter().all(u8::is_ascii_whitespace) {
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
                    bytes.len()
                };
                let mut iter = ConFrameIterator::from_bytes(&bytes[start..end]);
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
            match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
                Ok(pool) => pool.install(parse_chunks),
                Err(_) => parse_chunks(),
            }
        }
    }
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

/// Skip `index` frames (no atom parse), then parse the next one.
///
/// `index == 0` is [`read_first_frame`]. Out of range is an error.
pub fn read_nth_frame(
    path: &Path,
    index: usize,
) -> Result<types::ConFrame, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str()?;
    read_nth_frame_from_text(text, index)
}

/// Same as [`read_nth_frame`] on an already-loaded buffer.
pub fn read_nth_frame_from_text(
    text: &str,
    index: usize,
) -> Result<types::ConFrame, Box<dyn std::error::Error>> {
    let mut iter = ConFrameIterator::new(text);
    let skipped = iter.skip_frames(index)?;
    if skipped < index {
        return Err(format!("frame {index} out of range (only {skipped} frames)").into());
    }
    match iter.next() {
        Some(Ok(frame)) => Ok(frame),
        Some(Err(e)) => Err(Box::new(e)),
        None => Err(format!("frame {index} out of range").into()),
    }
}

/// Reads all frames using the checked `.rcidx` sidecar next to `path`.
///
/// Uncompressed input uses (and refreshes) `path.rcidx`; compressed
/// input is scanned in memory each time. UTF-8 is validated in
/// newline-aligned slices.
#[cfg(feature = "parallel")]
pub fn read_all_frames_indexed(
    path: &Path,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let text = contents.as_str_sliced()?;
    let idx = match contents {
        crate::compression::FileContents::Mapped(_) => {
            crate::frame_index::load_or_build(path, text, true)?
        }
        crate::compression::FileContents::Owned(_) => {
            let on_disk = std::fs::metadata(path)?.len();
            crate::frame_index::load_or_build(path, text, on_disk == text.len() as u64)?
        }
    };
    let offs: Vec<usize> = idx.offsets.iter().map(|&o| o as usize).collect();
    parse_frames_at_offsets(text, &offs, num_threads)
        .into_iter()
        .map(|r| r.map_err(|e| Box::new(e) as Box<dyn std::error::Error>))
        .collect()
}

/// I/O, UTF-8, or a located parse failure while loading a path.
#[derive(Debug)]
pub enum LoadError {
    Io(std::io::Error),
    Utf8(std::str::Utf8Error),
    Parse(error::LocatedParseError),
    /// The path opened and decoded, and it held no frame.
    Empty,
}

impl std::fmt::Display for LoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LoadError::Io(e) => write!(f, "{e}"),
            LoadError::Utf8(e) => write!(f, "{e}"),
            LoadError::Parse(e) => write!(f, "{e}"),
            LoadError::Empty => write!(f, "no frames found in file"),
        }
    }
}

impl std::error::Error for LoadError {}

fn load_error_from_box(err: Box<dyn std::error::Error>) -> LoadError {
    if let Some(io) = err.downcast_ref::<std::io::Error>() {
        return LoadError::Io(std::io::Error::new(io.kind(), io.to_string()));
    }
    LoadError::Io(std::io::Error::other(err.to_string()))
}

fn load_text(path: &Path) -> Result<crate::compression::FileContents, LoadError> {
    crate::compression::read_file_contents(path).map_err(load_error_from_box)
}

/// 1-based line number of the line that contains `byte`.
#[cfg(feature = "parallel")]
fn file_line_at(text: &str, byte: usize) -> u32 {
    let end = byte.min(text.len());
    1 + text.as_bytes()[..end]
        .iter()
        .filter(|&&b| b == b'\n')
        .count() as u32
}

/// Collect every frame, keeping the line and frame index of the first error.
pub fn frames_from_text_located(
    text: &str,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, error::LocatedParseError> {
    #[cfg(feature = "parallel")]
    {
        let use_parallel = match num_threads {
            Some(1) => false,
            Some(n) if n >= 2 => true,
            _ => text.len() >= PARALLEL_BYTES_THRESHOLD,
        };
        if use_parallel {
            let pool = num_threads.filter(|&n| n >= 2);
            return collect_parallel_located(text, pool);
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = num_threads;
    }
    let mut frames = Vec::new();
    let mut iter = ConFrameIterator::new(text);
    let mut index = 0u64;
    while let Some(item) = iter.next() {
        match item {
            Ok(frame) => {
                frames.push(frame);
                index += 1;
            }
            Err(e) => {
                return Err(error::LocatedParseError::new(
                    e,
                    iter.lines.line_no(),
                    index,
                ));
            }
        }
    }
    Ok(frames)
}

/// Read every frame from `path`, with the line and frame index of the first error.
pub fn read_all_frames_located(
    path: &Path,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, LoadError> {
    let contents = load_text(path)?;
    let text = contents.as_str().map_err(LoadError::Utf8)?;
    frames_from_text_located(text, num_threads).map_err(LoadError::Parse)
}

/// Read the first frame from `path`, with a line number on failure.
pub fn read_first_frame_located(path: &Path) -> Result<types::ConFrame, LoadError> {
    let contents = load_text(path)?;
    let text = contents.as_str().map_err(LoadError::Utf8)?;
    let mut iter = ConFrameIterator::new(text);
    match iter.next() {
        Some(Ok(frame)) => Ok(frame),
        Some(Err(e)) => Err(LoadError::Parse(error::LocatedParseError::new(
            e,
            iter.lines.line_no(),
            0,
        ))),
        None => Err(LoadError::Empty),
    }
}

/// Skip `index` frames, then parse one, with a line number on failure.
pub fn read_nth_frame_located(path: &Path, index: usize) -> Result<types::ConFrame, LoadError> {
    let contents = load_text(path)?;
    let text = contents.as_str().map_err(LoadError::Utf8)?;
    let mut iter = ConFrameIterator::new(text);
    match iter.skip_frames_counted(index) {
        Ok(skipped) if skipped == index => {}
        Ok(skipped) => {
            return Err(LoadError::Parse(error::LocatedParseError::new(
                error::ParseError::IncompleteFrame,
                iter.lines.line_no(),
                skipped as u64,
            )));
        }
        Err((failed_at, e)) => {
            return Err(LoadError::Parse(error::LocatedParseError::new(
                e,
                iter.lines.line_no(),
                failed_at as u64,
            )));
        }
    }
    match iter.next() {
        Some(Ok(frame)) => Ok(frame),
        Some(Err(e)) => Err(LoadError::Parse(error::LocatedParseError::new(
            e,
            iter.lines.line_no(),
            index as u64,
        ))),
        None => Err(LoadError::Parse(error::LocatedParseError::new(
            error::ParseError::IncompleteFrame,
            iter.lines.line_no(),
            index as u64,
        ))),
    }
}

/// Frame start byte offsets via [`ConFrameIterator::forward_fast`] (no atom parse).
/// Stops at the first skip error (that start is still included).
pub fn frame_start_offsets(file_contents: &str) -> Vec<usize> {
    let mut boundaries = Vec::new();
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
    boundaries
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
    // Phase 1: skip walk (no atom parse) for frame start offsets.
    let boundaries = frame_start_offsets(file_contents);
    parse_frames_at_offsets(file_contents, &boundaries, num_threads)
}

/// Phase 2 of [`parse_frames_parallel_with_threads`]: parse the frames
/// that start at `boundaries` (strictly increasing byte offsets into
/// `file_contents`; frame `i` ends where frame `i + 1` starts).
///
/// Offsets may come from [`frame_start_offsets`] or from a checked
/// [`crate::frame_index::FrameIndex`]. Results are ordered by frame index.
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_at_offsets(
    file_contents: &str,
    boundaries: &[usize],
    num_threads: Option<usize>,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    use rayon::prelude::*;

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
            match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
                Ok(pool) => pool.install(parse_chunks),
                Err(_) => parse_chunks(),
            }
        }
    }
}

/// Parallel parse that keeps the file line of the first error.
/// Workers return the error. They do not write thread-local error state.
#[cfg(feature = "parallel")]
fn collect_parallel_located(
    file_contents: &str,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, error::LocatedParseError> {
    use rayon::prelude::*;

    let boundaries = frame_start_offsets(file_contents);
    let parse_chunks = || -> Result<Vec<types::ConFrame>, error::LocatedParseError> {
        let num_frames = boundaries.len();
        let parts: Vec<Result<types::ConFrame, error::LocatedParseError>> = (0..num_frames)
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
                    Some(Ok(frame)) => Ok(frame),
                    Some(Err(e)) => {
                        let local = iter.lines.line_no();
                        let base = file_line_at(file_contents, start);
                        let cursor = if local == 0 { base } else { base + local - 1 };
                        Err(error::LocatedParseError::new(e, cursor, i as u64))
                    }
                    None => Err(error::LocatedParseError::new(
                        error::ParseError::IncompleteFrame,
                        file_line_at(file_contents, start),
                        i as u64,
                    )),
                }
            })
            .collect();
        let mut frames = Vec::with_capacity(parts.len());
        for part in parts {
            frames.push(part?);
        }
        Ok(frames)
    };
    match num_threads {
        None => parse_chunks(),
        Some(n) => {
            let n = n.max(1);
            match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
                Ok(pool) => pool.install(parse_chunks),
                Err(_) => parse_chunks(),
            }
        }
    }
}

#[cfg(all(test, feature = "parallel"))]
mod parallel_strong_scale_tests {
    use super::*;
    use std::path::PathBuf;

    fn multi_frame_fixture() -> String {
        let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/test/tiny_cuh2.con");
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
