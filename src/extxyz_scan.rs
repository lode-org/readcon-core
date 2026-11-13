// Copyright (c) readcon-core developers
//! Sequential extended-XYZ scan.
//!
//! One byte buffer, fixed token walks, and plain arrays. The comment
//! line supplies the lattice and the column layout.

use std::fs;
use std::path::Path;

#[derive(Debug, Clone)]
pub struct XyzColumn {
    pub name: String,
    pub kind: u8,
    pub width: usize,
    /// Text values for an `S` column. Empty for a numeric column.
    pub text: Vec<String>,
    /// Numeric values for an `R`, `I`, or `L` column, in column-major
    /// order within each atom. Empty for a text column.
    pub real: Vec<f64>,
}

#[derive(Debug, Clone)]
pub struct XyzTables {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub positions: Vec<f64>,
    pub masses: Vec<f64>,
    pub cell: Vec<f64>,
    /// One symbol per atom, frame by frame. Empty strings when the file
    /// has no `species` column.
    pub species: Vec<String>,
    /// Every per-atom column named by `Properties`, including species,
    /// positions, masses and forces.
    pub columns: Vec<XyzColumn>,
}

fn trim(bytes: &[u8]) -> &[u8] {
    let start = bytes
        .iter()
        .position(|byte| !byte.is_ascii_whitespace())
        .unwrap_or(bytes.len());
    let end = bytes
        .iter()
        .rposition(|byte| !byte.is_ascii_whitespace())
        .map(|index| index + 1)
        .unwrap_or(start);
    &bytes[start..end]
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

fn parse_f64(bytes: &[u8]) -> Result<f64, String> {
    let (value, _consumed) =
        fast_float2::parse_partial::<f64, _>(bytes).map_err(|_| "float".to_string())?;
    // fast_float2 only returns Ok after consuming at least one digit.
    Ok(value)
}

fn quoted_after<'a>(line: &'a [u8], key: &[u8]) -> Option<&'a [u8]> {
    let mut index = 0;
    while index + key.len() <= line.len() {
        if &line[index..index + key.len()] == key {
            let mut mark = index + key.len();
            if mark < line.len() && line[mark] == b'"' {
                mark += 1;
                let start = mark;
                while mark < line.len() && line[mark] != b'"' {
                    mark += 1;
                }
                return Some(&line[start..mark]);
            }
            let start = mark;
            while mark < line.len() && !line[mark].is_ascii_whitespace() {
                mark += 1;
            }
            return Some(&line[start..mark]);
        }
        index += 1;
    }
    None
}

struct ColumnSpec {
    name: String,
    kind: u8,
    width: usize,
    offset: usize,
}

fn property_columns(properties: &[u8]) -> Result<Vec<ColumnSpec>, String> {
    let mut offset = 0;
    let mut columns = Vec::new();
    let mut rest = properties;
    let mut saw_pos = false;
    while !rest.is_empty() {
        let name_end = rest
            .iter()
            .position(|byte| *byte == b':')
            .ok_or("properties")?;
        let name = std::str::from_utf8(&rest[..name_end]).map_err(|_| "properties")?;
        rest = &rest[name_end + 1..];
        let kind_end = rest
            .iter()
            .position(|byte| *byte == b':')
            .ok_or("properties")?;
        if kind_end != 1 {
            return Err("properties".to_string());
        }
        let kind = rest[0];
        if !matches!(kind, b'S' | b'R' | b'I' | b'L') {
            return Err("properties".to_string());
        }
        rest = &rest[kind_end + 1..];
        let count_end = rest
            .iter()
            .position(|byte| *byte == b':')
            .unwrap_or(rest.len());
        let count = parse_f64(&rest[..count_end])? as usize;
        if count == 0 {
            return Err("properties".to_string());
        }
        if name == "pos" {
            saw_pos = true;
            if count != 3 {
                return Err("pos".to_string());
            }
        }
        columns.push(ColumnSpec {
            name: name.to_string(),
            kind,
            width: count,
            offset,
        });
        offset += count;
        if count_end == rest.len() {
            break;
        }
        rest = &rest[count_end + 1..];
    }
    if !saw_pos {
        return Err("pos".to_string());
    }
    Ok(columns)
}

