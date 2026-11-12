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
pub fn positions_for_frames(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    // A vector section means the frame objects cannot be rebuilt from the
    // coordinate column. Stop at the first one so the caller can fall back
    // to the frame parser without a second full walk.
    parse_con(bytes, true, true)
}

/// Write one frame's coordinates, masses, and cell into the caller buffers.
///
/// `frame` is one span from the frame-start scan. A metadata line this walker
/// does not certify returns an error so the caller can use the frame parser.
#[cfg(feature = "parallel")]
pub(crate) fn fill_frame_positions(
    frame: &[u8],
    dest: &mut [f64],
    masses: &mut [f64],
    cell: &mut [f64],
) -> Result<(), ParseError> {
    let mut pos = 0usize;
    skip_line(frame, &mut pos)?;
    let meta = read_line(frame, &mut pos)?;
    if !stock_meta_line(meta) {
        return Err(ParseError::ValidationError(
            "column walker declined this metadata line".into(),
        ));
    }
    let spec = spec_version(meta)?;
    let box_line = utf8_line(read_line(frame, &mut pos)?)?;
    let boxl = parse_line_of_n_f64(box_line, 3)?;
    let ang_line = utf8_line(read_line(frame, &mut pos)?)?;
    let angles = parse_line_of_n_f64(ang_line, 3)?;
    if cell.len() < 6 {
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    cell[..3].copy_from_slice(&boxl);
    cell[3..6].copy_from_slice(&angles);
    skip_line(frame, &mut pos)?;
    skip_line(frame, &mut pos)?;
    let types_line = utf8_line(read_line(frame, &mut pos)?)?;
    let natm_types = parse_count_line(types_line, 1)?[0];
    if natm_types == 0 {
        if dest.is_empty() && masses.is_empty() {
            return Ok(());
        }
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    let count_line = utf8_line(read_line(frame, &mut pos)?)?;
    let counts = parse_count_line(count_line, natm_types)?;
    if counts.contains(&0) {
        return Err(ParseError::InvalidCount(
            "each per-type count must be >= 1".into(),
        ));
    }
    let mass_line = utf8_line(read_line(frame, &mut pos)?)?;
    let mass_vals = parse_line_of_n_f64(mass_line, natm_types)?;
    let mut written = 0usize;
    for (count, mass) in counts.iter().zip(&mass_vals) {
        skip_line(frame, &mut pos)?;
        skip_line(frame, &mut pos)?;
        for atom in 0..*count {
            let (row, next) = parse_coord_row_at(frame, pos, spec, atom as u64)?;
            let at = written * 3;
            if at + 3 > dest.len() || written >= masses.len() {
                return Err(ParseError::InvalidCount(
                    "frame atom count does not match the first frame".into(),
                ));
            }
            dest[at..at + 3].copy_from_slice(&row.0);
            masses[written] = *mass;
            pos = next;
            written += 1;
        }
    }
    if written * 3 != dest.len() || written != masses.len() {
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    Ok(())
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

/// Extended XYZ positions.
///
/// The comment line must carry `Lattice` and `Properties`, the same
/// requirement as [`crate::extxyz_scan::tables_from_extxyz_bytes`]. Atom
/// lines are parsed as they are reached; the line table is not stored.
#[cfg_attr(not(feature = "scout"), allow(dead_code))]
pub fn positions_from_extxyz_bytes(bytes: &[u8]) -> Result<ConPositions, String> {
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
    let mut cached_comment: Vec<u8> = Vec::new();
    let mut cached_col = 0usize;
    while pos < bytes.len() {
        if bytes[pos..].iter().all(u8::is_ascii_whitespace) {
            break;
        }
        let start = pos;
        let count_line = trim_ascii(read_line(bytes, &mut pos).map_err(|err| err.to_string())?);
        if count_line.is_empty() {
            continue;
        }
        let count = parse_extxyz_count(count_line)?;
        let comment = read_line(bytes, &mut pos).map_err(|err| err.to_string())?;
        if quoted_after(comment, b"Lattice=").is_none() {
            return Err("lattice".into());
        }
        let pos_col = if comment == cached_comment.as_slice() {
            cached_col
        } else {
            let properties = quoted_after(comment, b"Properties=").ok_or("properties")?;
            let col = pos_column(properties)?;
            cached_comment.clear();
            cached_comment.extend_from_slice(comment);
            cached_col = col;
            col
        };
        for _ in 0..count {
            let line = read_line(bytes, &mut pos).map_err(|err| err.to_string())?;
            let (x, y, z) = xyz_from_atom_line(line, pos_col)?;
            out.positions.extend_from_slice(&[x, y, z]);
        }
        out.counts.push(count);
        out.spans.push(start..pos);
        out.n_frames += 1;
    }
    if out.n_frames == 0 {
        return Err("no frames".into());
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
        if rich {
            let symbol: Arc<str> = Arc::from(symbol_line.trim());
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

fn parse_extxyz_count(line: &[u8]) -> Result<usize, String> {
    let text = std::str::from_utf8(line).map_err(|_| "count")?;
    let token = text.split_ascii_whitespace().next().ok_or("count")?;
    token.parse::<usize>().map_err(|_| "count".into())
}

fn quoted_after<'a>(line: &'a [u8], key: &[u8]) -> Option<&'a [u8]> {
    let mut index = 0;
    while index + key.len() <= line.len() {
        if &line[index..index + key.len()] == key {
            let mut cursor = index + key.len();
            if cursor < line.len() && line[cursor] == b'"' {
                cursor += 1;
                let start = cursor;
                while cursor < line.len() && line[cursor] != b'"' {
                    cursor += 1;
                }
                return Some(&line[start..cursor]);
            }
            let start = cursor;
            while cursor < line.len() && !line[cursor].is_ascii_whitespace() {
                cursor += 1;
            }
            return Some(&line[start..cursor]);
        }
        index += 1;
    }
    None
}

fn pos_column(properties: &[u8]) -> Result<usize, String> {
    let mut offset = 0usize;
    let mut pos = None;
    let mut rest = properties;
    while !rest.is_empty() {
        let name_end = rest.iter().position(|b| *b == b':').ok_or("properties")?;
        let name = &rest[..name_end];
        rest = &rest[name_end + 1..];
        let kind_end = rest.iter().position(|b| *b == b':').ok_or("properties")?;
        rest = &rest[kind_end + 1..];
        let count_end = rest.iter().position(|b| *b == b':').unwrap_or(rest.len());
        let count: usize = std::str::from_utf8(&rest[..count_end])
            .map_err(|_| "properties")?
            .parse()
            .map_err(|_| "properties")?;
        if name == b"pos" {
            pos = Some(offset);
        }
        offset += count;
        if count_end == rest.len() {
            break;
        }
        rest = &rest[count_end + 1..];
    }
    pos.ok_or("pos".into())
}

fn xyz_from_atom_line(line: &[u8], pos_col: usize) -> Result<(f64, f64, f64), String> {
    let mut index = 0usize;
    let mut column = 0usize;
    let mut coords = [0.0; 3];
    let mut got = 0usize;
    while let Some((start, end)) = next_token(line, index) {
        if column >= pos_col && column < pos_col + 3 {
            coords[got] = token_f64(&line[start..end])?;
            got += 1;
        }
        column += 1;
        index = end;
        if got == 3 {
            break;
        }
    }
    if got != 3 {
        return Err("atom".into());
    }
    Ok((coords[0], coords[1], coords[2]))
}

fn next_token(line: &[u8], mut index: usize) -> Option<(usize, usize)> {
    while index < line.len() && line[index].is_ascii_whitespace() {
        index += 1;
    }
    if index >= line.len() {
        return None;
    }
    let start = index;
    while index < line.len() && !line[index].is_ascii_whitespace() {
        index += 1;
    }
    Some((start, index))
}

fn token_f64(token: &[u8]) -> Result<f64, String> {
    let (value, consumed) =
        fast_float2::parse_partial::<f64, _>(token).map_err(|_| "float".to_string())?;
    if consumed == 0 {
        return Err("float".into());
    }
    Ok(value)
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

    #[test]
    fn extxyz_matches_the_line_table_reader() {
        let text = "\
2
Lattice=\"10 0 0 0 12 0 0 0 14\" Properties=species:S:1:pos:R:3:masses:R:1 pbc=\"T T T\"
Cu 1.0 2.0 3.0 63.546
Cu 4.0 5.0 6.0 63.546
2
Lattice=\"10 0 0 0 12 0 0 0 14\" Properties=species:S:1:pos:R:3:masses:R:1 pbc=\"T T T\"
Cu 1.5 -2.25 3.125 63.546
H 0.25 0.50 0.75 1.007
";
        let got = positions_from_extxyz_bytes(text.as_bytes()).unwrap();
        let expect = crate::extxyz_scan::tables_from_extxyz_bytes(text.as_bytes()).unwrap();
        assert_eq!(got.n_frames, 2);
        assert_eq!(got.counts, vec![2, 2]);
        assert_eq!(first_bit_mismatch(&got.positions, &expect.positions), None);
    }
}
