use crate::error::ParseError;
use crate::helpers::symbol_to_atomic_number;
use crate::types::{
    AtomDatum, ConFrame, FrameHeader, PreboxHeader, SECTION_CHARGES, SECTION_DISPLACEMENTS,
    SECTION_ENERGIES, SECTION_FORCES, SECTION_MAGMOMS, SECTION_SPINS, SECTION_SPREADS,
    SECTION_VELOCITIES, meta,
};
use serde_json::Value;
use std::collections::BTreeMap;
use std::iter::Peekable;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

/// Line source with peek for section detection (blank-line separators).
///
/// Implemented by the memchr cursor on the hot iterator path and by
/// `Peekable<I>` for tests / ad-hoc callers.
pub trait LineStream<'a> {
    fn next_line(&mut self) -> Option<&'a str>;
    fn peek_line(&mut self) -> Option<&'a str>;
    /// True when every remaining line, including the current peek, is
    /// empty or whitespace. Default is false so a one-line peek cannot
    /// hide a following section.
    fn remainder_is_whitespace(&mut self) -> bool {
        false
    }
    /// Called while a blank line is peeked. True when that blank begins a
    /// section: the next line is a symbol and the line after it is a
    /// component label. A blank that does not is line 1 of the next frame.
    fn blank_line_opens_section(&mut self) -> bool {
        false
    }

    /// With a blank line peeked, true when [`Self::blank_line_opens_section`]
    /// is true. A stream that cannot look ahead keeps the legacy rule and
    /// returns true.
    fn blank_opens_velocity_block(&mut self) -> bool {
        true
    }

    /// One coordinate row, fused with the line scan when the stream can do it.
    ///
    /// The default pulls a `&str` line. [`crate::iterators::MemchrLines`]
    /// parses the row directly from the byte cursor so tokenize and numeric
    /// parse are one pass.
    fn next_coord_row(
        &mut self,
        spec_version: u32,
        default_id: u64,
    ) -> Result<([f64; 3], [bool; 3], u64), ParseError> {
        let line = self.next_line().ok_or(ParseError::IncompleteFrame)?;
        parse_coord_row(line, spec_version, default_id)
    }

    /// Parse `n` coordinate rows straight into reserved buffers.
    ///
    /// `Ok(None)` means this stream has no block cursor; the caller reads
    /// one row at a time. `Ok(Some(next_id))` means the rows were stored.
    fn ingest_known_coords(
        &mut self,
        n: usize,
        spec_version: u32,
        global_atom_idx: u64,
        symbol: &Arc<str>,
        reuse: bool,
        pos_flat: &mut Vec<f64>,
        ids: &mut Vec<u64>,
        atom_data: &mut Vec<AtomDatum>,
    ) -> Result<Option<u64>, ParseError> {
        let _ = (
            n,
            spec_version,
            global_atom_idx,
            symbol,
            reuse,
            pos_flat,
            ids,
            atom_data,
        );
        Ok(None)
    }

    /// One vector-section row (xyz, flag, required id), fused with the line
    /// scan when the stream can do it. End of input is [`ParseError::IncompleteFrame`];
    /// callers that are inside a named section map that to `IncompleteSection`.
    fn next_vector_row(
        &mut self,
        spec_version: u32,
    ) -> Result<([f64; 3], [bool; 3], u64), ParseError> {
        let line = self.next_line().ok_or(ParseError::IncompleteFrame)?;
        parse_vector_section_row(line, spec_version)
    }

    /// `n` vector rows stored with `store`. A byte cursor overrides this and
    /// calls [`parse_vector_row_at`] so the section walk and the row parser
    /// share one scan.
    fn apply_vector_rows(
        &mut self,
        n: usize,
        spec_version: u32,
        rows: &mut [AtomDatum],
        mut index: usize,
        store: fn(&mut AtomDatum, [f64; 3]),
    ) -> Result<usize, ParseError> {
        for _ in 0..n {
            let (xyz, _, _) = self.next_vector_row(spec_version)?;
            if index < rows.len() {
                store(&mut rows[index], xyz);
            }
            index += 1;
        }
        Ok(index)
    }
}

fn read_vector_components<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
    section: &str,
    heading: &str,
    identity: &str,
    store: fn(&mut AtomDatum, [f64; 3]),
) -> Result<bool, ParseError> {
    let validate = header.strict_validation;
    let mut atom_idx = 0usize;
    let prefix = match heading {
        "Velocities" => "Velocities of Component",
        "Forces" => "Forces of Component",
        _ => heading,
    };
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(section.to_string()))?
            .trim();
        let comp_line = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(section.to_string()))?;
        if !label_has_prefix(comp_line, prefix) {
            return Err(ParseError::IncompleteSection(section.to_string()));
        }
        if validate {
            validate_section_component(
                heading, type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
            for _ in 0..num_atoms {
                let (vals, fixed, atom_id) = take_vector_row(lines, header.spec_version, section)?;
                validate_section_atom_identity(identity, atom_idx, fixed, atom_id, atom_data)?;
                if atom_idx < atom_data.len() {
                    store(&mut atom_data[atom_idx], vals);
                }
                atom_idx += 1;
            }
        } else {
            atom_idx = lines
                .apply_vector_rows(num_atoms, header.spec_version, atom_data, atom_idx, store)
                .map_err(|err| match err {
                    ParseError::IncompleteFrame => {
                        ParseError::IncompleteSection(section.to_string())
                    }
                    other => other,
                })?;
        }
    }
    Ok(true)
}

fn take_vector_row<'a>(
    lines: &mut impl LineStream<'a>,
    spec_version: u32,
    section: &str,
) -> Result<([f64; 3], [bool; 3], u64), ParseError> {
    match lines.next_vector_row(spec_version) {
        Ok(row) => Ok(row),
        Err(ParseError::IncompleteFrame) => Err(ParseError::IncompleteSection(section.to_string())),
        Err(err) => Err(err),
    }
}

impl<'a, I> LineStream<'a> for Peekable<I>
where
    I: Iterator<Item = &'a str> + Clone,
{
    #[inline]
    fn next_line(&mut self) -> Option<&'a str> {
        Iterator::next(self)
    }
    #[inline]
    fn peek_line(&mut self) -> Option<&'a str> {
        Peekable::peek(self).copied()
    }
    fn blank_line_opens_section(&mut self) -> bool {
        let mut probe = self.clone();
        let Some(blank) = probe.next_line() else {
            return false;
        };
        if !blank.trim().is_empty() {
            return false;
        }
        section_follows(&mut probe)
    }

    fn blank_opens_velocity_block(&mut self) -> bool {
        match self.peek_line() {
            Some(line) if line.trim().is_empty() => self.blank_line_opens_section(),
            _ => true,
        }
    }
}

/// True when `line` has the words `of` and `Component` in that order.
pub(crate) fn line_has_component_label(line: &str) -> bool {
    let mut words = line.split_ascii_whitespace();
    while let Some(word) = words.next() {
        if word.eq_ignore_ascii_case("of")
            && words
                .next()
                .is_some_and(|next| next.eq_ignore_ascii_case("component"))
        {
            return true;
        }
    }
    false
}

fn section_follows<'a>(lines: &mut impl LineStream<'a>) -> bool {
    let Some(symbol) = lines.next_line() else {
        return false;
    };
    if symbol.trim().is_empty() || symbol.trim_start().starts_with('{') {
        return false;
    }
    let Some(label) = lines.next_line() else {
        return false;
    };
    line_has_component_label(label)
}

/// Length of the stack buffer of [`parse_line_of_range_f64_stack`]: the most
/// columns an atom line has, which are x, y, z, the flag and the optional id
/// (spec "Coordinates").
pub const NUMERIC_STACK_WIDTH: usize = COORD_ROW_MIN_COLUMNS + 1;

/// Hot-path: parse up to [`NUMERIC_STACK_WIDTH`] whitespace-separated f64s
/// into a stack buffer.
/// Returns count of tokens actually present (before padding).
/// Pads `out[found..max]` from `defaults` when `found < max` and `found >= min`.
///
/// Single-pass over the line bytes: skip ASCII whitespace, then
/// [`fast_float2::parse_partial`] (Eisel–Lemire / SIMD-class decimal kernel)
/// with a token-boundary check. No `SplitWhitespace`, no per-token `&str`,
/// no heap `Vec`. Prefer this over allocating [`parse_line_of_n_f64`] on atom lines.
#[inline]
pub fn parse_line_of_range_f64_stack(
    line: &str,
    min: usize,
    max: usize,
    defaults: &[f64],
    out: &mut [f64; NUMERIC_STACK_WIDTH],
) -> Result<usize, ParseError> {
    debug_assert!(max <= NUMERIC_STACK_WIDTH && min <= max && defaults.len() >= max);
    let bytes = line.as_bytes();
    let n = bytes.len();
    let mut i = 0usize;
    let mut found = 0usize;
    while found < max {
        while i < n && bytes[i].is_ascii_whitespace() {
            i += 1;
        }
        if i >= n {
            break;
        }
        let end = bytes[i..]
            .iter()
            .position(|b| b.is_ascii_whitespace())
            .map(|k| i + k)
            .unwrap_or(n);
        // The line is already UTF-8. A plain decimal is accepted here, so the
        // general parser (and its UTF-8 check of the token) runs only when
        // this scan refuses the token.
        if let Some((val, next)) = crate::fast_dec::parse_f64_hot(bytes, i)
            && next == end
            && val.is_finite()
        {
            out[found] = val;
            found += 1;
            i = next;
            continue;
        }
        let token = std::str::from_utf8(&bytes[i..end]).unwrap_or("");
        if is_nonfinite_spelling(token) {
            return Err(ParseError::NonFiniteValue(token.to_string()));
        }
        let (val, consumed) = fast_float2::parse_partial::<f64, _>(&bytes[i..])
            .map_err(|_| ParseError::InvalidNumberFormat(format!("invalid float: {token}")))?;
        let next = i + consumed;
        // Reject partial tokens like "1.2abc" (must end at whitespace or EOS).
        if next != end {
            return Err(ParseError::InvalidNumberFormat(format!(
                "invalid float: {token}"
            )));
        }
        if !val.is_finite() {
            return Err(ParseError::NonFiniteValue(token.to_string()));
        }
        out[found] = val;
        found += 1;
        i = next;
    }
    while i < n && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    // Reject trailing extra tokens (same contract as the old split loop).
    if i < n {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found: found + 1,
        });
    }
    if found < min || found > max {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found,
        });
    }
    while found < max {
        out[found] = defaults[found];
        found += 1;
    }
    Ok(found)
}

fn read_header_f64s<const N: usize>(line: &str) -> Result<[f64; N], ParseError> {
    let mut out = [0.0; N];
    if scan_header_f64s(line, N, &mut out) {
        return Ok(out);
    }
    let parsed = parse_line_of_n_f64(line, N)?;
    out.copy_from_slice(&parsed);
    Ok(out)
}

fn read_header_f64_vec(line: &str, n: usize) -> Result<Vec<f64>, ParseError> {
    if n <= 8 {
        let mut buf = [0.0; 8];
        if scan_header_f64s(line, n, &mut buf) {
            return Ok(buf[..n].to_vec());
        }
    }
    parse_line_of_n_f64(line, n)
}

/// `n` plain decimals separated by spaces or tabs. `false` when the shape
/// needs the general parser (an exponent, a non-finite token, a bad width).
fn scan_header_f64s(line: &str, n: usize, out: &mut [f64]) -> bool {
    if n > out.len() {
        return false;
    }
    let bytes = line.as_bytes();
    let mut i = 0usize;
    let mut found = 0usize;
    while found < n {
        while i < bytes.len() && is_header_ws(bytes[i]) {
            i += 1;
        }
        if i >= bytes.len() {
            return false;
        }
        let Some((val, next)) = crate::fast_dec::parse_f64_hot(bytes, i) else {
            return false;
        };
        if next < bytes.len() && !is_header_ws(bytes[next]) {
            return false;
        }
        out[found] = val;
        found += 1;
        i = next;
    }
    while i < bytes.len() && is_header_ws(bytes[i]) {
        i += 1;
    }
    i == bytes.len()
}

fn is_header_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\r' | 0x0c)
}

/// Parses a line of whitespace-separated f64 values using fast-float2.
///
/// This is the hot-path parser for coordinate and velocity lines. It uses
/// `fast_float2::parse` instead of `str::parse::<f64>()` for better throughput
/// on the numeric-heavy atom data lines. Fixed-width atom lines use
/// [`parse_line_of_range_f64_stack`] to avoid a heap `Vec` per line.
///
/// # Arguments
///
/// * `line` - A string slice representing a single line of data.
/// * `n` - The exact number of f64 values expected on the line.
pub fn parse_line_of_n_f64(line: &str, n: usize) -> Result<Vec<f64>, ParseError> {
    if n <= NUMERIC_STACK_WIDTH {
        let defaults = [0.0f64; NUMERIC_STACK_WIDTH];
        let mut buf = [0.0f64; NUMERIC_STACK_WIDTH];
        parse_line_of_range_f64_stack(line, n, n, &defaults, &mut buf)?;
        return Ok(buf[..n].to_vec());
    }
    let mut values = Vec::with_capacity(n.min(max_tokens_on_line(line)));
    for token in line.split_ascii_whitespace() {
        values.push(parse_finite_float_token(token)?);
    }
    if values.len() == n {
        Ok(values)
    } else {
        Err(ParseError::InvalidVectorLength {
            expected: n,
            found: values.len(),
        })
    }
}

/// Parses a line of whitespace-separated f64 values, accepting between `min`
/// and `max` values (inclusive). Returns a vector of exactly `max` elements,
/// padding with values from `defaults` when fewer than `max` are present.
///
/// Used for atom lines where column 5 (atom_index) is optional.
/// Prefer [`parse_line_of_range_f64_stack`] on the atom hot path
/// (`max <= NUMERIC_STACK_WIDTH`).
pub fn parse_line_of_range_f64(
    line: &str,
    min: usize,
    max: usize,
    defaults: &[f64],
) -> Result<Vec<f64>, ParseError> {
    if max <= NUMERIC_STACK_WIDTH {
        let mut buf = [0.0f64; NUMERIC_STACK_WIDTH];
        parse_line_of_range_f64_stack(line, min, max, defaults, &mut buf)?;
        return Ok(buf[..max].to_vec());
    }
    let mut values = Vec::with_capacity(max);
    for token in line.split_ascii_whitespace() {
        values.push(parse_finite_float_token(token)?);
    }
    if values.len() < min || values.len() > max {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found: values.len(),
        });
    }
    while values.len() < max {
        let idx = values.len();
        values.push(defaults[idx]);
    }
    Ok(values)
}

