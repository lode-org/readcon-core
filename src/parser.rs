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
    /// With a blank line peeked, true unless the stream can see that the
    /// line two past the blank is not a `Velocities of Component` label.
    /// Default is true, which keeps the legacy blank-separator rule.
    fn blank_opens_velocity_block(&mut self) -> bool {
        true
    }
}

impl<'a, I> LineStream<'a> for Peekable<I>
where
    I: Iterator<Item = &'a str>,
{
    #[inline]
    fn next_line(&mut self) -> Option<&'a str> {
        Iterator::next(self)
    }
    #[inline]
    fn peek_line(&mut self) -> Option<&'a str> {
        Peekable::peek(self).copied()
    }
}

/// Hot-path: parse up to 5 whitespace-separated f64s into a stack buffer.
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
    out: &mut [f64; 5],
) -> Result<usize, ParseError> {
    debug_assert!(max <= 5 && min <= max && defaults.len() >= max);
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
    if n <= 5 {
        let defaults = [0.0f64; 5];
        let mut buf = [0.0f64; 5];
        parse_line_of_range_f64_stack(line, n, n, &defaults, &mut buf)?;
        return Ok(buf[..n].to_vec());
    }
    let mut values = Vec::with_capacity(n);
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
/// Prefer [`parse_line_of_range_f64_stack`] on the atom hot path (`max <= 5`).
pub fn parse_line_of_range_f64(
    line: &str,
    min: usize,
    max: usize,
    defaults: &[f64],
) -> Result<Vec<f64>, ParseError> {
    if max <= 5 {
        let mut buf = [0.0f64; 5];
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
    let bytes = line.as_bytes();
    let mut i = skip_ascii_ws(bytes, 0);
    let mut xyz = [0.0f64; 3];
    for slot in 0..3 {
        if i >= bytes.len() {
            return Err(ParseError::InvalidVectorLength {
                expected: 5,
                found: slot,
            });
        }
        let (val, next) = parse_finite_at(line, i)?;
        xyz[slot] = val;
        i = skip_ascii_ws(bytes, next);
    }
    let (flag_tok, i) = take_token(line, i).ok_or(ParseError::InvalidVectorLength {
        expected: 5,
        found: 3,
    })?;
    let fixed = parse_fixed_flag(flag_tok, spec_version)?;
    let i = skip_ascii_ws(bytes, i);
    let (atom_id, i) = match take_token(line, i) {
        Some((tok, next)) => (parse_atom_id_token(tok)?, next),
        None => (
            default_id.ok_or(ParseError::InvalidVectorLength {
                expected: 5,
                found: 4,
            })?,
            i,
        ),
    };
    let i = skip_ascii_ws(bytes, i);
    if i < bytes.len() {
        let found = 5 + line[i..].split_ascii_whitespace().count();
        return Err(ParseError::InvalidVectorLength { expected: 5, found });
    }
    Ok((xyz, fixed, atom_id))
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
    let mut values = Vec::with_capacity(n);
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
        if trimmed.starts_with('{') {
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

    let boxl_vec = parse_line_of_n_f64(lines.next().ok_or(ParseError::IncompleteHeader)?, 3)?;
    let angles_vec = parse_line_of_n_f64(lines.next().ok_or(ParseError::IncompleteHeader)?, 3)?;
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
        if natms_per_type.iter().any(|n| *n == 0) {
            return Err(ParseError::InvalidCount(
                "each per-type count must be >= 1".into(),
            ));
        }
        let masses_per_type = parse_line_of_n_f64(
            lines.next().ok_or(ParseError::IncompleteHeader)?,
            natm_types,
        )?;
        (natms_per_type, masses_per_type)
    };
    if validate {
        validate_header_geometry(&boxl_vec, &angles_vec)?;
        validate_masses(&masses_per_type)?;
    }
    Ok(FrameHeader {
        prebox_header: PreboxHeader {
            user: prebox1,
            metadata_line: prebox2,
        },
        boxl: boxl_vec.try_into().unwrap(),
        angles: angles_vec.try_into().unwrap(),
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
    let header = parse_frame_header(lines)?;
    let validate = header.strict_validation;
    let total_atoms: usize = header.natms_per_type.iter().sum();
    let mut atom_data = Vec::with_capacity(total_atoms);
    // SoA positions: default f64 fills a flat `Vec` then one Arc wrap (profile:
    // per-row ArcArray mut checks were a real cost on multi-atom parse).
    use crate::storage_dtype::{ElementKind, FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let f64_positions = dt.positions == ElementKind::Float64;
    let mut pos_flat = if f64_positions {
        vec![0.0f64; total_atoms.saturating_mul(3)]
    } else {
        Vec::new()
    };
    let mut positions_other = if f64_positions {
        None
    } else {
        Some(FloatArray2::zeros(dt.positions, total_atoms, 3))
    };

    let mut global_atom_idx: u64 = 0;
    let mut atom_i = 0usize;
    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        // Allocate the per-component Arc<str> directly from the trimmed
        // line; going through a String intermediate would add a second
        // allocation and copy for no semantic gain.
        let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
        let symbol: Arc<str> = Arc::from(symbol_line.trim());
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
        }
        for _ in 0..*num_atoms {
            let coord_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            // Column 5 is optional and defaults to the 0-based position
            // in the frame (CON-id.9). Flag and id are integer tokens (D8, D9).
            let (xyz, fixed, atom_id) =
                parse_coord_row(coord_line, header.spec_version, global_atom_idx)?;
            if f64_positions {
                let o = atom_i * 3;
                pos_flat[o] = xyz[0];
                pos_flat[o + 1] = xyz[1];
                pos_flat[o + 2] = xyz[2];
            } else if let Some(ref mut pos) = positions_other {
                pos.set_f64_row(atom_i, xyz);
            }
            atom_data.push(AtomDatum {
                // This is a cheap reference-count increment, not a full string clone.
                symbol: Arc::clone(&symbol),
                x: xyz[0],
                y: xyz[1],
                z: xyz[2],
                fixed,
                atom_id,
                velocity: None,
                force: None,
                energy: None,
                charge: None,
                spin: None,
                magmom: None,
                displacement: None,
                spread: None,
            });
            global_atom_idx += 1;
            atom_i += 1;
        }
    }
    let positions = if f64_positions {
        FloatArray2::from_f64_row_major(total_atoms, 3, pos_flat)
    } else {
        positions_other.expect("non-f64 positions allocated")
    };
    // Sections still attach to AoS; assemble uses prefilled positions (no second pos pass).
    Ok(crate::types::con_frame_from_atom_data_with_positions(
        header, atom_data, positions,
    ))
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
    let validate = header.strict_validation;
    // A blank line followed only by whitespace to EOF is not a velocity
    // block (CON-frame.5, D2). Leave those lines for the iterator.
    match lines.peek_line() {
        Some(line) if line.trim().is_empty() => {
            if lines.remainder_is_whitespace() {
                return Ok(false);
            }
            lines.next_line();
        }
        _ => return Ok(false),
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        // Symbol line
        let symbol = lines
            .next_line()
            .ok_or(ParseError::IncompleteSection(SECTION_VELOCITIES.into()))?
            .trim();

        // "Velocities of Component N" line
        let comp_line = lines
            .next_line()
            .ok_or(ParseError::IncompleteSection(SECTION_VELOCITIES.into()))?;
        if !label_has_prefix(comp_line, "Velocities of Component") {
            return Err(ParseError::IncompleteSection(SECTION_VELOCITIES.into()));
        }
        if validate {
            validate_section_component(
                "Velocities",
                type_idx,
                atom_idx,
                symbol,
                comp_line,
                header,
                atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let vel_line = lines
                .next_line()
                .ok_or(ParseError::IncompleteSection(SECTION_VELOCITIES.into()))?;
            let (vals, fixed, atom_id) = parse_vector_section_row(vel_line, header.spec_version)?;
            if validate {
                validate_section_atom_identity("velocities", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].velocity = Some(vals);
            }
            atom_idx += 1;
        }
    }

    Ok(true)
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
    let validate = header.strict_validation;
    if !open_section(lines)? {
        return Ok(false);
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or(ParseError::IncompleteSection(SECTION_FORCES.into()))?
            .trim();

        let comp_line = lines
            .next_line()
            .ok_or(ParseError::IncompleteSection(SECTION_FORCES.into()))?;
        if !label_has_prefix(comp_line, "Forces of Component") {
            return Err(ParseError::IncompleteSection(SECTION_FORCES.into()));
        }
        if validate {
            validate_section_component(
                "Forces", type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let force_line = lines
                .next_line()
                .ok_or(ParseError::IncompleteSection(SECTION_FORCES.into()))?;
            let (vals, fixed, atom_id) = parse_vector_section_row(force_line, header.spec_version)?;
            if validate {
                validate_section_atom_identity("forces", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].force = Some(vals);
            }
            atom_idx += 1;
        }
    }

    Ok(true)
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
                atom_data[atom_idx].energy = Some(value);
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
                    if frame_minor(header) > u64::from(crate::CON_SPEC_MINOR) {
                        if let Some(arity) = section_row_arity(header, other) {
                            skip_unknown_section(lines, header, other, arity)?;
                            continue;
                        }
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
        |a, v| a.charge = Some(v),
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
        |a, v| a.spin = Some(v),
    )
}

fn parse_vector_named_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
    section_name: &str,
    component_label: &str,
    label_kind: &str,
    mut set_value: impl FnMut(&mut AtomDatum, [f64; 3]),
    mut check_row: impl FnMut(usize, [f64; 3]) -> Result<(), ParseError>,
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
                label_kind, type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }
        for _ in 0..num_atoms {
            let row = lines
                .next_line()
                .ok_or_else(|| ParseError::IncompleteSection(section_name.into()))?;
            let (vals, fixed, atom_id) = parse_vector_section_row(row, header.spec_version)?;
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
        SECTION_MAGMOMS,
        "Magmoms of Component",
        "Magmoms",
        |a, v| a.magmom = Some(v),
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
        SECTION_DISPLACEMENTS,
        "Displacements of Component",
        "Displacements",
        |a, v| a.displacement = Some(v),
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
        SECTION_SPREADS,
        "Spreads of Component",
        "Spreads",
        |a, v| a.spread = Some(v),
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
                panic!(
                    "Parsing failed when it should have succeeded. Error: {:?}",
                    e
                );
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        assert_eq!(frame.atom_data[0].velocity, Some([0.1, 0.2, 0.3]));
        assert_eq!(frame.atom_data[1].velocity, Some([0.4, 0.5, 0.6]));
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        let lines = vec![
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
        assert_eq!(frame.atom_data[0].velocity, None);
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
        let mut buf = [0.0f64; 5];
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
        let mut buf = [0.0f64; 5];
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
        let lines = vec![
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
}
