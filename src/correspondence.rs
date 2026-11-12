//! Pair atoms across frames by column-5 `atom_id`.
//!
//! CON stores atoms in type-grouped order. The id is the index from before
//! that grouping, so a reactant and a product that a writer grouped
//! differently still name the same atom. These helpers are the map, the
//! reorder, the band check, and the minimum-image displacement of the
//! matched pairs.
//!
//! The cell is [`FrameHeader::cell_matrix`] and [`FrameHeader::pbc_effective`].
//! The matrix is inverted here; lengths and angles are not rebuilt.
//!
//! ```
//! use readcon_core::types::ConFrameBuilder;
//! use readcon_core::{
//!     IdentityCheck, atom_id_permutation, check_atom_id_consistency,
//!     minimum_image_displacements, reorder_like,
//! };
//!
//! fn frame(rows: &[(u64, &str, f64)]) -> readcon_core::types::ConFrame {
//!     let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
//!     for (id, symbol, x) in rows {
//!         builder.add_atom(symbol, *x, 0.0, 0.0, [false; 3], *id, 12.0);
//!     }
//!     builder.build().unwrap()
//! }
//!
//! let reactant = frame(&[(1, "C", 0.0), (2, "O", 1.0)]);
//! let product = frame(&[(2, "O", 1.2), (1, "C", 0.1)]);
//! let perm = atom_id_permutation(&reactant, &product, IdentityCheck::Strict).unwrap();
//! assert_eq!(perm, vec![1, 0]);
//! let ordered = reorder_like(&reactant, &product, IdentityCheck::Strict).unwrap();
//! assert_eq!(ordered.atom_data[0].atom_id, 1);
//! assert_eq!(ordered.atom_data[1].atom_id, 2);
//! check_atom_id_consistency(&[reactant.clone(), product.clone()], IdentityCheck::Strict)
//!     .unwrap();
//! let disp = minimum_image_displacements(&reactant, &product, IdentityCheck::Strict).unwrap();
//! assert_eq!(disp.len(), 2);
//! assert!((disp[0][0] - 0.1).abs() < 1e-12);
//! ```

use crate::storage_dtype::{FloatArray1, FloatArray2};
use crate::types::{Bond, ConFrame, ConFrameBuilder};
use rustc_hash::FxHashMap;

/// How strictly two atoms that share an `atom_id` must agree.
///
/// Symbol mismatches, duplicate ids, and missing or extra ids fail in both
/// modes. [`IdentityCheck::Strict`] also requires the mass and the fixed
/// mask to agree. Masses within [`ConFrameBuilder::TYPE_MASS_ABS_TOL`] agree.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum IdentityCheck {
    /// Symbol, mass, and fixed mask agree.
    #[default]
    Strict,
    /// Symbol agrees. Mass and fixed mask may differ.
    Lenient,
}

/// Why two frames (or a later frame in a sequence) do not correspond.
#[derive(Debug, Clone, PartialEq)]
pub enum CorrespondenceError {
    /// `check_atom_id_consistency` was given no frames.
    EmptySequence,
    /// The same id occurs twice in one frame.
    Duplicate {
        frame_index: usize,
        atom_id: u64,
        /// Index of the second occurrence.
        atom_index: usize,
        first_index: usize,
    },
    /// `atom_id` is in the reference frame and absent from this frame.
    Missing {
        frame_index: usize,
        atom_id: u64,
        /// Index of the atom in the reference frame.
        reference_index: usize,
    },
    /// `atom_id` is in this frame and absent from the reference frame.
    Extra {
        frame_index: usize,
        atom_id: u64,
        atom_index: usize,
    },
    Symbol {
        frame_index: usize,
        atom_id: u64,
        atom_index: usize,
        reference_symbol: String,
        found_symbol: String,
    },
    Mass {
        frame_index: usize,
        atom_id: u64,
        atom_index: usize,
        reference_mass: f64,
        found_mass: f64,
    },
    Fixed {
        frame_index: usize,
        atom_id: u64,
        atom_index: usize,
        reference_fixed: [bool; 3],
        found_fixed: [bool; 3],
    },
    /// Reference cell matrix cannot be inverted.
    SingularCell {
        determinant: f64,
    },
    NonFiniteDelta,
    NonFiniteCoordinate {
        frame_index: usize,
        atom_id: u64,
        atom_index: usize,
    },
    SectionLength {
        section: &'static str,
        rows: usize,
        atoms: usize,
    },
    BondEndpoint {
        index: u32,
        atoms: usize,
    },
}