/// CON-num.1 spellings. A leading sign is optional. Case is ignored.
/// Digit and dot tokens return before any letter compare so the atom
/// hot path does not allocate.
fn is_nonfinite_spelling(token: &str) -> bool {
    let rest = token
        .strip_prefix('+')
        .or_else(|| token.strip_prefix('-'))
        .unwrap_or(token);
    match rest.as_bytes().first() {
        Some(b) if b.is_ascii_digit() || *b == b'.' => return false,
        None => return false,
        _ => {}
    }
    rest.eq_ignore_ascii_case("nan")
        || rest.eq_ignore_ascii_case("inf")
        || rest.eq_ignore_ascii_case("infinity")
}

fn parse_finite_float_token(token: &str) -> Result<f64, ParseError> {
    if is_nonfinite_spelling(token) {
        return Err(ParseError::NonFiniteValue(token.to_string()));
    }
    let (val, consumed) = fast_float2::parse_partial::<f64, _>(token.as_bytes())
        .map_err(|_| ParseError::InvalidNumberFormat(format!("invalid float: {token}")))?;
    if consumed != token.len() {
        return Err(ParseError::InvalidNumberFormat(format!(
            "invalid float: {token}"
        )));
    }
    if !val.is_finite() {
        return Err(ParseError::NonFiniteValue(token.to_string()));
    }
    Ok(val)
}

fn skip_ascii_ws(bytes: &[u8], mut i: usize) -> usize {
    while i < bytes.len() && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    i
}

fn take_token(line: &str, i: usize) -> Option<(&str, usize)> {
    let bytes = line.as_bytes();
    if i >= bytes.len() {
        return None;
    }
    let mut j = i;
    while j < bytes.len() && !bytes[j].is_ascii_whitespace() {
        j += 1;
    }
    Some((&line[i..j], j))
}

/// Column 4. A sign, a decimal point, or a value outside the spec's set
/// is `InvalidFixedFlag` in every mode (CON-mask.1, CON-mask.5, D8).
fn parse_fixed_flag(token: &str, spec_version: u32) -> Result<[bool; 3], ParseError> {
    let bad = || {
        ParseError::InvalidFixedFlag(format!(
            "column 4 flag {token:?} is not a legal integer for spec {spec_version}"
        ))
    };
    if token.is_empty() || !token.bytes().all(|b| b.is_ascii_digit()) {
        return Err(bad());
    }
    let val: u64 = token.parse::<u64>().map_err(|_| bad())?;
    if spec_version < 2 {
        return match val {
            0 => Ok([false, false, false]),
            1 => Ok([true, true, true]),
            _ => Err(bad()),
        };
    }
    if val > 7 {
        return Err(bad());
    }
    let v = val as u8;
    Ok([v & 1 != 0, v & 2 != 0, v & 4 != 0])
}

/// Column 5. Digits only, parsed as `u64`, never through `f64` (CON-id.1, D9).
/// A sign or a decimal point is `InvalidNumberFormat` at the token level.
fn parse_atom_id_token(token: &str) -> Result<u64, ParseError> {
    if token.is_empty() || !token.bytes().all(|b| b.is_ascii_digit()) {
        return Err(ParseError::InvalidNumberFormat(format!(
            "invalid integer: {token}"
        )));
    }
    token.parse::<u64>().map_err(|_| {
        ParseError::InvalidNumberFormat(format!("integer out of range 0..=2^64-1: {token}"))
    })
}

/// Coordinate row: three finite floats, an integer flag, and an optional id.
/// Four columns take `default_id`, the 0-based position in the frame
/// (CON-id.9). Any other width is `InvalidVectorLength` (CON-num.9).
fn parse_coord_row(
    line: &str,
    spec_version: u32,
    default_id: u64,
) -> Result<([f64; 3], [bool; 3], u64), ParseError> {
    parse_vector_row(line, spec_version, Some(default_id))
}

/// Vector section row. The flag and id columns are required (exact width 5).
fn parse_vector_section_row(
    line: &str,
    spec_version: u32,
) -> Result<([f64; 3], [bool; 3], u64), ParseError> {
    parse_vector_row(line, spec_version, None)
}

fn parse_vector_row(
    line: &str,
    spec_version: u32,
    default_id: Option<u64>,
) -> Result<([f64; 3], [bool; 3], u64), ParseError> {
    let (row, end) = parse_coord_fields(line.as_bytes(), 0, spec_version, default_id)?;
    if end != line.len() {
        let found = 5 + count_tokens_on_line(line.as_bytes(), end);
        return Err(ParseError::InvalidVectorLength { expected: 5, found });
    }
    Ok(row)
}

/// Field separator inside a coordinate row. Newline ends the row.
#[inline(always)]
fn is_field_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\r' | 0x0c)
}

#[inline(always)]
fn skip_field_ws(bytes: &[u8], mut i: usize) -> usize {
    while i < bytes.len() && is_field_ws(bytes[i]) {
        i += 1;
    }
    i
}

fn token_on_line(bytes: &[u8], i: usize) -> String {
    let mut j = i;
    while j < bytes.len() && !is_field_ws(bytes[j]) && bytes[j] != b'\n' {
        j += 1;
    }
    String::from_utf8_lossy(&bytes[i..j]).into_owned()
}

fn count_tokens_on_line(bytes: &[u8], mut i: usize) -> usize {
    let mut n = 0usize;
    loop {
        i = skip_field_ws(bytes, i);
        if i >= bytes.len() || bytes[i] == b'\n' {
            break;
        }
        n += 1;
        while i < bytes.len() && !is_field_ws(bytes[i]) && bytes[i] != b'\n' {
            i += 1;
        }
    }
    n
}

/// Invalid UTF-8 in a numeric row, otherwise a normal number-format error.
fn utf8_or_number(bytes: &[u8], line_start: usize, i: usize) -> ParseError {
    let end = bytes[line_start..]
        .iter()
        .position(|b| *b == b'\n')
        .map(|p| line_start + p)
        .unwrap_or(bytes.len());
    if std::str::from_utf8(&bytes[line_start..end]).is_err() {
        return ParseError::ValidationError("invalid UTF-8".into());
    }
    ParseError::InvalidNumberFormat(format!("invalid float: {}", token_on_line(bytes, i)))
}

#[inline(always)]
fn parse_f64_at(bytes: &[u8], i: usize, line_start: usize) -> Result<(f64, usize), ParseError> {
    if i >= bytes.len() || bytes[i] == b'\n' {
        return Err(ParseError::InvalidVectorLength {
            expected: 5,
            found: 0,
        });
    }
    if bytes[i] >= 0x80 {
        return Err(utf8_or_number(bytes, line_start, i));
    }
    if looks_like_nonfinite(bytes, i) {
        let token = token_on_line(bytes, i);
        if is_nonfinite_spelling(&token) {
            return Err(ParseError::NonFiniteValue(token));
        }
    }
    let (val, consumed) = fast_float2::parse_partial::<f64, _>(&bytes[i..]).map_err(|_| {
        ParseError::InvalidNumberFormat(format!("invalid float: {}", token_on_line(bytes, i)))
    })?;
    let next = i + consumed;
    let boundary = next >= bytes.len() || is_field_ws(bytes[next]) || bytes[next] == b'\n';
    if !boundary || !val.is_finite() {
        let token = token_on_line(bytes, i);
        if is_nonfinite_spelling(&token) || !val.is_finite() {
            return Err(ParseError::NonFiniteValue(token));
        }
        return Err(ParseError::InvalidNumberFormat(format!(
            "invalid float: {token}"
        )));
    }
    Ok((val, next))
}

#[inline(always)]
fn parse_flag_at(
    bytes: &[u8],
    i: usize,
    spec_version: u32,
) -> Result<([bool; 3], usize), ParseError> {
    if i >= bytes.len() || bytes[i] == b'\n' {
        return Err(ParseError::InvalidVectorLength {
            expected: 5,
            found: 3,
        });
    }
    let bad = || {
        ParseError::InvalidFixedFlag(format!(
            "column 4 flag {:?} is not a legal integer for spec {spec_version}",
            token_on_line(bytes, i)
        ))
    };
    if !bytes[i].is_ascii_digit() {
        return Err(bad());
    }
    let mut j = i;
    let mut val: u64 = 0;
    while j < bytes.len() && bytes[j].is_ascii_digit() {
        let d = u64::from(bytes[j] - b'0');
        val = val
            .checked_mul(10)
            .and_then(|v| v.checked_add(d))
            .ok_or_else(bad)?;
        j += 1;
    }
    if j < bytes.len() && !is_field_ws(bytes[j]) && bytes[j] != b'\n' {
        return Err(bad());
    }
    let fixed = if spec_version < 2 {
        match val {
            0 => [false, false, false],
            1 => [true, true, true],
            _ => return Err(bad()),
        }
    } else if val <= 7 {
        let v = val as u8;
        [v & 1 != 0, v & 2 != 0, v & 4 != 0]
    } else {
        return Err(bad());
    };
    Ok((fixed, j))
}

#[inline(always)]
fn parse_id_at(bytes: &[u8], i: usize) -> Result<(u64, usize), ParseError> {
    if i >= bytes.len() || bytes[i] == b'\n' || !bytes[i].is_ascii_digit() {
        return Err(ParseError::InvalidNumberFormat(format!(
            "invalid integer: {}",
            token_on_line(bytes, i)
        )));
    }
    let mut j = i;
    let mut val: u64 = 0;
    while j < bytes.len() && bytes[j].is_ascii_digit() {
        let d = u64::from(bytes[j] - b'0');
        val = val
            .checked_mul(10)
            .and_then(|v| v.checked_add(d))
            .ok_or_else(|| {
                ParseError::InvalidNumberFormat(format!(
                    "integer out of range 0..=2^64-1: {}",
                    token_on_line(bytes, i)
                ))
            })?;
        j += 1;
    }
    if j < bytes.len() && !is_field_ws(bytes[j]) && bytes[j] != b'\n' {
        return Err(ParseError::InvalidNumberFormat(format!(
            "invalid integer: {}",
            token_on_line(bytes, i)
        )));
    }
    Ok((val, j))
}

/// One parsed coordinate row: xyz, fixed flags, and the atom id.
type ParsedCoord = ([f64; 3], [bool; 3], u64);

fn skip_row_spaces(bytes: &[u8], mut i: usize) -> usize {
    while i < bytes.len() && bytes[i] == b' ' {
        i += 1;
    }
    i
}

fn fixed_flag(digit: u8, spec_version: u32) -> Option<[bool; 3]> {
    if spec_version < 2 {
        match digit {
            0 => Some([false, false, false]),
            1 => Some([true, true, true]),
            _ => None,
        }
    } else if digit <= 7 {
        Some([digit & 1 != 0, digit & 2 != 0, digit & 4 != 0])
    } else {
        None
    }
}

/// One coordinate row whose three values use a dot and 16 or 17 fraction digits.
///
/// The line end was found once, before this function. Fields are then read in
/// a single left-to-right pass. Anything else returns `None` so the general
/// row parser can take the line.
#[inline(never)]
fn parse_fixed_line(
    mut line: &[u8],
    spec_version: u32,
    default_id: Option<u64>,
) -> Option<ParsedCoord> {
    if line.last() == Some(&b'\r') {
        line = &line[..line.len() - 1];
    }
    let mut i = skip_row_spaces(line, 0);
    let mut xyz = [0.0f64; 3];
    for slot in &mut xyz {
        let (val, next) = crate::fast_dec::parse_fixed_decimal(line, i)?;
        *slot = val;
        i = skip_row_spaces(line, next);
    }
    let digit = *line.get(i)?;
    if !digit.is_ascii_digit() {
        return None;
    }
    let flag = digit - b'0';
    if i + 1 < line.len() && line[i + 1].is_ascii_digit() {
        return None;
    }
    let fixed = fixed_flag(flag, spec_version)?;
    i = skip_row_spaces(line, i + 1);
    let (atom_id, next) = if i >= line.len() {
        (default_id?, i)
    } else {
        let mut j = i;
        let mut val = 0u64;
        let mut digits = 0u32;
        if !line[j].is_ascii_digit() {
            return None;
        }
        while j < line.len() && line[j].is_ascii_digit() {
            digits += 1;
            if digits > 18 {
                return None;
            }
            val = val * 10 + u64::from(line[j] - b'0');
            j += 1;
        }
        (val, j)
    };
    i = skip_row_spaces(line, next);
    if i != line.len() {
        return None;
    }
    Some((xyz, fixed, atom_id))
}

pub(crate) struct CoordBlock<'a> {
    pub pos_flat: &'a mut Vec<f64>,
    pub ids: &'a mut Vec<u64>,
    pub atom_data: &'a mut Vec<AtomDatum>,
}

pub(crate) struct BlockCursor {
    pub pos: usize,
    pub lines: u32,
    pub atom_id: u64,
}

/// Read `n` coordinate rows, finding each newline once for the whole block.
pub(crate) fn fill_coord_block(
    bytes: &[u8],
    n: usize,
    spec_version: u32,
    symbol: &Arc<str>,
    reuse: bool,
    cursor: &mut BlockCursor,
    out: &mut CoordBlock<'_>,
) -> Result<(), ParseError> {
    let mut shares = if reuse {
        None
    } else {
        Some(symbol_shares(symbol, n))
    };
    let frame_base = cursor.atom_id as usize;
    out.pos_flat.reserve(n.saturating_mul(3));
    out.ids.reserve(n);
    if !reuse {
        out.atom_data.reserve(n);
    }
    for i in 0..n {
        if cursor.pos >= bytes.len() {
            return Err(ParseError::IncompleteFrame);
        }
        let rest = &bytes[cursor.pos..];
        let nl = memchr::memchr(b'\n', rest);
        let (raw, next) = match nl {
            Some(cut) => (&rest[..cut], cursor.pos + cut + 1),
            None => (rest, bytes.len()),
        };
        cursor.lines = cursor.lines.saturating_add(1);
        let line = if raw.last() == Some(&b'\r') {
            &raw[..raw.len() - 1]
        } else {
            raw
        };
        let row = if line.len() >= 48 {
            parse_fixed_line(line, spec_version, Some(cursor.atom_id))
        } else {
            None
        };
        let (xyz, fixed, atom_id) = if let Some(row) = row {
            row
        } else {
            parse_coord_fields(line, 0, spec_version, Some(cursor.atom_id))?.0
        };
        let index = frame_base + i;
        store_coord(
            out,
            index,
            xyz,
            fixed,
            atom_id,
            shares.as_mut().map(|shares| shares.take()),
        );
        cursor.atom_id = cursor.atom_id.saturating_add(1);
        cursor.pos = next;
        if nl.is_none() && i + 1 < n {
            return Err(ParseError::IncompleteFrame);
        }
    }
    Ok(())
}