fn logical_value(token: &[u8]) -> f64 {
    match token {
        b"T" | b"t" | b"1" | b"true" | b"True" | b"TRUE" => 1.0,
        _ => 0.0,
    }
}

fn lattice_cell(lattice: &[u8]) -> Result<[f64; 6], String> {
    let mut values = [0.0; 9];
    let mut rest = trim(lattice);
    for slot in values.iter_mut() {
        rest = trim(rest);
        let (value, consumed) =
            fast_float2::parse_partial::<f64, _>(rest).map_err(|_| "lattice".to_string())?;
        *slot = value;
        rest = rest.get(consumed..).unwrap_or(b"");
    }
    let length = |i: usize| {
        (values[i] * values[i] + values[i + 1] * values[i + 1] + values[i + 2] * values[i + 2])
            .sqrt()
    };
    let la = length(0);
    let lb = length(3);
    let lc = length(6);
    let dot = |i: usize, j: usize| {
        values[i] * values[j] + values[i + 1] * values[j + 1] + values[i + 2] * values[j + 2]
    };
    let angle = |cos_v: f64| cos_v.clamp(-1.0, 1.0).acos().to_degrees();
    let gamma = angle(dot(0, 3) / (la * lb));
    let beta = angle(dot(0, 6) / (la * lc));
    let alpha = angle(dot(3, 6) / (lb * lc));
    Ok([la, lb, lc, alpha, beta, gamma])
}

fn tokens(line: &[u8]) -> Vec<&[u8]> {
    let mut found = Vec::new();
    let mut index = 0;
    while let Some((start, end)) = next_token(line, index) {
        found.push(&line[start..end]);
        index = end;
    }
    found
}

fn push_atom(line: &[u8], specs: &[ColumnSpec], columns: &mut [XyzColumn]) -> Result<(), String> {
    let words = tokens(line);
    let need = specs
        .last()
        .map(|spec| spec.offset + spec.width)
        .unwrap_or(0);
    if words.len() < need {
        return Err("atom".to_string());
    }
    for (spec, column) in specs.iter().zip(columns.iter_mut()) {
        for slot in 0..spec.width {
            let token = words[spec.offset + slot];
            match spec.kind {
                b'S' => column
                    .text
                    .push(String::from_utf8_lossy(token).into_owned()),
                b'L' => column.real.push(logical_value(token)),
                _ => column.real.push(parse_f64(token)?),
            }
        }
    }
    Ok(())
}

pub fn tables_from_extxyz_bytes(bytes: &[u8]) -> Result<XyzTables, String> {
    tables_from_extxyz_bytes_with_threads(bytes, 1)
}