impl CorrespondenceError {
    /// Frame that failed. `None` when the failure is not a frame.
    pub fn frame_index(&self) -> Option<usize> {
        match self {
            Self::EmptySequence | Self::SingularCell { .. } | Self::NonFiniteDelta => None,
            Self::Duplicate { frame_index, .. }
            | Self::Missing { frame_index, .. }
            | Self::Extra { frame_index, .. }
            | Self::Symbol { frame_index, .. }
            | Self::Mass { frame_index, .. }
            | Self::Fixed { frame_index, .. }
            | Self::NonFiniteCoordinate { frame_index, .. } => Some(*frame_index),
            Self::SectionLength { .. } | Self::BondEndpoint { .. } => None,
        }
    }

    /// Atom id involved, when the failure names one atom.
    pub fn atom_id(&self) -> Option<u64> {
        match self {
            Self::Duplicate { atom_id, .. }
            | Self::Missing { atom_id, .. }
            | Self::Extra { atom_id, .. }
            | Self::Symbol { atom_id, .. }
            | Self::Mass { atom_id, .. }
            | Self::Fixed { atom_id, .. }
            | Self::NonFiniteCoordinate { atom_id, .. } => Some(*atom_id),
            _ => None,
        }
    }

    /// Storage index of that atom.
    ///
    /// For [`CorrespondenceError::Missing`] this is the index in the
    /// reference frame. Otherwise it is the index in [`Self::frame_index`].
    pub fn atom_index(&self) -> Option<usize> {
        match self {
            Self::Duplicate { atom_index, .. }
            | Self::Extra { atom_index, .. }
            | Self::Symbol { atom_index, .. }
            | Self::Mass { atom_index, .. }
            | Self::Fixed { atom_index, .. }
            | Self::NonFiniteCoordinate { atom_index, .. } => Some(*atom_index),
            Self::Missing {
                reference_index, ..
            } => Some(*reference_index),
            _ => None,
        }
    }
}

impl std::fmt::Display for CorrespondenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EmptySequence => {
                write!(f, "atom-id consistency check needs at least one frame")
            }
            Self::Duplicate {
                frame_index,
                atom_id,
                atom_index,
                first_index,
            } => write!(
                f,
                "duplicate atom_id {atom_id} in frame {frame_index} at index {atom_index} (first index {first_index})"
            ),
            Self::Missing {
                frame_index,
                atom_id,
                reference_index,
            } => write!(
                f,
                "frame {frame_index} is missing atom_id {atom_id} (reference index {reference_index})"
            ),
            Self::Extra {
                frame_index,
                atom_id,
                atom_index,
            } => write!(
                f,
                "frame {frame_index} atom_id {atom_id} at index {atom_index} is not in the reference frame"
            ),
            Self::Symbol {
                frame_index,
                atom_id,
                atom_index,
                reference_symbol,
                found_symbol,
            } => write!(
                f,
                "frame {frame_index} atom_id {atom_id} at index {atom_index} has symbol {found_symbol}; reference symbol is {reference_symbol}"
            ),
            Self::Mass {
                frame_index,
                atom_id,
                atom_index,
                reference_mass,
                found_mass,
            } => write!(
                f,
                "frame {frame_index} atom_id {atom_id} at index {atom_index} has mass {found_mass}; reference mass is {reference_mass} (tolerance {})",
                ConFrameBuilder::TYPE_MASS_ABS_TOL
            ),
            Self::Fixed {
                frame_index,
                atom_id,
                atom_index,
                reference_fixed,
                found_fixed,
            } => write!(
                f,
                "frame {frame_index} atom_id {atom_id} at index {atom_index} has fixed mask {found_fixed:?}; reference fixed mask is {reference_fixed:?}"
            ),
            Self::SingularCell { determinant } => write!(
                f,
                "minimum-image displacement: reference cell matrix is singular (determinant {determinant})"
            ),
            Self::NonFiniteDelta => {
                write!(
                    f,
                    "minimum-image displacement: cartesian delta is non-finite"
                )
            }
            Self::NonFiniteCoordinate {
                frame_index,
                atom_id,
                atom_index,
            } => write!(
                f,
                "frame {frame_index} atom_id {atom_id} at index {atom_index} has a non-finite coordinate"
            ),
            Self::SectionLength {
                section,
                rows,
                atoms,
            } => write!(f, "{section} has {rows} rows for {atoms} atoms"),
            Self::BondEndpoint { index, atoms } => {
                write!(
                    f,
                    "bond endpoint {index} is outside the atom list ({atoms} atoms)"
                )
            }
        }
    }
}