fn store_coord(
    out: &mut CoordBlock<'_>,
    index: usize,
    xyz: [f64; 3],
    fixed: [bool; 3],
    atom_id: u64,
    symbol: Option<Arc<str>>,
) {
    let pos_at = index * 3;
    debug_assert!(out.pos_flat.capacity() >= pos_at + 3);
    debug_assert!(out.ids.capacity() > index);
    unsafe {
        let p = out.pos_flat.as_mut_ptr().add(pos_at);
        p.write(xyz[0]);
        p.add(1).write(xyz[1]);
        p.add(2).write(xyz[2]);
        out.ids.as_mut_ptr().add(index).write(atom_id);
        if out.pos_flat.len() < pos_at + 3 {
            out.pos_flat.set_len(pos_at + 3);
        }
        if out.ids.len() <= index {
            out.ids.set_len(index + 1);
        }
    }
    match symbol {
        Some(sym) => {
            let atom = AtomDatum::coords(sym, xyz[0], xyz[1], xyz[2], fixed, atom_id);
            if index == out.atom_data.len() {
                out.atom_data.reserve(1);
                unsafe {
                    out.atom_data.as_mut_ptr().add(index).write(atom);
                    out.atom_data.set_len(index + 1);
                }
            } else {
                out.atom_data[index] = atom;
            }
        }
        None => out.atom_data[index].set_coords(xyz, fixed, atom_id),
    }
}

/// One coordinate or vector row starting at `i`.
///
/// Stops at newline or end of `bytes` and returns the index just past the
/// row (after the newline, when one was present). Floats, the flag, and the
/// id are parsed in that single scan. The success path does not build error
/// strings; those stay on the cold fallback.
#[inline(always)]
fn parse_coord_fields(
    bytes: &[u8],
    i: usize,
    spec_version: u32,
    default_id: Option<u64>,
) -> Result<(ParsedCoord, usize), ParseError> {
    if let Some(parsed) = parse_coord_fields_fast(bytes, i, spec_version, default_id) {
        return Ok(parsed);
    }
    parse_coord_fields_detailed(bytes, i, spec_version, default_id)
}

/// Common coordinate row: three finite decimals, a small flag, an optional id.
#[inline(always)]
fn parse_coord_fields_fast(
    bytes: &[u8],
    i: usize,
    spec_version: u32,
    default_id: Option<u64>,
) -> Option<(ParsedCoord, usize)> {
    let mut i = skip_field_ws(bytes, i);
    let mut xyz = [0.0f64; 3];
    for dest in &mut xyz {
        if i >= bytes.len() || bytes[i] == b'\n' || bytes[i] >= 0x80 {
            return None;
        }
        // A 20-digit fixed-point dump does not fit the 19-digit hot scan.
        // Resolve that token here so the other two fields stay on the hot scan
        // instead of the whole row falling through to the general parser.
        let (val, next) = match crate::fast_dec::parse_f64_hot(bytes, i) {
            Some(parsed) => parsed,
            None => crate::fast_dec::parse_f64_long(bytes, i)?,
        };
        if next < bytes.len() && !is_field_ws(bytes[next]) && bytes[next] != b'\n' {
            return None;
        }
        *dest = val;
        i = skip_field_ws(bytes, next);
    }
    let (fixed, next) = parse_flag_fast(bytes, i, spec_version)?;
    i = skip_field_ws(bytes, next);
    let (atom_id, next) = if i >= bytes.len() || bytes[i] == b'\n' {
        (default_id?, i)
    } else {
        parse_u64_fast(bytes, i)?
    };
    i = skip_field_ws(bytes, next);
    if i < bytes.len() && bytes[i] != b'\n' {
        return None;
    }
    if i < bytes.len() && bytes[i] == b'\n' {
        i += 1;
    }
    Some(((xyz, fixed, atom_id), i))
}

#[inline(always)]
fn parse_u64_fast(bytes: &[u8], i: usize) -> Option<(u64, usize)> {
    if i >= bytes.len() || !bytes[i].is_ascii_digit() {
        return None;
    }
    let mut j = i;
    let mut val: u64 = 0;
    let mut digits = 0u32;
    while j < bytes.len() && bytes[j].is_ascii_digit() {
        digits += 1;
        // 19 digits can overflow u64; the detailed parser reports that.
        if digits > 18 {
            return None;
        }
        val = val * 10 + u64::from(bytes[j] - b'0');
        j += 1;
    }
    if j < bytes.len() && !is_field_ws(bytes[j]) && bytes[j] != b'\n' {
        return None;
    }
    Some((val, j))
}

#[inline(always)]
fn parse_flag_fast(bytes: &[u8], i: usize, spec_version: u32) -> Option<([bool; 3], usize)> {
    let (val, j) = parse_u64_fast(bytes, i)?;
    let fixed = if spec_version < 2 {
        match val {
            0 => [false, false, false],
            1 => [true, true, true],
            _ => return None,
        }
    } else if val <= 7 {
        let v = val as u8;
        [v & 1 != 0, v & 2 != 0, v & 4 != 0]
    } else {
        return None;
    };
    Some((fixed, j))
}

#[cold]
#[inline(never)]
fn parse_coord_fields_detailed(
    bytes: &[u8],
    i: usize,
    spec_version: u32,
    default_id: Option<u64>,
) -> Result<(ParsedCoord, usize), ParseError> {
    let line_start = i;
    let mut i = skip_field_ws(bytes, i);
    if i >= bytes.len() || bytes[i] == b'\n' {
        return Err(ParseError::InvalidVectorLength {
            expected: 5,
            found: 0,
        });
    }
    let mut xyz = [0.0f64; 3];
    for (slot, dest) in xyz.iter_mut().enumerate() {
        if i >= bytes.len() || bytes[i] == b'\n' {
            return Err(ParseError::InvalidVectorLength {
                expected: 5,
                found: slot,
            });
        }
        if bytes[i] >= 0x80 {
            return Err(utf8_or_number(bytes, line_start, i));
        }
        let (val, next) = parse_f64_at(bytes, i, line_start)?;
        *dest = val;
        i = skip_field_ws(bytes, next);
    }
    let (fixed, next) = parse_flag_at(bytes, i, spec_version)?;
    i = skip_field_ws(bytes, next);
    let (atom_id, next) = if i >= bytes.len() || bytes[i] == b'\n' {
        (
            default_id.ok_or(ParseError::InvalidVectorLength {
                expected: 5,
                found: 4,
            })?,
            i,
        )
    } else {
        parse_id_at(bytes, i)?
    };
    i = skip_field_ws(bytes, next);
    if i < bytes.len() && bytes[i] != b'\n' {
        let found = 5 + count_tokens_on_line(bytes, i);
        return Err(ParseError::InvalidVectorLength { expected: 5, found });
    }
    if i < bytes.len() && bytes[i] == b'\n' {
        i += 1;
    }
    Ok(((xyz, fixed, atom_id), i))
}

/// Coordinate row at byte offset `i` in a multi-line buffer.
///
/// The returned index is the start of the next line. ASCII rows are valid
/// UTF-8 without a separate scan; a non-ASCII byte is checked only then.
pub(crate) fn parse_coord_row_at(
    bytes: &[u8],
    i: usize,
    spec_version: u32,
    default_id: u64,
) -> Result<(ParsedCoord, usize), ParseError> {
    if i >= bytes.len() {
        return Err(ParseError::IncompleteFrame);
    }
    parse_coord_fields(bytes, i, spec_version, Some(default_id))
}

/// Vector-section row at `i`. The id column is required.
pub(crate) fn parse_vector_row_at(
    bytes: &[u8],
    i: usize,
    spec_version: u32,
) -> Result<(ParsedCoord, usize), ParseError> {
    if i >= bytes.len() {
        return Err(ParseError::IncompleteFrame);
    }
    parse_coord_fields(bytes, i, spec_version, None)
}

/// Scalar section row: one finite float, a flag, and an id. Exact width 3.
fn parse_scalar_section_row(
    line: &str,
    spec_version: u32,
) -> Result<(f64, [bool; 3], u64), ParseError> {
    let bytes = line.as_bytes();
    let i = skip_ascii_ws(bytes, 0);
    let (value, i) = parse_finite_at(line, i)?;
    let i = skip_ascii_ws(bytes, i);
    let (flag_tok, i) = take_token(line, i).ok_or(ParseError::InvalidVectorLength {
        expected: 3,
        found: 1,
    })?;
    let fixed = parse_fixed_flag(flag_tok, spec_version)?;
    let i = skip_ascii_ws(bytes, i);
    let (id_tok, i) = take_token(line, i).ok_or(ParseError::InvalidVectorLength {
        expected: 3,
        found: 2,
    })?;
    let atom_id = parse_atom_id_token(id_tok)?;
    let i = skip_ascii_ws(bytes, i);
    if i < bytes.len() {
        let found = 3 + line[i..].split_ascii_whitespace().count();
        return Err(ParseError::InvalidVectorLength { expected: 3, found });
    }
    Ok((value, fixed, atom_id))
}

fn parse_finite_at(line: &str, i: usize) -> Result<(f64, usize), ParseError> {
    let bytes = line.as_bytes();
    if i >= bytes.len() {
        return Err(ParseError::InvalidVectorLength {
            expected: 3,
            found: 0,
        });
    }
    // "infinity" parses as the prefix "inf" in fast_float2. Name that
    // spelling before the numeric kernel so the leftover is not a format error.
    if looks_like_nonfinite(bytes, i) {
        let token = take_token(line, i).map(|(tok, _)| tok).unwrap_or("");
        if is_nonfinite_spelling(token) {
            return Err(ParseError::NonFiniteValue(token.to_string()));
        }
    }
    let (val, consumed) = fast_float2::parse_partial::<f64, _>(&bytes[i..]).map_err(|_| {
        let token = take_token(line, i).map(|(tok, _)| tok).unwrap_or("");
        ParseError::InvalidNumberFormat(format!("invalid float: {token}"))
    })?;
    let next = i + consumed;
    let boundary = next == bytes.len() || bytes[next].is_ascii_whitespace();
    if !boundary || !val.is_finite() {
        let token = take_token(line, i).map(|(tok, _)| tok).unwrap_or("");
        if is_nonfinite_spelling(token) || !val.is_finite() {
            return Err(ParseError::NonFiniteValue(token.to_string()));
        }
        return Err(ParseError::InvalidNumberFormat(format!(
            "invalid float: {token}"
        )));
    }
    Ok((val, next))
}

/// True when the token may be a non-finite spelling. Digit and dot
/// tokens, the common atom-line case, are false after one byte.
fn looks_like_nonfinite(bytes: &[u8], i: usize) -> bool {
    let mut j = i;
    if bytes[j] == b'+' || bytes[j] == b'-' {
        j += 1;
        if j >= bytes.len() {
            return false;
        }
    }
    let b = bytes[j];
    !b.is_ascii_digit() && b != b'.'
}

/// Case-insensitive, after collapsing each run of spaces (CON-file.5, D17).
fn labels_equal(found: &str, expected: &str) -> bool {
    let mut found_words = found.split_ascii_whitespace();
    let mut expected_words = expected.split_ascii_whitespace();
    loop {
        match (found_words.next(), expected_words.next()) {
            (Some(a), Some(b)) => {
                if !a.eq_ignore_ascii_case(b) {
                    return false;
                }
            }
            (None, None) => return true,
            _ => return false,
        }
    }
}

/// True when `line`, after the same folding, starts with every word of `prefix`.
fn label_has_prefix(line: &str, prefix: &str) -> bool {
    let mut found_words = line.split_ascii_whitespace();
    for word in prefix.split_ascii_whitespace() {
        match found_words.next() {
            Some(got) if got.eq_ignore_ascii_case(word) => {}
            _ => return false,
        }
    }
    true
}

fn token_count(line: &str) -> usize {
    line.split_ascii_whitespace().count()
}

/// Most whitespace-separated tokens `line` can hold.
///
/// `k` tokens take at least one byte each and one separator between each
/// pair, `2k - 1` bytes in all.
fn max_tokens_on_line(line: &str) -> usize {
    line.len().div_ceil(2)
}

fn json_u64(value: &Value) -> Option<u64> {
    value.as_u64()
}

fn validate_section_arity_value(value: &Value) -> Result<(), ParseError> {
    let obj = value.as_object().ok_or_else(|| {
        metadata_json_error("section_arity must be an object mapping section names to integers")
    })?;
    for (name, entry) in obj {
        let n = json_u64(entry).ok_or_else(|| {
            metadata_json_error(format!("section_arity.{name} must be an integer >= 1"))
        })?;
        if n < 1 {
            return Err(ParseError::InvalidCount(format!(
                "section_arity.{name} must be >= 1"
            )));
        }
        // Reserved names have a fixed value-field count (CON-section.13).
        if let Some(expect) = crate::types::reserved_section_value_arity(name)
            && n != expect
        {
            return Err(ParseError::InvalidVectorLength {
                expected: usize::try_from(expect).unwrap_or(usize::MAX),
                found: usize::try_from(n).unwrap_or(usize::MAX),
            });
        }
    }
    Ok(())
}

/// Integer counts. A sign, a decimal point, or any other non-digit token
/// is `InvalidCount` (CON-error.3). Zero is a legal token here. The caller
/// rejects a per-type count of 0 when the type count is 1 or more (D4).
pub(crate) fn parse_count_line(line: &str, n: usize) -> Result<Vec<usize>, ParseError> {
    let mut values = Vec::with_capacity(n.min(max_tokens_on_line(line)));
    for token in line.split_ascii_whitespace() {
        if token.is_empty() || !token.bytes().all(|b| b.is_ascii_digit()) {
            return Err(ParseError::InvalidCount(format!(
                "count field is not an unsigned integer: {token}"
            )));
        }
        let val: u64 = token.parse::<u64>().map_err(|_| {
            ParseError::InvalidCount(format!("count field is out of range: {token}"))
        })?;
        let val = usize::try_from(val).map_err(|_| {
            ParseError::InvalidCount(format!("count field is out of range: {token}"))
        })?;
        values.push(val);
    }
    if values.len() == n {
        Ok(values)
    } else {
        Err(ParseError::InvalidVectorLength {
            expected: n,
            found: values.len(),
        })
    }
}

/// True when `line` has no tokens. Spaces and tabs count as empty.
pub(crate) fn line_is_whitespace(line: &str) -> bool {
    line.split_ascii_whitespace().next().is_none()
}

/// Lines 8 and 9 of a type count of 0.
///
/// A token on either line is `InvalidCount`. At end of file, a missing
/// line is empty (CON-count.4), and that frame is not `IncompleteHeader`
/// (CON-frame.3). Mid-file, both lines are required.
pub(crate) fn read_zero_atom_tail<'a>(
    mut next_line: impl FnMut() -> Option<&'a str>,
) -> Result<(), ParseError> {
    let bad = || {
        ParseError::InvalidCount("a zero-atom frame requires whitespace-only lines 8 and 9".into())
    };
    match next_line() {
        None => Ok(()),
        Some(line) if line_is_whitespace(line) => match next_line() {
            None => Ok(()),
            Some(line) if line_is_whitespace(line) => Ok(()),
            Some(_) => Err(bad()),
        },
        Some(_) => Err(bad()),
    }
}

fn metadata_json_error(message: impl Into<String>) -> ParseError {
    ParseError::InvalidMetadataJson(message.into())
}

fn validate_metadata_number(key: &str, value: &Value) -> Result<(), ParseError> {
    if value.as_f64().is_some() {
        Ok(())
    } else {
        Err(metadata_json_error(format!(
            "{key} must be a finite number"
        )))
    }
}

