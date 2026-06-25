//! Chemfiles selection grammar applied to readcon frames (feature = "chemfiles").
//!
//! Wraps [`chemfiles::Selection`] so callers can evaluate selection-language
//! strings (e.g. `name O`, `all`, `pairs: name(#1) H and name(#2) O`) against
//! a [`ConFrame`](crate::types::ConFrame) by projecting it into a temporary
//! chemfiles [`Frame`](chemfiles::Frame).

use chemfiles::{Atom, Frame, Selection, UnitCell};
use serde_json::Value;

use crate::chemfiles_import::ChemfilesImportError;
use crate::types::ConFrame;

/// One selection match: up to four atom indices (chemfiles contexts: atom=1,
/// pair/bond=2, angle/three=3, dihedral/four=4).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectionMatch {
    /// Number of meaningful indices in [`Self::atoms`] (1..=4).
    pub size: usize,
    /// Atom indices in the frame order used for evaluation.
    pub atoms: [usize; 4],
}

impl SelectionMatch {
    /// Indices slice of length [`Self::size`].
    pub fn indices(&self) -> &[usize] {
        &self.atoms[..self.size]
    }
}

/// Result of evaluating a chemfiles selection string on a frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectionResult {
    /// Original selection string.
    pub selection: String,
    /// Selection context size (1 atom, 2 pair, etc.).
    pub context_size: usize,
    /// All matches.
    pub matches: Vec<SelectionMatch>,
}

impl SelectionResult {
    /// Flat list of first-atom indices (atom-context selections); for pair+
    /// contexts this is only index 0 of each match.
    pub fn primary_indices(&self) -> Vec<usize> {
        self.matches.iter().map(|m| m.atoms[0]).collect()
    }

    /// For atom context only: all matched atom indices (same as primary).
    pub fn atom_indices(&self) -> Vec<usize> {
        if self.context_size == 1 {
            self.primary_indices()
        } else {
            self.matches
                .iter()
                .flat_map(|m| m.indices().iter().copied())
                .collect()
        }
    }
}

/// Build a chemfiles [`Frame`] from a readcon [`ConFrame`] for selection.
///
/// Populates atom names/types from symbols, positions, optional velocities,
/// and orthorhombic/triclinic cell from `boxl`/`angles`. Bond topology is
/// not reconstructed; bond/angle selection contexts only work if the
/// chemfiles frame already has bonds (not set here).
pub fn chemfiles_frame_from_con_frame(frame: &ConFrame) -> Result<Frame, ChemfilesImportError> {
    let mut chfl = Frame::new();
    let cell = frame.header.boxl;
    let angles = frame.header.angles;
    let is_ortho = (angles[0] - 90.0).abs() < 1e-6
        && (angles[1] - 90.0).abs() < 1e-6
        && (angles[2] - 90.0).abs() < 1e-6;
    let unit_cell = if cell.iter().all(|&c| c <= 0.0) {
        UnitCell::infinite()
    } else if is_ortho {
        UnitCell::new(cell)
    } else {
        UnitCell::triclinic(cell, angles)
    };
    chfl.set_cell(&unit_cell);

    let n = frame.atom_data.len();
    let mut need_vel = false;
    for atom in &frame.atom_data {
        if atom.velocity.is_some() {
            need_vel = true;
            break;
        }
    }
    if need_vel {
        chfl.add_velocities();
    }

    for atom in &frame.atom_data {
        let name = atom.symbol.as_ref();
        let ch_atom = Atom::new(name);
        let vel = atom.velocity;
        chfl.add_atom(&ch_atom, [atom.x, atom.y, atom.z], vel);
    }

    // Restore velocities explicitly if add_atom did not set them.
    if need_vel {
        if let Some(vels) = chfl.velocities_mut() {
            for (i, atom) in frame.atom_data.iter().enumerate() {
                if let Some(v) = atom.velocity {
                    if i < vels.len() {
                        vels[i] = v;
                    }
                }
            }
        }
    }

    if chfl.size() != n {
        return Err(ChemfilesImportError::InvalidFrame(format!(
            "chemfiles frame size {} != con frame {}",
            chfl.size(),
            n
        )));
    }

    // Preserve step from metadata when present.
    if let Some(idx) = frame.header.frame_index() {
        chfl.set_step(idx as usize);
    }

    // Copy a few scalar frame properties useful for selection filters.
    if let Some(e) = frame.header.energy() {
        chfl.set("energy", e);
    }
    if let Some(t) = frame.header.time() {
        chfl.set("time", t);
    }

    Ok(chfl)
}

/// Evaluate a chemfiles selection-language string on a chemfiles [`Frame`].
pub fn evaluate_selection_on_chemfiles_frame(
    selection: &str,
    frame: &Frame,
) -> Result<SelectionResult, ChemfilesImportError> {
    let mut sel = Selection::new(selection).map_err(ChemfilesImportError::from)?;
    let context_size = sel.size();
    let matches_raw = sel.evaluate(frame);
    let matches = matches_raw
        .into_iter()
        .map(|m| {
            let size = m.len();
            let mut atoms = [0usize; 4];
            for (i, idx) in m.iter().enumerate() {
                if i < 4 {
                    atoms[i] = *idx;
                }
            }
            SelectionMatch { size, atoms }
        })
        .collect();
    Ok(SelectionResult {
        selection: selection.to_string(),
        context_size,
        matches,
    })
}

