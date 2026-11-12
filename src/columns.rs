//! Lazy coordinate columns.
//!
//! simdjson splits a structural index from value materialization
//! (Langdale and Lemire, VLDB Journal 2019, <https://doi.org/10.1007/s00778-019-00578-5>).
//! CON already finds newlines with `memchr` and AVX2. The cost that remains
//! on a homogeneous trajectory is the per-frame object: JSON metadata,
//! owned header strings, and an atom table. This walker reads the counts
//! the frame-skip path reads, writes `x y z` into one buffer, and skips
//! vector sections by line count.

use std::sync::Arc;

use crate::error::ParseError;
use crate::parser::{
    line_has_component_label, parse_coord_row_at, parse_count_line, parse_line_of_n_f64,
};

/// The two metadata lines this walker certifies without a second parse.
/// Anything else, including extra JSON keys, is left to the frame parser.
const STOCK_V2: &[u8] = b"{\"con_spec_version\":2}";
const STOCK_V3: &[u8] = b"{\"con_spec_version\":3,\"con_spec_minor\":1,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}";

/// Coordinates in file order, plus the byte span of each frame.
///
/// `stock` is true when every metadata line is spec 1 or one of the two
/// stock JSON lines, and every section label is a known CON section. The
/// read path uses that certificate. A false certificate means the frame
/// parser must produce the result.
#[derive(Debug, Clone, PartialEq)]
pub struct ConPositions {
    pub n_frames: usize,
    pub counts: Vec<usize>,
    pub positions: Vec<f64>,
    /// Six numbers per frame: box lengths, then angles.
    pub cells: Vec<f64>,
    /// One mass per atom, repeated from the per-type mass line.
    pub masses: Vec<f64>,
    pub spans: Vec<std::ops::Range<usize>>,
    pub stock: bool,
    /// True when any frame had a vector section after the coordinates.
    pub has_section: bool,
    pub ids: Vec<u64>,
    /// Column-4 bitmask, one per atom.
    pub flags: Vec<u8>,
    /// `(symbol, atom count)` in file order, across every frame.
    pub components: Vec<(Arc<str>, usize)>,
    /// Byte offset where the first coordinate row of each frame starts.
    pub head_ends: Vec<usize>,
}

impl ConPositions {
    /// Atom count when every frame has the same count.
    pub fn rectangular_atoms(&self) -> Option<usize> {
        let first = *self.counts.first()?;
        self.counts
            .iter()
            .all(|count| *count == first)
            .then_some(first)
    }
}

/// Positions from a CON or convel buffer, in file order.
pub fn positions_from_con_bytes(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    parse_con(bytes, false, false)
}

/// Like [`positions_from_con_bytes`], also keeping ids, flags, and symbols
/// so a frame can be rebuilt without a second numeric scan.
#[allow(dead_code)]
pub fn positions_for_frames(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    // A vector section means the frame objects cannot be rebuilt from the
    // coordinate column. Stop at the first one so the caller can fall back
    // to the frame parser without a second full walk.
    parse_con(bytes, true, true)
}

fn parse_con(bytes: &[u8], rich: bool, stop_on_section: bool) -> Result<ConPositions, ParseError> {
    let mut pos = 0usize;
    let mut out = ConPositions {
        n_frames: 0,
        counts: Vec::new(),
        positions: Vec::new(),
        cells: Vec::new(),
        masses: Vec::new(),
        spans: Vec::new(),
        stock: true,
        has_section: false,
        ids: Vec::new(),
        flags: Vec::new(),
        components: Vec::new(),
        head_ends: Vec::new(),
    };
    loop {
        if pos >= bytes.len() || bytes[pos..].iter().all(u8::is_ascii_whitespace) {
            break;
        }
        let start = pos;
        let (n, stock) = parse_one_frame(bytes, &mut pos, &mut out, rich)?;
        out.stock &= stock;
        out.counts.push(n);
        out.spans.push(start..pos);
        out.n_frames += 1;
        if stop_on_section && out.has_section {
            break;
        }
    }
    Ok(out)
}