fn validate_metadata_integer(key: &str, value: &Value) -> Result<(), ParseError> {
    if value.as_u64().is_some() {
        Ok(())
    } else {
        Err(metadata_json_error(format!(
            "{key} must be a non-negative integer"
        )))
    }
}

/// Validates a parsed metadata JSON object against the spec v2 schema.
///
/// Type-checks the `validate` and `sections` keys, then runs per-key
/// schema checks for the recommended metadata keys. Used by the
/// builder/Python `set_metadata_json` paths to fail fast on malformed
/// input, and by the parser when the file requested strict validation
/// via `"validate": true`.
pub fn validate_metadata_schema(
    json_obj: &serde_json::Map<String, Value>,
) -> Result<(), ParseError> {
    let strict_requested = match json_obj.get(meta::VALIDATE) {
        Some(Value::Bool(b)) => *b,
        Some(_) => return Err(metadata_json_error("validate must be a boolean")),
        None => false,
    };

    match json_obj.get(meta::SECTIONS) {
        Some(Value::Array(values)) => {
            if values.iter().any(|entry| !entry.is_string()) {
                return Err(metadata_json_error("sections must be an array of strings"));
            }
        }
        Some(_) => return Err(metadata_json_error("sections must be an array of strings")),
        None if strict_requested => {
            return Err(metadata_json_error(
                "validate=true requires a sections array, even when empty",
            ));
        }
        None => {}
    }

    for (key, value) in json_obj {
        match key.as_str() {
            meta::CON_SPEC_VERSION | meta::SECTIONS | meta::VALIDATE => {}
            meta::CON_SPEC_MINOR => {
                if json_u64(value).is_none() {
                    return Err(metadata_json_error(
                        "con_spec_minor must be a JSON integer >= 0",
                    ));
                }
            }
            meta::SECTION_ARITY => validate_section_arity_value(value)?,
            meta::ENERGY
            | meta::TIME
            | meta::TIMESTEP
            | meta::CONVERGENCE_FMAX
            | meta::CONVERGENCE_ENERGY
            | meta::FMAX => validate_metadata_number(key, value)?,
            meta::FRAME_INDEX | meta::NEB_BEAD | meta::NEB_BAND => {
                validate_metadata_integer(key, value)?
            }
            meta::GENERATOR if !value.is_string() => {
                return Err(metadata_json_error("generator must be a string"));
            }
            meta::GENERATOR => {}
            meta::UNITS | meta::POTENTIAL if !value.is_object() => {
                return Err(metadata_json_error(format!("{key} must be an object")));
            }
            meta::POTENTIAL => {
                if let Some(potential_type) = value.get("type")
                    && !potential_type.is_string()
                {
                    return Err(metadata_json_error("potential.type must be a string"));
                }
            }
            meta::UNITS => {
                // Full v3 checks (required keys) run when con_spec_version >= 3.
            }
            meta::PBC => validate_pbc_metadata(value)?,
            meta::BONDS => validate_bonds_metadata(value)?,
            meta::LATTICE_VECTORS => validate_lattice_vectors_metadata(value)?,
            meta::CONVERGED if !value.is_boolean() => {
                return Err(metadata_json_error("converged must be a boolean"));
            }
            meta::CONVERGED => {}
            _ => {}
        }
    }

    Ok(())
}

fn validate_pbc_metadata(value: &Value) -> Result<(), ParseError> {
    let Some(values) = value.as_array() else {
        return Err(metadata_json_error("pbc must be a length-3 boolean array"));
    };
    if values.len() != 3 || values.iter().any(|entry| !entry.is_boolean()) {
        return Err(metadata_json_error("pbc must be a length-3 boolean array"));
    }
    Ok(())
}

/// Validate optional `bonds` frame topology metadata.
///
/// Each element is either a length-2 non-negative integer pair `[i, j]` or an
/// object `{"i": i, "j": j, "order"?: integer}`. Indices are 0-based into
/// `atom_data` order (parser does not yet know atom count at metadata time;
/// bounds are enforced when projecting to chemfiles / selection).
fn validate_bonds_metadata(value: &Value) -> Result<(), ParseError> {
    let Some(items) = value.as_array() else {
        return Err(metadata_json_error("bonds must be an array"));
    };
    for (idx, item) in items.iter().enumerate() {
        if let Some(pair) = item.as_array() {
            if pair.len() != 2 {
                return Err(metadata_json_error(format!(
                    "bonds[{idx}] pair must have exactly two indices"
                )));
            }
            for (k, entry) in pair.iter().enumerate() {
                let Some(n) = entry.as_u64() else {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}][{k}] must be a non-negative integer"
                    )));
                };
                if n > u32::MAX as u64 {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}][{k}] index exceeds u32"
                    )));
                }
            }
            continue;
        }
        if let Some(obj) = item.as_object() {
            for key in ["i", "j"] {
                let Some(entry) = obj.get(key) else {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}] object must include \"{key}\""
                    )));
                };
                let Some(n) = entry.as_u64() else {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}].{key} must be a non-negative integer"
                    )));
                };
                if n > u32::MAX as u64 {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}].{key} index exceeds u32"
                    )));
                }
            }
            if let Some(order) = obj.get("order")
                && order.as_i64().is_none()
            {
                return Err(metadata_json_error(format!(
                    "bonds[{idx}].order must be an integer when present"
                )));
            }
            continue;
        }
        return Err(metadata_json_error(format!(
            "bonds[{idx}] must be [i, j] or {{\"i\": i, \"j\": j, \"order\"?: ...}}"
        )));
    }
    Ok(())
}

fn validate_lattice_vectors_metadata(value: &Value) -> Result<(), ParseError> {
    let Some(rows) = value.as_array() else {
        return Err(metadata_json_error(
            "lattice_vectors must be a 3x3 numeric array",
        ));
    };
    if rows.len() != 3 {
        return Err(metadata_json_error(
            "lattice_vectors must be a 3x3 numeric array",
        ));
    }
    for row in rows {
        let Some(entries) = row.as_array() else {
            return Err(metadata_json_error(
                "lattice_vectors must be a 3x3 numeric array",
            ));
        };
        if entries.len() != 3 || entries.iter().any(|entry| entry.as_f64().is_none()) {
            return Err(metadata_json_error(
                "lattice_vectors must be a 3x3 numeric array",
            ));
        }
    }
    Ok(())
}

/// Parses a line of whitespace-separated values into a vector of a specific type.
///
/// This generic helper function takes a string slice, splits it by whitespace,
/// and attempts to parse each substring into the target type `T`. The type `T`
/// must implement `std::str::FromStr`.
///
/// # Arguments
///
/// * `line` - A string slice representing a single line of data.
/// * `n` - The exact number of values expected on the line.
///
/// # Errors
///
/// * `ParseError::InvalidVectorLength` if the number of parsed values is not equal to `n`.
/// * Propagates any error from the `parse()` method of the target type `T`.
///
/// # Example
///
/// ```
/// use readcon_core::parser::parse_line_of_n;
/// let line = "10.5 20.0 30.5";
/// let values: Vec<f64> = parse_line_of_n(line, 3).unwrap();
/// assert_eq!(values, vec![10.5, 20.0, 30.5]);
///
/// let result = parse_line_of_n::<i32>(line, 2);
/// assert!(result.is_err());
/// ```
pub fn parse_line_of_n<T: std::str::FromStr>(line: &str, n: usize) -> Result<Vec<T>, ParseError>
where
    ParseError: From<<T as std::str::FromStr>::Err>,
{
    let values: Vec<T> = line
        .split_whitespace()
        .map(|s| s.parse::<T>())
        .collect::<Result<_, _>>()?;

    if values.len() == n {
        Ok(values)
    } else {
        Err(ParseError::InvalidVectorLength {
            expected: n,
            found: values.len(),
        })
    }
}

/// Parses the 9-line header of a `.con` file frame from an iterator.
///
/// This function consumes the next 9 lines from the given line iterator to
/// construct a `FrameHeader`. The iterator is advanced by 9 lines on success.
///
/// # Arguments
///
/// * `lines` - A mutable reference to an iterator that yields string slices.
///
/// # Errors
///
/// * `ParseError::IncompleteHeader` if the iterator has fewer than 9 lines remaining.
/// * Propagates any errors from `parse_line_of_n` if the numeric data within
///   the header is malformed.
///
/// # Panics
///
/// This function will panic if the intermediate vectors for box dimensions or angles,
/// after being successfully parsed, cannot be converted into fixed-size arrays.
/// This should not happen if `parse_line_of_n` is used correctly with `n=3`.
pub fn parse_frame_header<'a>(
    lines: &mut impl Iterator<Item = &'a str>,
) -> Result<FrameHeader, ParseError> {
    let prebox1 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    // CON-file.2: a leading BOM is rejected. It would sit on line 1.
    if prebox1.starts_with('\u{feff}') {
        return Err(ParseError::ValidationError(
            "file begins with a byte-order mark".into(),
        ));
    }
    let prebox2_raw = lines.next().ok_or(ParseError::IncompleteHeader)?;

    // Line 2: if it starts with '{', parse as JSON metadata (spec v2+).
    // Otherwise treat as a legacy (pre-v2) file with spec_version = 1.
    // One JSON object and nothing else (CON-line2.1). serde_json::from_str
    // rejects trailing junk after the value.
    let trimmed = prebox2_raw.trim();
    let (spec_version, metadata, sections, validate, sections_declared) =
        if trimmed == "{\"con_spec_version\":2}" {
            // The line written by every stock trajectory. Same object the
            // JSON parser would build: major 2, no extra keys.
            (2, BTreeMap::new(), Vec::new(), false, false)
        } else if trimmed.starts_with('{') {
            let json_val: serde_json::Value = serde_json::from_str(trimmed)
                .map_err(|e| ParseError::InvalidMetadataJson(e.to_string()))?;
            let json_obj = json_val.as_object().ok_or_else(|| {
                ParseError::InvalidMetadataJson("expected a JSON object".to_string())
            })?;
            let ver_value = json_obj
                .get(meta::CON_SPEC_VERSION)
                .ok_or(ParseError::MissingSpecVersion)?;
            let ver = json_u64(ver_value).ok_or_else(|| {
                ParseError::InvalidMetadataJson(
                    "con_spec_version must be a JSON integer, the major version".into(),
                )
            })?;
            if ver > u64::from(u32::MAX) {
                return Err(ParseError::UnsupportedVersion(u32::MAX));
            }
            let ver = ver as u32;
            // JSON majors 0 and 1 are UnsupportedVersion (CON-line2.5).
            // An unknown major is UnsupportedVersion (CON-line2.6).
            // Unknown minors of a known major are accepted (CON-line2.7, CON-status.1).
            if ver == 0 || ver == 1 || ver > crate::CON_SPEC_VERSION {
                return Err(ParseError::UnsupportedVersion(ver));
            }
            if ver >= 3 {
                match json_obj.get(meta::UNITS) {
                    Some(u) => crate::units::validate_v3_units_metadata(u)
                        .map_err(|e| ParseError::InvalidUnits(format!("v3 units: {e}")))?,
                    None => {
                        return Err(ParseError::InvalidUnits(
                        "con_spec_version >= 3 requires metadata \"units\" with length and energy"
                            .into(),
                    ));
                    }
                }
            }

            // Single pass over the JSON object: collect sections, capture the
            // validate flag, copy the rest into metadata. Folds the previous
            // pre-extract get(validate) + re-iterate pattern into one walk.
            let mut sections: Vec<String> = Vec::new();
            let mut metadata = BTreeMap::new();
            let mut sections_declared = false;
            let mut validate = false;
            for (k, v) in json_obj {
                match k.as_str() {
                    meta::CON_SPEC_VERSION => {}
                    meta::CON_SPEC_MINOR => {
                        if json_u64(v).is_none() {
                            return Err(metadata_json_error(
                                "con_spec_minor must be a JSON integer >= 0",
                            ));
                        }
                        metadata.insert(k.clone(), v.clone());
                    }
                    meta::SECTION_ARITY => {
                        validate_section_arity_value(v)?;
                        metadata.insert(k.clone(), v.clone());
                    }
                    meta::SECTIONS => {
                        sections_declared = true;
                        let arr = v.as_array().ok_or_else(|| {
                            metadata_json_error("sections must be an array of strings")
                        })?;
                        sections.reserve(arr.len());
                        for entry in arr {
                            let s = entry.as_str().ok_or_else(|| {
                                metadata_json_error("sections must be an array of strings")
                            })?;
                            sections.push(s.to_string());
                        }
                    }
                    meta::VALIDATE => {
                        validate = match v {
                            Value::Bool(b) => *b,
                            _ => return Err(metadata_json_error("validate must be a boolean")),
                        };
                        metadata.insert(k.clone(), v.clone());
                    }
                    _ => {
                        metadata.insert(k.clone(), v.clone());
                    }
                }
            }

            // Strict-mode schema check fires only when the file requested
            // it. Hot-path parses (validate=false) skip the per-key match.
            if validate {
                validate_metadata_schema(json_obj)?;
            }

            (ver, metadata, sections, validate, sections_declared)
        } else {
            // Legacy file: no JSON metadata line.
            (1_u32, BTreeMap::new(), Vec::new(), false, false)
        };
    let prebox2 = prebox2_raw.to_string();

    let boxl = read_header_f64s::<3>(lines.next().ok_or(ParseError::IncompleteHeader)?)?;
    let angles = read_header_f64s::<3>(lines.next().ok_or(ParseError::IncompleteHeader)?)?;
    let postbox1 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    let postbox2 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    let natm_types_line = lines.next().ok_or(ParseError::IncompleteHeader)?;
    let natm_types = parse_count_line(natm_types_line, 1)?[0];
    // A type count of 0 is a zero-atom frame (CON-count.1, CON-count.4).
    // A per-type count of 0 is InvalidCount only when the type count is >= 1.
    let (natms_per_type, masses_per_type) = if natm_types == 0 {
        read_zero_atom_tail(|| lines.next())?;
        (Vec::new(), Vec::new())
    } else {
        let natms_per_type = parse_count_line(
            lines.next().ok_or(ParseError::IncompleteHeader)?,
            natm_types,
        )?;
        if natms_per_type.contains(&0) {
            return Err(ParseError::InvalidCount(
                "each per-type count must be >= 1".into(),
            ));
        }
        let masses_per_type = read_header_f64_vec(
            lines.next().ok_or(ParseError::IncompleteHeader)?,
            natm_types,
        )?;
        (natms_per_type, masses_per_type)
    };
    if validate {
        validate_header_geometry(&boxl, &angles)?;
        validate_masses(&masses_per_type)?;
    }
    Ok(FrameHeader {
        prebox_header: PreboxHeader {
            user: prebox1,
            metadata_line: prebox2,
        },
        boxl,
        angles,
        postbox_header: [postbox1, postbox2],
        natm_types,
        natms_per_type,
        masses_per_type,
        spec_version,
        metadata,
        sections,
        strict_validation: validate,
        sections_declared,
    })
}

