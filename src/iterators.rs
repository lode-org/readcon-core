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
    /// Absolute offsets of every `\n`. Set only for a frame-start scan.
    /// `None` keeps the per-line `memchr` path used by a full parse.
    newlines: Option<Vec<usize>>,
    /// Index of the line that starts at `pos` when `newlines` is in use.
    line_no: usize,
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
            newlines: None,
            line_no: 0,
        }
    }

    #[inline]
    fn read_one(&mut self) -> Option<&'a str> {
        if self.newlines.is_some() {
            return self.read_one_indexed();
        }
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
                    self.pos += advance;
                    Some(s)
                }
                Err(_) => {
                    // Stay on the rejected line. Moving past it makes a
                    // whitespace tail look like a clean end of file.
                    self.utf8_bad = true;
                    None
                }
            }
        } else {
            self.pos += advance;
            // SAFETY: source was `&str`; line is a UTF-8 prefix cut on ASCII `\n`/`\r`.
            Some(unsafe { std::str::from_utf8_unchecked(trimmed) })
        }
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
            if let Some(nl) = self.newlines.as_deref() {
                self.line_no = line_no_for_pos(nl, self.bytes.len(), start);
            }
        }
    }

    /// One line from the precomputed newline index.
    ///
    /// The cursor must sit on a line start (or at the end). The bytes of
    /// the line are the same slice `memchr` would return, including a line
    /// whose body crosses a chunk boundary: only the `\n` is indexed.
    fn read_one_indexed(&mut self) -> Option<&'a str> {
        if self.utf8_bad || self.pos >= self.bytes.len() {
            return None;
        }
        let len = self.bytes.len();
        let line_no = {
            let nl = self.newlines.as_deref().unwrap();
            if self.pos == line_start_pos(nl, len, self.line_no) {
                self.line_no
            } else {
                line_no_for_pos(nl, len, self.pos)
            }
        };
        let Some(span) = indexed_span(self.newlines.as_deref().unwrap(), self.bytes, line_no)
        else {
            return None;
        };
        let trimmed = &self.bytes[span.start..span.content_end];
        if self.check_utf8 {
            match std::str::from_utf8(trimmed) {
                Ok(s) => {
                    self.pos = span.next_pos;
                    self.line_no = line_no + 1;
                    Some(s)
                }
                Err(_) => {
                    self.utf8_bad = true;
                    self.line_no = line_no;
                    None
                }
            }
        } else {
            self.pos = span.next_pos;
            self.line_no = line_no + 1;
            // SAFETY: source was `&str`; the span is a UTF-8 line cut on ASCII `\n`/`\r`.
            Some(unsafe { std::str::from_utf8_unchecked(trimmed) })
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

    /// Like [`Self::new`], but reading from byte `pos` of `file_contents`.
    ///
    /// `pos` must be 0 or follow a `\n`. The iterator keeps no state from
    /// earlier frames, so skipping from `pos` sees what a scan sees there.
    pub(crate) fn starting_at(file_contents: &'a str, pos: usize) -> Self {
        debug_assert!(pos == 0 || file_contents.as_bytes()[pos - 1] == b'\n');
        let mut it = Self::new(file_contents);
        it.lines.pos = pos;
        it
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
        if self.lines.newlines.is_some() {
            return self.advance_lines_indexed(n);
        }
        for i in 0..n {
            let rest = &self.lines.bytes[self.lines.pos..];
            match memchr::memchr(b'\n', rest) {
                Some(pos) => self.lines.pos += pos + 1,
                None => {
                    if rest.is_empty() {
                        return Err(error::ParseError::IncompleteFrame);
                    }
                    self.lines.pos = self.lines.bytes.len();
                    if i + 1 == n {
                        return Ok(());
                    }
                    return Err(error::ParseError::IncompleteFrame);
                }
            }
        }
        Ok(())
    }

    /// [`Self::advance_lines`] for `n` lines expected to end at `end`.
    ///
    /// When `end` follows a `\n` and exactly `n` newlines lie before it,
    /// the per-line search would stop at `end` too, so one vectorized
    /// count replaces it. Any other case takes the per-line search.
    fn advance_lines_to(&mut self, n: usize, end: Option<usize>) -> Result<(), error::ParseError> {
        // The newline index jumps by line count. `end` does not change
        // where that jump lands; it only shortcuts the per-line search.
        if self.lines.newlines.is_some() {
            return self.advance_lines(n);
        }
        self.lines.clear_peek();
        let pos = self.lines.pos;
        let bytes = self.lines.bytes;
        if let Some(end) = end
            && pos < end
            && end <= bytes.len()
            && bytes[end - 1] == b'\n'
            && memchr::memchr_iter(b'\n', &bytes[pos..end]).count() == n
        {
            self.lines.pos = end;
            return Ok(());
        }
        self.advance_lines(n)
    }

    /// [`Self::advance_lines`] using the stitched newline index.
    ///
    /// A missing line and a final line with no `\n` land on the same byte
    /// as the `memchr` loop. The index is not consulted for a full parse.
    fn advance_lines_indexed(&mut self, n: usize) -> Result<(), error::ParseError> {
        let len = self.lines.bytes.len();
        let step = {
            let nl = self.lines.newlines.as_deref().unwrap();
            let nlines = line_count(nl, len);
            let line_no = if self.lines.pos == line_start_pos(nl, len, self.lines.line_no) {
                self.lines.line_no
            } else {
                line_no_for_pos(nl, len, self.lines.pos)
            };
            if n == 0 {
                IndexStep::Stay(line_no)
            } else if line_no >= nlines {
                IndexStep::Missing(line_no)
            } else {
                match line_no.checked_add(n) {
                    Some(target) if target <= nlines => {
                        let pos = if target == nlines {
                            len
                        } else {
                            line_start_pos(nl, len, target)
                        };
                        IndexStep::Landed(target, pos)
                    }
                    _ => IndexStep::Short(nlines, len),
                }
            }
        };
        match step {
            IndexStep::Stay(line_no) => {
                self.lines.line_no = line_no;
                Ok(())
            }
            IndexStep::Missing(line_no) => {
                self.lines.line_no = line_no;
                Err(error::ParseError::IncompleteFrame)
            }
            IndexStep::Landed(line_no, pos) => {
                self.lines.line_no = line_no;
                self.lines.pos = pos;
                Ok(())
            }
            IndexStep::Short(line_no, pos) => {
                self.lines.line_no = line_no;
                self.lines.pos = pos;
                Err(error::ParseError::IncompleteFrame)
            }
        }
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
        self.forward_fast_to(None)
    }

    /// [`Self::forward_fast`] for a frame expected to end at byte `end`.
    ///
    /// The result and the new position are the same as without `end`.
    /// Line blocks that end exactly at `end` are counted, not searched.
    pub(crate) fn forward_fast_to(
        &mut self,
        end: Option<usize>,
    ) -> Option<Result<(), error::ParseError>> {
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
        if let Err(e) = self.advance_lines_to(coord_block_lines, end) {
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
            if let Err(e) = self.advance_lines_to(coord_block_lines, end) {
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
        let mut skipped = 0usize;
        for _ in 0..n {
            match self.forward() {
                None => break,
                Some(Err(e)) => return Err(e),
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

    /// [`Iterator::next`] plus the byte offset where the frame ends.
    pub(crate) fn next_with_end(
        &mut self,
    ) -> Option<Result<(types::ConFrame, usize), error::ParseError>> {
        let frame = match self.next()? {
            Ok(f) => f,
            Err(e) => return Some(Err(e)),
        };
        let end = match self.lines.peek_line() {
            Some(line) => line.as_ptr() as usize - self.lines.bytes.as_ptr() as usize,
            None => self.lines.pos,
        };
        Some(Ok((frame, end)))
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
/// The bytes are read into one owned buffer and parsed on the calling
/// thread. A worker pool runs only when [`read_all_frames_with_threads`]
/// is asked for two or more threads.
pub fn read_all_frames(path: &Path) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    read_all_frames_with_threads(path, None)
}

/// Collect every frame from `text`.
///
/// `None`, `Some(0)`, and `Some(1)` parse on the calling thread.
/// `Some(n)` with `n >= 2` uses a Rayon pool of that size when the
/// `parallel` feature is on. Builds without `parallel` always parse
/// sequentially.
pub fn frames_from_text(
    text: &str,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, error::ParseError> {
    #[cfg(feature = "parallel")]
    {
        if let Some(n) = num_threads.filter(|n| *n >= 2) {
            let parts = parse_frames_parallel_with_threads(text, Some(n));
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
/// `None`, `Some(0)`, and `Some(1)` parse on the calling thread.
/// `Some(n)` with `n >= 2` pins a Rayon pool when `parallel` is on.
/// The file is read into one owned buffer. The caller who wants a map
/// uses the streaming iterator.
pub fn read_all_frames_with_threads(
    path: &Path,
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, Box<dyn std::error::Error>> {
    let bytes = crate::compression::read_file_bytes(path)?;
    Ok(frames_from_bytes(&bytes, num_threads)?)
}

/// Positions of every frame, one row-major `f64` buffer.
///
/// The boundary walk records each frame start. Each worker then parses
/// only its span and writes that frame's coordinates at
/// `frame * n_atoms * 3`. The returned buffer is the only retained
/// coordinate storage. A file whose frames do not share one atom count
/// is rejected, because the buffer is rectangular.
pub struct PositionBlock {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub values: Vec<f64>,
}

pub fn read_positions_with_threads(
    path: &Path,
    num_threads: Option<usize>,
) -> Result<PositionBlock, Box<dyn std::error::Error>> {
    let contents = crate::compression::read_file_contents(path)?;
    let block = match &contents {
        crate::compression::FileContents::Owned(text) => {
            fill_position_block(text.as_bytes(), num_threads)
        }
        crate::compression::FileContents::Mapped(map) => fill_position_block(map, num_threads),
    }?;
    Ok(block)
}

fn frame_starts(bytes: &[u8]) -> Result<Vec<usize>, error::ParseError> {
    let mut scanner = ConFrameIterator::from_bytes(bytes);
    let mut boundaries = Vec::new();
    loop {
        scanner.lines.clear_peek();
        let start = scanner.lines.pos;
        if start >= bytes.len() || bytes[start..].iter().all(u8::is_ascii_whitespace) {
            break;
        }
        boundaries.push(start);
        match scanner.forward_fast() {
            Some(Ok(())) => {}
            Some(Err(err)) => return Err(err),
            None => break,
        }
    }
    Ok(boundaries)
}

fn parse_span(
    bytes: &[u8],
    start: usize,
    end: usize,
) -> Result<types::ConFrame, error::ParseError> {
    let mut iter = ConFrameIterator::from_bytes(&bytes[start..end]);
    match iter.next() {
        Some(result) => result,
        None => Err(error::ParseError::IncompleteFrame),
    }
}

fn copy_positions(frame: &types::ConFrame, dest: &mut [f64]) -> Result<(), error::ParseError> {
    if frame.positions.nrows().saturating_mul(3) != dest.len() {
        return Err(error::ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    if let Some(src) = frame.positions.f64_slice() {
        dest.copy_from_slice(src);
        return Ok(());
    }
    for (i, slot) in dest.chunks_exact_mut(3).enumerate() {
        slot.copy_from_slice(&frame.positions.as_f64_row(i));
    }
    Ok(())
}

fn fill_position_block(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> Result<PositionBlock, error::ParseError> {
    let boundaries = frame_starts(bytes)?;
    if boundaries.is_empty() {
        return Ok(PositionBlock {
            n_frames: 0,
            n_atoms: 0,
            values: Vec::new(),
        });
    }
    let end0 = boundaries.get(1).copied().unwrap_or(bytes.len());
    let first = parse_span(bytes, boundaries[0], end0)?;
    let n_atoms = first.positions.nrows();
    let n_frames = boundaries.len();
    let stride = n_atoms.saturating_mul(3);
    let mut values = vec![0.0_f64; n_frames.saturating_mul(stride)];
    if stride == 0 {
        return Ok(PositionBlock {
            n_frames,
            n_atoms,
            values,
        });
    }
    fill_position_spans(bytes, &boundaries, n_atoms, num_threads, &mut values)?;
    Ok(PositionBlock {
        n_frames,
        n_atoms,
        values,
    })
}

fn fill_position_spans(
    bytes: &[u8],
    boundaries: &[usize],
    n_atoms: usize,
    num_threads: Option<usize>,
    values: &mut [f64],
) -> Result<(), error::ParseError> {
    let stride = n_atoms * 3;
    let write_one = |i: usize, dest: &mut [f64]| {
        let start = boundaries[i];
        let end = boundaries.get(i + 1).copied().unwrap_or(bytes.len());
        let frame = parse_span(bytes, start, end)?;
        copy_positions(&frame, dest)
    };
    #[cfg(feature = "parallel")]
    {
        let parallel = !matches!(num_threads, Some(n) if n <= 1);
        if parallel {
            use rayon::prelude::*;
            let mut run = || {
                values
                    .par_chunks_mut(stride)
                    .enumerate()
                    .try_for_each(|(i, dest)| write_one(i, dest))
            };
            return match num_threads {
                Some(n) if n >= 2 => {
                    let pool = rayon::ThreadPoolBuilder::new()
                        .num_threads(n)
                        .build()
                        .map_err(|err| error::ParseError::ValidationError(err.to_string()))?;
                    pool.install(run)
                }
                _ => run(),
            };
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = num_threads;
    }
    for (i, dest) in values.chunks_mut(stride).enumerate() {
        write_one(i, dest)?;
    }
    Ok(())
}

/// [`frames_from_text`] for bytes that may not be UTF-8 yet.
pub fn frames_from_bytes(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> Result<Vec<types::ConFrame>, error::ParseError> {
    #[cfg(feature = "parallel")]
    {
        if let Some(n) = num_threads.filter(|n| *n >= 2) {
            let parts = parse_frames_parallel_bytes(bytes, Some(n));
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
fn span_end(boundaries: &[usize], index: usize, len: usize) -> usize {
    if index + 1 < boundaries.len() {
        boundaries[index + 1]
    } else {
        len
    }
}

/// Parse each frame into a slot allocated before any worker runs.
///
/// The frames are split by index into contiguous ranges, one range per
/// worker. Worker `t` writes only `slots[start..end]`. The returned
/// vector is that slot storage, in boundary order, which is the serial
/// iterator order. `workers < 2` parses on the calling thread.
#[cfg(feature = "parallel")]
fn parse_into_slots<F>(
    len: usize,
    boundaries: &[usize],
    workers: usize,
    parse_span: F,
) -> Vec<Result<types::ConFrame, error::ParseError>>
where
    F: Fn(usize, usize) -> Result<types::ConFrame, error::ParseError> + Sync,
{
    parse_into_slots_timed(len, boundaries, workers, parse_span).0
}

/// Slot allocation and the worker parse, timed apart.
///
/// The first `f64` is the slot allocation. The second is the worker
/// parse. `workers < 2` still reserves the slot vector before the
/// calling thread fills it.
#[cfg(feature = "parallel")]
fn parse_into_slots_timed<F>(
    len: usize,
    boundaries: &[usize],
    workers: usize,
    parse_span: F,
) -> (Vec<Result<types::ConFrame, error::ParseError>>, f64, f64)
where
    F: Fn(usize, usize) -> Result<types::ConFrame, error::ParseError> + Sync,
{
    let n = boundaries.len();
    if n == 0 {
        return (Vec::new(), 0.0, 0.0);
    }
    if workers < 2 {
        let t_alloc = std::time::Instant::now();
        let mut slots = Vec::with_capacity(n);
        let alloc_s = t_alloc.elapsed().as_secs_f64();
        let t_work = std::time::Instant::now();
        for i in 0..n {
            slots.push(parse_span(boundaries[i], span_end(boundaries, i, len)));
        }
        return (slots, alloc_s, t_work.elapsed().as_secs_f64());
    }
    let t_alloc = std::time::Instant::now();
    let mut slots: Vec<std::mem::MaybeUninit<Result<types::ConFrame, error::ParseError>>> =
        (0..n).map(|_| std::mem::MaybeUninit::uninit()).collect();
    let alloc_s = t_alloc.elapsed().as_secs_f64();
    let chunk = n.div_ceil(workers).max(1);
    let t_work = std::time::Instant::now();
    {
        use rayon::prelude::*;
        slots
            .par_chunks_mut(chunk)
            .enumerate()
            .for_each(|(chunk_index, part)| {
                let base = chunk_index * chunk;
                for (offset, slot) in part.iter_mut().enumerate() {
                    let i = base + offset;
                    slot.write(parse_span(boundaries[i], span_end(boundaries, i, len)));
                }
            });
    }
    let work_s = t_work.elapsed().as_secs_f64();
    // Each index in `0..n` was written once. `par_chunks_mut` hands out
    // disjoint slices, and the last slice is shorter when `n` does not
    // divide the worker count.
    let mut slots = std::mem::ManuallyDrop::new(slots);
    let slots = unsafe {
        Vec::from_raw_parts(
            slots.as_mut_ptr() as *mut Result<types::ConFrame, error::ParseError>,
            slots.len(),
            slots.capacity(),
        )
    };
    (slots, alloc_s, work_s)
}

#[cfg(feature = "parallel")]
fn parse_byte_span(
    bytes: &[u8],
    start: usize,
    end: usize,
) -> Result<types::ConFrame, error::ParseError> {
    let mut iter = ConFrameIterator::from_bytes(&bytes[start..end]);
    match iter.next() {
        Some(result) => result,
        None => Err(error::ParseError::IncompleteFrame),
    }
}

#[cfg(feature = "parallel")]
fn parse_text_span(
    text: &str,
    start: usize,
    end: usize,
) -> Result<types::ConFrame, error::ParseError> {
    let mut iter = ConFrameIterator::new(&text[start..end]);
    match iter.next() {
        Some(result) => result,
        None => Err(error::ParseError::IncompleteFrame),
    }
}

#[cfg(feature = "parallel")]
fn parse_frames_parallel_bytes(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    parse_bytes_timed(bytes, num_threads).0
}

/// Scan, slot allocation, and worker parse of `bytes`.
///
/// The three times are seconds. `Some(n)` with `n >= 2` uses a pool of
/// that size for the chunked newline scan and the slot parse. Every
/// other count stays on the calling thread. `None` follows
/// [`scan_thread_count`].
#[cfg(feature = "parallel")]
fn parse_bytes_timed(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> (
    Vec<Result<types::ConFrame, error::ParseError>>,
    f64,
    f64,
    f64,
) {
    let threads = scan_thread_count(num_threads, bytes.len());
    // The scan stays serial below `SCAN_PARALLEL_MIN`. An explicit pool
    // still parses on that many workers.
    let parse_workers = match num_threads {
        Some(n) if n >= 2 => n,
        Some(_) => 1,
        None => threads,
    };
    let run = || {
        let t_scan = std::time::Instant::now();
        let mut scanner = ConFrameIterator::from_bytes(bytes);
        if threads >= 2 {
            // Same pool as the parse, so the newline chunks do not start
            // a second set of workers.
            scanner.lines.newlines = Some(newline_positions(bytes, threads));
            scanner.lines.line_no = 0;
        }
        // Whitespace after the final frame does not open another frame.
        let boundaries = collect_frame_starts(scanner, true);
        let scan_s = t_scan.elapsed().as_secs_f64();
        let (slots, slot_s, work_s) =
            parse_into_slots_timed(bytes.len(), &boundaries, parse_workers, |start, end| {
                parse_byte_span(bytes, start, end)
            });
        (slots, scan_s, slot_s, work_s)
    };
    match num_threads {
        None => run(),
        Some(n) if n <= 1 => {
            let _ = n;
            let t_scan = std::time::Instant::now();
            let boundaries = collect_frame_starts(ConFrameIterator::from_bytes(bytes), true);
            let scan_s = t_scan.elapsed().as_secs_f64();
            let (slots, slot_s, work_s) =
                parse_into_slots_timed(bytes.len(), &boundaries, 1, |start, end| {
                    parse_byte_span(bytes, start, end)
                });
            (slots, scan_s, slot_s, work_s)
        }
        Some(n) => match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
            Ok(pool) => pool.install(run),
            Err(_) => run(),
        },
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

/// Minimum buffer length for a chunked newline scan.
///
/// On this host a chunked scan of a real trajectory is slower than one
/// serial pass at 4 MiB, and the gap exceeds the chunked interquartile
/// range at 2 and 4 workers. At 64 MiB the chunked median is faster at
/// 2, 4, and 8 workers, and each of those gaps exceeds the chunked
/// interquartile range. The constant is that 64 MiB size.
#[cfg(feature = "parallel")]
pub const SCAN_PARALLEL_MIN: usize = 64 * 1024 * 1024;

enum IndexStep {
    Stay(usize),
    Missing(usize),
    Landed(usize, usize),
    Short(usize, usize),
}

struct IndexedSpan {
    start: usize,
    content_end: usize,
    next_pos: usize,
}

/// Lines in `bytes`, counting a final line that has no `\n`.
fn line_count(nl: &[usize], len: usize) -> usize {
    if len == 0 {
        0
    } else if nl.last().copied() == Some(len - 1) {
        nl.len()
    } else {
        nl.len() + 1
    }
}

fn line_start_pos(nl: &[usize], len: usize, line_no: usize) -> usize {
    if line_no == 0 {
        return 0;
    }
    if line_no >= line_count(nl, len) {
        return len;
    }
    nl[line_no - 1] + 1
}

/// Line index of the line that contains `pos`, or the line count at `len`.
fn line_no_for_pos(nl: &[usize], len: usize, pos: usize) -> usize {
    if pos >= len {
        return line_count(nl, len);
    }
    nl.partition_point(|&p| p < pos)
}

fn indexed_span(nl: &[usize], bytes: &[u8], line_no: usize) -> Option<IndexedSpan> {
    let len = bytes.len();
    if line_no >= line_count(nl, len) {
        return None;
    }
    let start = if line_no == 0 { 0 } else { nl[line_no - 1] + 1 };
    let (raw_end, next_pos) = if line_no < nl.len() {
        (nl[line_no], nl[line_no] + 1)
    } else {
        (len, len)
    };
    let mut content_end = raw_end;
    if content_end > start && bytes[content_end - 1] == b'\r' {
        content_end -= 1;
    }
    Some(IndexedSpan {
        start,
        content_end,
        next_pos,
    })
}

/// `n` cuts covering `0..=len`. A cut may fall in the middle of a header line.
#[cfg(feature = "parallel")]
fn equal_cuts(len: usize, n: usize) -> Vec<usize> {
    let n = n.max(1);
    let mut cuts = Vec::with_capacity(n + 1);
    for i in 0..=n {
        let at = ((i as u128) * (len as u128) / (n as u128)) as usize;
        let at = at.min(len);
        if cuts.last().copied() != Some(at) {
            cuts.push(at);
        }
    }
    if cuts.last().copied() != Some(len) {
        cuts.push(len);
    }
    cuts
}

/// Newline offsets in `bytes`.
///
/// `cuts` splits the buffer into `[cuts[i], cuts[i + 1])`. Each piece is
/// scanned on its own and the offsets are concatenated. A `\n` belongs to
/// the piece that contains that byte, so a header line whose body crosses
/// a cut still contributes one newline.
#[cfg(feature = "parallel")]
fn newline_positions_at_cuts(bytes: &[u8], cuts: &[usize]) -> Vec<usize> {
    let spans: Vec<(usize, usize)> = cuts
        .windows(2)
        .map(|w| (w[0].min(bytes.len()), w[1].min(bytes.len())))
        .filter(|(start, end)| start < end)
        .collect();
    if spans.len() <= 1 {
        let (start, end) = spans.first().copied().unwrap_or((0, 0));
        return memchr::memchr_iter(b'\n', &bytes[start..end])
            .map(|p| start + p)
            .collect();
    }
    // The current Rayon pool, or the global pool when the caller has not
    // installed one. Chunk count is the worker cap: two chunks do not
    // wake every core.
    use rayon::prelude::*;
    let parts: Vec<Vec<usize>> = spans
        .par_iter()
        .map(|&(start, end)| {
            memchr::memchr_iter(b'\n', &bytes[start..end])
                .map(|p| start + p)
                .collect()
        })
        .collect();
    let mut all = Vec::with_capacity(bytes.len() / 32);
    for part in parts {
        all.extend(part);
    }
    all
}

#[cfg(feature = "parallel")]
fn newline_positions(bytes: &[u8], threads: usize) -> Vec<usize> {
    newline_positions_at_cuts(bytes, &equal_cuts(bytes.len(), threads))
}

#[cfg(feature = "parallel")]
fn scan_thread_count(num_threads: Option<usize>, len: usize) -> usize {
    let requested = match num_threads {
        Some(n) => n,
        None => std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1),
    };
    if requested < 2 || len < SCAN_PARALLEL_MIN {
        1
    } else {
        requested
    }
}

fn collect_frame_starts(
    mut scanner: ConFrameIterator<'_>,
    skip_whitespace_tail: bool,
) -> Vec<usize> {
    let mut boundaries = Vec::new();
    loop {
        scanner.lines.clear_peek();
        let start = scanner.lines.pos;
        if start >= scanner.lines.bytes.len() {
            break;
        }
        if skip_whitespace_tail {
            let rest = &scanner.lines.bytes[start..];
            if rest.iter().all(u8::is_ascii_whitespace) {
                break;
            }
        }
        boundaries.push(start);
        match scanner.forward_fast() {
            Some(Ok(())) => {}
            Some(Err(_)) | None => break,
        }
    }
    boundaries
}

/// Serial header walk. This is the reference the chunked scan must match.
pub fn frame_start_offsets_serial(file_contents: &str) -> Vec<usize> {
    collect_frame_starts(ConFrameIterator::new(file_contents), false)
}

#[cfg(feature = "parallel")]
fn scanner_with_newlines<'a>(text: &'a str, newlines: Vec<usize>) -> ConFrameIterator<'a> {
    let mut scanner = ConFrameIterator::new(text);
    scanner.lines.line_no = 0;
    scanner.lines.newlines = Some(newlines);
    scanner
}

#[cfg(feature = "parallel")]
fn frame_start_offsets_indexed(text: &str, newlines: Vec<usize>) -> Vec<usize> {
    collect_frame_starts(scanner_with_newlines(text, newlines), false)
}

/// Frame starts for `text` when the newline scan is split at `cuts`.
///
/// `cuts` is the chunk edges, including 0 and `text.len()`. A cut inside a
/// header line is the straddling case: the stitched offsets are still the
/// serial offsets.
#[cfg(all(feature = "parallel", test))]
fn frame_start_offsets_at_cuts(text: &str, cuts: &[usize]) -> Vec<usize> {
    let newlines = newline_positions_at_cuts(text.as_bytes(), cuts);
    frame_start_offsets_indexed(text, newlines)
}

/// Frame start byte offsets via [`ConFrameIterator::forward_fast`] (no atom parse).
///
/// Stops at the first skip error (that start is still included).
///
/// With the `parallel` feature, a buffer of at least
/// [`SCAN_PARALLEL_MIN`] bytes is split into chunks and the newline bytes
/// are scanned together. The chunks are not aligned to lines. A header
/// that straddles a cut is one line, because each `\n` is recorded by the
/// chunk that holds that byte and the lists are stitched in order. The
/// returned offsets match the serial walk.
pub fn frame_start_offsets(file_contents: &str) -> Vec<usize> {
    frame_start_offsets_with_threads(file_contents, None)
}

/// [`frame_start_offsets`] using `num_threads` chunks.
///
/// `None` uses the machine's parallelism. `Some(0)` and `Some(1)` stay on
/// the calling thread. The offsets do not depend on the thread count.
///
/// The timed work includes the cut setup, the per-chunk scans, the
/// stitch, and the frame walk that reads the stitched newline index.
pub fn frame_start_offsets_with_threads(
    file_contents: &str,
    num_threads: Option<usize>,
) -> Vec<usize> {
    #[cfg(feature = "parallel")]
    {
        let threads = scan_thread_count(num_threads, file_contents.len());
        if threads >= 2 {
            let newlines = newline_positions(file_contents.as_bytes(), threads);
            return frame_start_offsets_indexed(file_contents, newlines);
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = num_threads;
    }
    frame_start_offsets_serial(file_contents)
}

/// Parses frames in parallel using rayon, splitting on frame boundaries.
///
/// Phase 1: frame-start offsets from [`frame_start_offsets_with_threads`].
/// The newline scan is split into chunks and stitched, including a header
/// that crosses a chunk edge. The offsets match a serial
/// [`ConFrameIterator::forward_fast`] walk. An earlier walk built a
/// `Vec<&str>` of every line and summed lengths up to each frame, which
/// is O(N^2) in the line count.
///
/// Phase 2: each worker parses a contiguous run of those frames into
/// slots allocated before the parse. The slot order is the boundary
/// order. See [`parse_frames_parallel_with_threads`].
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_parallel(
    file_contents: &str,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    parse_frames_parallel_with_threads(file_contents, None)
}

/// Like [`parse_frames_parallel`], but runs both phases on an explicit
/// Rayon pool with `num_threads` workers when `Some(n)` (`n` is clamped
/// to at least 1). `None` uses the global pool when the buffer is at
/// least [`SCAN_PARALLEL_MIN`] bytes, and the calling thread otherwise.
///
/// Phase 2 splits the frame offsets into one contiguous range per
/// worker. Each worker writes its frames into slots allocated before
/// the parse. The result matches a serial iterator, field for field
/// and in frame order.
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_parallel_with_threads(
    file_contents: &str,
    num_threads: Option<usize>,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    // Phase 1 runs on the same pool as phase 2. Building the pool twice
    // would put the newline scan on the global pool and the parse on
    // another.
    let threads = scan_thread_count(num_threads, file_contents.len());
    let parse_workers = match num_threads {
        Some(n) if n >= 2 => n,
        Some(_) => 1,
        None => threads,
    };
    let run = || {
        // A whitespace tail is not a frame. The serial iterator stops
        // there. The offset scan used by callers still records that byte
        // when a skip error includes it.
        let boundaries = if threads >= 2 {
            let newlines = newline_positions(file_contents.as_bytes(), threads);
            collect_frame_starts(scanner_with_newlines(file_contents, newlines), true)
        } else {
            collect_frame_starts(ConFrameIterator::new(file_contents), true)
        };
        parse_into_slots(
            file_contents.len(),
            &boundaries,
            parse_workers,
            |start, end| parse_text_span(file_contents, start, end),
        )
    };
    match num_threads {
        Some(n) if n >= 2 => match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
            Ok(pool) => pool.install(run),
            Err(_) => run(),
        },
        _ => run(),
    }
}

/// Phase 2 of [`parse_frames_parallel_with_threads`]: parse the frames
/// that start at `boundaries` (strictly increasing byte offsets into
/// `file_contents`; frame `i` ends where frame `i + 1` starts).
///
/// Offsets may come from [`frame_start_offsets`] or from a checked
/// [`crate::frame_index::FrameIndex`]. The output slots are allocated
/// first. Each worker then fills one contiguous index range. Results
/// stay in frame order.
///
/// The timer for this function starts after `boundaries` exist. It
/// includes slot allocation and the worker parse. It does not include
/// the newline scan or the stitch.
///
/// Requires the `parallel` feature.
#[cfg(feature = "parallel")]
pub fn parse_frames_at_offsets(
    file_contents: &str,
    boundaries: &[usize],
    num_threads: Option<usize>,
) -> Vec<Result<types::ConFrame, error::ParseError>> {
    let workers = match num_threads {
        Some(n) if n <= 1 => 1,
        Some(n) => n,
        None => rayon::current_num_threads().max(1),
    };
    let run = || {
        parse_into_slots(file_contents.len(), boundaries, workers, |start, end| {
            parse_text_span(file_contents, start, end)
        })
    };
    match num_threads {
        Some(n) if n >= 2 => match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
            Ok(pool) => pool.install(run),
            Err(_) => run(),
        },
        _ => run(),
    }
}

/// Seconds for one phased read. The open time is the file read or the
/// map. Scan, slot allocation, and the worker parse are separate.
#[derive(Clone, Copy, Debug, Default)]
pub struct ReadPhaseTimes {
    pub open_mmap_s: f64,
    pub scan_s: f64,
    pub slot_alloc_s: f64,
    pub worker_parse_s: f64,
    /// True when the bytes came from a map rather than an owned buffer.
    pub mapped: bool,
}

/// Frames from one phased read, plus the byte length of the buffer.
pub struct PhasedFrames {
    pub frames: Vec<types::ConFrame>,
    pub phases: ReadPhaseTimes,
    pub n_bytes: usize,
}

/// Read `path` and time open, scan, slot allocation, and the worker parse.
///
/// Plain text at or above the map threshold is mapped. Smaller files and
/// compressed files are owned buffers. `Some(n)` with `n >= 2` parses on
/// that many workers. Every other count parses on the calling thread.
/// The frame list matches [`frames_from_bytes`].
pub fn read_all_frames_phased(
    path: &Path,
    num_threads: Option<usize>,
) -> Result<PhasedFrames, Box<dyn std::error::Error>> {
    let t_open = std::time::Instant::now();
    let contents = crate::compression::read_file_contents(path)?;
    let open_mmap_s = t_open.elapsed().as_secs_f64();
    let mapped = matches!(contents, crate::compression::FileContents::Mapped(_));
    let n_bytes = match &contents {
        crate::compression::FileContents::Owned(text) => text.len(),
        crate::compression::FileContents::Mapped(map) => map.len(),
    };
    let bytes: &[u8] = match &contents {
        crate::compression::FileContents::Owned(text) => text.as_bytes(),
        crate::compression::FileContents::Mapped(map) => map,
    };
    let (frames, scan_s, slot_alloc_s, worker_parse_s) =
        frames_from_bytes_phased(bytes, num_threads)?;
    Ok(PhasedFrames {
        frames,
        n_bytes,
        phases: ReadPhaseTimes {
            open_mmap_s,
            scan_s,
            slot_alloc_s,
            worker_parse_s,
            mapped,
        },
    })
}

/// [`frames_from_bytes`] with scan, slot allocation, and worker-parse times.
///
/// `Some(n)` with `n >= 2` uses that pool. Every other count, including
/// `None`, stays on the calling thread. That is the `read_con` policy:
/// an omitted count does not start a pool.
pub fn frames_from_bytes_phased(
    bytes: &[u8],
    num_threads: Option<usize>,
) -> Result<(Vec<types::ConFrame>, f64, f64, f64), error::ParseError> {
    #[cfg(feature = "parallel")]
    {
        let requested = match num_threads {
            Some(n) if n >= 2 => Some(n),
            _ => Some(1),
        };
        let (parts, scan_s, slot_s, work_s) = parse_bytes_timed(bytes, requested);
        let mut frames = Vec::with_capacity(parts.len());
        for part in parts {
            frames.push(part?);
        }
        return Ok((frames, scan_s, slot_s, work_s));
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = num_threads;
        let t_work = std::time::Instant::now();
        let mut frames = Vec::new();
        for part in ConFrameIterator::from_bytes(bytes) {
            frames.push(part?);
        }
        Ok((frames, 0.0, 0.0, t_work.elapsed().as_secs_f64()))
    }
}

/// Copy every frame's coordinates into one row-major buffer.
///
/// `None` means the frames do not share one atom count. `workers >= 2`
/// writes disjoint frame runs. The copy is bit-identical to reading
/// each frame's `f64` positions in order.
pub fn pack_position_slab(frames: &[types::ConFrame], workers: usize) -> Option<Vec<f64>> {
    if frames.is_empty() {
        return None;
    }
    let n_atoms = frames[0].positions.nrows();
    if frames
        .iter()
        .any(|frame| frame.positions.nrows() != n_atoms)
    {
        return None;
    }
    let stride = n_atoms.saturating_mul(3);
    let mut values = vec![0.0_f64; frames.len().saturating_mul(stride)];
    if stride == 0 {
        return Some(values);
    }
    let write = |frame: &types::ConFrame, dest: &mut [f64]| {
        if let Some(src) = frame.positions.f64_slice() {
            dest.copy_from_slice(src);
        } else {
            for (row, slot) in dest.chunks_exact_mut(3).enumerate() {
                slot.copy_from_slice(&frame.positions.as_f64_row(row));
            }
        }
    };
    #[cfg(feature = "parallel")]
    {
        if workers >= 2 {
            use rayon::prelude::*;
            let chunk_frames = frames.len().div_ceil(workers).max(1);
            let chunk_vals = chunk_frames.saturating_mul(stride);
            values
                .par_chunks_mut(chunk_vals)
                .enumerate()
                .for_each(|(chunk_index, dest)| {
                    let base = chunk_index * chunk_frames;
                    for (offset, slot) in dest.chunks_exact_mut(stride).enumerate() {
                        let index = base + offset;
                        if index < frames.len() {
                            write(&frames[index], slot);
                        }
                    }
                });
            return Some(values);
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = workers;
    }
    for (frame, dest) in frames.iter().zip(values.chunks_exact_mut(stride)) {
        write(frame, dest);
    }
    Some(values)
}

/// Time a newline scan of `text`.
///
/// `chunked` with `threads >= 2` splits the buffer into that many
/// chunks, stitches the newline index, and walks frame starts. The
/// pool is built before the timer starts. The serial walk is
/// [`frame_start_offsets_serial`]. The returned offsets are the frame
/// starts. The size gate used by the hot path is not applied here.
pub fn measure_newline_scan(text: &str, threads: usize, chunked: bool) -> (Vec<usize>, f64) {
    #[cfg(feature = "parallel")]
    {
        if chunked && threads >= 2 {
            let pool = rayon::ThreadPoolBuilder::new().num_threads(threads).build();
            let t_scan = std::time::Instant::now();
            let offsets = match pool {
                Ok(pool) => pool.install(|| {
                    let newlines = newline_positions(text.as_bytes(), threads);
                    frame_start_offsets_indexed(text, newlines)
                }),
                Err(_) => {
                    let newlines = newline_positions(text.as_bytes(), threads);
                    frame_start_offsets_indexed(text, newlines)
                }
            };
            return (offsets, t_scan.elapsed().as_secs_f64());
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = (threads, chunked);
    }
    let t_scan = std::time::Instant::now();
    let offsets = frame_start_offsets_serial(text);
    (offsets, t_scan.elapsed().as_secs_f64())
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

    fn live_threads() -> usize {
        std::fs::read_to_string("/proc/self/status")
            .unwrap()
            .lines()
            .find(|line| line.starts_with("Threads:"))
            .unwrap()
            .split_whitespace()
            .nth(1)
            .unwrap()
            .parse()
            .unwrap()
    }

    /// A file past the old map and pool gates stays on this thread.
    #[test]
    fn default_read_of_a_wide_file_stays_on_the_calling_thread() {
        const CHILD: &str = "READCON_DEFAULT_THREAD_CHILD";
        const NAME: &str = "iterators::parallel_strong_scale_tests::default_read_of_a_wide_file_stays_on_the_calling_thread";
        if std::env::var_os(CHILD).is_none() {
            let out = std::process::Command::new(std::env::current_exe().unwrap())
                .args([NAME, "--exact", "--test-threads=1"])
                .env(CHILD, "1")
                .output()
                .unwrap();
            let stdout = String::from_utf8_lossy(&out.stdout);
            assert!(
                out.status.success() && stdout.contains("test result: ok. 1 passed;"),
                "{stdout}{}",
                String::from_utf8_lossy(&out.stderr)
            );
            return;
        }
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("wide.con");
        let one = std::fs::read_to_string(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/test/tiny_cuh2.con"),
        )
        .unwrap();
        std::fs::write(&path, one.repeat(200)).unwrap();
        assert!(std::fs::metadata(&path).unwrap().len() > 64 * 1024);
        let before = live_threads();
        let frames = super::read_all_frames(&path).unwrap();
        let after = live_threads();
        assert_eq!(before, after, "default read started worker threads");
        assert!(frames.len() > 1);
        let text = std::fs::read_to_string(&path).unwrap();
        let sequential = super::frames_from_text(&text, None).unwrap();
        assert_eq!(sequential.len(), frames.len());
        assert_eq!(
            sequential[0].atom_data[0].x, frames[0].atom_data[0].x,
            "default read changed a coordinate"
        );
    }
}

#[cfg(all(test, feature = "parallel"))]
mod parallel_header_scan_tests {
    use super::*;
    use std::path::PathBuf;

    fn fixture(name: &str) -> String {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test")
            .join(name);
        std::fs::read_to_string(path).expect(name)
    }

    /// A cut on the byte between `\r` and `\n`. The `\n` is in the next chunk.
    fn assert_crlf_gap_cut(text: &str) {
        let bytes = text.as_bytes();
        let mut found = 0usize;
        let mut i = 0usize;
        while i + 1 < bytes.len() && found < 6 {
            if bytes[i] == b'\r' && bytes[i + 1] == b'\n' {
                let cut = i + 1;
                assert_eq!(bytes[cut - 1], b'\r');
                assert_eq!(bytes[cut], b'\n');
                assert_cuts_match(text, &[0, cut, bytes.len()]);
                found += 1;
                i += 2;
                continue;
            }
            i += 1;
        }
        assert!(found > 0, "fixture has no CRLF pair");
    }

    fn assert_cuts_match(text: &str, cuts: &[usize]) {
        let serial_nl: Vec<usize> = memchr::memchr_iter(b'\n', text.as_bytes()).collect();
        let stitched = newline_positions_at_cuts(text.as_bytes(), cuts);
        assert_eq!(stitched, serial_nl, "newline stitch at {cuts:?}");
        let serial = frame_start_offsets_serial(text);
        let parallel = frame_start_offsets_at_cuts(text, cuts);
        assert_eq!(parallel, serial, "frame offsets at {cuts:?}");
    }

    fn header_straddle_cuts(text: &str) -> Vec<Vec<usize>> {
        let serial = frame_start_offsets_serial(text);
        let bytes = text.as_bytes();
        let mut out = Vec::new();
        // Equal splits, plus a cut forced into a header line of every frame.
        for n in [2usize, 3, 4, 8] {
            out.push(equal_cuts(bytes.len(), n));
        }
        for &start in &serial {
            let window = (start + 160).min(bytes.len());
            let mut line = start;
            let mut straddled = 0usize;
            while line < window && straddled < 9 {
                let Some(rel) = memchr::memchr(b'\n', &bytes[line..window]) else {
                    break;
                };
                let end = line + rel;
                if end - line > 1 {
                    let mid = line + (end - line) / 2;
                    // mid is inside the line, so the header byte sits across two chunks.
                    assert!(mid > line && mid < end);
                    out.push(vec![0, mid, bytes.len()]);
                    straddled += 1;
                }
                line = end + 1;
            }
        }
        out
    }

    fn assert_slab(text: &str) {
        assert!(!text.is_empty());
        for cuts in header_straddle_cuts(&text) {
            assert_cuts_match(&text, &cuts);
        }
        let bare = text.trim_end_matches(['\n', '\r']);
        if !bare.is_empty() {
            assert_cuts_match(bare, &equal_cuts(bare.len(), 4));
            let mid = bare.len() / 2;
            let line_start = bare[..mid].rfind('\n').map(|i| i + 1).unwrap_or(0);
            let line_end = bare[mid..]
                .find('\n')
                .map(|i| mid + i)
                .unwrap_or(bare.len());
            if line_end - line_start > 1 {
                let cut = line_start + (line_end - line_start) / 2;
                assert_cuts_match(bare, &[0, cut, bare.len()]);
            }
        }
        let tailed = format!("{text}\n   \n\t\n");
        assert_cuts_match(
            &tailed,
            &[0, 3, tailed.len() / 2, tailed.len() - 1, tailed.len()],
        );
        let crlf = text.replace('\n', "\r\n");
        assert_cuts_match(&crlf, &equal_cuts(crlf.len(), 5));
        assert_crlf_gap_cut(&crlf);
        let serial = frame_start_offsets_serial(text);
        if serial.len() >= 2 {
            let second = serial[1];
            let next = serial.get(2).copied().unwrap_or(text.len());
            let broken_at = second + (next - second) / 2;
            let broken = &text[..broken_at.max(1)];
            assert_cuts_match(broken, &[0, 1.max(broken.len() / 3), broken.len()]);
        }
    }

    #[test]
    fn chunked_header_scan_matches_serial_offsets() {
        assert_eq!(frame_start_offsets_serial(""), frame_start_offsets(""));
        assert_cuts_match("\n", &[0, 1]);
        assert_cuts_match("   \n\n", &[0, 2, 5]);
        for name in [
            "tiny_cuh2.con",
            "tiny_cuh2.convel",
            "tiny_cuh2_forces.con",
            "tiny_cuh2_vel_forces.con",
            "cuh2.con",
        ] {
            let one = fixture(name);
            assert_slab(&one);
            assert_slab(&one.repeat(3));
        }
        // The bytes parser (the read_con path) uses the same stitch.
        // Repeat until the buffer crosses the measured chunked-scan gate.
        let one = fixture("cuh2.con");
        let wide = one.repeat(SCAN_PARALLEL_MIN.div_ceil(one.len()).max(1));
        assert!(wide.len() >= SCAN_PARALLEL_MIN);
        let serial = frame_start_offsets_serial(&wide);
        for workers in [2usize, 3, 4, 8] {
            let parallel = frame_start_offsets_with_threads(&wide, Some(workers));
            assert_eq!(parallel, serial, "workers={workers}");
            let parsed = frames_from_bytes(wide.as_bytes(), Some(workers)).expect("bytes parse");
            assert_eq!(parsed.len(), serial.len());
            let seq = frames_from_text(&wide, Some(1)).expect("serial parse");
            assert_eq!(parsed.len(), seq.len());
            assert_eq!(parsed[0].atom_data[0].x, seq[0].atom_data[0].x);
            assert_eq!(
                parsed.last().unwrap().atom_data.last().unwrap().z,
                seq.last().unwrap().atom_data.last().unwrap().z
            );
        }
    }
}

#[cfg(all(test, feature = "parallel"))]
mod parallel_frame_parse_tests {
    use super::*;
    use std::path::PathBuf;

    const ZERO_ATOM: &str = "\
zero-atom frame
{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}
10.0 10.0 10.0
90.0 90.0 90.0


0


";

    fn fixture(name: &str) -> String {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test")
            .join(name);
        std::fs::read_to_string(path).expect(name)
    }

    fn serial_results(text: &str) -> Vec<Result<types::ConFrame, error::ParseError>> {
        ConFrameIterator::new(text).collect()
    }

    fn written(frame: &types::ConFrame) -> Vec<u8> {
        let mut out = Vec::new();
        {
            let mut writer = crate::writer::ConFrameWriter::new(&mut out);
            writer.write_frame(frame).expect("write");
            writer.flush().expect("flush");
        }
        out
    }

    fn assert_same_results(
        label: &str,
        serial: Vec<Result<types::ConFrame, error::ParseError>>,
        parallel: Vec<Result<types::ConFrame, error::ParseError>>,
    ) {
        assert_eq!(serial.len(), parallel.len(), "{label} count");
        for (i, (left, right)) in serial.into_iter().zip(parallel).enumerate() {
            match (left, right) {
                (Ok(a), Ok(b)) => {
                    assert_eq!(written(&a), written(&b), "{label} bytes frame {i}");
                    assert_eq!(a, b, "{label} fields frame {i}");
                }
                (Err(a), Err(b)) => {
                    assert_eq!(
                        format!("{a:?}"),
                        format!("{b:?}"),
                        "{label} error frame {i}"
                    );
                }
                (Ok(_), Err(err)) => panic!("{label} frame {i} serial ok parallel {err:?}"),
                (Err(err), Ok(_)) => panic!("{label} frame {i} serial {err:?} parallel ok"),
            }
        }
    }

    fn assert_workers(label: &str, text: &str) {
        let serial_ok = serial_results(text).iter().all(|item| item.is_ok());
        for workers in [1usize, 2, 3, 4, 8] {
            let parallel = parse_frames_parallel_with_threads(text, Some(workers));
            assert_same_results(
                &format!("{label} workers {workers}"),
                serial_results(text),
                parallel,
            );
            let bounds = collect_frame_starts(ConFrameIterator::new(text), true);
            let at = parse_frames_at_offsets(text, &bounds, Some(workers));
            assert_same_results(
                &format!("{label} offsets workers {workers}"),
                serial_results(text),
                at,
            );
        }
        if serial_ok {
            for workers in [2usize, 3, 8] {
                let bytes = frames_from_bytes(text.as_bytes(), Some(workers)).expect(label);
                let seq = frames_from_text(text, Some(1)).expect(label);
                assert_eq!(bytes.len(), seq.len(), "{label} byte count");
                for (i, (a, b)) in bytes.iter().zip(seq.iter()).enumerate() {
                    assert_eq!(written(a), written(b), "{label} byte path frame {i}");
                    assert_eq!(a, b, "{label} byte path fields frame {i}");
                }
            }
        }
    }

    fn crlf_gap_offsets(text: &str) -> Vec<usize> {
        let bytes = text.as_bytes();
        let mut cut = None;
        let mut i = 0usize;
        while i + 1 < bytes.len() {
            if bytes[i] == b'\r' && bytes[i + 1] == b'\n' {
                cut = Some(i + 1);
                break;
            }
            i += 1;
        }
        let cut = cut.expect("crlf");
        frame_start_offsets_at_cuts(text, &[0, cut, bytes.len()])
    }

    #[test]
    fn parallel_slots_match_serial_frames() {
        assert_workers("empty", "");
        assert_workers("blank", "\n");
        assert_workers("space", "   \n\n");
        assert_workers("zero", ZERO_ATOM);
        assert_workers("zero-repeat", &ZERO_ATOM.repeat(5));
        for name in [
            "tiny_cuh2.con",
            "tiny_cuh2.convel",
            "tiny_cuh2_forces.con",
            "tiny_cuh2_vel_forces.con",
            "tiny_cuh2_charges_spins_magmoms.con",
            "tiny_cuh2_displacements.con",
            "tiny_cuh2_spreads.con",
            "cuh2.con",
        ] {
            let one = fixture(name);
            assert_workers(name, &one);
            assert_workers(&format!("{name} x5"), &one.repeat(5));
            let bare = one.trim_end_matches(['\n', '\r']);
            assert_workers(&format!("{name} bare"), bare);
            let tailed = format!("{one}\n   \n\t\n");
            assert_workers(&format!("{name} tail"), &tailed);
            let crlf = one.replace('\n', "\r\n");
            assert_workers(&format!("{name} crlf"), &crlf);
            let gap = crlf_gap_offsets(&crlf);
            assert_eq!(
                gap,
                frame_start_offsets_serial(&crlf),
                "{name} crlf gap offsets"
            );
            let parsed = parse_frames_at_offsets(&crlf, &gap, Some(4));
            assert_same_results(
                &format!("{name} crlf gap parse"),
                serial_results(&crlf),
                parsed,
            );
            let serial_offs = frame_start_offsets_serial(&one);
            let broken: &str = if serial_offs.len() >= 2 {
                let second = serial_offs[1];
                let next = serial_offs.get(2).copied().unwrap_or(one.len());
                &one[..second + (next - second) / 2]
            } else if one.len() > 8 {
                &one[..one.len() / 2]
            } else {
                ""
            };
            if !broken.is_empty() {
                let serial_err = frames_from_text(broken, Some(1))
                    .err()
                    .map(|e| format!("{e:?}"));
                assert!(serial_err.is_some(), "{name} chopped still parsed");
                for workers in [1usize, 2, 4, 8] {
                    let parallel_err = frames_from_text(broken, Some(workers))
                        .err()
                        .map(|e| format!("{e:?}"));
                    assert_eq!(parallel_err, serial_err, "{name} chopped workers {workers}");
                    let byte_err = frames_from_bytes(broken.as_bytes(), Some(workers))
                        .err()
                        .map(|e| format!("{e:?}"));
                    assert_eq!(
                        byte_err, serial_err,
                        "{name} chopped bytes workers {workers}"
                    );
                }
            }
        }
    }
}

#[cfg(all(test, feature = "parallel"))]
mod phased_read_tests {
    use super::*;
    use std::path::PathBuf;

    fn fixture(name: &str) -> String {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test")
            .join(name);
        std::fs::read_to_string(path).expect(name)
    }

    #[test]
    fn phased_bytes_match_serial_frames() {
        let text = fixture("cuh2.con").repeat(4);
        let serial = frames_from_text(&text, Some(1)).expect("serial");
        for workers in [1usize, 2, 4, 8] {
            let (parallel, scan_s, slot_s, work_s) =
                frames_from_bytes_phased(text.as_bytes(), Some(workers)).expect("phased");
            assert_eq!(parallel.len(), serial.len(), "workers={workers}");
            assert!(scan_s >= 0.0 && slot_s >= 0.0 && work_s >= 0.0);
            assert_eq!(parallel[0], serial[0], "workers={workers} first");
            assert_eq!(
                parallel.last().unwrap(),
                serial.last().unwrap(),
                "workers={workers} last"
            );
            let slab = pack_position_slab(&serial, workers).expect("slab");
            let stride = serial[0].positions.nrows() * 3;
            let src = serial[0].positions.f64_slice().expect("f64");
            assert_eq!(&slab[..stride], src);
            let (chunked, _) = measure_newline_scan(&text, workers.max(2), true);
            let (plain, _) = measure_newline_scan(&text, 1, false);
            if workers >= 2 {
                assert_eq!(chunked, plain);
            }
        }
    }

    #[test]
    fn phased_file_matches_serial_and_maps_a_wide_file() {
        let text = fixture("cuh2.con").repeat(5);
        let dir = std::env::temp_dir();
        let path = dir.join("readcon-phased-wide.con");
        std::fs::write(&path, &text).expect("write");
        let phased = read_all_frames_phased(&path, Some(4)).expect("phased");
        let serial = frames_from_text(&text, Some(1)).expect("serial");
        assert_eq!(phased.frames, serial);
        assert!(phased.phases.mapped, "a file past 64 KiB is mapped");
        assert!(phased.phases.worker_parse_s >= 0.0);
        assert_eq!(phased.n_bytes, text.len());
        let _ = std::fs::remove_file(&path);
    }
}