fn parse_one_frame(
    bytes: &[u8],
    pos: &mut usize,
    out: &mut ConPositions,
    rich: bool,
) -> Result<(usize, bool), ParseError> {
    skip_line(bytes, pos)?;
    let meta = read_line(bytes, pos)?;
    let spec = spec_version(meta)?;
    let mut stock = stock_meta_line(meta);
    let box_line = utf8_line(read_line(bytes, pos)?)?;
    let boxl = parse_line_of_n_f64(box_line, 3)?;
    let ang_line = utf8_line(read_line(bytes, pos)?)?;
    let angles = parse_line_of_n_f64(ang_line, 3)?;
    out.cells.extend_from_slice(&boxl);
    out.cells.extend_from_slice(&angles);
    skip_line(bytes, pos)?;
    skip_line(bytes, pos)?;
    let types_line = utf8_line(read_line(bytes, pos)?)?;
    let natm_types = parse_count_line(types_line, 1)?[0];
    if natm_types == 0 {
        zero_atom_tail(bytes, pos)?;
        return Ok((0, stock));
    }
    let count_line = utf8_line(read_line(bytes, pos)?)?;
    let counts = parse_count_line(count_line, natm_types)?;
    if counts.contains(&0) {
        return Err(ParseError::InvalidCount(
            "each per-type count must be >= 1".into(),
        ));
    }
    let mass_line = utf8_line(read_line(bytes, pos)?)?;
    let masses = parse_line_of_n_f64(mass_line, natm_types)?;
    let mut n = 0usize;
    let mut head_end = *pos;
    for (count, mass) in counts.iter().zip(&masses) {
        let symbol_line = utf8_line(read_line(bytes, pos)?)?;
        let symbol: Arc<str> = Arc::from(symbol_line.trim());
        if rich {
            out.components.push((symbol, *count));
        }
        skip_line(bytes, pos)?;
        if n == 0 {
            head_end = *pos;
        }
        for atom in 0..*count {
            let (row, next) = parse_coord_row_at(bytes, *pos, spec, atom as u64)?;
            out.positions.extend_from_slice(&row.0);
            if rich {
                out.ids.push(row.2);
                out.flags.push(flag_bits(row.1));
            }
            out.masses.push(*mass);
            *pos = next;
            n += 1;
        }
    }
    let block_lines = n + natm_types * 2;
    let (certified, saw_section) = skip_sections(bytes, pos, block_lines)?;
    if !certified {
        stock = false;
    }
    out.has_section |= saw_section;
    out.head_ends.push(head_end);
    Ok((n, stock))
}

fn stock_meta_line(line: &[u8]) -> bool {
    let line = trim_ascii(line);
    if !line.starts_with(b"{") {
        return true;
    }
    line == STOCK_V2 || line == STOCK_V3
}

fn zero_atom_tail(bytes: &[u8], pos: &mut usize) -> Result<(), ParseError> {
    let bad = || {
        ParseError::InvalidCount("a zero-atom frame requires whitespace-only lines 8 and 9".into())
    };
    if *pos >= bytes.len() {
        return Ok(());
    }
    if !is_blank(read_line(bytes, pos)?) {
        return Err(bad());
    }
    if *pos >= bytes.len() {
        return Ok(());
    }
    if !is_blank(read_line(bytes, pos)?) {
        return Err(bad());
    }
    Ok(())
}

fn flag_bits(flags: [bool; 3]) -> u8 {
    u8::from(flags[0]) | (u8::from(flags[1]) << 1) | (u8::from(flags[2]) << 2)
}