/// Parses a complete frame from a `.con` file, including its header and atomic data.
///
/// This function first parses the complete frame header and then uses the information within it
/// (specifically the number of atom types and atoms per type) to parse the subsequent
/// atom coordinate blocks.
///
/// Each atom takes one line, so the atom vectors reserve no more rows than the
/// upper bound of `lines.size_hint()`. With no upper bound, as for `str::lines`,
/// they grow as the rows arrive.
///
/// # Arguments
///
/// * `lines` - A mutable reference to an iterator that yields string slices for the frame.
///
/// # Errors
///
/// * `ParseError::IncompleteFrame` if the iterator ends before all expected
///   atomic data has been read.
/// * Propagates any errors from the underlying calls to `parse_frame_header` and
///   `parse_line_of_n`.
///
/// # Example
///
/// ```
/// use readcon_core::parser::parse_single_frame;
///
/// let frame_text = r#"
///Generated by test
///{"con_spec_version":2}
///10.0 10.0 10.0
///90.0 90.0 90.0
///POSTBOX LINE 1
///POSTBOX LINE 2
///2
///1 1
///12.011 1.008
///C
///Coordinates of Component 1
///1.0 1.0 1.0 0 1
///H
///Coordinates of Component 2
///2.0 2.0 2.0 0 2
/// "#;
///
/// let mut lines = frame_text.trim().lines();
/// let con_frame = parse_single_frame(&mut lines).unwrap();
///
/// assert_eq!(con_frame.header.natm_types, 2);
/// assert_eq!(con_frame.atom_data.len(), 2);
/// assert_eq!(&*con_frame.atom_data[0].symbol, "C");
/// assert_eq!(con_frame.atom_data[1].atom_id, 2);
/// ```
pub fn parse_single_frame<'a>(
    lines: &mut impl Iterator<Item = &'a str>,
) -> Result<ConFrame, ParseError> {
    // The caller owns the iterator and may not be able to clone it. Section
    // detection, which needs a lookahead clone, runs later on a `LineStream`
    // that can probe (`MemchrLines`, or a `Peekable` whose source is `Clone`).
    let max_rows = lines.size_hint().1;
    parse_single_frame_ls(&mut IterStream(lines), max_rows)
}

/// Iterator adapter so [`parse_single_frame`] can satisfy [`LineStream`]
/// without requiring [`Clone`].
struct IterStream<I>(I);

impl<'a, I> Iterator for IterStream<I>
where
    I: Iterator<Item = &'a str>,
{
    type Item = &'a str;
    fn next(&mut self) -> Option<&'a str> {
        self.0.next()
    }
}

impl<'a, I> LineStream<'a> for IterStream<I>
where
    I: Iterator<Item = &'a str>,
{
    fn next_line(&mut self) -> Option<&'a str> {
        Iterator::next(self)
    }
    fn peek_line(&mut self) -> Option<&'a str> {
        None
    }
}

/// Columns every atom line has: x, y, z and the flag (spec "Coordinates",
/// CON-num.9). The id column is optional (CON-id.9).
const COORD_ROW_MIN_COLUMNS: usize = 4;

/// Fewest bytes an atom line takes, as in `0 0 0 0`: one byte for each of
/// the [`COORD_ROW_MIN_COLUMNS`] columns and one separator between each
/// pair. Newlines and the symbol and label lines only add bytes, so `n`
/// unread bytes hold at most `n / MIN_COORD_ROW_BYTES` atom lines.
pub(crate) const MIN_COORD_ROW_BYTES: usize = 2 * COORD_ROW_MIN_COLUMNS - 1;

/// Frame parse over a [`LineStream`].
///
/// Coordinate rows go through [`LineStream::next_coord_row`] so the memchr
/// cursor can fuse the newline scan with numeric parse. Positions, ids, and
/// flags land in flat buffers; [`AtomDatum`] values are built from those
/// buffers afterwards (one `Vec` allocation, no per-atom heap traffic).
///
/// `max_rows` bounds the atom lines the rest of the input can hold, and is
/// `None` when that is unknown. The buffers reserve no more atoms than it
/// allows, so a header that declares more atoms than the input holds
/// cannot force a large allocation. The declared counts still decide how
/// many rows are read, and so which error is reported.
pub(crate) fn parse_single_frame_ls<'a, L>(
    lines: &mut L,
    max_rows: Option<usize>,
) -> Result<ConFrame, ParseError>
where
    L: LineStream<'a> + Iterator<Item = &'a str>,
{
    let header = parse_frame_header(lines)?;
    // A count the unread input can hold stays in this function, on the same
    // reservation and `Arc` bump as before the bound existed. A count that
    // cannot fit is a separate cold function so it does not shape this loop.
    let Some(total_atoms) = fitting_atom_count(&header.natms_per_type, max_rows) else {
        return parse_oversized_frame(lines, header, max_rows);
    };
    // One compare per frame. Short frames never enter the block parser or
    // the atom-record pool.
    if total_atoms < crate::types::ATOM_REUSE_MIN {
        return parse_short_frame(lines, header, total_atoms);
    }
    parse_long_frame(lines, header, total_atoms)
}

fn parse_short_f64<'a, L>(
    lines: &mut L,
    header: FrameHeader,
    total_atoms: usize,
    validate: bool,
    dt: &crate::storage_dtype::StorageDtypes,
) -> Result<ConFrame, ParseError>
where
    L: LineStream<'a> + Iterator<Item = &'a str>,
{
    let mut positions = crate::frame_pool::take_small_positions(total_atoms);
    let mut ids = crate::frame_pool::take_small_ids(total_atoms);
    let mut atom_data = Vec::with_capacity(total_atoms);
    let mut global_atom_idx: u64 = 0;
    {
        let pos = positions
            .f64_slice_mut()
            .expect("short f64 positions are contiguous");
        let id_slice = ids
            .as_slice_memory_order_mut()
            .expect("short f64 ids are contiguous");
        for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
            let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            let symbol: Arc<str> = Arc::from(symbol_line.trim());
            let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
            if validate {
                validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
            }
            let mut shares = symbol_shares(&symbol, *num_atoms);
            for _ in 0..*num_atoms {
                let (xyz, fixed, atom_id) =
                    lines.next_coord_row(header.spec_version, global_atom_idx)?;
                let at = global_atom_idx as usize;
                let o = at * 3;
                pos[o] = xyz[0];
                pos[o + 1] = xyz[1];
                pos[o + 2] = xyz[2];
                id_slice[at] = atom_id;
                atom_data.push(AtomDatum::coords(
                    shares.take(),
                    xyz[0],
                    xyz[1],
                    xyz[2],
                    fixed,
                    atom_id,
                ));
                global_atom_idx += 1;
            }
        }
    }
    let masses = crate::frame_pool::take_small_masses(&header, total_atoms);
    if dt.masses != crate::storage_dtype::ElementKind::Float64 {
        let mut projected = crate::storage_dtype::FloatArray1::zeros(dt.masses, total_atoms);
        if let Some(src) = masses.f64_slice() {
            for (i, &v) in src.iter().enumerate() {
                projected.set_f64(i, v);
            }
        }
        return Ok(crate::types::assemble_coord_frame(
            header, atom_data, positions, projected, ids, dt,
        ));
    }
    Ok(crate::types::assemble_coord_frame(
        header, atom_data, positions, masses, ids, dt,
    ))
}

#[inline(never)]
fn parse_short_frame<'a, L>(
    lines: &mut L,
    header: FrameHeader,
    total_atoms: usize,
) -> Result<ConFrame, ParseError>
where
    L: LineStream<'a> + Iterator<Item = &'a str>,
{
    let validate = header.strict_validation;
    use crate::storage_dtype::{ElementKind, FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let f64_positions = dt.positions == ElementKind::Float64;
    if f64_positions {
        return parse_short_f64(lines, header, total_atoms, validate, &dt);
    }
    let mut pos_flat = Vec::with_capacity(total_atoms.saturating_mul(3));
    let mut positions_other = if f64_positions {
        None
    } else {
        Some(FloatArray2::zeros(dt.positions, total_atoms, 3))
    };
    let mut ids = Vec::with_capacity(total_atoms);
    let mut atom_data = Vec::with_capacity(total_atoms);
    let mut global_atom_idx: u64 = 0;
    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
        let symbol: Arc<str> = Arc::from(symbol_line.trim());
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
        }
        global_atom_idx = if positions_other.is_none() {
            ingest_fresh_coords(
                lines,
                *num_atoms,
                header.spec_version,
                global_atom_idx,
                &symbol,
                &mut pos_flat,
                &mut ids,
                &mut atom_data,
            )?
        } else {
            ingest_coord_rows(
                lines,
                *num_atoms,
                header.spec_version,
                global_atom_idx,
                &symbol,
                false,
                CoordSink {
                    pos_flat: &mut pos_flat,
                    ids: &mut ids,
                    positions_other: &mut positions_other,
                    atom_data: &mut atom_data,
                },
            )?
        };
    }
    let positions = if f64_positions {
        FloatArray2::from_f64_row_major(total_atoms, 3, pos_flat)
    } else {
        positions_other.expect("non-f64 positions allocated")
    };
    Ok(crate::types::con_frame_coords_only_with_ids(
        header, atom_data, positions, ids,
    ))
}

#[inline(never)]
fn parse_long_frame<'a, L>(
    lines: &mut L,
    header: FrameHeader,
    total_atoms: usize,
) -> Result<ConFrame, ParseError>
where
    L: LineStream<'a> + Iterator<Item = &'a str>,
{
    let validate = header.strict_validation;
    use crate::storage_dtype::{ElementKind, FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let f64_positions = dt.positions == ElementKind::Float64;
    let mut pos_flat = if total_atoms >= crate::frame_pool::SOA_MIN {
        crate::frame_pool::take_pos(total_atoms)
    } else {
        Vec::with_capacity(total_atoms.saturating_mul(3))
    };
    let mut positions_other = if f64_positions {
        None
    } else {
        Some(FloatArray2::zeros(dt.positions, total_atoms, 3))
    };
    let mut ids = if total_atoms >= crate::frame_pool::SOA_MIN {
        crate::frame_pool::take_ids(total_atoms)
    } else {
        Vec::with_capacity(total_atoms)
    };
    let mut atom_data = crate::types::take_atom_buf(total_atoms);
    let mut global_atom_idx: u64 = 0;
    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
        let sym_str = symbol_line.trim();
        let offset = global_atom_idx as usize;
        let reuse = atom_data.len() == total_atoms
            && offset + num_atoms <= atom_data.len()
            && atom_data[offset..offset + num_atoms]
                .iter()
                .all(|atom| atom.sections_empty() && atom.symbol.as_ref() == sym_str);
        let symbol: Arc<str> = if reuse {
            atom_data[offset].symbol.clone()
        } else {
            Arc::from(sym_str)
        };
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
        }
        global_atom_idx = ingest_coord_rows(
            lines,
            *num_atoms,
            header.spec_version,
            global_atom_idx,
            &symbol,
            reuse,
            CoordSink {
                pos_flat: &mut pos_flat,
                ids: &mut ids,
                positions_other: &mut positions_other,
                atom_data: &mut atom_data,
            },
        )?;
    }
    let positions = if f64_positions {
        FloatArray2::from_f64_row_major(total_atoms, 3, pos_flat)
    } else {
        positions_other.expect("non-f64 positions allocated")
    };
    Ok(crate::types::con_frame_coords_only_with_ids(
        header, atom_data, positions, ids,
    ))
}

/// Atom total when it can use [`Vec::with_capacity`] safely.
///
/// `None` means the counts wrap, exceed `isize::MAX / 4`, or exceed the
/// unread atom lines. A `u32::MAX` count with no size hint is `None`: that
/// reservation is tens of GiB.
#[inline]
fn fitting_atom_count(counts: &[usize], max_rows: Option<usize>) -> Option<usize> {
    let mut total = 0usize;
    for &count in counts {
        total = total.checked_add(count)?;
    }
    if total > (isize::MAX as usize) / 4 {
        return None;
    }
    match max_rows {
        Some(rows) if total > rows => None,
        None if total > (1 << 20) => None,
        _ => Some(total),
    }
}

/// A header declared more atoms than the rest of the input can hold.
///
/// Reservations stay within `max_rows`. Rows are still read up to the
/// declared count, so a short file is `IncompleteFrame`.
#[cold]
#[inline(never)]
fn parse_oversized_frame<'a, L>(
    lines: &mut L,
    header: FrameHeader,
    max_rows: Option<usize>,
) -> Result<ConFrame, ParseError>
where
    L: LineStream<'a> + Iterator<Item = &'a str>,
{
    let validate = header.strict_validation;
    let total_atoms = header
        .natms_per_type
        .iter()
        .fold(0usize, |sum, &n| sum.saturating_add(n));
    let reserve_atoms = max_rows.map_or(0, |rows| total_atoms.min(rows));
    use crate::storage_dtype::{FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let mut pos_flat = Vec::new();
    let _ = pos_flat.try_reserve_exact(reserve_atoms.saturating_mul(3));
    let mut ids = Vec::new();
    let _ = ids.try_reserve_exact(reserve_atoms);
    let mut atom_data: Vec<AtomDatum> = Vec::new();
    let _ = atom_data.try_reserve_exact(reserve_atoms);

    let mut global_atom_idx: u64 = 0;
    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
        let symbol: Arc<str> = Arc::from(symbol_line.trim());
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
        }
        global_atom_idx = ingest_coord_rows_cloned(
            lines,
            *num_atoms,
            header.spec_version,
            global_atom_idx,
            &symbol,
            &mut pos_flat,
            &mut ids,
            &mut atom_data,
        )?;
    }
    let mut positions = FloatArray2::from_f64_row_major(total_atoms, 3, pos_flat);
    positions.project_to(dt.positions);
    Ok(crate::types::con_frame_coords_only_with_ids(
        header, atom_data, positions, ids,
    ))
}

struct CoordSink<'a> {
    pos_flat: &'a mut Vec<f64>,
    ids: &'a mut Vec<u64>,
    positions_other: &'a mut Option<crate::storage_dtype::FloatArray2>,
    atom_data: &'a mut Vec<AtomDatum>,
}

