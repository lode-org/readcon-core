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
    /// Absolute newline positions of the coordinate rows, one vector per
    /// frame. Empty when the rows were not indexed.
    pub(crate) wide_breaks: Vec<Vec<usize>>,
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
    parse_con(bytes, false, false, true, 1)
}

/// Coordinates plus column 5, the fixed mask, and the per-type symbol runs.
///
/// The position walker still skips vector sections by line count. `ids`,
/// `flags`, and `components` are filled so a later frame can keep an element
/// order that is not the first frame's.
pub fn positions_with_identity(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    parse_con(bytes, true, false, true, 1)
}

/// Like [`positions_from_con_bytes`], also keeping ids, flags, and symbols
/// so a frame can be rebuilt without a second numeric scan.
#[allow(dead_code)]
pub fn positions_for_frames(bytes: &[u8]) -> Result<ConPositions, ParseError> {
    // A vector section means the frame objects cannot be rebuilt from the
    // coordinate column. Stop at the first one so the caller can fall back
    // to the frame parser without a second full walk.
    parse_con(bytes, true, true, true, 1)
}

/// Header walk plus a parallel fill of the coordinate rows.
///
/// The serial walker parses every float on the calling thread and the
/// old parallel path parsed them again. This walk only counts lines,
/// then the rows are parsed into one buffer. `workers < 2` is the
/// serial walker.
#[cfg(feature = "parallel")]
pub(crate) fn positions_parallel(
    bytes: &[u8],
    workers: usize,
    rich: bool,
) -> Result<ConPositions, ParseError> {
    if workers < 2 {
        return parse_con(bytes, rich, false, true, 1);
    }
    let mut out = parse_con(bytes, rich, false, false, workers)?;
    let n_atoms: usize = out.counts.iter().sum();
    let mut positions = Vec::<f64>::with_capacity(n_atoms.saturating_mul(3));
    // The workers write every lane. A zeroed allocation would fault the
    // slab on this thread before they start.
    if n_atoms > 0 {
        // SAFETY: every index is overwritten before the buffer is read,
        // and `f64` has no destructor.
        unsafe { positions.set_len(n_atoms * 3) };
    }
    let mut ids = Vec::<u64>::new();
    let mut flags = Vec::<u8>::new();
    if rich && n_atoms > 0 {
        ids = Vec::with_capacity(n_atoms);
        flags = Vec::with_capacity(n_atoms);
        // SAFETY: same as the position slab.
        unsafe {
            ids.set_len(n_atoms);
            flags.set_len(n_atoms);
        }
    }
    let mut jobs = Vec::with_capacity(out.n_frames);
    let mut dest_at = 0usize;
    for frame in 0..out.n_frames {
        jobs.push((frame, dest_at));
        dest_at += out.counts[frame];
    }
    // One wide frame must start the row split on this thread. An outer
    // parallel iterator of a single job would run the split inside a
    // worker that already holds the pool.
    if jobs.len() == 1 {
        let (frame, dest) = jobs[0];
        fill_frame_rows(
            bytes,
            &out,
            frame,
            dest,
            workers,
            rich,
            positions.as_mut_ptr(),
            ids.as_mut_ptr(),
            flags.as_mut_ptr(),
        )?;
        out.positions = positions;
        if rich {
            out.ids = ids;
            out.flags = flags;
        }
        return Ok(out);
    }
    let positions_ptr = positions.as_mut_ptr() as usize;
    let ids_ptr = ids.as_mut_ptr() as usize;
    let flags_ptr = flags.as_mut_ptr() as usize;
    use rayon::prelude::*;
    let failed = jobs.par_iter().find_map_any(|&(frame, dest)| {
        fill_frame_rows(
            bytes,
            &out,
            frame,
            dest,
            workers,
            rich,
            positions_ptr as *mut f64,
            ids_ptr as *mut u64,
            flags_ptr as *mut u8,
        )
        .err()
    });
    if let Some(err) = failed {
        return Err(err);
    }
    out.positions = positions;
    if rich {
        out.ids = ids;
        out.flags = flags;
    }
    Ok(out)
}

#[cfg(feature = "parallel")]
fn fill_frame_rows(
    bytes: &[u8],
    out: &ConPositions,
    frame: usize,
    dest: usize,
    workers: usize,
    rich: bool,
    positions: *mut f64,
    ids: *mut u64,
    flags: *mut u8,
) -> Result<(), ParseError> {
    let count = out.counts[frame];
    if count == 0 {
        return Ok(());
    }
    let head = out.head_ends[frame];
    let spec = frame_spec(bytes, out.spans[frame].start)?;
    if out.wide_breaks.get(frame).map(|item| item.len()) == Some(count) {
        let breaks = &out.wide_breaks[frame];
        let mut relative = Vec::with_capacity(count);
        for &absolute in breaks {
            relative.push(absolute - head);
        }
        let ids_ptr = if rich {
            unsafe { ids.add(dest) }
        } else {
            std::ptr::null_mut()
        };
        let flags_ptr = if rich {
            unsafe { flags.add(dest) }
        } else {
            std::ptr::null_mut()
        };
        return crate::parser::fill_rows_from_breaks(
            &bytes[head..],
            &relative,
            spec,
            0,
            workers,
            unsafe { positions.add(dest * 3) },
            ids_ptr,
            flags_ptr,
        );
    }
    let rows = if count >= 4096 {
        crate::parser::parallel_coord_rows(&bytes[head..], count, spec, 0, workers, None)?
    } else {
        serial_coord_rows(&bytes[head..], count, spec)?
    };
    if rows.xyz.len() != count * 3 {
        return Err(ParseError::InvalidCount(
            "frame atom count does not match the first frame".into(),
        ));
    }
    unsafe {
        std::ptr::copy_nonoverlapping(rows.xyz.as_ptr(), positions.add(dest * 3), count * 3);
        if rich {
            std::ptr::copy_nonoverlapping(rows.ids.as_ptr(), ids.add(dest), count);
            for (index, flag) in rows.flags.iter().enumerate() {
                *flags.add(dest + index) = flag_bits(*flag);
            }
        }
    }
    Ok(())
}