impl std::error::Error for CorrespondenceError {}

/// `perm[i]` is the index in `other` of the atom whose `atom_id` equals
/// `reference.atom_data[i].atom_id`.
///
/// Frame index 0 in an error is `reference`. Frame index 1 is `other`.
pub fn atom_id_permutation(
    reference: &ConFrame,
    other: &ConFrame,
    check: IdentityCheck,
) -> Result<Vec<usize>, CorrespondenceError> {
    atom_id_permutation_at(reference, other, 1, check)
}

fn atom_id_permutation_at(
    reference: &ConFrame,
    other: &ConFrame,
    other_index: usize,
    check: IdentityCheck,
) -> Result<Vec<usize>, CorrespondenceError> {
    index_ids(&reference.atom_data, 0)?;
    let other_index_map = index_ids(&other.atom_data, other_index)?;
    let ref_mass = masses_of(reference)?;
    let other_mass = masses_of(other)?;
    let mut perm = Vec::with_capacity(reference.atom_data.len());
    for (ri, atom) in reference.atom_data.iter().enumerate() {
        let Some(&bi) = other_index_map.get(&atom.atom_id) else {
            return Err(CorrespondenceError::Missing {
                frame_index: other_index,
                atom_id: atom.atom_id,
                reference_index: ri,
            });
        };
        let found = &other.atom_data[bi];
        if found.symbol != atom.symbol {
            return Err(CorrespondenceError::Symbol {
                frame_index: other_index,
                atom_id: atom.atom_id,
                atom_index: bi,
                reference_symbol: atom.symbol.to_string(),
                found_symbol: found.symbol.to_string(),
            });
        }
        if check == IdentityCheck::Strict {
            let reference_mass = ref_mass[ri];
            let found_mass = other_mass[bi];
            if !reference_mass.is_finite()
                || !found_mass.is_finite()
                || (reference_mass - found_mass).abs() > ConFrameBuilder::TYPE_MASS_ABS_TOL
            {
                return Err(CorrespondenceError::Mass {
                    frame_index: other_index,
                    atom_id: atom.atom_id,
                    atom_index: bi,
                    reference_mass,
                    found_mass,
                });
            }
            if found.fixed != atom.fixed {
                return Err(CorrespondenceError::Fixed {
                    frame_index: other_index,
                    atom_id: atom.atom_id,
                    atom_index: bi,
                    reference_fixed: atom.fixed,
                    found_fixed: found.fixed,
                });
            }
        }
        perm.push(bi);
    }
    if other.atom_data.len() != reference.atom_data.len() {
        let mut seen = vec![false; other.atom_data.len()];
        for &bi in &perm {
            seen[bi] = true;
        }
        for (i, atom) in other.atom_data.iter().enumerate() {
            if !seen[i] {
                return Err(CorrespondenceError::Extra {
                    frame_index: other_index,
                    atom_id: atom.atom_id,
                    atom_index: i,
                });
            }
        }
    }
    Ok(perm)
}

fn index_ids(
    atoms: &[crate::types::AtomDatum],
    frame_index: usize,
) -> Result<FxHashMap<u64, usize>, CorrespondenceError> {
    let mut map = FxHashMap::with_capacity_and_hasher(atoms.len(), Default::default());
    for (i, atom) in atoms.iter().enumerate() {
        if let Some(first) = map.insert(atom.atom_id, i) {
            return Err(CorrespondenceError::Duplicate {
                frame_index,
                atom_id: atom.atom_id,
                atom_index: i,
                first_index: first,
            });
        }
    }
    Ok(map)
}