/// Parse `n` coordinate rows into flat SoA buffers.
fn ingest_coord_rows<'a, L>(
    lines: &mut L,
    n: usize,
    spec_version: u32,
    global_atom_idx: u64,
    symbol: &Arc<str>,
    reuse: bool,
    sink: CoordSink<'_>,
) -> Result<u64, ParseError>
where
    L: LineStream<'a>,
{
    let CoordSink {
        pos_flat,
        ids,
        positions_other,
        atom_data,
    } = sink;
    if positions_other.is_none() {
        // A short group that is appending new atoms uses the original loop.
        // The fixed-line block path is a separate function, so this one
        // does not pay for that dispatch.
        if n < 16 && !reuse && atom_data.len() == global_atom_idx as usize {
            return ingest_fresh_coords(
                lines,
                n,
                spec_version,
                global_atom_idx,
                symbol,
                pos_flat,
                ids,
                atom_data,
            );
        }
        return ingest_coord_rows_f64(
            lines,
            n,
            spec_version,
            global_atom_idx,
            symbol,
            reuse,
            pos_flat,
            ids,
            atom_data,
        );
    }
    let mut global_atom_idx = global_atom_idx;
    for _ in 0..n {
        let (xyz, fixed, atom_id) = lines.next_coord_row(spec_version, global_atom_idx)?;
        if let Some(pos) = positions_other.as_mut() {
            pos.set_f64_row(ids.len(), xyz);
        }
        pos_flat.extend_from_slice(&xyz);
        ids.push(atom_id);
        atom_data.push(AtomDatum::coords(
            Arc::clone(symbol),
            xyz[0],
            xyz[1],
            xyz[2],
            fixed,
            atom_id,
        ));
        global_atom_idx += 1;
    }
    Ok(global_atom_idx)
}

/// Append coordinate rows into empty tail capacity.
///
/// This is the path every short row takes. It does not call the fixed-line
/// block parser.
#[inline(never)]
fn ingest_fresh_coords<'a, L>(
    lines: &mut L,
    n: usize,
    spec_version: u32,
    mut global_atom_idx: u64,
    symbol: &Arc<str>,
    pos_flat: &mut Vec<f64>,
    ids: &mut Vec<u64>,
    atom_data: &mut Vec<AtomDatum>,
) -> Result<u64, ParseError>
where
    L: LineStream<'a>,
{
    let mut shares = symbol_shares(symbol, n);
    let pos0 = pos_flat.len();
    let id0 = ids.len();
    let atom0 = atom_data.len();
    pos_flat.reserve(n.saturating_mul(3));
    ids.reserve(n);
    atom_data.reserve(n);
    for i in 0..n {
        let (xyz, fixed, atom_id) = lines.next_coord_row(spec_version, global_atom_idx)?;
        let sym = shares.take();
        // Header counts reserved these slots. Store the coordinate straight
        // into the SoA buffer and the atom record, then publish that element.
        // Safety: `reserve` made these indexes fit, and each slot is written
        // before its length includes it.
        unsafe {
            let p = pos_flat.as_mut_ptr().add(pos0 + i * 3);
            p.write(xyz[0]);
            p.add(1).write(xyz[1]);
            p.add(2).write(xyz[2]);
            ids.as_mut_ptr().add(id0 + i).write(atom_id);
            atom_data
                .as_mut_ptr()
                .add(atom0 + i)
                .write(AtomDatum::coords(
                    sym, xyz[0], xyz[1], xyz[2], fixed, atom_id,
                ));
            pos_flat.set_len(pos0 + (i + 1) * 3);
            ids.set_len(id0 + i + 1);
            atom_data.set_len(atom0 + i + 1);
        }
        global_atom_idx += 1;
    }
    Ok(global_atom_idx)
}

/// Coordinate rows for the f64 storage path.
///
/// The symbol `Arc` is bumped once for the whole block. Cloning it per atom
/// was a visible share of the coordinate parse. Groups of 16 or more rows
/// are parsed as one block; a recycled frame overwrites coordinates in place.
#[inline(never)]
#[allow(clippy::too_many_arguments)]
fn ingest_coord_rows_f64<'a, L>(
    lines: &mut L,
    n: usize,
    spec_version: u32,
    mut global_atom_idx: u64,
    symbol: &Arc<str>,
    reuse: bool,
    pos_flat: &mut Vec<f64>,
    ids: &mut Vec<u64>,
    atom_data: &mut Vec<AtomDatum>,
) -> Result<u64, ParseError>
where
    L: LineStream<'a>,
{
    if n >= 16 {
        if let Some(next) = lines.ingest_known_coords(
            n,
            spec_version,
            global_atom_idx,
            symbol,
            reuse,
            pos_flat,
            ids,
            atom_data,
        )? {
            return Ok(next);
        }
    }
    let pos0 = pos_flat.len();
    let id0 = ids.len();
    pos_flat.reserve(n.saturating_mul(3));
    ids.reserve(n);
    if reuse {
        for i in 0..n {
            let (xyz, fixed, atom_id) = lines.next_coord_row(spec_version, global_atom_idx)?;
            unsafe {
                let p = pos_flat.as_mut_ptr().add(pos0 + i * 3);
                p.write(xyz[0]);
                p.add(1).write(xyz[1]);
                p.add(2).write(xyz[2]);
                ids.as_mut_ptr().add(id0 + i).write(atom_id);
                pos_flat.set_len(pos0 + (i + 1) * 3);
                ids.set_len(id0 + i + 1);
            }
            let at = global_atom_idx as usize;
            atom_data[at].set_coords(xyz, fixed, atom_id);
            global_atom_idx += 1;
        }
        return Ok(global_atom_idx);
    }
    let mut shares = symbol_shares(symbol, n);
    atom_data.reserve(n);
    for i in 0..n {
        let (xyz, fixed, atom_id) = lines.next_coord_row(spec_version, global_atom_idx)?;
        let sym = shares.take();
        let at = global_atom_idx as usize;
        unsafe {
            let p = pos_flat.as_mut_ptr().add(pos0 + i * 3);
            p.write(xyz[0]);
            p.add(1).write(xyz[1]);
            p.add(2).write(xyz[2]);
            ids.as_mut_ptr().add(id0 + i).write(atom_id);
            pos_flat.set_len(pos0 + (i + 1) * 3);
            ids.set_len(id0 + i + 1);
        }
        let atom = AtomDatum::coords(sym, xyz[0], xyz[1], xyz[2], fixed, atom_id);
        if at == atom_data.len() {
            atom_data.push(atom);
        } else {
            atom_data[at] = atom;
        }
        global_atom_idx += 1;
    }
    Ok(global_atom_idx)
}

/// Coordinate rows when the declared count must not bump an `Arc` by `n`.
fn ingest_coord_rows_cloned<'a, L>(
    lines: &mut L,
    n: usize,
    spec_version: u32,
    mut global_atom_idx: u64,
    symbol: &Arc<str>,
    pos_flat: &mut Vec<f64>,
    ids: &mut Vec<u64>,
    atom_data: &mut Vec<AtomDatum>,
) -> Result<u64, ParseError>
where
    L: LineStream<'a>,
{
    for _ in 0..n {
        let (xyz, fixed, atom_id) = lines.next_coord_row(spec_version, global_atom_idx)?;
        pos_flat.extend_from_slice(&xyz);
        ids.push(atom_id);
        atom_data.push(AtomDatum::coords(
            Arc::clone(symbol),
            xyz[0],
            xyz[1],
            xyz[2],
            fixed,
            atom_id,
        ));
        global_atom_idx += 1;
    }
    Ok(global_atom_idx)
}

/// `n` extra strong references to `symbol`, taken one at a time.
///
/// `Arc<str>` stores the header (strong count, weak count) immediately
/// before the bytes. One `fetch_add` covers the block; each [`SymbolShares::take`]
/// turns one of those counts into an `Arc`. Leftovers drop with the guard.
struct SymbolShares {
    data: *const u8,
    len: usize,
    left: usize,
}

impl SymbolShares {
    fn raw(&self) -> *const str {
        std::ptr::slice_from_raw_parts(self.data, self.len) as *const str
    }

    fn take(&mut self) -> Arc<str> {
        debug_assert!(self.left > 0);
        self.left -= 1;
        unsafe { Arc::from_raw(self.raw()) }
    }
}

impl Drop for SymbolShares {
    fn drop(&mut self) {
        for _ in 0..self.left {
            drop(unsafe { Arc::from_raw(self.raw()) });
        }
        self.left = 0;
    }
}

fn symbol_shares(symbol: &Arc<str>, n: usize) -> SymbolShares {
    if n == 0 {
        return SymbolShares {
            data: std::ptr::null(),
            len: 0,
            left: 0,
        };
    }
    let data = Arc::as_ptr(symbol);
    let offset = arc_str_header(symbol.as_ref());
    // SAFETY: `Arc::as_ptr` points at the `str` inside the allocation, and
    // the two atomic counts sit in front of it. This is the same subtraction
    // `Arc::increment_strong_count` performs, done once for `n` clones.
    let bytes = data as *const u8;
    let strong = unsafe { bytes.sub(offset) as *const AtomicUsize };
    unsafe { (*strong).fetch_add(n, Ordering::Relaxed) };
    SymbolShares {
        data: bytes,
        len: symbol.len(),
        left: n,
    }
}

fn arc_str_header(text: &str) -> usize {
    let header = 2 * std::mem::size_of::<usize>();
    let align = std::mem::align_of_val(text);
    let rem = header % align;
    if rem == 0 {
        header
    } else {
        header + (align - rem)
    }
}

#[cfg(test)]
mod symbol_share_tests {
    use super::symbol_shares;
    use std::sync::Arc;

    #[test]
    fn one_bump_matches_n_clones() {
        for text in ["", "Cu", "Gold", "a-much-longer-component-symbol"] {
            let symbol: Arc<str> = Arc::from(text);
            let mut shares = symbol_shares(&symbol, 3);
            assert_eq!(Arc::strong_count(&symbol), 4);
            let owned = [shares.take(), shares.take(), shares.take()];
            assert!(owned.iter().all(|arc| arc.as_ref() == text));
            drop(owned);
            assert_eq!(Arc::strong_count(&symbol), 1);
            let mut partial = symbol_shares(&symbol, 2);
            let one = partial.take();
            drop(partial);
            drop(one);
            assert_eq!(Arc::strong_count(&symbol), 1);
        }
    }
}

fn validate_header_geometry(boxl: &[f64], angles: &[f64]) -> Result<(), ParseError> {
    if boxl
        .iter()
        .any(|length| !length.is_finite() || *length <= 0.0)
        || angles
            .iter()
            .any(|angle| !angle.is_finite() || *angle <= 0.0 || *angle >= 180.0)
    {
        return Err(ParseError::ValidationError(
            "cell geometry must have positive lengths and angles between 0 and 180 degrees"
                .to_string(),
        ));
    }
    Ok(())
}

fn validate_masses(masses_per_type: &[f64]) -> Result<(), ParseError> {
    if masses_per_type
        .iter()
        .any(|mass| !mass.is_finite() || *mass <= 0.0)
    {
        return Err(ParseError::ValidationError(
            "component masses must be positive".to_string(),
        ));
    }
    Ok(())
}

fn validate_coordinate_component(
    type_idx: usize,
    symbol: &str,
    label: &str,
) -> Result<(), ParseError> {
    let expected_label = format!("Coordinates of Component {}", type_idx + 1);
    if !labels_equal(label, &expected_label) {
        return Err(ParseError::ValidationError(format!(
            "expected coordinate label {expected_label:?}, found {label:?}"
        )));
    }
    if symbol != "X" && symbol_to_atomic_number(symbol) == 0 {
        return Err(ParseError::ValidationError(format!(
            "unknown component symbol {symbol}"
        )));
    }
    Ok(())
}

fn validate_section_component(
    section: &str,
    type_idx: usize,
    atom_idx: usize,
    symbol: &str,
    label: &str,
    header: &FrameHeader,
    atom_data: &[AtomDatum],
) -> Result<(), ParseError> {
    let expected_label = format!("{section} of Component {}", type_idx + 1);
    if !labels_equal(label, &expected_label) {
        return Err(ParseError::ValidationError(format!(
            "expected section label {expected_label:?}, found {label:?}"
        )));
    }

    if header.natms_per_type[type_idx] == 0 {
        return Ok(());
    }

    let expected_symbol = atom_data
        .get(atom_idx)
        .map(|atom| atom.symbol.as_ref())
        .ok_or_else(|| {
            ParseError::ValidationError(format!(
                "{section} component {} has no coordinate atom to validate against",
                type_idx + 1
            ))
        })?;
    if symbol != expected_symbol {
        return Err(ParseError::ValidationError(format!(
            "{section} component {} symbol mismatch: expected {expected_symbol}, found {symbol}",
            type_idx + 1
        )));
    }

    Ok(())
}

fn validate_section_atom_identity(
    section: &str,
    atom_idx: usize,
    fixed: [bool; 3],
    atom_id: u64,
    atom_data: &[AtomDatum],
) -> Result<(), ParseError> {
    let atom = atom_data.get(atom_idx).ok_or_else(|| {
        ParseError::ValidationError(format!(
            "{section} row {atom_idx} has no coordinate atom to validate against"
        ))
    })?;

    if atom.fixed != fixed {
        return Err(ParseError::ValidationError(format!(
            "{section} row {atom_idx} fixed mask mismatch for atom_id {}",
            atom.atom_id
        )));
    }
    if atom.atom_id != atom_id {
        return Err(ParseError::ValidationError(format!(
            "{section} row {atom_idx} atom_id mismatch: expected {}, found {atom_id}",
            atom.atom_id
        )));
    }

    Ok(())
}

/// Consume the single blank line that opens a section.
///
/// A blank line followed only by whitespace to EOF does not open a section
/// (CON-frame.5). The lines stay in the stream.
fn frame_minor(header: &FrameHeader) -> u64 {
    header
        .metadata
        .get(meta::CON_SPEC_MINOR)
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
}

fn section_row_arity(header: &FrameHeader, name: &str) -> Option<usize> {
    let obj = header.metadata.get(meta::SECTION_ARITY)?.as_object()?;
    let n = obj.get(name)?.as_u64()?;
    if n >= 1 { Some(n as usize) } else { None }
}

/// Skip one unknown section of a newer minor.
///
/// `arity` is the value-field count (CON-section.12). Each data row holds
/// that many values, then the flag, and an optional id, so the row has
/// `arity + 1` or `arity + 2` tokens (CON-section.14). The label is the
/// section name under CON-file.5, then `of Component N` (CON-section.15).
fn skip_unknown_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    name: &str,
    arity: usize,
) -> Result<(), ParseError> {
    if !open_section(lines)? {
        return Err(ParseError::IncompleteSection(name.to_string()));
    }
    let with_flag = arity.saturating_add(1);
    let with_id = arity.saturating_add(2);
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        if lines.next_line().is_none() {
            return Err(ParseError::IncompleteSection(name.to_string()));
        }
        let label = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(name.to_string()))?;
        let expected = format!("{name} of Component {}", type_idx + 1);
        if !labels_equal(label, &expected) {
            return Err(ParseError::IncompleteSection(name.to_string()));
        }
        for _ in 0..num_atoms {
            let row = lines
                .next_line()
                .ok_or_else(|| ParseError::IncompleteSection(name.to_string()))?;
            let found = token_count(row);
            if found != with_flag && found != with_id {
                let expected = if found < with_flag {
                    with_flag
                } else {
                    with_id
                };
                return Err(ParseError::InvalidVectorLength { expected, found });
            }
        }
    }
    Ok(())
}

fn open_section<'a>(lines: &mut impl LineStream<'a>) -> Result<bool, ParseError> {
    match lines.peek_line() {
        Some(line) if line.trim().is_empty() => {
            if lines.remainder_is_whitespace() {
                return Ok(false);
            }
            lines.next_line();
            Ok(true)
        }
        _ => Ok(false),
    }
}

