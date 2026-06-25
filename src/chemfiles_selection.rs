//! Chemfiles selection grammar applied to readcon frames (feature = "chemfiles").
//!
//! Wraps [`chemfiles::Selection`] so callers can evaluate selection-language
//! strings (e.g. `name O`, `all`, `pairs: name(#1) H and name(#2) O`) against
//! a [`ConFrame`](crate::types::ConFrame) by projecting it into a temporary
//! chemfiles [`Frame`](chemfiles::Frame).

use chemfiles::{Atom, BondOrder, Frame, Selection, UnitCell};
use serde_json::Value;

use crate::chemfiles_import::ChemfilesImportError;
use crate::types::ConFrame;

/// Map optional integer bond order from CON metadata to chemfiles [`BondOrder`].
fn bond_order_from_i32(order: Option<i32>) -> Option<BondOrder> {
    match order {
        None => None,
        Some(0) => Some(BondOrder::Unknown),
        Some(1) => Some(BondOrder::Single),
        Some(2) => Some(BondOrder::Double),
        Some(3) => Some(BondOrder::Triple),
        Some(4) => Some(BondOrder::Quadruple),
        Some(5) => Some(BondOrder::Quintuplet),
        Some(6) => Some(BondOrder::Amide),
        Some(7) => Some(BondOrder::Aromatic),
        Some(_) => Some(BondOrder::Unknown),
    }
}

/// Apply readcon frame topology (`metadata["bonds"]`) onto a chemfiles frame.
///
/// Bond indices are 0-based into [`ConFrame::atom_data`] order (same order used
/// when adding atoms to `chfl`). Out-of-range indices or self-bonds are skipped.
pub fn apply_con_bonds_to_chemfiles_frame(frame: &ConFrame, chfl: &mut Frame) {
    let n = chfl.size();
    debug_assert_eq!(n, frame.atom_data.len());
    for bond in frame.bonds() {
        let i = bond.i as usize;
        let j = bond.j as usize;
        if i >= n || j >= n || i == j {
            continue;
        }
        if let Some(order) = bond_order_from_i32(bond.order) {
            chfl.add_bond_with_order(i, j, order);
        } else {
            chfl.add_bond(i, j);
        }
    }
}

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
/// orthorhombic/triclinic cell from `boxl`/`angles`, and optional frame
/// topology from `metadata["bonds"]` (enables chemfiles `bonds:` / `angles:` /
/// `is_bonded` selection when present).
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

    // Optional topology: enables bonds:/angles:/is_bonded selections.
    apply_con_bonds_to_chemfiles_frame(frame, &mut chfl);

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

    #[test]
    fn con_frame_bonds_projected_for_bonds_selection() {
        use crate::types::Bond;
        let mut frame = water_con_frame();
        // Water: O(0)-H(1), O(0)-H(2)
        frame.header.set_bonds(&[Bond::new(0, 1), Bond::new(0, 2)]);
        let result = evaluate_selection_on_con_frame("bonds: all", &frame).expect("bonds: all");
        assert_eq!(result.context_size, 2);
        assert_eq!(result.matches.len(), 2);
        // Projection must have applied topology (without bonds, bonds: all is empty).
        let frame_no_topo = water_con_frame();
        let empty = evaluate_selection_on_con_frame("bonds: all", &frame_no_topo).expect("no topo");
        assert!(empty.matches.is_empty());
    }

    #[test]
    fn angles_all_with_projected_bonds() {
        use crate::types::Bond;
        let mut frame = water_con_frame();
        frame.header.set_bonds(&[Bond::new(0, 1), Bond::new(0, 2)]);
        let result = evaluate_selection_on_con_frame("angles: all", &frame).expect("angles: all");
        assert_eq!(result.context_size, 3);
        // H-O-H angle: one triple (1,0,2) or (2,0,1)
        assert_eq!(result.matches.len(), 1, "water with 2 bonds should yield 1 angle");
        let m = &result.matches[0];
        assert_eq!(m.size, 3);
        assert_eq!(m.atoms[1], 0, "center should be O (index 0)");
        let ends = [m.atoms[0], m.atoms[2]];
        assert!(ends.contains(&1) && ends.contains(&2));

        let no_topo = water_con_frame();
        let empty = evaluate_selection_on_con_frame("angles: all", &no_topo).expect("empty");
        assert!(empty.matches.is_empty());
    }

    #[test]
    fn import_preserves_chemfiles_bonds_in_metadata() {
        use crate::chemfiles_import::con_frame_from_chemfiles;
        let mut chfl = Frame::new();
        chfl.add_atom(&Atom::new("C"), [0.0, 0.0, 0.0], None);
        chfl.add_atom(&Atom::new("O"), [1.2, 0.0, 0.0], None);
        chfl.add_bond(0, 1);
        chfl.set_cell(&UnitCell::new([5.0, 5.0, 5.0]));
        let con = con_frame_from_chemfiles(&chfl).expect("import");
        assert!(con.has_bonds());
        let bonds = con.bonds();
        assert_eq!(bonds.len(), 1);
        assert_eq!(bonds[0].i.min(bonds[0].j), 0);
        assert_eq!(bonds[0].i.max(bonds[0].j), 1);
    }
}