fn masses_of(frame: &ConFrame) -> Result<Vec<f64>, CorrespondenceError> {
    let n = frame.atom_data.len();
    if frame.masses.len() != n {
        return Err(CorrespondenceError::SectionLength {
            section: "masses",
            rows: frame.masses.len(),
            atoms: n,
        });
    }
    Ok((0..n).map(|i| frame.masses.get_f64(i)).collect())
}

/// `other` with atoms stored in `reference` order.
///
/// Positions, velocities, forces, and the other per-atom sections move
/// with the atom. Bond endpoints, which are `atom_data` indices, are
/// remapped. The cell, the metadata, and the per-frame scalars stay
/// those of `other`. Type counts are rebuilt from the new order so the
/// frame still writes as CON when that order is type-grouped.
pub fn reorder_like(
    reference: &ConFrame,
    other: &ConFrame,
    check: IdentityCheck,
) -> Result<ConFrame, CorrespondenceError> {
    let perm = atom_id_permutation(reference, other, check)?;
    apply_permutation(other, &perm)
}

fn apply_permutation(frame: &ConFrame, perm: &[usize]) -> Result<ConFrame, CorrespondenceError> {
    let n = perm.len();
    let mut out = frame.clone();
    let mut atoms = Vec::with_capacity(n);
    for &j in perm {
        let mut atom = frame.atom_data[j].clone();
        let p = position_of(frame, j)?;
        atom.x = p[0];
        atom.y = p[1];
        atom.z = p[2];
        overlay_sections(&mut atom, frame, j)?;
        atoms.push(atom);
    }
    out.atom_data = atoms;
    out.positions = permute_rows(&frame.positions, perm, "positions")?;
    out.velocities = permute_rows(&frame.velocities, perm, "velocities")?;
    out.forces = permute_rows(&frame.forces, perm, "forces")?;
    out.magmoms = permute_rows(&frame.magmoms, perm, "magmoms")?;
    out.displacements = permute_rows(&frame.displacements, perm, "displacements")?;
    out.spreads = permute_rows(&frame.spreads, perm, "spreads")?;
    out.atom_energies = permute_col(&frame.atom_energies, perm, "energies")?;
    out.charges = permute_col(&frame.charges, perm, "charges")?;
    out.spins = permute_col(&frame.spins, perm, "spins")?;
    out.masses = permute_col(&frame.masses, perm, "masses")?;
    let ids: Vec<u64> = perm.iter().map(|&j| frame.atom_data[j].atom_id).collect();
    out.atom_ids = ndarray::Array1::from_vec(ids).into_shared();
    // Positions were copied above. When the source stored coordinates only
    // on the atoms, the permuted array is empty and the atoms carry xyz.
    if frame.positions.nrows() == n {
        for (i, atom) in out.atom_data.iter().enumerate() {
            out.positions.set_f64_row(i, [atom.x, atom.y, atom.z]);
        }
    }
    refresh_type_runs(&mut out);
    remap_bonds(&mut out, perm)?;
    Ok(out)
}

fn position_of(frame: &ConFrame, i: usize) -> Result<[f64; 3], CorrespondenceError> {
    let n = frame.atom_data.len();
    if frame.positions.nrows() == n {
        return Ok(frame.positions.as_f64_row(i));
    }
    if frame.positions.nrows() == 0 {
        let atom = &frame.atom_data[i];
        return Ok([atom.x, atom.y, atom.z]);
    }
    Err(CorrespondenceError::SectionLength {
        section: "positions",
        rows: frame.positions.nrows(),
        atoms: n,
    })
}