/// [`tables_from_extxyz_bytes`] using `workers` for the atom rows.
///
/// `workers < 2` is the serial scan. Two or more workers split frames
/// after the line index. The tables match the serial scan.
pub fn tables_from_extxyz_bytes_with_threads(
    bytes: &[u8],
    workers: usize,
) -> Result<XyzTables, String> {
    if workers < 2 {
        return tables_serial(bytes);
    }
    let lines = split_lines(bytes);
    let mut specs: Vec<ColumnSpec> = Vec::new();
    let mut cell = Vec::new();
    let mut starts = Vec::new();
    let mut mark = 0usize;
    let mut n_atoms = 0usize;
    while mark < lines.len() {
        let count_line = trim(lines[mark]);
        if count_line.is_empty() {
            mark += 1;
            continue;
        }
        let count = parse_f64(count_line)? as usize;
        if mark + 1 >= lines.len() {
            return Err("comment".to_string());
        }
        let comment = lines[mark + 1];
        let lattice = quoted_after(comment, b"Lattice=").ok_or("lattice")?;
        let properties = quoted_after(comment, b"Properties=").ok_or("properties")?;
        let frame_specs = property_columns(properties)?;
        let frame_cell = lattice_cell(lattice)?;
        if starts.is_empty() {
            specs = frame_specs;
            n_atoms = count;
        } else if count != n_atoms
            || frame_specs.len() != specs.len()
            || frame_specs.iter().zip(specs.iter()).any(|(left, right)| {
                left.name != right.name || left.kind != right.kind || left.width != right.width
            })
        {
            return Err("properties".to_string());
        }
        cell.extend_from_slice(&frame_cell);
        mark += 2;
        if mark + count > lines.len() {
            return Err("atoms".to_string());
        }
        starts.push(mark);
        mark += count;
    }
    let n_frames = starts.len();
    if n_frames == 0 {
        return Err("no frames".to_string());
    }
    let mut columns: Vec<XyzColumn> = specs
        .iter()
        .map(|spec| {
            let n = n_frames * n_atoms * spec.width;
            XyzColumn {
                name: spec.name.clone(),
                kind: spec.kind,
                width: spec.width,
                text: if spec.kind == b'S' {
                    Vec::with_capacity(n)
                } else {
                    Vec::new()
                },
                real: if spec.kind == b'S' {
                    Vec::new()
                } else {
                    vec![0.0; n]
                },
            }
        })
        .collect();
    let chunk = n_frames.div_ceil(workers).max(1);
    // The columns are disjoint by frame. Each worker writes its frames.
    let column_ptrs: Vec<(usize, usize, u8, usize)> = columns
        .iter_mut()
        .map(|column| {
            (
                column.text.as_mut_ptr() as usize,
                column.real.as_mut_ptr() as usize,
                column.kind,
                column.width,
            )
        })
        .collect();
    let spec_ref = &specs;
    let line_ref = &lines;
    let failed = std::thread::scope(|scope| {
        let mut handles = Vec::new();
        for worker in 0..workers {
            let from = worker * chunk;
            if from >= n_frames {
                break;
            }
            let to = (from + chunk).min(n_frames);
            let column_ptrs = &column_ptrs;
            let starts = &starts;
            handles.push(scope.spawn(move || -> Result<(), String> {
                for frame in from..to {
                    let base_atom = frame * n_atoms;
                    for (atom, line) in line_ref[starts[frame]..starts[frame] + n_atoms]
                        .iter()
                        .enumerate()
                    {
                        let words = tokens(line);
                        for (col, spec) in spec_ref.iter().enumerate() {
                            let (text_ptr, real_ptr, kind, width) = column_ptrs[col];
                            for slot in 0..width {
                                let token = words.get(spec.offset + slot).copied().ok_or("atom")?;
                                let index = (base_atom + atom) * width + slot;
                                if kind == b'S' {
                                    let text = String::from_utf8_lossy(token).into_owned();
                                    unsafe {
                                        std::ptr::write((text_ptr as *mut String).add(index), text);
                                    }
                                } else {
                                    let value = if kind == b'L' {
                                        logical_value(token)
                                    } else {
                                        parse_f64(token)?
                                    };
                                    unsafe {
                                        *((real_ptr as *mut f64).add(index)) = value;
                                    }
                                }
                            }
                        }
                    }
                }
                Ok(())
            }));
        }
        handles
            .into_iter()
            .find_map(|handle| handle.join().ok().and_then(|result| result.err()))
    });
    if let Some(err) = failed {
        for column in &mut columns {
            // Slots were written with `ptr::write` and `len` is still 0.
            // Forgetting the buffer drops nothing and leaks only on error.
            std::mem::forget(std::mem::take(&mut column.text));
        }
        return Err(err);
    }
    for column in &mut columns {
        if column.kind == b'S' {
            let n = n_frames * n_atoms * column.width;
            unsafe { column.text.set_len(n) };
        }
    }
    assemble_tables(n_frames, n_atoms, cell, columns)
}

fn split_lines(bytes: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut index = 0;
    while index < bytes.len() {
        let start = index;
        while index < bytes.len() && bytes[index] != b'\n' {
            index += 1;
        }
        let mut line = &bytes[start..index];
        if line.last() == Some(&b'\r') {
            line = &line[..line.len() - 1];
        }
        lines.push(line);
        if index < bytes.len() {
            index += 1;
        }
    }
    lines
}

