//! Sequential PDB scan.
//!
//! The reader keeps one byte buffer and fills positions, masses and the
//! cell with fixed-column parses. It does not build a per-atom object.

use std::fs;
use std::path::Path;

/// Positions are `n_frames * n_atoms * 3` in frame-major order.
/// Masses are `n_frames * n_atoms`. Cell is `n_frames * 6` (lengths, then angles).
#[derive(Debug, Clone)]
pub struct PdbTables {
    pub n_frames: usize,
    pub n_atoms: usize,
    pub positions: Vec<f64>,
    pub masses: Vec<f64>,
    pub cell: Vec<f64>,
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

fn parse_f64(bytes: &[u8]) -> Result<f64, String> {
    let token = trim(bytes);
    let (value, consumed) = fast_float2::parse_partial::<f64, _>(token).map_err(|_| "float".to_string())?;
    if consumed == 0 {
        return Err("float".to_string());
    }
    Ok(value)
}

fn mass_of(symbol: &[u8]) -> f64 {
    let mut upper = [0u8; 2];
    let n = symbol.len().min(2);
    for (index, byte) in symbol.iter().take(n).enumerate() {
        upper[index] = byte.to_ascii_uppercase();
    }
    match &upper[..n] {
        b"CU" => 63.546,
        b"H" => 1.00794,
        _ => f64::NAN,
    }
}

fn element_symbol(line: &[u8]) -> &[u8] {
    if line.len() >= 78 {
        let field = trim(&line[76..78.min(line.len())]);
        if !field.is_empty() {
            return field;
        }
    }
    trim(line)
}

fn parse_cryst(line: &[u8], cell: &mut [f64; 6]) -> Result<(), String> {
    let mut rest = trim(line.get(6..).unwrap_or(b""));
    for slot in cell.iter_mut() {
        rest = trim(rest);
        let (value, consumed) = fast_float2::parse_partial::<f64, _>(rest).map_err(|_| "cryst".to_string())?;
        if consumed == 0 {
            return Err("cryst".to_string());
        }
        *slot = value;
        rest = rest.get(consumed..).unwrap_or(b"");
    }
    Ok(())
}

fn push_atom(line: &[u8], pos: &mut Vec<f64>, mass: &mut Vec<f64>) -> Result<(), String> {
    if line.len() < 54 {
        return Err("atom".to_string());
    }
    pos.push(parse_f64(&line[30..38])?);
    pos.push(parse_f64(&line[38..46])?);
    pos.push(parse_f64(&line[46..54])?);
    mass.push(mass_of(element_symbol(line)));
    Ok(())
}

pub fn tables_from_pdb_bytes(bytes: &[u8]) -> Result<PdbTables, String> {
    let mut cell = [0.0; 6];
    let mut positions = Vec::new();
    let mut masses = Vec::new();
    let mut frame_positions: Vec<Vec<f64>> = Vec::new();
    let mut frame_masses: Vec<Vec<f64>> = Vec::new();
    let mut current_pos = Vec::new();
    let mut current_mass = Vec::new();
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
        if index < bytes.len() {
            index += 1;
        }
        if line.starts_with(b"CRYST1") {
            parse_cryst(line, &mut cell)?;
        } else if line.starts_with(b"ATOM") || line.starts_with(b"HETATM") {
            push_atom(line, &mut current_pos, &mut current_mass)?;
        } else if line.starts_with(b"ENDMDL") {
            frame_positions.push(std::mem::take(&mut current_pos));
            frame_masses.push(std::mem::take(&mut current_mass));
        }
    }
    if !current_pos.is_empty() {
        frame_positions.push(current_pos);
        frame_masses.push(current_mass);
    }
    if frame_positions.is_empty() {
        return Err("no atoms".to_string());
    }
    let n_atoms = frame_positions[0].len() / 3;
    if n_atoms == 0 || frame_positions.iter().any(|frame| frame.len() != n_atoms * 3) {
        return Err("frame size".to_string());
    }
    let n_frames = frame_positions.len();
    positions.reserve(n_frames * n_atoms * 3);
    masses.reserve(n_frames * n_atoms);
    let mut cell_out = Vec::with_capacity(n_frames * 6);
    for (frame_pos, frame_mass) in frame_positions.into_iter().zip(frame_masses) {
        positions.extend(frame_pos);
        masses.extend(frame_mass);
        cell_out.extend_from_slice(&cell);
    }
    Ok(PdbTables {
        n_frames,
        n_atoms,
        positions,
        masses,
        cell: cell_out,
    })
}

pub fn tables_from_pdb_path(path: &Path) -> Result<PdbTables, String> {
    let bytes = fs::read(path).map_err(|_| "read".to_string())?;
    tables_from_pdb_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn two_copper_atoms_keep_coordinates_cell_and_mass() {
        let text = "\
CRYST1   10.000   12.000   14.000  90.00  90.00  90.00 P 1
MODEL     1
ATOM      1   Cu MOL     1       0.000   1.000   2.000  1.00  0.00          CU
ATOM      2   Cu MOL     1       3.000   4.000   5.000  1.00  0.00          CU
ENDMDL
";
        let tables = tables_from_pdb_bytes(text.as_bytes()).unwrap();
        assert_eq!(tables.n_frames, 1);
        assert_eq!(tables.n_atoms, 2);
        assert_eq!(tables.positions, vec![0.0, 1.0, 2.0, 3.0, 4.0, 5.0]);
        assert_eq!(tables.masses, vec![63.546, 63.546]);
        assert_eq!(tables.cell, vec![10.0, 12.0, 14.0, 90.0, 90.0, 90.0]);
    }
}