fn overlay_sections(
    atom: &mut crate::types::AtomDatum,
    frame: &ConFrame,
    j: usize,
) -> Result<(), CorrespondenceError> {
    let n = frame.atom_data.len();
    if frame.velocities.nrows() == n {
        atom.set_velocity(Some(frame.velocities.as_f64_row(j)));
    } else if frame.velocities.nrows() != 0 {
        return Err(CorrespondenceError::SectionLength {
            section: "velocities",
            rows: frame.velocities.nrows(),
            atoms: n,
        });
    }
    if frame.forces.nrows() == n {
        atom.set_force(Some(frame.forces.as_f64_row(j)));
    } else if frame.forces.nrows() != 0 {
        return Err(CorrespondenceError::SectionLength {
            section: "forces",
            rows: frame.forces.nrows(),
            atoms: n,
        });
    }
    if frame.atom_energies.len() == n {
        atom.set_energy(Some(frame.atom_energies.get_f64(j)));
    } else if !frame.atom_energies.is_empty() {
        return Err(CorrespondenceError::SectionLength {
            section: "energies",
            rows: frame.atom_energies.len(),
            atoms: n,
        });
    }
    if frame.charges.len() == n {
        atom.set_charge(Some(frame.charges.get_f64(j)));
    } else if !frame.charges.is_empty() {
        return Err(CorrespondenceError::SectionLength {
            section: "charges",
            rows: frame.charges.len(),
            atoms: n,
        });
    }
    if frame.spins.len() == n {
        atom.set_spin(Some(frame.spins.get_f64(j)));
    } else if !frame.spins.is_empty() {
        return Err(CorrespondenceError::SectionLength {
            section: "spins",
            rows: frame.spins.len(),
            atoms: n,
        });
    }
    if frame.magmoms.nrows() == n {
        atom.set_magmom(Some(frame.magmoms.as_f64_row(j)));
    } else if frame.magmoms.nrows() != 0 {
        return Err(CorrespondenceError::SectionLength {
            section: "magmoms",
            rows: frame.magmoms.nrows(),
            atoms: n,
        });
    }
    if frame.displacements.nrows() == n {
        atom.set_displacement(Some(frame.displacements.as_f64_row(j)));
    } else if frame.displacements.nrows() != 0 {
        return Err(CorrespondenceError::SectionLength {
            section: "displacements",
            rows: frame.displacements.nrows(),
            atoms: n,
        });
    }
    if frame.spreads.nrows() == n {
        atom.set_spread(Some(frame.spreads.as_f64_row(j)));
    } else if frame.spreads.nrows() != 0 {
        return Err(CorrespondenceError::SectionLength {
            section: "spreads",
            rows: frame.spreads.nrows(),
            atoms: n,
        });
    }
    Ok(())
}

fn permute_rows(
    src: &FloatArray2,
    perm: &[usize],
    section: &'static str,
) -> Result<FloatArray2, CorrespondenceError> {
    let n = perm.len();
    if src.nrows() == 0 {
        return Ok(FloatArray2::zeros(src.kind(), 0, 3));
    }
    if src.nrows() != n {
        return Err(CorrespondenceError::SectionLength {
            section,
            rows: src.nrows(),
            atoms: n,
        });
    }
    let mut out = FloatArray2::zeros(src.kind(), n, src.ncols().max(3));
    for (i, &j) in perm.iter().enumerate() {
        out.set_f64_row(i, src.as_f64_row(j));
    }
    Ok(out)
}

fn permute_col(
    src: &FloatArray1,
    perm: &[usize],
    section: &'static str,
) -> Result<FloatArray1, CorrespondenceError> {
    let n = perm.len();
    if src.is_empty() {
        return Ok(FloatArray1::zeros(src.kind(), 0));
    }
    if src.len() != n {
        return Err(CorrespondenceError::SectionLength {
            section,
            rows: src.len(),
            atoms: n,
        });
    }
    let mut out = FloatArray1::zeros(src.kind(), n);
    for (i, &j) in perm.iter().enumerate() {
        out.set_f64(i, src.get_f64(j));
    }
    Ok(out)
}

fn refresh_type_runs(frame: &mut ConFrame) {
    let n = frame.atom_data.len();
    if n == 0 {
        frame.header.natm_types = 0;
        frame.header.natms_per_type.clear();
        frame.header.masses_per_type.clear();
        return;
    }
    let mut counts = Vec::new();
    let mut masses = Vec::new();
    let mut run_symbol = frame.atom_data[0].symbol.clone();
    let mut run_count = 0usize;
    let mut run_mass = frame.masses.get_f64(0);
    for i in 0..n {
        if frame.atom_data[i].symbol != run_symbol {
            counts.push(run_count);
            masses.push(run_mass);
            run_symbol = frame.atom_data[i].symbol.clone();
            run_count = 0;
            run_mass = frame.masses.get_f64(i);
        }
        run_count += 1;
    }
    counts.push(run_count);
    masses.push(run_mass);
    frame.header.natm_types = counts.len();
    frame.header.natms_per_type = counts;
    frame.header.masses_per_type = masses;
}