#[cfg(feature = "parallel")]
fn frame_spec(bytes: &[u8], frame_start: usize) -> Result<u32, ParseError> {
    let mut pos = frame_start;
    skip_line(bytes, &mut pos)?;
    let meta = read_line(bytes, &mut pos)?;
    spec_version(meta)
}

#[cfg(feature = "parallel")]
fn serial_coord_rows(
    bytes: &[u8],
    n: usize,
    spec: u32,
) -> Result<crate::parser::CoordRows, ParseError> {
    let mut xyz = Vec::with_capacity(n * 3);
    let mut ids = Vec::with_capacity(n);
    let mut flags = Vec::with_capacity(n);
    let mut pos = 0usize;
    let mut default_id = 0u64;
    for _ in 0..n {
        let ((row, fixed, atom_id), next) = parse_coord_row_at(bytes, pos, spec, default_id)?;
        xyz.extend_from_slice(&row);
        ids.push(atom_id);
        flags.push(fixed);
        pos = next;
        default_id = default_id.saturating_add(1);
    }
    Ok(crate::parser::CoordRows {
        xyz,
        ids,
        flags,
        atoms: Vec::new(),
        consumed: pos,
    })
}

fn parse_con(
    bytes: &[u8],
    rich: bool,
    stop_on_section: bool,
    store_rows: bool,
    workers: usize,
) -> Result<ConPositions, ParseError> {
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
        wide_breaks: Vec::new(),
    };
    loop {
        if pos >= bytes.len() || bytes[pos..].iter().all(u8::is_ascii_whitespace) {
            break;
        }
        let start = pos;
        let (n, stock) = parse_one_frame(bytes, &mut pos, &mut out, rich, store_rows, workers)?;
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
    store_rows: bool,
    workers: usize,
) -> Result<(usize, bool), ParseError> {
    out.wide_breaks.push(Vec::new());
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
    if store_rows {
        let total: usize = counts.iter().sum();
        // One allocation for the whole frame. Growing by three floats at a
        // time copied the slab on every power of two, which is what made a
        // one-thread million-atom read slower than the plain walker.
        out.positions.reserve(total.saturating_mul(3));
        out.masses.reserve(total);
        if rich {
            out.ids.reserve(total);
            out.flags.reserve(total);
        }
    }
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
        if store_rows {
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
        } else if counts.len() == 1 && *count >= 4096 && workers >= 2 {
            let start = *pos;
            let index = crate::parser::newline_index(&bytes[start..], workers);
            if index.len() < *count {
                return Err(ParseError::IncompleteFrame);
            }
            out.wide_breaks
                .last_mut()
                .expect("frame breaks")
                .extend(index.iter().take(*count).map(|rel| start + rel));
            *pos = start + index[*count - 1] + 1;
            out.masses.extend(std::iter::repeat_n(*mass, *count));
            n += *count;
        } else {
            skip_count_lines(bytes, pos, *count)?;
            out.masses.extend(std::iter::repeat_n(*mass, *count));
            n += *count;
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

fn skip_count_lines(bytes: &[u8], pos: &mut usize, n: usize) -> Result<(), ParseError> {
    let rest = &bytes[*pos..];
    let mut seen = 0usize;
    let mut at = 0usize;
    while seen < n {
        if at >= rest.len() {
            return Err(ParseError::IncompleteFrame);
        }
        match memchr::memchr(b'\n', &rest[at..]) {
            Some(hit) => {
                at += hit + 1;
                seen += 1;
            }
            None => {
                at = rest.len();
                seen += 1;
                if seen < n {
                    return Err(ParseError::IncompleteFrame);
                }
            }
        }
    }
    *pos += at;
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

    #[cfg(feature = "parallel")]
    #[test]
    fn parallel_rows_match_the_serial_walker_on_a_wide_frame() {
        let n = 5000usize;
        let mut text = String::new();
        text.push_str(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!(" {i}.000000 0.250000 0.500000 0 {i}\n"));
        }
        let bytes = text.as_bytes();
        let serial = positions_with_identity(bytes).unwrap();
        let parallel = positions_parallel(bytes, 4, true).unwrap();
        assert_eq!(parallel.counts, serial.counts);
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        assert_eq!(parallel.ids, serial.ids);
        assert_eq!(parallel.flags, serial.flags);
        assert_eq!(parallel.masses, serial.masses);
    }

    #[cfg(feature = "parallel")]
    #[test]
    fn parallel_newlines_match_serial_rows_past_one_mib() {
        let n = 80_000usize;
        let mut text = String::new();
        text.push_str(
            "grid\n{\"con_spec_version\":2}\n100.0 100.0 100.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!("{i}.125000 1.250000 2.500000 0 {i}\n"));
        }
        assert!(text.len() > (1 << 20));
        let bytes = text.as_bytes();
        let serial = positions_with_identity(bytes).unwrap();
        let parallel = positions_parallel(bytes, 4, true).unwrap();
        assert_eq!(
            first_bit_mismatch(&parallel.positions, &serial.positions),
            None
        );
        assert_eq!(parallel.ids, serial.ids);
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