/// Regression cases ported from chemfiles `tests/selection.cpp` (master / v0.10.x).
///
/// Each case evaluates the same selection string on (1) a chemfiles [`Frame`]
/// built like chemfiles' `testing_frame()` and (2) the same topology after
/// import → CON `bonds` → re-projection. Topology-derived selectors must agree.
#[cfg(test)]
mod chemfiles_selection_cpp_regression {
    use super::*;
    use crate::chemfiles_import::con_frame_from_chemfiles;
    use chemfiles::{Atom, Frame};

    /// Mirror of chemfiles `tests/selection.cpp` `testing_frame()` (topology + names/types).
    ///
    /// Atoms: H1(H) @ (0,1,2), O @ (1,2,3), O @ (2,3,4), H @ (3,4,5).
    /// Bonds: 0-1, 1-2, 2-3 (linear H–O–O–H chain → 2 angles, 1 dihedral).
    fn chemfiles_cpp_testing_frame() -> Frame {
        let mut frame = Frame::new();
        // Atom(name, type) — matches C++ Atom("H1", "H") / Atom("O") / Atom("H")
        let mut h1 = Atom::new("H1");
        h1.set_atomic_type("H");
        frame.add_atom(&h1, [0.0, 1.0, 2.0], None);
        frame.add_atom(&Atom::new("O"), [1.0, 2.0, 3.0], None);
        frame.add_atom(&Atom::new("O"), [2.0, 3.0, 4.0], None);
        frame.add_atom(&Atom::new("H"), [3.0, 4.0, 5.0], None);
        frame.add_bond(0, 1);
        frame.add_bond(1, 2);
        frame.add_bond(2, 3);
        frame
    }

    /// CON path: chemfiles import (bonds in metadata) then selection via projection.
    fn con_from_cpp_testing_frame() -> ConFrame {
        let chfl = chemfiles_cpp_testing_frame();
        con_frame_from_chemfiles(&chfl).expect("import chemfiles testing_frame")
    }

    fn match_key(m: &SelectionMatch) -> Vec<usize> {
        m.indices().to_vec()
    }

    fn sort_match_keys(result: &SelectionResult) -> Vec<Vec<usize>> {
        let mut keys: Vec<Vec<usize>> = result.matches.iter().map(match_key).collect();
        keys.sort();
        keys
    }

    /// Map chemfiles atom index → CON `atom_data` index via stored `atom_id`.
    fn chemfiles_idx_to_con_data(con: &ConFrame, chfl_idx: usize) -> Option<usize> {
        con.atom_data
            .iter()
            .position(|a| a.atom_id == chfl_idx as u64)
    }

    /// Remap a chemfiles match (indices in chemfiles order) into CON `atom_data` order.
    fn remap_match_to_con_order(con: &ConFrame, m: &SelectionMatch) -> Option<Vec<usize>> {
        let mut out = Vec::with_capacity(m.size);
        for &idx in m.indices() {
            out.push(chemfiles_idx_to_con_data(con, idx)?);
        }
        Some(out)
    }

    /// Canonical key for topology multiset compare (bond/angle/dihedral orientation).
    ///
    /// Chemfiles may emit either bond direction or reversed angle/dihedral walk;
    /// CON projection must agree as an undirected multiset in `atom_data` order.
    fn canonicalize_topology_match(indices: &[usize], context_size: usize) -> Vec<usize> {
        match context_size {
            2 => {
                let mut p = [indices[0], indices[1]];
                p.sort_unstable();
                p.to_vec()
            }
            3 => {
                // Angle i-j-k is same as k-j-i (same center j).
                let (i, j, k) = (indices[0], indices[1], indices[2]);
                if i <= k {
                    vec![i, j, k]
                } else {
                    vec![k, j, i]
                }
            }
            4 => {
                let a = indices.to_vec();
                let mut rev = a.clone();
                rev.reverse();
                if a <= rev { a } else { rev }
            }
            _ => indices.to_vec(),
        }
    }

    fn multiset_topology_keys(result: &SelectionResult) -> Vec<Vec<usize>> {
        let mut keys: Vec<Vec<usize>> = result
            .matches
            .iter()
            .map(|m| canonicalize_topology_match(m.indices(), result.context_size))
            .collect();
        keys.sort();
        keys
    }