fn assemble_tables(
    n_frames: usize,
    n_atoms: usize,
    cell: Vec<f64>,
    mut columns: Vec<XyzColumn>,
) -> Result<XyzTables, String> {
    let mut positions = Vec::new();
    let mut masses = vec![f64::NAN; n_frames * n_atoms];
    let mut species = Vec::new();
    for column in &mut columns {
        if column.name == "pos" {
            positions.clone_from(&column.real);
        } else if column.name == "masses" || column.name == "mass" {
            if column.width == 1 {
                masses.clone_from(&column.real);
            }
        } else if column.name == "species" && column.width == 1 {
            // The parallel scan wrote each symbol once, into this column.
            // Moving it is the species table. A second clone of every
            // string was the serial tail.
            species = std::mem::take(&mut column.text);
        }
    }
    if positions.len() != n_frames * n_atoms * 3 {
        return Err("pos".to_string());
    }
    Ok(XyzTables {
        n_frames,
        n_atoms,
        positions,
        masses,
        cell,
        species,
        columns,
    })
}

fn tables_serial(bytes: &[u8]) -> Result<XyzTables, String> {
    let mut lines = Vec::new();
    let mut index = 0;
    while index < bytes.len() {
        let start = index;
        while index < bytes.len() && bytes[index] != b'\n' {
            index += 1;
        }
        let mut line = &bytes[start..index];
        if line.last() == Some(&b'\r') {
            line = &line[..line.len() - 1];
        }
        lines.push(line);
        if index < bytes.len() {
            index += 1;
        }
    }
    let mut cell = Vec::new();
    let mut columns: Vec<XyzColumn> = Vec::new();
    let mut specs: Vec<ColumnSpec> = Vec::new();
    let mut mark = 0;
    let mut n_atoms = 0;
    let mut n_frames = 0;
    while mark < lines.len() {
        let count_line = trim(lines[mark]);
        if count_line.is_empty() {
            mark += 1;
            continue;
        }
        let count = parse_f64(count_line)? as usize;
        if mark + 1 >= lines.len() {
            return Err("comment".to_string());
        }
        let comment = lines[mark + 1];
        let lattice = quoted_after(comment, b"Lattice=").ok_or("lattice")?;
        let properties = quoted_after(comment, b"Properties=").ok_or("properties")?;
        let frame_specs = property_columns(properties)?;
        let frame_cell = lattice_cell(lattice)?;
        if n_frames == 0 {
            columns = frame_specs
                .iter()
                .map(|spec| XyzColumn {
                    name: spec.name.clone(),
                    kind: spec.kind,
                    width: spec.width,
                    text: Vec::new(),
                    real: Vec::new(),
                })
                .collect();
            specs = frame_specs;
            n_atoms = count;
        } else if count != n_atoms
            || frame_specs.len() != specs.len()
            || frame_specs.iter().zip(specs.iter()).any(|(left, right)| {
                left.name != right.name || left.kind != right.kind || left.width != right.width
            })
        {
            return Err("properties".to_string());
        }
        mark += 2;
        if mark + count > lines.len() {
            return Err("atoms".to_string());
        }
        for line in &lines[mark..mark + count] {
            push_atom(line, &specs, &mut columns)?;
        }
        cell.extend_from_slice(&frame_cell);
        mark += count;
        n_frames += 1;
    }
    if n_frames == 0 {
        return Err("no frames".to_string());
    }
    let mut positions = Vec::new();
    let mut masses = vec![f64::NAN; n_frames * n_atoms];
    let mut species = vec![String::new(); n_frames * n_atoms];
    for column in &columns {
        if column.name == "pos" {
            positions.clone_from(&column.real);
        } else if column.name == "masses" || column.name == "mass" {
            if column.width == 1 {
                masses.clone_from(&column.real);
            }
        } else if column.name == "species" && column.width == 1 {
            species.clone_from(&column.text);
        }
    }
    if positions.len() != n_frames * n_atoms * 3 {
        return Err("pos".to_string());
    }
    Ok(XyzTables {
        n_frames,
        n_atoms,
        positions,
        masses,
        cell,
        species,
        columns,
    })
}

pub fn tables_from_extxyz_path(path: &Path) -> Result<XyzTables, String> {
    let bytes = fs::read(path).map_err(|_| "read".to_string())?;
    tables_from_extxyz_bytes(&bytes)
}

fn format_number(value: f64) -> String {
    if value.is_nan() {
        return "nan".to_string();
    }
    format!("{value}")
}