/// `(certified, saw a section)`.
fn skip_sections(
    bytes: &[u8],
    pos: &mut usize,
    block_lines: usize,
) -> Result<(bool, bool), ParseError> {
    let mut saw = false;
    loop {
        if *pos >= bytes.len() {
            return Ok((true, saw));
        }
        let rest = &bytes[*pos..];
        let eol = memchr::memchr(b'\n', rest);
        let line = strip_cr(match eol {
            Some(i) => &rest[..i],
            None => rest,
        });
        if !is_blank(line) {
            return Ok((true, saw));
        }
        let after = eol.map(|i| *pos + i + 1).unwrap_or(bytes.len());
        if bytes[after..].iter().all(u8::is_ascii_whitespace) {
            *pos = bytes.len();
            return Ok((true, saw));
        }
        if !blank_opens_section(bytes, after)? {
            return Ok((true, saw));
        }
        let known = section_word_known(bytes, after)?;
        *pos = after;
        for _ in 0..block_lines {
            skip_line(bytes, pos)?;
        }
        saw = true;
        if !known {
            return Ok((false, saw));
        }
    }
}

fn section_word_known(bytes: &[u8], blank_end: usize) -> Result<bool, ParseError> {
    let after_symbol = next_line_pos(bytes, blank_end);
    let Some(label) = line_at(bytes, after_symbol) else {
        return Ok(false);
    };
    let text = utf8_line(label)?;
    let word = text.split_ascii_whitespace().next().unwrap_or("");
    Ok(matches!(
        word,
        "Velocities"
            | "Forces"
            | "Energies"
            | "Charges"
            | "Spins"
            | "Magmoms"
            | "Displacements"
            | "Spreads"
    ))
}

fn blank_opens_section(bytes: &[u8], blank_end: usize) -> Result<bool, ParseError> {
    let Some(line1) = line_at(bytes, blank_end) else {
        return Ok(false);
    };
    if is_blank(line1) {
        return Ok(false);
    }
    let text1 = utf8_line(line1)?;
    if text1.trim_start().starts_with('{') {
        return Ok(false);
    }
    let after1 = next_line_pos(bytes, blank_end);
    let Some(line2) = line_at(bytes, after1) else {
        return Ok(false);
    };
    Ok(line_has_component_label(utf8_line(line2)?))
}

fn spec_version(line: &[u8]) -> Result<u32, ParseError> {
    let line = trim_ascii(line);
    if !line.starts_with(b"{") {
        return Ok(1);
    }
    let key = b"\"con_spec_version\"";
    let Some(at) = find_slice(line, key) else {
        return Err(ParseError::MissingSpecVersion);
    };
    let mut i = at + key.len();
    while i < line.len() && matches!(line[i], b' ' | b'\t' | b':') {
        i += 1;
    }
    if i >= line.len() || !line[i].is_ascii_digit() {
        return Err(ParseError::InvalidMetadataJson(
            "con_spec_version must be an integer".into(),
        ));
    }
    let mut val: u32 = 0;
    while i < line.len() && line[i].is_ascii_digit() {
        let digit = u32::from(line[i] - b'0');
        val = val
            .checked_mul(10)
            .and_then(|v| v.checked_add(digit))
            .ok_or(ParseError::UnsupportedVersion(u32::MAX))?;
        i += 1;
    }
    if val == 0 || val > crate::CON_SPEC_VERSION {
        return Err(ParseError::UnsupportedVersion(val));
    }
    Ok(val)
}

fn utf8_line(line: &[u8]) -> Result<&str, ParseError> {
    std::str::from_utf8(line).map_err(|_| ParseError::ValidationError("invalid UTF-8".into()))
}

fn is_blank(line: &[u8]) -> bool {
    line.iter().all(|b| matches!(b, b' ' | b'\t'))
}

fn strip_cr(line: &[u8]) -> &[u8] {
    if line.last() == Some(&b'\r') {
        &line[..line.len() - 1]
    } else {
        line
    }
}