/// Evaluate selection on a readcon [`ConFrame`] (projects to chemfiles first).
pub fn evaluate_selection_on_con_frame(
    selection: &str,
    frame: &ConFrame,
) -> Result<SelectionResult, ChemfilesImportError> {
    let chfl = chemfiles_frame_from_con_frame(frame)?;
    evaluate_selection_on_chemfiles_frame(selection, &chfl)
}

/// Convenience: atom-context selection returns sorted unique indices only.
pub fn select_atom_indices(selection: &str, frame: &ConFrame) -> Result<Vec<usize>, ChemfilesImportError> {
    let result = evaluate_selection_on_con_frame(selection, frame)?;
    if result.context_size != 1 {
        return Err(ChemfilesImportError::InvalidFrame(format!(
            "select_atom_indices requires atom context (size 1), got {}",
            result.context_size
        )));
    }
    let mut idxs = result.primary_indices();
    idxs.sort_unstable();
    idxs.dedup();
    Ok(idxs)
}

/// Validate that a selection string parses (does not evaluate on a frame).
pub fn parse_selection_string(selection: &str) -> Result<usize, ChemfilesImportError> {
    let sel = Selection::new(selection).map_err(ChemfilesImportError::from)?;
    Ok(sel.size())
}

/// Helper for tests/metadata: read optional f64 from frame header metadata.
#[allow(dead_code)]
fn meta_f64(frame: &ConFrame, key: &str) -> Option<f64> {
    frame.header.metadata.get(key).and_then(Value::as_f64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chemfiles_import::con_frame_from_chemfiles;
    use crate::types::ConFrameBuilder;
    use chemfiles::{Atom, Frame, UnitCell};

    fn water_con_frame() -> ConFrame {
        let mut b = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        b.add_atom("O", 0.0, 0.0, 0.0, [false; 3], 0, 16.0);
        b.add_atom("H", 0.96, 0.0, 0.0, [false; 3], 1, 1.0);
        b.add_atom("H", -0.24, 0.93, 0.0, [false; 3], 2, 1.0);
        b.build()
    }

    #[test]
    fn selects_oxygen_by_name() {
        let frame = water_con_frame();
        let idxs = select_atom_indices("name O", &frame).expect("select O");
        assert_eq!(idxs, vec![0]);
    }

    #[test]
    fn selects_all_hydrogens() {
        let frame = water_con_frame();
        let idxs = select_atom_indices("name H", &frame).expect("select H");
        assert_eq!(idxs, vec![1, 2]);
    }

    #[test]
    fn selects_all_atoms() {
        let frame = water_con_frame();
        let result = evaluate_selection_on_con_frame("all", &frame).expect("all");
        assert_eq!(result.context_size, 1);
        assert_eq!(result.matches.len(), 3);
        let mut idxs = result.primary_indices();
        idxs.sort_unstable();
        assert_eq!(idxs, vec![0, 1, 2]);
    }

    #[test]
    fn invalid_selection_errors() {
        let frame = water_con_frame();
        let err = evaluate_selection_on_con_frame("not a valid !!! selection", &frame);
        assert!(err.is_err(), "expected error for invalid grammar");
    }

    #[test]
    fn parse_selection_reports_context_size() {
        assert_eq!(parse_selection_string("name O").unwrap(), 1);
        assert_eq!(
            parse_selection_string("pairs: name(#1) H and name(#2) O").unwrap(),
            2
        );
    }

    #[test]
    fn pair_selection_on_chemfiles_frame_with_topology() {
        // Build chemfiles frame directly (pairs need names only; no bonds required for name pair sel)
        let mut frame = Frame::new();
        frame.add_atom(&Atom::new("H"), [1.0, 0.0, 0.0], None);
        frame.add_atom(&Atom::new("O"), [0.0, 0.0, 0.0], None);
        frame.add_atom(&Atom::new("H"), [-1.0, 0.0, 0.0], None);
        frame.set_cell(&UnitCell::new([10.0, 10.0, 10.0]));

        let result = evaluate_selection_on_chemfiles_frame(
            "pairs: name(#1) H and name(#2) O",
            &frame,
        )
        .expect("pair sel");
        assert_eq!(result.context_size, 2);
        assert_eq!(result.matches.len(), 2);
        for m in &result.matches {
            assert_eq!(m.size, 2);
            assert_eq!(frame.atom(m.atoms[0]).name(), "H");
            assert_eq!(frame.atom(m.atoms[1]).name(), "O");
        }
    }

    #[test]
    fn selection_works_after_chemfiles_import_roundtrip() {
        let mut chfl = Frame::new();
        chfl.add_atom(&Atom::new("Cu"), [0.0, 0.0, 0.0], None);
        chfl.add_atom(&Atom::new("H"), [1.0, 0.0, 0.0], None);
        chfl.set_cell(&UnitCell::new([5.0, 5.0, 5.0]));
        let con = con_frame_from_chemfiles(&chfl).expect("import");
        let idxs = select_atom_indices("name Cu", &con).expect("select Cu");
        assert_eq!(idxs.len(), 1);
        assert_eq!(con.atom_data[idxs[0]].symbol.as_ref(), "Cu");
    }

    #[test]
    fn con_frame_projection_preserves_atom_count() {
        let frame = water_con_frame();
        let chfl = chemfiles_frame_from_con_frame(&frame).expect("project");
        assert_eq!(chfl.size(), 3);
        assert_eq!(chfl.atom(0).name(), "O");
    }
}