fn cos_sin(degrees: f64) -> (f64, f64) {
    if (degrees - 90.0).abs() < 1e-8 {
        return (0.0, 1.0);
    }
    if degrees.abs() < 1e-8 {
        return (1.0, 0.0);
    }
    if (degrees - 180.0).abs() < 1e-8 {
        return (-1.0, 0.0);
    }
    let radians = degrees.to_radians();
    (radians.cos(), radians.sin())
}

pub fn lattice_from_cell(cell: &[f64]) -> Result<[f64; 9], String> {
    if cell.len() < 6 {
        return Err("cell".to_string());
    }
    let (a, b, c) = (cell[0], cell[1], cell[2]);
    let (cos_a, _sin_a) = cos_sin(cell[3]);
    let (cos_b, _sin_b) = cos_sin(cell[4]);
    let (cos_g, sin_g) = cos_sin(cell[5]);
    let bx = b * cos_g;
    let by = b * sin_g;
    let cx = c * cos_b;
    let cy = if sin_g.abs() < 1e-15 {
        0.0
    } else {
        c * (cos_a - cos_b * cos_g) / sin_g
    };
    let cz2 = c * c - cx * cx - cy * cy;
    let cz = if cz2 > 0.0 { cz2.sqrt() } else { 0.0 };
    Ok([a, 0.0, 0.0, bx, by, 0.0, cx, cy, cz])
}

/// One per-atom column the writer can format without taking ownership.
pub trait ExtxyzSource {
    fn column_name(&self) -> &str;
    fn column_kind(&self) -> u8;
    fn column_width(&self) -> usize;
    fn write_fields(&self, base: usize, out: &mut Vec<u8>);
}

impl ExtxyzSource for XyzColumn {
    fn column_name(&self) -> &str {
        &self.name
    }

    fn column_kind(&self) -> u8 {
        self.kind
    }

    fn column_width(&self) -> usize {
        self.width
    }

    fn write_fields(&self, base: usize, out: &mut Vec<u8>) {
        for slot in 0..self.width {
            if slot > 0 {
                out.push(b' ');
            }
            if self.kind == b'S' {
                out.extend_from_slice(self.text[base + slot].as_bytes());
            } else {
                let text = format_number(self.real[base + slot]);
                out.extend_from_slice(text.as_bytes());
            }
        }
    }
}

/// Write species, the lattice, `pbc`, and every per-atom column.
///
/// `columns` are borrowed. The only large buffer this allocates is the
/// output text.
pub fn extxyz_bytes(
    n_frames: usize,
    n_atoms: usize,
    cell: &[f64],
    columns: &[&(dyn ExtxyzSource + Sync)],
) -> Result<Vec<u8>, String> {
    extxyz_bytes_with_threads(n_frames, n_atoms, cell, columns, 1)
}

/// [`extxyz_bytes`] with each frame run formatted on its own thread.
///
/// The runs are concatenated in frame order, so the bytes match one
/// serial [`extxyz_bytes`] call. `workers < 2` formats on the calling thread.
pub fn extxyz_bytes_with_threads(
    n_frames: usize,
    n_atoms: usize,
    cell: &[f64],
    columns: &[&(dyn ExtxyzSource + Sync)],
    workers: usize,
) -> Result<Vec<u8>, String> {
    if n_frames == 0 || n_atoms == 0 || columns.is_empty() {
        return Err("frames".to_string());
    }
    if cell.len() < n_frames * 6 {
        return Err("cell".to_string());
    }
    let properties = columns
        .iter()
        .map(|column| {
            format!(
                "{}:{}:{}",
                column.column_name(),
                column.column_kind() as char,
                column.column_width()
            )
        })
        .collect::<Vec<_>>()
        .join(":");
    if workers >= 2 && n_frames >= 2 {
        let chunk = n_frames.div_ceil(workers).max(1);
        let mut parts: Vec<Vec<u8>> = (0..workers).map(|_| Vec::new()).collect();
        let error = std::thread::scope(|scope| {
            let mut handles = Vec::new();
            for worker in 0..workers {
                let from = worker * chunk;
                if from >= n_frames {
                    break;
                }
                let to = (from + chunk).min(n_frames);
                let properties = properties.as_str();
                handles.push(scope.spawn(move || {
                    format_extxyz_range(from, to, n_atoms, cell, columns, properties)
                }));
            }
            for (index, handle) in handles.into_iter().enumerate() {
                match handle.join() {
                    Ok(Ok(buf)) => parts[index] = buf,
                    Ok(Err(err)) => return Err(err),
                    Err(_) => return Err("write".to_string()),
                }
            }
            Ok(())
        });
        error?;
        let mut out = Vec::new();
        for part in parts {
            out.extend_from_slice(&part);
        }
        return Ok(out);
    }
    let mut out = Vec::with_capacity(n_frames.saturating_mul(n_atoms).saturating_mul(64));
    for frame in 0..n_frames {
        let lattice = lattice_from_cell(&cell[frame * 6..frame * 6 + 6])?;
        let lattice_text = lattice
            .iter()
            .map(|value| format_number(*value))
            .collect::<Vec<_>>()
            .join(" ");
        let header = format!(
            "{n_atoms}\nLattice=\"{lattice_text}\" Properties={properties} pbc=\"T T T\"\n"
        );
        out.extend_from_slice(header.as_bytes());
        for atom in 0..n_atoms {
            for (index, column) in columns.iter().enumerate() {
                if index > 0 {
                    out.push(b' ');
                }
                let base = (frame * n_atoms + atom) * column.column_width();
                column.write_fields(base, &mut out);
            }
            out.push(b'\n');
        }
    }
    Ok(out)
}