/// Attempts to parse an optional velocity section following coordinate blocks.
///
/// In `.convel` files, after all coordinate blocks there is a blank separator line
/// followed by per-component velocity blocks with the same structure as coordinate
/// blocks (symbol line, "Velocities of Component N" line, then atom lines with
/// `vx vy vz fixed atomID`).
///
/// This function peeks at the next line. If it is blank (or contains only whitespace),
/// it consumes the blank line and parses velocity data into the existing `atom_data`.
/// If the next line is not blank (or is absent), no velocities are parsed.
///
/// Returns `Ok(true)` if velocities were found and parsed, `Ok(false)` otherwise.
pub fn parse_velocity_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    // A blank line followed only by whitespace to EOF is not a velocity
    // block (CON-frame.5, D2). Leave those lines for the iterator.
    match lines.peek_line() {
        Some(line) if line.trim().is_empty() => {
            if lines.remainder_is_whitespace() {
                return Ok(false);
            }
            // CON-section.2 / the legacy fallback: the blank counts only
            // when it begins a complete velocity block. Otherwise it is
            // line 1 of the next frame (CON-frame.7, CON-header.4).
            if !lines.blank_line_opens_section() {
                return Ok(false);
            }
            lines.next_line();
        }
        _ => return Ok(false),
    }

    read_vector_components(
        lines,
        header,
        atom_data,
        SECTION_VELOCITIES,
        "Velocities",
        "velocities",
        AtomDatum::store_velocity,
    )
}

/// Attempts to parse a force section following coordinate (and optional velocity) blocks.
///
/// Force sections mirror velocity sections: a blank separator line followed by per-component
/// force blocks (symbol line, "Forces of Component N" line, then atom lines with
/// `fx fy fz fixed_flag atom_id`).
///
/// Returns `Ok(true)` if forces were found and parsed, `Ok(false)` otherwise.
pub fn parse_force_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    if !open_section(lines)? {
        return Ok(false);
    }

    read_vector_components(
        lines,
        header,
        atom_data,
        SECTION_FORCES,
        "Forces",
        "forces",
        AtomDatum::store_force,
    )
}

/// Attempts to parse an energies section following coordinate (and optional
/// velocity / force) blocks.
///
/// Energy sections mirror force sections but with one scalar per atom:
/// blank separator, then per-component blocks of (symbol, "Energies of
/// Component N", and atom lines `e fixed_flag atom_id`). The two
/// trailing identity columns are optional and used only for strict
/// validation; in non-strict mode any whitespace after the energy is
/// ignored.
///
/// Returns `Ok(true)` if energies were found and parsed, `Ok(false)`
/// otherwise.
pub fn parse_energy_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    let validate = header.strict_validation;
    if !open_section(lines)? {
        return Ok(false);
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or(ParseError::IncompleteSection(SECTION_ENERGIES.into()))?
            .trim();

        let comp_line = lines
            .next_line()
            .ok_or(ParseError::IncompleteSection(SECTION_ENERGIES.into()))?;
        if !label_has_prefix(comp_line, "Energies of Component") {
            return Err(ParseError::IncompleteSection(SECTION_ENERGIES.into()));
        }
        if validate {
            validate_section_component(
                "Energies", type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let energy_line = lines
                .next_line()
                .ok_or(ParseError::IncompleteSection(SECTION_ENERGIES.into()))?;
            let (value, fixed, atom_id) =
                parse_scalar_section_row(energy_line, header.spec_version)?;
            if validate {
                validate_section_atom_identity("energies", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].set_energy(Some(value));
            }
            atom_idx += 1;
        }
    }

    Ok(true)
}

/// Parses declared sections from a frame's header metadata.
///
/// If `header.sections` is non-empty (v2 file with `"sections"` key in JSON),
/// parses each declared section in order. Otherwise falls back to legacy
/// blank-separator velocity detection.
pub fn parse_declared_sections<'a>(
    lines: &mut impl LineStream<'a>,
    header: &mut FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<usize, ParseError> {
    let mut applied = 0usize;
    // A zero-atom frame has no coordinate block and no section block.
    // The legacy velocity fallback must not run (CON-count.1).
    if header.natm_types == 0 {
        if !header.sections.is_empty() {
            return Err(ParseError::InvalidCount(
                "a zero-atom frame cannot declare sections".into(),
            ));
        }
        return Ok(0);
    }
    if !header.sections_declared && header.sections.is_empty() {
        // Legacy: try velocity detection via blank separator. A blank
        // line can also be the empty line 1 of the next frame, so look for
        // the velocity label before committing (CON-frame.5).
        let found =
            lines.blank_opens_velocity_block() && parse_velocity_section(lines, header, atom_data)?;
        if found {
            header.sections.push(SECTION_VELOCITIES.into());
            applied = 1;
        }
    } else {
        let sections = std::mem::take(&mut header.sections);
        for section in &sections {
            match section.as_str() {
                SECTION_VELOCITIES => {
                    let found = parse_velocity_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_VELOCITIES.into()));
                    }
                    applied += 1;
                }
                SECTION_FORCES => {
                    let found = parse_force_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_FORCES.into()));
                    }
                    applied += 1;
                }
                SECTION_ENERGIES => {
                    let found = parse_energy_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_ENERGIES.into()));
                    }
                    applied += 1;
                }
                SECTION_CHARGES => {
                    let found = parse_charge_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_CHARGES.into()));
                    }
                    applied += 1;
                }
                SECTION_SPINS => {
                    let found = parse_spin_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_SPINS.into()));
                    }
                    applied += 1;
                }
                SECTION_MAGMOMS => {
                    let found = parse_magmom_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_MAGMOMS.into()));
                    }
                    applied += 1;
                }
                SECTION_DISPLACEMENTS => {
                    let found = parse_displacement_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_DISPLACEMENTS.into()));
                    }
                    applied += 1;
                }
                SECTION_SPREADS => {
                    let found = parse_spread_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteSection(SECTION_SPREADS.into()));
                    }
                    applied += 1;
                }
                other => {
                    if frame_minor(header) > u64::from(crate::CON_SPEC_MINOR)
                        && let Some(arity) = section_row_arity(header, other)
                    {
                        skip_unknown_section(lines, header, other, arity)?;
                        continue;
                    }
                    return Err(ParseError::UnknownSection(other.to_string()));
                }
            }
        }
        header.sections = sections;
    }
    reject_velocities_without_time(header)?;
    Ok(applied)
}

/// CON-units.11. Versions 1, 2, and 3.0 do not require `units.time`
/// (CON-units.8, CON-units.9). From minor 1 the key is required when a
/// velocities section is present.
fn reject_velocities_without_time(header: &FrameHeader) -> Result<(), ParseError> {
    if header.spec_version < 3 || frame_minor(header) < 1 {
        return Ok(());
    }
    if !header
        .sections
        .iter()
        .any(|name| name == SECTION_VELOCITIES)
    {
        return Ok(());
    }
    let time_ok = header
        .metadata
        .get(meta::UNITS)
        .and_then(|units| units.get("time"))
        .and_then(|value| value.as_str())
        .is_some_and(|unit| !unit.trim().is_empty());
    if time_ok {
        Ok(())
    } else {
        Err(ParseError::InvalidUnits(
            "minor >= 1 requires units.time when a velocities section is present".into(),
        ))
    }
}

/// Scalar per-atom section: blank separator + per-type blocks
/// (`symbol`, `"X of Component N"`, lines `value fixed atom_id`).
fn parse_scalar_atom_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
    section_name: &str,
    component_label: &str,
    mut set_value: impl FnMut(&mut AtomDatum, f64),
) -> Result<bool, ParseError> {
    let validate = header.strict_validation;
    if !open_section(lines)? {
        return Ok(false);
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(section_name.into()))?
            .trim();

        let comp_line = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(section_name.into()))?;
        if !label_has_prefix(comp_line, component_label) {
            return Err(ParseError::IncompleteSection(section_name.into()));
        }
        if validate {
            validate_section_component(
                component_label.trim_end_matches(" of Component").trim(),
                type_idx,
                atom_idx,
                symbol,
                comp_line,
                header,
                atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let data_line = lines
                .next_line()
                .ok_or_else(|| ParseError::IncompleteSection(section_name.into()))?;
            let (value, fixed, atom_id) = parse_scalar_section_row(data_line, header.spec_version)?;
            if validate {
                validate_section_atom_identity(section_name, atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                set_value(&mut atom_data[atom_idx], value);
            }
            atom_idx += 1;
        }
    }
    Ok(true)
}

pub fn parse_charge_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    parse_scalar_atom_section(
        lines,
        header,
        atom_data,
        SECTION_CHARGES,
        "Charges of Component",
        |a, v| a.set_charge(Some(v)),
    )
}

pub fn parse_spin_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    parse_scalar_atom_section(
        lines,
        header,
        atom_data,
        SECTION_SPINS,
        "Spins of Component",
        |a, v| a.set_spin(Some(v)),
    )
}

fn parse_vector_named_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
    names: (&str, &str, &str),
    mut set_value: impl FnMut(&mut AtomDatum, [f64; 3]),
    mut check_row: impl FnMut(usize, [f64; 3]) -> Result<(), ParseError>,
) -> Result<bool, ParseError> {
    let (section_name, component_label, label_kind) = names;
    let validate = header.strict_validation;
    if !open_section(lines)? {
        return Ok(false);
    }
    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(section_name.into()))?
            .trim();
        let comp_line = lines
            .next_line()
            .ok_or_else(|| ParseError::IncompleteSection(section_name.into()))?;
        if !label_has_prefix(comp_line, component_label) {
            return Err(ParseError::IncompleteSection(section_name.into()));
        }
        if validate {
            validate_section_component(
                label_kind, type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }
        for _ in 0..num_atoms {
            let (vals, fixed, atom_id) = take_vector_row(lines, header.spec_version, section_name)?;
            check_row(atom_idx, vals)?;
            if validate {
                validate_section_atom_identity(section_name, atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                set_value(&mut atom_data[atom_idx], vals);
            }
            atom_idx += 1;
        }
    }
    Ok(true)
}

/// Magmoms: 3-vector per atom, same layout as velocities/forces.
pub fn parse_magmom_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    parse_vector_named_section(
        lines,
        header,
        atom_data,
        (SECTION_MAGMOMS, "Magmoms of Component", "Magmoms"),
        |a, v| a.set_magmom(Some(v)),
        |_, _| Ok(()),
    )
}

/// Displacements: 3-vector per atom (Angstrom), same layout as velocities/forces.
pub fn parse_displacement_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    parse_vector_named_section(
        lines,
        header,
        atom_data,
        (
            SECTION_DISPLACEMENTS,
            "Displacements of Component",
            "Displacements",
        ),
        |a, v| a.set_displacement(Some(v)),
        |_, _| Ok(()),
    )
}