fn trim_ascii(line: &[u8]) -> &[u8] {
    let start = line
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .unwrap_or(line.len());
    let end = line
        .iter()
        .rposition(|b| !b.is_ascii_whitespace())
        .map(|i| i + 1)
        .unwrap_or(start);
    &line[start..end]
}

fn read_line<'a>(bytes: &'a [u8], pos: &mut usize) -> Result<&'a [u8], ParseError> {
    if *pos >= bytes.len() {
        return Err(ParseError::IncompleteFrame);
    }
    let rest = &bytes[*pos..];
    let (raw, advance) = match memchr::memchr(b'\n', rest) {
        Some(i) => (&rest[..i], i + 1),
        None => (rest, rest.len()),
    };
    *pos += advance;
    Ok(strip_cr(raw))
}

fn skip_line(bytes: &[u8], pos: &mut usize) -> Result<(), ParseError> {
    let _ = read_line(bytes, pos)?;
    Ok(())
}

fn line_at(bytes: &[u8], pos: usize) -> Option<&[u8]> {
    if pos >= bytes.len() {
        return None;
    }
    let rest = &bytes[pos..];
    let raw = match memchr::memchr(b'\n', rest) {
        Some(i) => &rest[..i],
        None => rest,
    };
    Some(strip_cr(raw))
}

fn next_line_pos(bytes: &[u8], pos: usize) -> usize {
    let rest = &bytes[pos..];
    match memchr::memchr(b'\n', rest) {
        Some(i) => pos + i + 1,
        None => bytes.len(),
    }
}

fn find_slice(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len())
        .position(|window| window == needle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::ConFrameIterator;
    use std::path::PathBuf;

    fn first_bit_mismatch(left: &[f64], right: &[f64]) -> Option<usize> {
        if left.len() != right.len() {
            return Some(left.len().min(right.len()));
        }
        left.iter()
            .zip(right)
            .position(|(a, b)| a.to_bits() != b.to_bits())
    }

    fn manifest(rel: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(rel)
    }

    fn bits_match_iterator(rel: &str) {
        let bytes = std::fs::read(manifest(rel)).unwrap();
        let got = positions_from_con_bytes(&bytes).unwrap();
        let mut expected = Vec::new();
        let mut counts = Vec::new();
        for frame in ConFrameIterator::from_bytes(&bytes) {
            let frame = frame.unwrap();
            counts.push(frame.atom_data.len());
            for atom in &frame.atom_data {
                expected.extend_from_slice(&[atom.x, atom.y, atom.z]);
            }
        }
        assert_eq!(got.counts, counts, "{rel}");
        assert_eq!(first_bit_mismatch(&got.positions, &expected), None, "{rel}");
        assert_eq!(got.spans.first().map(|span| span.start), Some(0), "{rel}");
        let tail = got.spans.last().map(|span| span.end).unwrap_or(0);
        assert!(
            bytes[tail..].iter().all(u8::is_ascii_whitespace),
            "{rel} left {} non-whitespace bytes",
            bytes.len() - tail
        );
    }

    #[test]
    fn golden_con_and_convel_match_the_frame_parser() {
        for rel in [
            "resources/conformance/valid/v2_minimal.con",
            "resources/conformance/valid/v3_units.con",
            "resources/conformance/valid/empty_user_line.con",
            "resources/conformance/valid/empty_user_line_two.con",
            "resources/conformance/valid/zero_atom.con",
            "resources/conformance/valid/zero_atom_eof.con",
            "resources/conformance/valid/zero_atom_then_frame.con",
            "resources/conformance/valid/column4_spec1_all_fixed.con",
            "resources/conformance/valid/column4_spec2_xz.con",
            "resources/test/tiny_cuh2.con",
            "resources/test/tiny_cuh2.convel",
            "resources/test/tiny_multi_cuh2.con",
            "resources/test/tiny_multi_cuh2.convel",
            "resources/test/tiny_cuh2_vel_forces.con",
            "resources/test/cuh2.con",
        ] {
            bits_match_iterator(rel);
        }
    }
}