fn format_extxyz_range(
    from: usize,
    to: usize,
    n_atoms: usize,
    cell: &[f64],
    columns: &[&(dyn ExtxyzSource + Sync)],
    properties: &str,
) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    for frame in from..to {
        let lattice = lattice_from_cell(&cell[frame * 6..frame * 6 + 6])?;
        let lattice_text = lattice
            .iter()
            .map(|value| format_number(*value))
            .collect::<Vec<_>>()
            .join(" ");
        let header = format!(
            "{n_atoms}\nLattice=\"{lattice_text}\" Properties={properties} pbc=\"T T T\"\n"
        );
        out.extend_from_slice(header.as_bytes());
        for atom in 0..n_atoms {
            for (index, column) in columns.iter().enumerate() {
                if index > 0 {
                    out.push(b' ');
                }
                let base = (frame * n_atoms + atom) * column.column_width();
                column.write_fields(base, &mut out);
            }
            out.push(b'\n');
        }
    }
    Ok(out)
}

/// Write species, the lattice, `pbc`, and every per-atom column.
pub fn tables_to_extxyz_bytes(tables: &XyzTables) -> Result<Vec<u8>, String> {
    let columns: Vec<&(dyn ExtxyzSource + Sync)> = tables
        .columns
        .iter()
        .map(|column| column as &(dyn ExtxyzSource + Sync))
        .collect();
    extxyz_bytes(tables.n_frames, tables.n_atoms, &tables.cell, &columns)
}