fn remap_bonds(frame: &mut ConFrame, perm: &[usize]) -> Result<(), CorrespondenceError> {
    let bonds = frame.bonds();
    if bonds.is_empty() {
        return Ok(());
    }
    let n = perm.len();
    let mut inverse = vec![0usize; n];
    for (i, &j) in perm.iter().enumerate() {
        inverse[j] = i;
    }
    let mut mapped = Vec::with_capacity(bonds.len());
    for bond in bonds {
        if bond.i as usize >= n {
            return Err(CorrespondenceError::BondEndpoint {
                index: bond.i,
                atoms: n,
            });
        }
        if bond.j as usize >= n {
            return Err(CorrespondenceError::BondEndpoint {
                index: bond.j,
                atoms: n,
            });
        }
        mapped.push(Bond {
            i: inverse[bond.i as usize] as u32,
            j: inverse[bond.j as usize] as u32,
            order: bond.order,
        });
    }
    frame.header.set_bonds(&mapped);
    Ok(())
}

/// Walk `frames` in order. Frame 0 is the reference.
///
/// The error is the first frame that disagrees with frame 0, and the
/// atom involved. A one-frame sequence checks that its ids are unique.
pub fn check_atom_id_consistency(
    frames: &[ConFrame],
    check: IdentityCheck,
) -> Result<(), CorrespondenceError> {
    let refs: Vec<&ConFrame> = frames.iter().collect();
    check_atom_id_consistency_refs(&refs, check)
}

pub(crate) fn check_atom_id_consistency_refs(
    frames: &[&ConFrame],
    check: IdentityCheck,
) -> Result<(), CorrespondenceError> {
    let Some(reference) = frames.first() else {
        return Err(CorrespondenceError::EmptySequence);
    };
    if frames.len() == 1 {
        index_ids(&reference.atom_data, 0)?;
        return Ok(());
    }
    for (i, frame) in frames.iter().enumerate().skip(1) {
        atom_id_permutation_at(reference, frame, i, check)?;
    }
    Ok(())
}

/// Minimum-image displacement of each reference atom toward the atom in
/// `other` with the same `atom_id`.
///
/// Row `i` is the wrapped `r_other - r_reference` for reference atom `i`.
/// The cell and the periodic flags are the reference frame's
/// [`FrameHeader::cell_matrix`] and [`FrameHeader::pbc_effective`].
pub fn minimum_image_displacements(
    reference: &ConFrame,
    other: &ConFrame,
    check: IdentityCheck,
) -> Result<Vec<[f64; 3]>, CorrespondenceError> {
    let perm = atom_id_permutation(reference, other, check)?;
    let cell = reference.header.cell_matrix();
    let pbc = reference.header.pbc_effective();
    let mut out = Vec::with_capacity(perm.len());
    for (i, &j) in perm.iter().enumerate() {
        let ra = position_of(reference, i)?;
        let rb = position_of(other, j)?;
        if !finite3(ra) {
            return Err(CorrespondenceError::NonFiniteCoordinate {
                frame_index: 0,
                atom_id: reference.atom_data[i].atom_id,
                atom_index: i,
            });
        }
        if !finite3(rb) {
            return Err(CorrespondenceError::NonFiniteCoordinate {
                frame_index: 1,
                atom_id: other.atom_data[j].atom_id,
                atom_index: j,
            });
        }
        let delta = [rb[0] - ra[0], rb[1] - ra[1], rb[2] - ra[2]];
        out.push(minimum_image_delta(cell, pbc, delta)?);
    }
    Ok(out)
}

fn finite3(v: [f64; 3]) -> bool {
    v.iter().all(|x| x.is_finite())
}