    /// Chemfiles-direct vs CON-projection agree after remapping chemfiles indices
    /// into CON type-grouped `atom_data` order (builder reorders; bonds use data order).
    fn assert_selection_parity_remapped(selection: &str, chfl: &Frame, con: &ConFrame) {
        let direct = evaluate_selection_on_chemfiles_frame(selection, chfl)
            .unwrap_or_else(|e| panic!("direct chemfiles '{selection}': {e}"));
        let via_con = evaluate_selection_on_con_frame(selection, con)
            .unwrap_or_else(|e| panic!("via CON projection '{selection}': {e}"));
        assert_eq!(direct.context_size, via_con.context_size);

        let mut remapped: Vec<Vec<usize>> = direct
            .matches
            .iter()
            .map(|m| {
                let r = remap_match_to_con_order(con, m)
                    .unwrap_or_else(|| panic!("atom_id missing for match in '{selection}'"));
                canonicalize_topology_match(&r, direct.context_size)
            })
            .collect();
        remapped.sort();
        let via_keys = multiset_topology_keys(&via_con);
        assert_eq!(
            remapped, via_keys,
            "remapped multiset mismatch for '{selection}'\n  chemfiles→con: {remapped:?}\n  via con:       {via_keys:?}"
        );
    }

    // --- TEST_CASE("Multiple selections") / SECTION("Bonds"|"Angles"|"Dihedrals") ---