pub fn write_extxyz_path(path: &Path, tables: &XyzTables) -> Result<(), String> {
    let bytes = tables_to_extxyz_bytes(tables)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|_| "write".to_string())?;
    }
    fs::write(path, bytes).map_err(|_| "write".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn threaded_tables_match_the_serial_scan() {
        let mut text = String::new();
        for frame in 0..6 {
            text.push_str("2\nLattice=\"4.0 0.0 0.0 0.0 4.0 0.0 0.0 0.0 4.0\" Properties=species:S:1:pos:R:3 pbc=\"T T T\"\n");
            text.push_str(&format!("Cu {frame}.125 0.25 0.5\nH 1.0 1.0 1.0\n"));
        }
        let serial = tables_from_extxyz_bytes(text.as_bytes()).unwrap();
        let parallel = tables_from_extxyz_bytes_with_threads(text.as_bytes(), 4).unwrap();
        assert_eq!(parallel.n_frames, serial.n_frames);
        assert_eq!(parallel.positions, serial.positions);
        assert_eq!(parallel.species, serial.species);
        assert_eq!(parallel.cell, serial.cell);
        let serial_bytes = extxyz_bytes(
            serial.n_frames,
            serial.n_atoms,
            &serial.cell,
            &serial
                .columns
                .iter()
                .map(|column| column as &(dyn ExtxyzSource + Sync))
                .collect::<Vec<_>>(),
        )
        .unwrap();
        // The parallel read moved species out of the column. Put it back
        // so the writer sees the same symbols as the serial table.
        let mut parallel = parallel;
        if let Some(column) = parallel
            .columns
            .iter_mut()
            .find(|column| column.name == "species")
        {
            column.text.clone_from(&parallel.species);
        }
        let parallel_bytes = extxyz_bytes_with_threads(
            parallel.n_frames,
            parallel.n_atoms,
            &parallel.cell,
            &parallel
                .columns
                .iter()
                .map(|column| column as &(dyn ExtxyzSource + Sync))
                .collect::<Vec<_>>(),
            4,
        )
        .unwrap();
        assert_eq!(parallel_bytes, serial_bytes);
    }

    #[test]
    fn a_quoted_value_and_a_bare_value_both_return_the_bytes() {
        assert_eq!(quoted_after(b"Lattice=10 0", b"Lattice="), Some(&b"10"[..]));
        assert_eq!(
            quoted_after(b"Lattice=\"10 0\" tail", b"Lattice="),
            Some(&b"10 0"[..])
        );
        assert_eq!(quoted_after(b"no key", b"Lattice="), None);
        assert!(property_columns(b"pos").is_err());
        let columns = property_columns(b"species:S:1:pos:R:3:masses:R:1").unwrap();
        assert_eq!(columns[0].name, "species");
        assert_eq!(columns[1].offset, 1);
        assert_eq!(columns[2].offset, 4);
    }

    #[test]
    fn one_frame_keeps_lattice_position_and_mass() {
        let text = "\
2
Lattice=\"10 0 0 0 12 0 0 0 14\" Properties=species:S:1:pos:R:3:masses:R:1 pbc=\"T T T\"
Cu 1.0 2.0 3.0 63.546
Cu 4.0 5.0 6.0 63.546
";
        let tables = tables_from_extxyz_bytes(text.as_bytes()).unwrap();
        assert_eq!(tables.n_frames, 1);
        assert_eq!(tables.n_atoms, 2);
        assert_eq!(tables.positions, vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0]);
        assert_eq!(tables.masses, vec![63.546, 63.546]);
        assert_eq!(tables.species, vec!["Cu".to_string(), "Cu".to_string()]);
        assert!(tables.columns.iter().any(|column| column.name == "species"));
        assert!((tables.cell[0] - 10.0).abs() < 1e-12);
        assert!((tables.cell[3] - 90.0).abs() < 1e-8);
    }

    #[test]
    fn forces_and_species_round_trip_from_the_small_fixture() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("bench/h2h/fixtures/small-1.extxyz");
        let tables = tables_from_extxyz_path(&path).unwrap();
        assert_eq!(tables.n_frames, 1);
        assert_eq!(tables.n_atoms, 10);
        assert!(tables.species.iter().all(|symbol| symbol == "Cu"));
        let forces = tables
            .columns
            .iter()
            .find(|column| column.name == "forces")
            .unwrap();
        assert_eq!(forces.width, 3);
        assert!((forces.real[3] - 0.25).abs() < 1e-12);
        assert!((forces.real[4] - 0.5).abs() < 1e-12);
        assert!((forces.real[5] - 1.0).abs() < 1e-12);
        let names: Vec<_> = tables
            .columns
            .iter()
            .map(|column| column.name.as_str())
            .collect();
        assert_eq!(names, vec!["species", "pos", "masses", "forces"]);
    }

    #[test]
    fn written_bytes_reread_with_the_same_species_and_forces() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("bench/h2h/fixtures/small-n.extxyz");
        let tables = tables_from_extxyz_path(&path).unwrap();
        let bytes = tables_to_extxyz_bytes(&tables).unwrap();
        let again = tables_from_extxyz_bytes(&bytes).unwrap();
        assert_eq!(again.species, tables.species);
        assert_eq!(again.positions, tables.positions);
        assert_eq!(again.masses, tables.masses);
        let forces = |item: &XyzTables| {
            item.columns
                .iter()
                .find(|column| column.name == "forces")
                .unwrap()
                .real
                .clone()
        };
        assert_eq!(forces(&again), forces(&tables));
        assert!((again.cell[3] - 90.0).abs() < 1e-8);
    }

    #[test]
    fn frames_cover_quotes_angles_blank_lines_and_errors() {
        assert_eq!(
            tables_from_extxyz_bytes(
                b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=pos:R:3\nCu nope 0 0\n"
            )
            .unwrap_err(),
            "float"
        );
        let text = "\r\n2\r\nLattice=\"10 0 0 0 12 0 0 0 14\" Properties=species:S:1:pos:R:3:masses:R:1\r\nCu 1 2 3 63.546\r\nCu 4 5 6 63.546\r\n";
        let tables = tables_from_extxyz_bytes(text.as_bytes()).unwrap();
        assert_eq!(tables.n_frames, 1);
        assert_eq!(tables.n_atoms, 2);
        assert_eq!(tables.positions.len(), 6);
        assert_eq!(tables.masses[0], 63.546);
        assert!((tables.cell[0] - 10.0).abs() < 1e-9);

        let no_newline =
            b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=species:S:1:pos:R:3\nH 0 1 2";
        let one = tables_from_extxyz_bytes(no_newline).unwrap();
        assert_eq!(one.positions, vec![0.0, 1.0, 2.0]);
        assert!(one.masses[0].is_nan());

        assert_eq!(tables_from_extxyz_bytes(b"\n\n").unwrap_err(), "no frames");
        assert_eq!(tables_from_extxyz_bytes(b"1\n").unwrap_err(), "comment");
        assert_eq!(
            tables_from_extxyz_bytes(
                b"2\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=pos:R:3\nH 0 0 0\n"
            )
            .unwrap_err(),
            "atoms"
        );
        assert_eq!(
            tables_from_extxyz_bytes(b"1\nnote\nH 0 0 0\n").unwrap_err(),
            "lattice"
        );
        assert_eq!(
            tables_from_extxyz_bytes(b"1\nLattice=\"1 0 0 0 1 0 0 0 1\"\nH 0 0 0\n").unwrap_err(),
            "properties"
        );
        assert_eq!(
            tables_from_extxyz_bytes(
                b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=masses:R:1\nH 1\n"
            )
            .unwrap_err(),
            "pos"
        );
        assert_eq!(
            tables_from_extxyz_bytes(b"1\nLattice=\"1 0 0\" Properties=pos:R:3\nH 0 0 0\n")
                .unwrap_err(),
            "lattice"
        );
        assert_eq!(
            tables_from_extxyz_bytes(b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=pos\nH 0 0 0\n")
                .unwrap_err(),
            "properties"
        );
        assert_eq!(
            tables_from_extxyz_bytes(
                b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=pos:R:x\nH 0 0 0\n"
            )
            .unwrap_err(),
            "float"
        );
        assert_eq!(
            tables_from_extxyz_bytes(
                b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=pos:R:3\nH 0 nope 2\n"
            )
            .unwrap_err(),
            "float"
        );
        assert_eq!(
            tables_from_extxyz_bytes(
                b"1\nLattice=\"nope 0 0 0 1 0 0 0 1\" Properties=pos:R:3\nH 0 0 0\n"
            )
            .unwrap_err(),
            "lattice"
        );
        assert_eq!(tables_from_extxyz_bytes(b"abc\n").unwrap_err(), "float");
        assert_eq!(
            tables_from_extxyz_bytes(b"1\nLattice=\"1 0 0 Properties=pos:R:3\nH 0 0 0\n")
                .unwrap_err(),
            "lattice"
        );
        assert_eq!(
            tables_from_extxyz_bytes(b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=\nH 0 0 0\n")
                .unwrap_err(),
            "pos"
        );
        assert_eq!(
            tables_from_extxyz_bytes(
                b"1\nLattice=\"1 0 0 0 1 0 0 0 1\" Properties=species:S:1:pos:R:3\n\n"
            )
            .unwrap_err(),
            "atom"
        );

        let missing = tables_from_extxyz_path(std::path::Path::new("/no/such/extxyz")).unwrap_err();
        assert_eq!(missing, "read");
        let path = std::env::temp_dir().join(format!("readcon-extxyz-{}.xyz", std::process::id()));
        std::fs::write(&path, no_newline).unwrap();
        let from_path = tables_from_extxyz_path(&path).unwrap();
        assert_eq!(from_path.n_frames, 1);
        std::fs::remove_file(&path).unwrap();
    }
}