/// Spreads: per-atom root-mean-square spread `[sx, sy, sz]` (Angstrom, each
/// non-negative), same layout as velocities/forces.
pub fn parse_spread_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    parse_vector_named_section(
        lines,
        header,
        atom_data,
        (SECTION_SPREADS, "Spreads of Component", "Spreads"),
        |a, v| a.set_spread(Some(v)),
        |atom_idx, vals| {
            if !vals.iter().all(|v| v.is_finite()) {
                return Err(ParseError::NonFiniteValue(format!(
                    "spreads atom {atom_idx}"
                )));
            }
            if vals.iter().any(|v| *v < 0.0) {
                return Err(crate::types::invalid_spread(atom_idx));
            }
            Ok(())
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::ConFrameIterator;

    #[test]
    fn test_parse_line_of_n_success() {
        let line = "1.0 2.5 -3.0";
        let values = parse_line_of_n::<f64>(line, 3).unwrap();
        assert_eq!(values, vec![1.0, 2.5, -3.0]);
    }

    #[test]
    fn test_parse_line_of_n_too_short() {
        let line = "1.0 2.5";
        let result = parse_line_of_n::<f64>(line, 3);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 3,
                found: 2
            }
        ));
    }

    #[test]
    fn test_parse_line_of_n_too_long() {
        let line = "1.0 2.5 -3.0 4.0";
        let result = parse_line_of_n::<f64>(line, 3);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 3,
                found: 4
            }
        ));
    }

    #[test]
    fn test_parse_line_of_n_invalid_float() {
        let line = "1.0 abc -3.0";
        let result = parse_line_of_n::<f64>(line, 3);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidNumberFormat(_)
        ));
    }

    #[test]
    fn test_parse_frame_header_success() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        match parse_frame_header(&mut line_it) {
            Ok(header) => {
                assert_eq!(header.prebox_header.user, "PREBOX1");
                assert_eq!(header.spec_version, 2);
                assert_eq!(header.boxl, [10.0, 20.0, 30.0]);
                assert_eq!(header.angles, [90.0, 90.0, 90.0]);
                assert_eq!(header.postbox_header, ["POSTBOX1", "POSTBOX2"]);
                assert_eq!(header.natm_types, 2);
                assert_eq!(header.natms_per_type, vec![1, 1]);
                assert_eq!(header.masses_per_type, vec![12.011, 1.008]);
            }
            Err(e) => {
                panic!("Parsing failed when it should have succeeded. Error: {e:?}");
            }
        }
    }

    #[test]
    fn test_parse_frame_header_missing_line() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            // Missing masses_per_type
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ParseError::IncompleteHeader));
    }

    #[test]
    fn test_parse_frame_header_missing_spec_version() {
        let lines = [
            "PREBOX1",
            "{}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::MissingSpecVersion
        ));
    }

    #[test]
    fn test_parse_frame_header_legacy_no_json() {
        // A non-JSON line 2 is treated as a legacy (v1) file.
        let lines = [
            "PREBOX1",
            "0.0000 TIME",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).unwrap();
        assert_eq!(header.spec_version, 1);
        assert!(header.metadata.is_empty());
    }

    #[test]
    fn test_parse_frame_header_malformed_json() {
        // Line 2 starts with '{' but is not valid JSON -- this IS an error.
        let lines = [
            "PREBOX1",
            "{broken json",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidMetadataJson(_)
        ));
    }

    #[test]
    fn test_parse_frame_header_unsupported_version() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":999}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::UnsupportedVersion(999)
        ));
    }

    #[test]
    fn test_v3_missing_units_rejected() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":3}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "1.0",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();
        let msg = err.to_string();
        assert!(
            msg.contains("units") || msg.contains("v3"),
            "expected units error, got {msg}"
        );
    }

    #[test]
    fn test_v3_invalid_units_rejected() {
        let lines = [
            "PREBOX1",
            r#"{"con_spec_version":3,"units":{"length":"eV","energy":"angstrom"}}"#,
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "1.0",
        ];
        let mut line_it = lines.iter().copied();
        assert!(parse_frame_header(&mut line_it).is_err());
    }

    #[test]
    fn test_v3_valid_units_exposes_length_energy() {
        let lines = [
            "PREBOX1",
            r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}"#,
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "1.0",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).unwrap();
        assert_eq!(header.spec_version, 3);
        assert_eq!(header.length_unit(), Some("angstrom"));
        assert_eq!(header.energy_unit(), Some("eV"));
        let f = header.conversion_factor_to("length", "nm").unwrap();
        assert!((f - 0.1).abs() < 1e-12);
    }

    #[test]
    fn test_parse_frame_header_extra_metadata_preserved() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"generator\":\"test\"}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).unwrap();
        assert_eq!(header.spec_version, 2);
        assert_eq!(
            header.metadata.get("generator"),
            Some(&serde_json::Value::String("test".to_string()))
        );
    }

    #[test]
    fn test_parse_frame_header_invalid_natms_per_type() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1 1", // 3 values, but natm_types is 2
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 2,
                found: 3
            }
        ));
    }

    #[test]
    fn test_parse_single_frame_success() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "3 3",
            "12.011 1.008",
            "1",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0 1",
            "1.0940 0.0 0.0 0 2",
            "-0.5470 0.9499 0.0 0 3",
            "2",
            "Coordinates of Component 2",
            "5.0 5.0 5.0 0 4",
            "6.0940 5.0 5.0 0 5",
            "5.5470 5.9499 5.0 0 6",
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();

        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![3, 3]);
        assert_eq!(frame.header.masses_per_type, vec![12.011, 1.008]);
        assert_eq!(frame.atom_data.len(), 6);
        assert_eq!(&*frame.atom_data[0].symbol, "1");
        assert_eq!(frame.atom_data[0].atom_id, 1);
        assert_eq!(&*frame.atom_data[5].symbol, "2");
        assert_eq!(frame.atom_data[5].atom_id, 6);
    }

    #[test]
    fn test_column_4_value_1_is_x_only_on_spec_2() {
        let lines = [
            "Generated by probe",
            "{\"con_spec_version\":2}",
            "20.0 20.0 20.0",
            "90.0 90.0 90.0",
            "",
            "",
            "1",
            "1",
            "63.5",
            "Cu",
            "Coordinates of component   1",
            "1.0 2.0 3.0 1 1",
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();
        assert_eq!(frame.header.spec_version, 2);
        assert_eq!(frame.atom_data[0].fixed, [true, false, false]);
    }

    #[test]
    fn test_column_4_value_1_is_all_fixed_on_spec_1() {
        let lines = [
            "Generated by probe",
            "0.0000 TIME",
            "20.0 20.0 20.0",
            "90.0 90.0 90.0",
            "",
            "",
            "1",
            "1",
            "63.5",
            "Cu",
            "Coordinates of component   1",
            "1.0 2.0 3.0 1 1",
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();
        assert_eq!(frame.header.spec_version, 1);
        assert_eq!(frame.atom_data[0].fixed, [true, true, true]);
    }

    #[test]
    fn test_parse_single_frame_missing_line() {
        // With a valid header but truncated atom data, we get IncompleteFrame.
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "3 3",
            "12.011 1.008",
            "1",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0 1",
            "1.0940 0.0 0.0 0 2",
            "-0.5470 0.9499 0.0 0 3",
            // Missing Component 2 entirely
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_single_frame(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ParseError::IncompleteFrame));
    }

    #[test]
    fn test_parse_single_frame_missing_atom_index_defaults_sequential() {
        // Column 5 (atom_index) is optional; when absent, defaults to sequential.
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "3 3",
            "12.011 1.008",
            "1",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0 1",
            "1.0940 0.0 0.0 0 2",
            "-0.5470 0.9499 0.0 0 3",
            "2",
            "Coordinates of Component 2",
            "5.0 5.0 5.0 0",       // No atom_index: defaults to 3
            "6.0940 5.0 5.0 0 10", // Explicit atom_index: 10
            "5.5470 5.9499 5.0 0", // No atom_index: defaults to 5
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();
        assert_eq!(frame.atom_data.len(), 6);
        // First type: explicit atom_index values
        assert_eq!(frame.atom_data[0].atom_id, 1);
        assert_eq!(frame.atom_data[1].atom_id, 2);
        assert_eq!(frame.atom_data[2].atom_id, 3);
        // Second type: mixed explicit and defaulted
        assert_eq!(frame.atom_data[3].atom_id, 3); // defaulted (global idx 3)
        assert_eq!(frame.atom_data[4].atom_id, 10); // explicit
        assert_eq!(frame.atom_data[5].atom_id, 5); // defaulted (global idx 5)
    }

    #[test]
    fn test_parse_single_frame_too_few_columns_fails() {
        // Only 3 columns (missing fixed_flag too) should still fail.
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
            "C",
            "Coordinates of Component 1",
            "0.0 0.0 0.0", // Only 3 values
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_single_frame(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 5,
                found: 3
            }
        ));
    }

    #[test]
    fn test_parse_velocity_section_present() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "63.546 1.008",
            "Cu",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 1 0",
            "H",
            "Coordinates of Component 2",
            "1.0 2.0 3.0 0 1",
            "",
            "Cu",
            "Velocities of Component 1",
            "0.1 0.2 0.3 1 0",
            "H",
            "Velocities of Component 2",
            "0.4 0.5 0.6 0 1",
        ];
        let mut line_it = lines.iter().copied().peekable();
        // Parse the frame first (consuming 15 lines)
        let mut frame =
            parse_single_frame(&mut line_it).expect("coordinate parsing should succeed");
        assert!(!frame.has_velocities());

        // Now parse the velocity section
        let has_vel = parse_velocity_section(&mut line_it, &frame.header, &mut frame.atom_data)
            .expect("velocity parsing should succeed");
        assert!(has_vel);
        assert_eq!(frame.atom_data[0].velocity(), Some([0.1, 0.2, 0.3]));
        assert_eq!(frame.atom_data[1].velocity(), Some([0.4, 0.5, 0.6]));
    }

    #[test]
    fn test_validate_true_accepts_matching_section_identity() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
2
1 1
63.546 1.008
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0
H
Coordinates of Component 2
1.0 2.0 3.0 0 1

Cu
Velocities of Component 1
0.1 0.2 0.3 5 0
H
Velocities of Component 2
0.4 0.5 0.6 0 1
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let frame = iter.next().unwrap().unwrap();

        assert!(frame.has_velocities());
        assert_eq!(
            frame
                .header
                .metadata
                .get("validate")
                .and_then(|v| v.as_bool()),
            Some(true)
        );
    }

    #[test]
    fn test_validate_true_rejects_section_atom_id_mismatch() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0

Cu
Velocities of Component 1
0.1 0.2 0.3 5 99
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("atom_id mismatch"));
    }

    #[test]
    fn test_validate_true_rejects_section_symbol_mismatch() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["forces"],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0

H
Forces of Component 1
0.1 0.2 0.3 5 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("symbol mismatch"));
    }

    #[test]
    fn test_validate_absent_allows_legacy_duplicate_identity_mismatch() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"]}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0

Cu
Velocities of Component 1
0.1 0.2 0.3 0 99
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let frame = iter.next().unwrap().unwrap();

        assert!(frame.has_velocities());
        assert_eq!(frame.atom_data[0].atom_id, 0);
        assert_eq!(frame.atom_data[0].fixed, [true, false, true]);
    }

    #[test]
    fn test_validate_must_be_boolean_when_present() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"validate\":\"yes\",\"sections\":[]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("validate"));
    }

    #[test]
    fn test_validate_true_requires_sections_key() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"validate\":true}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("sections"));
    }

    #[test]
    fn test_sections_must_be_string_array_when_present() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[\"velocities\",7]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("sections"));
    }

    #[test]
    fn test_validate_true_rejects_non_integer_coordinate_identity_columns() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5.0 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::InvalidFixedFlag(_)));
        assert!(err.to_string().contains("5.0"));
    }

    #[test]
    fn test_validate_true_rejects_non_exact_coordinate_label() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates Component 1
0.0 0.0 0.0 5 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("Coordinates of Component 1"));
    }

    #[test]
    fn test_validate_true_rejects_unknown_component_symbol() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Qq
Coordinates of Component 1
0.0 0.0 0.0 0 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("symbol"));
    }

    #[test]
    fn test_declared_section_must_be_present() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"]}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 0 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(
            err,
            ParseError::IncompleteSection(ref name) if name == "velocities"
        ));
    }

    #[test]
    fn test_non_finite_cell_geometry_rejected_in_strict_mode() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true}",
            "10.0 NaN 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::NonFiniteValue(_)));
        assert!(err.to_string().contains("NaN"));
    }

    #[test]
    fn test_validate_true_rejects_non_physical_cell_geometry() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true}",
            "0.0 20.0 30.0",
            "90.0 180.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("cell"));
    }

    #[test]
    fn test_validate_true_rejects_reserved_metadata_type_mismatch() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true,\"energy\":\"low\"}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("energy"));
    }

    #[test]
    fn test_validate_true_rejects_malformed_bonds() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true,\"bonds\":[[0]]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();
        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("bonds"));
    }

    #[test]
    fn test_bonds_metadata_round_trip_in_header() {
        use crate::types::{Bond, meta};
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2,\"bonds\":[[0,1],{\"i\":0,\"j\":2,\"order\":1}]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).expect("header");
        let bonds = header.bonds();
        assert_eq!(bonds.len(), 2);
        assert_eq!(bonds[0], Bond::new(0, 1));
        assert_eq!(bonds[1].i, 0);
        assert_eq!(bonds[1].j, 2);
        assert_eq!(bonds[1].order, Some(1));
        assert!(header.metadata.contains_key(meta::BONDS));
    }

    #[test]
    fn test_parse_velocity_section_absent() {
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
            "C",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0 1",
        ];
        let mut line_it = lines.iter().copied().peekable();
        let mut frame = parse_single_frame(&mut line_it).expect("parse should succeed");
        let has_vel = parse_velocity_section(&mut line_it, &frame.header, &mut frame.atom_data)
            .expect("should succeed with no velocities");
        assert!(!has_vel);
        assert_eq!(frame.atom_data[0].velocity(), None);
    }

    #[test]
    fn test_parse_line_of_range_f64_exact() {
        let vals = parse_line_of_range_f64("1.0 2.0 3.0 0.0 42", 4, 5, &[0.0; 5]).unwrap();
        assert_eq!(vals, vec![1.0, 2.0, 3.0, 0.0, 42.0]);
    }

    #[test]
    fn test_byte_scan_stack_parses_realistic_coord_line() {
        // Typical CON atom line: x y z fixed_mask [atom_id]
        let line = "   0.63939999999999997    0.90449999999999997   -0.00009999999999977 1    0";
        let defaults = [0.0, 0.0, 0.0, 0.0, 99.0];
        let mut buf = [0.0f64; NUMERIC_STACK_WIDTH];
        let n = parse_line_of_range_f64_stack(line, 4, 5, &defaults, &mut buf).unwrap();
        assert_eq!(n, 5);
        assert!((buf[0] - 0.6394).abs() < 1e-4);
        assert!((buf[1] - 0.9045).abs() < 1e-4);
        assert_eq!(buf[3] as u8, 1);
        assert_eq!(buf[4] as u64, 0);
        // trailing junk must error
        let bad = "1.0 2.0 3.0 1 0 EXTRA";
        assert!(parse_line_of_range_f64_stack(bad, 4, 5, &defaults, &mut buf).is_err());
        // partial non-boundary token must error
        let glued = "1.0 2.0 3.0abc 1 0";
        assert!(parse_line_of_range_f64_stack(glued, 4, 5, &defaults, &mut buf).is_err());
    }

    #[test]
    fn test_parse_line_of_range_f64_stack_matches_vec_api() {
        let defaults = [0.0, 0.0, 0.0, 0.0, 7.0];
        let line = "1.0 2.0 3.0 0.0";
        let mut buf = [0.0f64; NUMERIC_STACK_WIDTH];
        parse_line_of_range_f64_stack(line, 4, 5, &defaults, &mut buf).unwrap();
        let via_vec = parse_line_of_range_f64(line, 4, 5, &defaults).unwrap();
        assert_eq!(&buf[..5], via_vec.as_slice());
        assert_eq!(buf[4], 7.0);
    }

    #[test]
    fn test_parse_line_of_range_f64_padded() {
        let defaults = [0.0, 0.0, 0.0, 0.0, 99.0];
        let vals = parse_line_of_range_f64("1.0 2.0 3.0 0.0", 4, 5, &defaults).unwrap();
        assert_eq!(vals, vec![1.0, 2.0, 3.0, 0.0, 99.0]);
    }

    #[test]
    fn test_parse_line_of_range_f64_too_few() {
        let result = parse_line_of_range_f64("1.0 2.0 3.0", 4, 5, &[0.0; 5]);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_line_of_range_f64_too_many() {
        let result = parse_line_of_range_f64("1.0 2.0 3.0 0.0 5.0 6.0", 4, 5, &[0.0; 5]);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_all_four_column_lines() {
        // All atom lines have only 4 columns; atom_index defaults to sequential.
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 10.0 10.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "3",
            "12.011",
            "C",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0",
            "1.0 0.0 0.0 0",
            "2.0 0.0 0.0 1",
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();
        assert_eq!(frame.atom_data[0].atom_id, 0);
        assert_eq!(frame.atom_data[1].atom_id, 1);
        assert_eq!(frame.atom_data[2].atom_id, 2);
        assert!(frame.atom_data[2].is_fixed());
    }

    #[test]
    fn test_positions_take_the_storage_dtype_of_the_metadata() {
        use crate::storage_dtype::{ElementKind, FloatArray2};
        let rows = [[0.5, -1.25, 3.0], [1.0e-3, 2.5e4, -7.75]];
        let atom_lines: Vec<String> = rows
            .iter()
            .enumerate()
            .map(|(id, [x, y, z])| format!("{x} {y} {z} 0 {id}"))
            .collect();
        for &kind in ElementKind::all_hosted() {
            let metadata = format!(
                "{{\"con_spec_version\":3,\"units\":{{\"length\":\"angstrom\",\"energy\":\"eV\"}},\
                 \"storage_dtypes\":{{\"positions\":\"{}\"}}}}",
                kind.as_str()
            );
            let mut lines = vec![
                "PREBOX1",
                metadata.as_str(),
                "10.0 10.0 10.0",
                "90.0 90.0 90.0",
                "POSTBOX1",
                "POSTBOX2",
                "1",
                "2",
                "1.008",
                "H",
                "Coordinates of Component 1",
            ];
            lines.extend(atom_lines.iter().map(String::as_str));
            let frame = parse_single_frame(&mut lines.iter().copied()).unwrap();
            assert_eq!(frame.positions.kind(), kind);
            assert_eq!(frame.positions.nrows(), rows.len());
            for (i, &xyz) in rows.iter().enumerate() {
                let mut expected = FloatArray2::zeros(kind, 1, 3);
                expected.set_f64_row(0, xyz);
                assert_eq!(
                    frame.positions.as_f64_row(i),
                    expected.as_f64_row(0),
                    "{kind:?} row {i}"
                );
            }
        }
    }
}