    #[test]
    fn cpp_bonds_all_parity_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        assert!(con.has_bonds());
        assert_eq!(con.bonds().len(), 3);
        assert_selection_parity_remapped("bonds: all", &chfl, &con);
        let r = evaluate_selection_on_con_frame("bonds: all", &con).unwrap();
        assert_eq!(r.context_size, 2);
        assert_eq!(r.matches.len(), 3);
    }

    #[test]
    fn cpp_bonds_name_o_type_h_parity_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        // selection.cpp: bonds: name(#1) O and type(#2) H → chemfiles {1,0}, {2,3}
        assert_selection_parity_remapped("bonds: name(#1) O and type(#2) H", &chfl, &con);
    }

    #[test]
    fn cpp_angles_all_parity_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        // selection.cpp: angles: all → {0,1,2}, {1,2,3} in chemfiles order
        assert_selection_parity_remapped("angles: all", &chfl, &con);
        let r = evaluate_selection_on_con_frame("angles: all", &con).unwrap();
        assert_eq!(r.context_size, 3);
        assert_eq!(r.matches.len(), 2);
    }

    #[test]
    fn cpp_angles_filtered_parity_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        // selection.cpp: angles: name(#1) O and name(#2) O and type(#3) H
        assert_selection_parity_remapped(
            "angles: name(#1) O and name(#2) O and type(#3) H",
            &chfl,
            &con,
        );
    }

    #[test]
    fn cpp_dihedrals_all_parity_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        // selection.cpp: dihedrals: all → single {0,1,2,3}
        assert_selection_parity_remapped("dihedrals: all", &chfl, &con);
        let r = evaluate_selection_on_con_frame("dihedrals: all", &con).unwrap();
        assert_eq!(r.context_size, 4);
        assert_eq!(r.matches.len(), 1);
    }

    #[test]
    fn cpp_is_bonded_equiv_bonds_context_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        let a = "two: type(#1) H and name(#2) O and is_bonded(#1, #2)";
        let b = "bonds: type(#1) H and name(#2) O";
        assert_selection_parity_remapped(a, &chfl, &con);
        assert_selection_parity_remapped(b, &chfl, &con);
        // On CON index space, is_bonded and bonds: filters must agree with each other.
        let ra = evaluate_selection_on_con_frame(a, &con).unwrap();
        let rb = evaluate_selection_on_con_frame(b, &con).unwrap();
        assert_eq!(sort_match_keys(&ra), sort_match_keys(&rb));
    }

    #[test]
    fn cpp_is_angle_equiv_angles_context_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        let a = "three: type(#1) H and name(#2) O and is_angle(#1, #2, #3)";
        let b = "angles: type(#1) H and name(#2) O";
        assert_selection_parity_remapped(a, &chfl, &con);
        assert_selection_parity_remapped(b, &chfl, &con);
        let ra = evaluate_selection_on_con_frame(a, &con).unwrap();
        let rb = evaluate_selection_on_con_frame(b, &con).unwrap();
        assert_eq!(sort_match_keys(&ra), sort_match_keys(&rb));
    }

    #[test]
    fn cpp_is_dihedral_type_h_parity_remapped() {
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        // selection.cpp uses name H1; type H is the CON-stable equivalent for atom 0.
        let sel = "four: type(#1) H and is_dihedral(#3, #4, #2, #1)";
        assert_selection_parity_remapped(sel, &chfl, &con);
    }

    /// Hand-authored CON bonds in `atom_data` order (no import reorder): exact index parity.
    #[test]
    fn cpp_topology_on_ungrouped_con_frame_exact_indices() {
        use crate::types::{Bond, ConFrameBuilder};
        // Force same order as chemfiles by adding atoms H,O,O,H with distinct atom_ids.
        // Builder still groups → H,H,O,O. Author bonds in that grouped order explicitly.
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 0.0, 1.0, 2.0, [false; 3], 0, 1.0);
        b.add_atom("O", 1.0, 2.0, 3.0, [false; 3], 1, 16.0);
        b.add_atom("O", 2.0, 3.0, 4.0, [false; 3], 2, 16.0);
        b.add_atom("H", 3.0, 4.0, 5.0, [false; 3], 3, 1.0);
        let mut frame = b.build();
        // After group: data order H(id0), H(id3), O(id1), O(id2) — bonds must use data idx.
        // chemfiles bonds 0-1,1-2,2-3 in id space → data pairs via atom_id lookup
        let id_to = |id: u64| {
            frame
                .atom_data
                .iter()
                .position(|a| a.atom_id == id)
                .unwrap() as u32
        };
        frame.header.set_bonds(&[
            Bond::new(id_to(0), id_to(1)),
            Bond::new(id_to(1), id_to(2)),
            Bond::new(id_to(2), id_to(3)),
        ]);
        let angles = evaluate_selection_on_con_frame("angles: all", &frame).unwrap();
        assert_eq!(angles.matches.len(), 2);
        let dih = evaluate_selection_on_con_frame("dihedrals: all", &frame).unwrap();
        assert_eq!(dih.matches.len(), 1);
    }

    #[test]
    fn cpp_pairs_all_no_topology_needed() {
        let chfl = chemfiles_cpp_testing_frame();
        let mut con = con_from_cpp_testing_frame();
        con.header.clear_bonds();
        let sel = "pairs: all";
        let direct = evaluate_selection_on_chemfiles_frame(sel, &chfl).unwrap();
        let via = evaluate_selection_on_con_frame(sel, &con).unwrap();
        assert_eq!(direct.matches.len(), 12);
        // pairs uses atom indices in projection order (type-grouped), not chemfiles order
        assert_eq!(via.matches.len(), 12);
    }

    #[test]
    fn cpp_without_bonds_topology_selectors_empty_on_con() {
        let mut con = con_from_cpp_testing_frame();
        con.header.clear_bonds();
        for sel in ["bonds: all", "angles: all", "dihedrals: all"] {
            let r = evaluate_selection_on_con_frame(sel, &con).unwrap();
            assert!(r.matches.is_empty(), "{sel} must be empty without bonds");
        }
    }

    #[test]
    fn cpp_import_project_roundtrip_topology_parity() {
        let chfl = chemfiles_cpp_testing_frame();
        let con1 = con_frame_from_chemfiles(&chfl).unwrap();
        let proj = chemfiles_frame_from_con_frame(&con1).unwrap();
        assert_eq!(proj.topology().bonds_count(), 3);
        let con2 = con_frame_from_chemfiles(&proj).unwrap();
        assert_eq!(con2.bonds().len(), 3);
        // First hop: chemfiles frame ↔ CON import/projection (atom_id preserves chemfiles index).
        assert_selection_parity_remapped("bonds: all", &chfl, &con1);
        assert_selection_parity_remapped("angles: all", &chfl, &con1);
        assert_selection_parity_remapped("dihedrals: all", &chfl, &con1);
        // Second hop: CON ↔ projected chemfiles ↔ CON (same atom_data order both times).
        for sel in ["bonds: all", "angles: all", "dihedrals: all"] {
            let a = multiset_topology_keys(&evaluate_selection_on_con_frame(sel, &con1).unwrap());
            let b = multiset_topology_keys(&evaluate_selection_on_con_frame(sel, &con2).unwrap());
            assert_eq!(a, b, "CON→project→import must preserve topology multiset for '{sel}'");
        }
    }

    #[test]
    fn cpp_h1_name_not_preserved_is_documented_gap() {
        // selection.cpp filters on name H1; import stores atomic_type "H" only.
        let chfl = chemfiles_cpp_testing_frame();
        let con = con_from_cpp_testing_frame();
        let direct = evaluate_selection_on_chemfiles_frame("name H1", &chfl).unwrap();
        assert_eq!(direct.primary_indices(), vec![0]);
        let via = evaluate_selection_on_con_frame("name H1", &con).unwrap();
        assert!(
            via.matches.is_empty(),
            "CON/symbol path does not preserve chemfiles display name H1 separate from type H"
        );
        // type/name H still selects both hydrogens after import
        let via_h = evaluate_selection_on_con_frame("type H", &con).unwrap();
        assert_eq!(via_h.matches.len(), 2);
    }
}