/// Wrap one cartesian delta into the reference cell.
///
/// `cell` is a [`FrameHeader::cell_matrix`]: each row is a lattice vector.
/// Fractional coordinates are `delta * cell^{-1}` (row vector on the left).
/// A periodic axis subtracts the nearest integer. `f64::round` breaks a
/// half-integer toward ±infinity, away from zero.
pub fn minimum_image_delta(
    cell: [[f64; 3]; 3],
    pbc: [bool; 3],
    delta: [f64; 3],
) -> Result<[f64; 3], CorrespondenceError> {
    if !finite3(delta) {
        return Err(CorrespondenceError::NonFiniteDelta);
    }
    let (inv, _) = invert_cell(cell).ok_or(CorrespondenceError::SingularCell {
        determinant: det3(cell),
    })?;
    let mut frac = mul_row(delta, inv);
    for axis in 0..3 {
        if pbc[axis] {
            frac[axis] -= frac[axis].round();
        }
    }
    Ok(mul_row(frac, cell))
}

fn det3(m: [[f64; 3]; 3]) -> f64 {
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
}

fn invert_cell(m: [[f64; 3]; 3]) -> Option<([[f64; 3]; 3], f64)> {
    let det = det3(m);
    if !det.is_finite() || det.abs() < 1e-18 {
        return None;
    }
    let inv_det = 1.0 / det;
    let c00 = m[1][1] * m[2][2] - m[1][2] * m[2][1];
    let c01 = -(m[1][0] * m[2][2] - m[1][2] * m[2][0]);
    let c02 = m[1][0] * m[2][1] - m[1][1] * m[2][0];
    let c10 = -(m[0][1] * m[2][2] - m[0][2] * m[2][1]);
    let c11 = m[0][0] * m[2][2] - m[0][2] * m[2][0];
    let c12 = -(m[0][0] * m[2][1] - m[0][1] * m[2][0]);
    let c20 = m[0][1] * m[1][2] - m[0][2] * m[1][1];
    let c21 = -(m[0][0] * m[1][2] - m[0][2] * m[1][0]);
    let c22 = m[0][0] * m[1][1] - m[0][1] * m[1][0];
    let inv = [
        [c00 * inv_det, c10 * inv_det, c20 * inv_det],
        [c01 * inv_det, c11 * inv_det, c21 * inv_det],
        [c02 * inv_det, c12 * inv_det, c22 * inv_det],
    ];
    Some((inv, det))
}

/// Row vector times a row-major matrix.
fn mul_row(v: [f64; 3], m: [[f64; 3]; 3]) -> [f64; 3] {
    [
        v[0] * m[0][0] + v[1] * m[1][0] + v[2] * m[2][0],
        v[0] * m[0][1] + v[1] * m[1][1] + v[2] * m[2][1],
        v[0] * m[0][2] + v[1] * m[1][2] + v[2] * m[2][2],
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::cell_vectors;

    fn close(a: [f64; 3], b: [f64; 3]) {
        for k in 0..3 {
            assert!(
                (a[k] - b[k]).abs() < 1e-9,
                "component {k}: {} vs {}",
                a[k],
                b[k]
            );
        }
    }

    #[test]
    fn orthogonal_wrap_uses_the_cell_matrix() {
        let cell = cell_vectors([10.0, 12.0, 14.0], [90.0, 90.0, 90.0]);
        let wrapped = minimum_image_delta(cell, [true, true, true], [9.0, 0.0, 0.0]).unwrap();
        close(wrapped, [-1.0, 0.0, 0.0]);
        let open = minimum_image_delta(cell, [false, true, true], [9.0, 9.0, 0.0]).unwrap();
        close(open, [9.0, -3.0, 0.0]);
    }

    #[test]
    fn a_lattice_vector_wraps_to_zero() {
        let cell = cell_vectors([10.0, 12.0, 14.0], [80.0, 90.0, 70.0]);
        let along_a = minimum_image_delta(cell, [true, true, true], cell[0]).unwrap();
        close(along_a, [0.0, 0.0, 0.0]);
        let along_b = minimum_image_delta(cell, [true, true, true], cell[1]).unwrap();
        close(along_b, [0.0, 0.0, 0.0]);
    }

    #[test]
    fn a_flat_cell_is_rejected() {
        let err = minimum_image_delta([[0.0; 3]; 3], [true; 3], [1.0, 0.0, 0.0]).unwrap_err();
        assert!(matches!(err, CorrespondenceError::SingularCell { .. }));
        assert!(err.to_string().contains("singular"));
    }
}
