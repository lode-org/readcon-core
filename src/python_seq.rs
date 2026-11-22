// Sequence views over `PyConFrame::inner`.
//
// Included from `python.rs` so these items share that module.

use std::sync::Arc;

use pyo3::exceptions::PyIndexError;
use pyo3::types::PySliceIndices;

use crate::storage_dtype::{FloatArray1, FloatArray2, StorageDtypes};
use crate::types::{
    FrameHeader, FrameMeta, PreboxHeader, SECTION_CHARGES, SECTION_DISPLACEMENTS, SECTION_ENERGIES,
    SECTION_FORCES, SECTION_MAGMOMS, SECTION_SPINS, SECTION_SPREADS, SECTION_VELOCITIES,
};

/// One atom, in the order the frame currently stores it.
#[derive(Clone, Debug)]
struct AtomSnap {
    symbol: String,
    x: f64,
    y: f64,
    z: f64,
    fixed: [bool; 3],
    atom_id: u64,
    mass: f64,
    velocity: Option<[f64; 3]>,
    force: Option<[f64; 3]>,
    energy: Option<f64>,
    charge: Option<f64>,
    spin: Option<f64>,
    magmom: Option<[f64; 3]>,
    displacement: Option<[f64; 3]>,
    spread: Option<[f64; 3]>,
    /// Index in this frame's cached `Atom` list the snapshot was read from.
    /// A rebuild keeps that object, so a held `frame.atoms[i]` stays attached.
    origin: Option<usize>,
}

fn snap_from_datum(atom: &PyAtomDatum) -> AtomSnap {
    let velocity = if atom.has_velocity() {
        Some([
            atom.vx.unwrap_or(0.0),
            atom.vy.unwrap_or(0.0),
            atom.vz.unwrap_or(0.0),
        ])
    } else {
        None
    };
    let force = if atom.has_forces() {
        Some([
            atom.fx.unwrap_or(0.0),
            atom.fy.unwrap_or(0.0),
            atom.fz.unwrap_or(0.0),
        ])
    } else {
        None
    };
    let magmom = if atom.mx.is_some() && atom.my.is_some() && atom.mz.is_some() {
        Some([
            atom.mx.unwrap_or(0.0),
            atom.my.unwrap_or(0.0),
            atom.mz.unwrap_or(0.0),
        ])
    } else {
        None
    };
    let displacement = if atom.has_displacement() {
        Some([
            atom.dx.unwrap_or(0.0),
            atom.dy.unwrap_or(0.0),
            atom.dz.unwrap_or(0.0),
        ])
    } else {
        None
    };
    let spread = if atom.has_spread() {
        Some([
            atom.sx.unwrap_or(0.0),
            atom.sy.unwrap_or(0.0),
            atom.sz.unwrap_or(0.0),
        ])
    } else {
        None
    };
    AtomSnap {
        symbol: atom.symbol.clone(),
        x: atom.x,
        y: atom.y,
        z: atom.z,
        fixed: atom.fixed,
        atom_id: atom.atom_id,
        mass: atom.mass.unwrap_or(0.0),
        velocity,
        force,
        energy: atom.energy,
        charge: atom.charge,
        spin: atom.spin,
        magmom,
        displacement,
        spread,
        origin: None,
    }
}

fn datum_from_snap(snap: &AtomSnap) -> PyAtomDatum {
    let (vx, vy, vz) = match snap.velocity {
        Some([x, y, z]) => (Some(x), Some(y), Some(z)),
        None => (None, None, None),
    };
    let (fx, fy, fz) = match snap.force {
        Some([x, y, z]) => (Some(x), Some(y), Some(z)),
        None => (None, None, None),
    };
    let (mx, my, mz) = match snap.magmom {
        Some([x, y, z]) => (Some(x), Some(y), Some(z)),
        None => (None, None, None),
    };
    let (dx, dy, dz) = match snap.displacement {
        Some([x, y, z]) => (Some(x), Some(y), Some(z)),
        None => (None, None, None),
    };
    let (sx, sy, sz) = match snap.spread {
        Some([x, y, z]) => (Some(x), Some(y), Some(z)),
        None => (None, None, None),
    };
    PyAtomDatum {
        symbol: snap.symbol.clone(),
        x: snap.x,
        y: snap.y,
        z: snap.z,
        fixed: snap.fixed,
        atom_id: snap.atom_id,
        mass: Some(snap.mass),
        vx,
        vy,
        vz,
        fx,
        fy,
        fz,
        energy: snap.energy,
        charge: snap.charge,
        spin: snap.spin,
        mx,
        my,
        mz,
        dx,
        dy,
        dz,
        sx,
        sy,
        sz,
    }
}

fn snap_from_bound(obj: &Bound<'_, PyAny>) -> PyResult<AtomSnap> {
    if let Ok(view) = obj.cast::<PyAtomView>() {
        return view.borrow().snapshot(obj.py());
    }
    match obj.extract::<PyAtomDatum>() {
        Ok(atom) => Ok(snap_from_datum(&atom)),
        Err(_) => Err(PyTypeError::new_err(
            "expected a readcon.Atom or readcon.AtomView",
        )),
    }
}

fn snaps_from_iterable(obj: &Bound<'_, PyAny>) -> PyResult<Vec<AtomSnap>> {
    let iter = PyIterator::from_object(obj)?;
    let mut out = Vec::new();
    for item in iter {
        out.push(snap_from_bound(&item?)?);
    }
    Ok(out)
}

fn row_opt(arr: &FloatArray2, index: usize, n: usize) -> Option<[f64; 3]> {
    if n > 0 && arr.nrows() == n {
        Some(arr.as_f64_row(index))
    } else {
        None
    }
}

fn scalar_opt(arr: &FloatArray1, index: usize, n: usize, fallback: Option<f64>) -> Option<f64> {
    if n > 0 && arr.len() == n {
        Some(arr.get_f64(index))
    } else {
        fallback
    }
}

fn mass_at(frame: &ConFrame, index: usize) -> f64 {
    let n = frame.atom_data.len();
    if frame.masses.len() == n {
        return frame.masses.get_f64(index);
    }
    let mut off = 0usize;
    for (ti, &count) in frame.header.natms_per_type.iter().enumerate() {
        if index < off + count {
            return frame
                .header
                .masses_per_type
                .get(ti)
                .copied()
                .unwrap_or(0.0);
        }
        off += count;
    }
    0.0
}

fn same_physical_atom(a: &AtomSnap, b: &AtomSnap) -> bool {
    a.symbol == b.symbol
        && a.x == b.x
        && a.y == b.y
        && a.z == b.z
        && a.fixed == b.fixed
        && a.mass == b.mass
        && a.velocity == b.velocity
        && a.force == b.force
}

fn opt3(v: Option<[f64; 3]>) -> [f64; 3] {
    v.unwrap_or([0.0; 3])
}

fn set_row_component(
    arr: &mut FloatArray2,
    n: usize,
    index: usize,
    axis: usize,
    value: f64,
    kind: crate::storage_dtype::ElementKind,
) -> [f64; 3] {
    if arr.nrows() != n {
        *arr = FloatArray2::zeros(kind, n, 3);
    }
    let mut row = arr.as_f64_row(index);
    row[axis] = value;
    arr.set_f64_row(index, row);
    arr.as_f64_row(index)
}

fn set_scalar_value(
    arr: &mut FloatArray1,
    n: usize,
    index: usize,
    value: f64,
    kind: crate::storage_dtype::ElementKind,
) -> f64 {
    if arr.len() != n {
        *arr = FloatArray1::zeros(kind, n);
    }
    arr.set_f64(index, value);
    arr.get_f64(index)
}

#[allow(clippy::too_many_arguments)]
fn try_build_grouped(
    cell: [f64; 3],
    angles: [f64; 3],
    prebox: &[String; 2],
    postbox: &[String; 2],
    metadata: BTreeMap<String, Value>,
    snaps: &[AtomSnap],
) -> Result<(ConFrame, Vec<usize>), ParseError> {
    let mut builder = ConFrameBuilder::new(cell, angles);
    builder
        .prebox_header(prebox[0].as_str())
        .postbox_header(postbox.clone())
        .metadata(metadata);
    for snap in snaps {
        builder.add_atom(
            &snap.symbol,
            snap.x,
            snap.y,
            snap.z,
            snap.fixed,
            snap.atom_id,
            snap.mass,
        );
        if let Some(v) = snap.velocity {
            builder.with_velocity(v);
        }
        if let Some(f) = snap.force {
            builder.with_force(f);
        }
        if let Some(e) = snap.energy {
            builder.with_energy(e);
        }
        if let Some(c) = snap.charge {
            builder.with_charge(c);
        }
        if let Some(s) = snap.spin {
            builder.with_spin(s);
        }
        if let Some(m) = snap.magmom {
            builder.with_magmom(m);
        }
        if let Some(d) = snap.displacement {
            builder.with_displacement(d);
        }
        if let Some(s) = snap.spread {
            builder.with_spread(s);
        }
    }
    let (mut frame, order) = builder.build_with_permutation()?;
    frame.sync_atom_data_from_arrays();
    Ok((frame, order))
}

fn build_ungrouped(
    cell: [f64; 3],
    angles: [f64; 3],
    prebox: &[String; 2],
    postbox: &[String; 2],
    metadata: BTreeMap<String, Value>,
    snaps: &[AtomSnap],
) -> ConFrame {
    let n = snaps.len();
    let has_vel = snaps.iter().any(|s| s.velocity.is_some());
    let has_frc = snaps.iter().any(|s| s.force.is_some());
    let has_eng = snaps.iter().any(|s| s.energy.is_some());
    let has_chg = snaps.iter().any(|s| s.charge.is_some());
    let has_spn = snaps.iter().any(|s| s.spin.is_some());
    let has_mag = snaps.iter().any(|s| s.magmom.is_some());
    let has_dsp = snaps.iter().any(|s| s.displacement.is_some());
    let has_spr = snaps.iter().any(|s| s.spread.is_some());
    let dt = StorageDtypes::from_metadata(&metadata).unwrap_or_default();
    let mut positions = FloatArray2::zeros(dt.positions, n, 3);
    let mut velocities = FloatArray2::zeros(dt.velocities, if has_vel { n } else { 0 }, 3);
    let mut forces = FloatArray2::zeros(dt.forces, if has_frc { n } else { 0 }, 3);
    let mut atom_energies = FloatArray1::zeros(dt.energies, if has_eng { n } else { 0 });
    let mut charges = FloatArray1::zeros(dt.energies, if has_chg { n } else { 0 });
    let mut spins = FloatArray1::zeros(dt.energies, if has_spn { n } else { 0 });
    let mut magmoms = FloatArray2::zeros(dt.forces, if has_mag { n } else { 0 }, 3);
    let mut displacements = FloatArray2::zeros(dt.forces, if has_dsp { n } else { 0 }, 3);
    let mut spreads = FloatArray2::zeros(dt.forces, if has_spr { n } else { 0 }, 3);
    let mut masses = FloatArray1::zeros(dt.masses, n);
    let mut id_buf = vec![0u64; n];
    let mut atom_data = Vec::with_capacity(n);
    let mut natms_per_type: Vec<usize> = Vec::new();
    let mut masses_per_type: Vec<f64> = Vec::new();
    let mut last_symbol: Option<String> = None;

    for (i, snap) in snaps.iter().enumerate() {
        positions.set_f64_row(i, [snap.x, snap.y, snap.z]);
        let xyz = positions.as_f64_row(i);
        let velocity = if has_vel {
            velocities.set_f64_row(i, opt3(snap.velocity));
            Some(velocities.as_f64_row(i))
        } else {
            None
        };
        let force = if has_frc {
            forces.set_f64_row(i, opt3(snap.force));
            Some(forces.as_f64_row(i))
        } else {
            None
        };
        let energy = if has_eng {
            let v = set_scalar_value(
                &mut atom_energies,
                n,
                i,
                snap.energy.unwrap_or(0.0),
                dt.energies,
            );
            Some(v)
        } else {
            None
        };
        let charge = if has_chg {
            Some(set_scalar_value(
                &mut charges,
                n,
                i,
                snap.charge.unwrap_or(0.0),
                dt.energies,
            ))
        } else {
            None
        };
        let spin = if has_spn {
            Some(set_scalar_value(
                &mut spins,
                n,
                i,
                snap.spin.unwrap_or(0.0),
                dt.energies,
            ))
        } else {
            None
        };
        let magmom = if has_mag {
            magmoms.set_f64_row(i, opt3(snap.magmom));
            Some(magmoms.as_f64_row(i))
        } else {
            None
        };
        let displacement = if has_dsp {
            displacements.set_f64_row(i, opt3(snap.displacement));
            Some(displacements.as_f64_row(i))
        } else {
            None
        };
        let spread = if has_spr {
            spreads.set_f64_row(i, opt3(snap.spread));
            Some(spreads.as_f64_row(i))
        } else {
            None
        };
        let mass = set_scalar_value(&mut masses, n, i, snap.mass, dt.masses);
        id_buf[i] = snap.atom_id;
        if last_symbol.as_ref() == Some(&snap.symbol) {
            *natms_per_type.last_mut().expect("type run") += 1;
        } else {
            last_symbol = Some(snap.symbol.clone());
            natms_per_type.push(1);
            masses_per_type.push(mass);
        }
        atom_data.push(AtomDatum::with_sections(
            Arc::<str>::from(snap.symbol.as_str()),
            xyz[0],
            xyz[1],
            xyz[2],
            snap.fixed,
            snap.atom_id,
            velocity,
            force,
            energy,
            charge,
            spin,
            magmom,
            displacement,
            spread,
        ));
    }

    let mut sections = Vec::new();
    if has_vel {
        sections.push(SECTION_VELOCITIES.to_string());
    }
    if has_frc {
        sections.push(SECTION_FORCES.to_string());
    }
    if has_eng {
        sections.push(SECTION_ENERGIES.to_string());
    }
    if has_chg {
        sections.push(SECTION_CHARGES.to_string());
    }
    if has_spn {
        sections.push(SECTION_SPINS.to_string());
    }
    if has_mag {
        sections.push(SECTION_MAGMOMS.to_string());
    }
    if has_dsp {
        sections.push(SECTION_DISPLACEMENTS.to_string());
    }
    if has_spr {
        sections.push(SECTION_SPREADS.to_string());
    }
    let strict_validation = matches!(metadata.get(meta::VALIDATE), Some(Value::Bool(true)));
    let sections_declared = metadata.contains_key(meta::SECTIONS) || !sections.is_empty();
    ConFrame {
        header: FrameHeader {
            prebox_header: PreboxHeader::new(prebox[0].clone()),
            boxl: cell,
            angles,
            postbox_header: postbox.clone(),
            natm_types: natms_per_type.len(),
            natms_per_type,
            masses_per_type,
            spec_version: crate::CON_SPEC_VERSION,
            metadata: FrameMeta::from_map(metadata),
            sections,
            strict_validation,
            sections_declared,
        },
        atom_data,
        column_tails: Vec::new(),
        sequential_plain: false,
        positions,
        velocities: velocities.into(),
        forces: forces.into(),
        atom_energies: atom_energies.into(),
        charges: charges.into(),
        spins: spins.into(),
        magmoms: magmoms.into(),
        displacements: displacements.into(),
        spreads: spreads.into(),
        masses,
        atom_ids: ndarray::Array1::from_vec(id_buf).into_shared(),
    }
}

fn frame_for_storage(
    cell: [f64; 3],
    angles: [f64; 3],
    prebox: &[String; 2],
    postbox: &[String; 2],
    metadata: BTreeMap<String, Value>,
    snaps: &[AtomSnap],
) -> PyResult<ConFrame> {
    match try_build_grouped(
        cell,
        angles,
        prebox,
        postbox,
        metadata.clone(),
        snaps,
    ) {
        Ok(frame) => Ok(frame),
        Err(ParseError::MassMismatch { .. }) => Ok(build_ungrouped(
            cell, angles, prebox, postbox, metadata, snaps,
        )),
        Err(e) => Err(PyValueError::new_err(e.to_string())),
    }
}

fn slice_indices(slice: &Bound<'_, PySlice>, len: usize) -> PyResult<PySliceIndices> {
    slice.indices(len as isize)
}

impl PyConFrame {
    fn store(&self) -> &ConFrame {
        self.inner.as_ref().expect("ConFrame atom store")
    }

    fn store_mut(&mut self) -> &mut ConFrame {
        self.inner.as_mut().expect("ConFrame atom store")
    }

    fn n_atoms(&self) -> usize {
        self.inner
            .as_ref()
            .map(|frame| frame.atom_data.len())
            .unwrap_or(0)
    }

    /// Drop the iterator's source substring. A later write would not emit it.
    fn note_mutated(&mut self) {
        self.source_text = None;
    }

    fn ensure_index(&self, index: usize) -> PyResult<()> {
        if index >= self.n_atoms() {
            Err(PyIndexError::new_err("ConFrame index out of range"))
        } else {
            Ok(())
        }
    }

    fn normalize_index(&self, index: isize) -> PyResult<usize> {
        let n = self.n_atoms() as isize;
        let i = if index < 0 { index + n } else { index };
        if i < 0 || i >= n {
            Err(PyIndexError::new_err("ConFrame index out of range"))
        } else {
            Ok(i as usize)
        }
    }

    /// Positions live in the Rust columns, not in a NumPy slab or owned view.
    fn columns_hold_positions(&self) -> bool {
        let Some(frame) = self.inner.as_ref() else {
            return false;
        };
        let n = frame.atom_data.len();
        self.slab.is_none()
            && self.xyz_owned.is_none()
            && (n == 0 || frame.positions.nrows() == n)
    }

    fn snap_unchecked(&self, index: usize) -> AtomSnap {
        let frame = self.store();
        let n = frame.atom_data.len();
        let atom = &frame.atom_data[index];
        let [x, y, z] = if n > 0 && self.columns_hold_positions() {
            frame.positions.as_f64_row(index)
        } else if n == 0 {
            [0.0; 3]
        } else {
            [atom.x(), atom.y(), atom.z()]
        };
        AtomSnap {
            symbol: atom.symbol.to_string(),
            x,
            y,
            z,
            fixed: atom.fixed(),
            atom_id: if frame.atom_ids.len() == n {
                frame.atom_ids[index]
            } else {
                atom.atom_id
            },
            mass: mass_at(frame, index),
            velocity: row_opt(&frame.velocities, index, n).or_else(|| atom.velocity()),
            force: row_opt(&frame.forces, index, n).or_else(|| atom.force()),
            energy: scalar_opt(&frame.atom_energies, index, n, atom.energy()),
            charge: scalar_opt(&frame.charges, index, n, atom.charge()),
            spin: scalar_opt(&frame.spins, index, n, atom.spin()),
            magmom: row_opt(&frame.magmoms, index, n).or_else(|| atom.magmom()),
            displacement: row_opt(&frame.displacements, index, n).or_else(|| atom.displacement()),
            spread: row_opt(&frame.spreads, index, n).or_else(|| atom.spread()),
        }
    }

    fn snapshot_atoms(&self) -> Vec<AtomSnap> {
        (0..self.n_atoms())
            .map(|i| self.snap_unchecked(i))
            .collect()
    }

    fn dtypes(&self) -> StorageDtypes {
        let map = self.store().header.metadata.to_map();
        StorageDtypes::from_metadata(&map).unwrap_or_default()
    }

    fn replace_atoms(&mut self, py: Python<'_>, snaps: Vec<AtomSnap>) -> PyResult<()> {
        let meta = self.metadata_map(py)?;
        let (inner, order) = frame_for_storage_with_order(
            self.cell,
            self.angles,
            &self.prebox_header,
            &self.postbox_header,
            meta,
            &snaps,
        )?;
        self.n_atoms = inner.atom_data.len();
        self.inner = Some(inner);
        self.slab = None;
        self.slab_index = 0;
        self.xyz_owned = None;
        self.atoms = PyList::empty(py).unbind();
        self.atoms_ready
            .store(true, std::sync::atomic::Ordering::Release);
        self.note_mutated();
        Ok(())
    }

    fn assemble_like(&self, py: Python<'_>, snaps: Vec<AtomSnap>) -> PyResult<Self> {
        let meta = self.metadata_map(py)?;
        let metadata = json_map_to_py_dict(py, &meta)?;
        let inner = frame_for_storage(
            self.cell,
            self.angles,
            &self.prebox_header,
            &self.postbox_header,
            meta,
            &snaps,
        )?;
        Ok(Self {
            cell: self.cell,
            angles: self.angles,
            prebox_header: self.prebox_header.clone(),
            postbox_header: self.postbox_header.clone(),
            atoms: PyList::empty(py).unbind(),
            atoms_ready: std::sync::atomic::AtomicBool::new(true),
            spec_version: self.spec_version,
            metadata,
            inner: Some(inner),
            n_atoms: snaps.len(),
            slab: None,
            slab_index: 0,
            xyz_owned: None,
            source_text: None,
        })
    }

    fn set_position_axis(
        &mut self,
        py: Python<'_>,
        index: usize,
        axis: usize,
        value: f64,
    ) -> PyResult<()> {
        self.ensure_index(index)?;
        let use_columns = self.columns_hold_positions();
        let n = self.n_atoms();
        let dt = self.dtypes();
        if use_columns {
            let frame = self.store_mut();
            if frame.positions.nrows() != n {
                frame.positions = FloatArray2::zeros(dt.positions, n, 3);
                for i in 0..n {
                    let atom = &frame.atom_data[i];
                    frame
                        .positions
                        .set_f64_row(i, [atom.x(), atom.y(), atom.z()]);
                }
            }
            let stored = set_row_component(
                &mut frame.positions,
                n,
                index,
                axis,
                value,
                dt.positions,
            );
            let atom = &mut frame.atom_data[index];
            atom.set_x(stored[0]);
            atom.set_y(stored[1]);
            atom.set_z(stored[2]);
        } else {
            let atom = &mut self.store_mut().atom_data[index];
            match axis {
                0 => atom.set_x(value),
                1 => atom.set_y(value),
                2 => atom.set_z(value),
                _ => {}
            }
            self.write_view_component(py, index, axis, value)?;
        }
        self.note_mutated();
        Ok(())
    }

    /// `read_con` keeps coordinates in a NumPy slab or an owned array.
    /// Atom pointers usually alias that memory. Write the array as well so a
    /// view edit is visible when the pointer addresses a different box.
    fn write_view_component(
        &self,
        py: Python<'_>,
        index: usize,
        axis: usize,
        value: f64,
    ) -> PyResult<()> {
        if let Some(owned) = &self.xyz_owned {
            let arr = owned.bind(py);
            let n = arr.shape()[0];
            if index < n {
                unsafe {
                    let slice = arr.as_slice_mut().map_err(|err| {
                        PyValueError::new_err(format!("xyz is not contiguous: {err}"))
                    })?;
                    slice[index * 3 + axis] = value;
                }
            }
        }
        if let Some(slab) = &self.slab {
            let arr = slab.bind(py);
            let shape = arr.shape();
            let n = shape[1];
            if index < n && self.slab_index < shape[0] {
                unsafe {
                    let slice = arr.as_slice_mut().map_err(|err| {
                        PyValueError::new_err(format!("coordinate slab is not contiguous: {err}"))
                    })?;
                    let offset = (self.slab_index * n + index) * 3 + axis;
                    slice[offset] = value;
                }
            }
        }
        Ok(())
    }

    fn set_vec_axis(
        &mut self,
        which: VecSection,
        index: usize,
        axis: usize,
        value: Option<f64>,
    ) -> PyResult<()> {
        self.ensure_index(index)?;
        let n = self.n_atoms();
        let dt = self.dtypes();
        let absent = {
            let frame = self.store();
            let arr = vec_array(frame, which);
            value.is_none() && arr.nrows() != n
        };
        if absent {
            self.clear_vec_atom(which, index);
            self.note_mutated();
            return Ok(());
        }
        let (created, stored) = {
            let frame = self.store_mut();
            let kind = vec_kind(which, &dt);
            let arr = vec_array_mut(frame, which);
            let created = arr.nrows() != n;
            let stored = set_row_component(arr, n, index, axis, value.unwrap_or(0.0), kind);
            (created, stored)
        };
        if created {
            self.fill_vec_section(which);
        } else {
            self.write_vec_atom(which, index, stored);
        }
        self.note_mutated();
        Ok(())
    }

    fn clear_vec_atom(&mut self, which: VecSection, index: usize) {
        let atom = &mut self.store_mut().atom_data[index];
        match which {
            VecSection::Velocity => atom.set_velocity(None),
            VecSection::Force => atom.set_force(None),
            VecSection::Magmom => atom.set_magmom(None),
            VecSection::Displacement => atom.set_displacement(None),
            VecSection::Spread => atom.set_spread(None),
        }
    }

    fn write_vec_atom(&mut self, which: VecSection, index: usize, row: [f64; 3]) {
        let atom = &mut self.store_mut().atom_data[index];
        match which {
            VecSection::Velocity => atom.set_velocity(Some(row)),
            VecSection::Force => atom.set_force(Some(row)),
            VecSection::Magmom => atom.set_magmom(Some(row)),
            VecSection::Displacement => atom.set_displacement(Some(row)),
            VecSection::Spread => atom.set_spread(Some(row)),
        }
    }

    fn fill_vec_section(&mut self, which: VecSection) {
        let n = self.n_atoms();
        for i in 0..n {
            let row = {
                let frame = self.store();
                vec_array(frame, which).as_f64_row(i)
            };
            self.write_vec_atom(which, i, row);
        }
    }

    fn set_scalar_axis(
        &mut self,
        which: ScalarSection,
        index: usize,
        value: Option<f64>,
    ) -> PyResult<()> {
        self.ensure_index(index)?;
        let n = self.n_atoms();
        let kind = self.dtypes().energies;
        let absent = {
            let frame = self.store();
            value.is_none() && scalar_array(frame, which).len() != n
        };
        if absent {
            self.write_scalar_atom(which, index, None);
            self.note_mutated();
            return Ok(());
        }
        let (created, stored) = {
            let frame = self.store_mut();
            let arr = scalar_array_mut(frame, which);
            let created = arr.len() != n;
            let stored = set_scalar_value(arr, n, index, value.unwrap_or(0.0), kind);
            (created, stored)
        };
        if created {
            for i in 0..n {
                let v = {
                    let frame = self.store();
                    scalar_array(frame, which).get_f64(i)
                };
                self.write_scalar_atom(which, i, Some(v));
            }
        } else {
            self.write_scalar_atom(which, index, Some(stored));
        }
        self.note_mutated();
        Ok(())
    }

    fn write_scalar_atom(&mut self, which: ScalarSection, index: usize, value: Option<f64>) {
        let atom = &mut self.store_mut().atom_data[index];
        match which {
            ScalarSection::Energy => atom.set_energy(value),
            ScalarSection::Charge => atom.set_charge(value),
            ScalarSection::Spin => atom.set_spin(value),
        }
    }

    fn set_symbol_at(&mut self, py: Python<'_>, index: usize, symbol: String) -> PyResult<()> {
        self.ensure_index(index)?;
        let mut snaps = self.snapshot_atoms();
        snaps[index].symbol = symbol;
        self.replace_atoms(py, snaps)
    }

    fn set_fixed_at(&mut self, index: usize, fixed: [bool; 3]) -> PyResult<()> {
        self.ensure_index(index)?;
        self.store_mut().atom_data[index].set_fixed(fixed);
        self.note_mutated();
        Ok(())
    }

    fn set_atom_id_at(&mut self, index: usize, atom_id: u64) -> PyResult<()> {
        self.ensure_index(index)?;
        let n = self.n_atoms();
        let frame = self.store_mut();
        if frame.atom_ids.len() != n {
            let mut ids = ndarray::Array1::<u64>::zeros(n);
            for i in 0..n {
                ids[i] = frame.atom_data[i].atom_id;
            }
            frame.atom_ids = ids.into_shared();
        }
        frame.atom_ids[index] = atom_id;
        frame.atom_data[index].atom_id = atom_id;
        self.note_mutated();
        Ok(())
    }

    fn set_mass_at(&mut self, index: usize, mass: Option<f64>) -> PyResult<()> {
        self.ensure_index(index)?;
        let n = self.n_atoms();
        let dt = self.dtypes();
        let frame = self.store_mut();
        if frame.masses.len() != n {
            let existing: Vec<f64> = (0..n).map(|i| mass_at(frame, i)).collect();
            frame.masses = FloatArray1::zeros(dt.masses, n);
            for (i, m) in existing.into_iter().enumerate() {
                frame.masses.set_f64(i, m);
            }
        }
        let _stored = set_scalar_value(
            &mut frame.masses,
            n,
            index,
            mass.unwrap_or(0.0),
            dt.masses,
        );
        self.note_mutated();
        Ok(())
    }

    fn section_present_vec(&self, arr: &FloatArray2) -> bool {
        let n = self.n_atoms();
        n > 0 && arr.nrows() == n
    }

    fn section_present_scalar(&self, arr: &FloatArray1) -> bool {
        let n = self.n_atoms();
        n > 0 && arr.len() == n
    }

    fn picked_snaps(&self, indices: &PySliceIndices) -> Vec<AtomSnap> {
        let all = self.snapshot_atoms();
        let mut picked = Vec::with_capacity(indices.slicelength);
        let mut i = indices.start;
        for _ in 0..indices.slicelength {
            picked.push(all[i as usize].clone());
            i += indices.step;
        }
        picked
    }

    fn set_slice_snaps(
        &mut self,
        py: Python<'_>,
        slice: &Bound<'_, PySlice>,
        incoming: Vec<AtomSnap>,
    ) -> PyResult<()> {
        let indices = slice_indices(slice, self.n_atoms())?;
        if indices.step != 1 && incoming.len() != indices.slicelength {
            return Err(PyValueError::new_err(format!(
                "attempt to assign sequence of size {} to extended slice of size {}",
                incoming.len(),
                indices.slicelength
            )));
        }
        let mut snaps = self.snapshot_atoms();
        if indices.step == 1 {
            let start = indices.start as usize;
            let end = start + indices.slicelength;
            snaps.splice(start..end, incoming);
        } else {
            let mut i = indices.start;
            for snap in incoming {
                snaps[i as usize] = snap;
                i += indices.step;
            }
        }
        self.replace_atoms(py, snaps)
    }

    fn del_at(&mut self, py: Python<'_>, index: usize) -> PyResult<()> {
        self.ensure_index(index)?;
        let mut snaps = self.snapshot_atoms();
        snaps.remove(index);
        self.replace_atoms(py, snaps)
    }

    fn del_slice(&mut self, py: Python<'_>, slice: &Bound<'_, PySlice>) -> PyResult<()> {
        let indices = slice_indices(slice, self.n_atoms())?;
        let mut drop_at = Vec::with_capacity(indices.slicelength);
        let mut i = indices.start;
        for _ in 0..indices.slicelength {
            drop_at.push(i as usize);
            i += indices.step;
        }
        drop_at.sort_unstable();
        drop_at.dedup();
        let mut snaps = self.snapshot_atoms();
        for idx in drop_at.into_iter().rev() {
            snaps.remove(idx);
        }
        self.replace_atoms(py, snaps)
    }

    fn same_physical(&self, other: &Self) -> bool {
        if self.cell != other.cell || self.angles != other.angles {
            return false;
        }
        let a = self.snapshot_atoms();
        let b = other.snapshot_atoms();
        a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| same_physical_atom(x, y))
    }
}

fn vec_kind(which: VecSection, dt: &StorageDtypes) -> crate::storage_dtype::ElementKind {
    match which {
        VecSection::Velocity => dt.velocities,
        VecSection::Force | VecSection::Magmom | VecSection::Displacement | VecSection::Spread => {
            dt.forces
        }
    }
}

fn vec_array(frame: &ConFrame, which: VecSection) -> &FloatArray2 {
    match which {
        VecSection::Velocity => &frame.velocities,
        VecSection::Force => &frame.forces,
        VecSection::Magmom => &frame.magmoms,
        VecSection::Displacement => &frame.displacements,
        VecSection::Spread => &frame.spreads,
    }
}

fn vec_array_mut(frame: &mut ConFrame, which: VecSection) -> &mut FloatArray2 {
    match which {
        VecSection::Velocity => &mut frame.velocities,
        VecSection::Force => &mut frame.forces,
        VecSection::Magmom => &mut frame.magmoms,
        VecSection::Displacement => &mut frame.displacements,
        VecSection::Spread => &mut frame.spreads,
    }
}

fn scalar_array(frame: &ConFrame, which: ScalarSection) -> &FloatArray1 {
    match which {
        ScalarSection::Energy => &frame.atom_energies,
        ScalarSection::Charge => &frame.charges,
        ScalarSection::Spin => &frame.spins,
    }
}

fn scalar_array_mut(frame: &mut ConFrame, which: ScalarSection) -> &mut FloatArray1 {
    match which {
        ScalarSection::Energy => &mut frame.atom_energies,
        ScalarSection::Charge => &mut frame.charges,
        ScalarSection::Spin => &mut frame.spins,
    }
}

#[derive(Clone, Copy)]
enum VecSection {
    Velocity,
    Force,
    Magmom,
    Displacement,
    Spread,
}

#[derive(Clone, Copy)]
enum ScalarSection {
    Energy,
    Charge,
    Spin,
}

/// Proxy for one atom. Reads and writes go through the owning frame's columns.
#[pyclass(name = "AtomView", unsendable)]
struct PyAtomView {
    frame: Py<PyConFrame>,
    index: usize,
}

impl PyAtomView {
    fn snapshot(&self, py: Python<'_>) -> PyResult<AtomSnap> {
        self.frame.borrow(py).snap_at_checked(self.index)
    }
}

impl PyConFrame {
    fn snap_at_checked(&self, index: usize) -> PyResult<AtomSnap> {
        self.ensure_index(index)?;
        Ok(self.snap_unchecked(index))
    }
}

#[pymethods]
impl PyAtomView {
    #[getter]
    fn symbol(&self, py: Python<'_>) -> PyResult<String> {
        Ok(self.snapshot(py)?.symbol)
    }

    #[setter]
    fn set_symbol(&self, py: Python<'_>, symbol: String) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_symbol_at(py, self.index, symbol)
    }

    #[getter]
    fn x(&self, py: Python<'_>) -> PyResult<f64> {
        Ok(self.snapshot(py)?.x)
    }

    #[setter]
    fn set_x(&self, py: Python<'_>, value: f64) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_position_axis(py, self.index, 0, value)
    }

    #[getter]
    fn y(&self, py: Python<'_>) -> PyResult<f64> {
        Ok(self.snapshot(py)?.y)
    }

    #[setter]
    fn set_y(&self, py: Python<'_>, value: f64) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_position_axis(py, self.index, 1, value)
    }

    #[getter]
    fn z(&self, py: Python<'_>) -> PyResult<f64> {
        Ok(self.snapshot(py)?.z)
    }

    #[setter]
    fn set_z(&self, py: Python<'_>, value: f64) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_position_axis(py, self.index, 2, value)
    }

    #[getter]
    fn fixed(&self, py: Python<'_>) -> PyResult<[bool; 3]> {
        Ok(self.snapshot(py)?.fixed)
    }

    #[setter]
    fn set_fixed(&self, py: Python<'_>, fixed: [bool; 3]) -> PyResult<()> {
        self.frame.borrow_mut(py).set_fixed_at(self.index, fixed)
    }

    #[getter]
    fn is_fixed(&self, py: Python<'_>) -> PyResult<bool> {
        let fixed = self.snapshot(py)?.fixed;
        Ok(fixed[0] || fixed[1] || fixed[2])
    }

    #[getter]
    fn atom_id(&self, py: Python<'_>) -> PyResult<u64> {
        Ok(self.snapshot(py)?.atom_id)
    }

    #[setter]
    fn set_atom_id(&self, py: Python<'_>, atom_id: u64) -> PyResult<()> {
        self.frame.borrow_mut(py).set_atom_id_at(self.index, atom_id)
    }

    #[getter]
    fn mass(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(Some(self.snapshot(py)?.mass))
    }

    #[setter]
    fn set_mass(&self, py: Python<'_>, mass: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_mass_at(self.index, mass)
    }

    #[getter]
    fn vx(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.velocity.map(|v| v[0]))
    }

    #[setter]
    fn set_vx(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_vec_axis(
            VecSection::Velocity,
            self.index,
            0,
            value,
        )
    }

    #[getter]
    fn vy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.velocity.map(|v| v[1]))
    }

    #[setter]
    fn set_vy(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_vec_axis(
            VecSection::Velocity,
            self.index,
            1,
            value,
        )
    }

    #[getter]
    fn vz(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.velocity.map(|v| v[2]))
    }

    #[setter]
    fn set_vz(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_vec_axis(
            VecSection::Velocity,
            self.index,
            2,
            value,
        )
    }

    #[getter]
    fn has_velocity(&self, py: Python<'_>) -> PyResult<bool> {
        let frame = self.frame.borrow(py);
        Ok(frame.section_present_vec(&frame.store().velocities))
    }

    #[getter]
    fn fx(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.force.map(|v| v[0]))
    }

    #[setter]
    fn set_fx(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Force, self.index, 0, value)
    }

    #[getter]
    fn fy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.force.map(|v| v[1]))
    }

    #[setter]
    fn set_fy(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Force, self.index, 1, value)
    }

    #[getter]
    fn fz(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.force.map(|v| v[2]))
    }

    #[setter]
    fn set_fz(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Force, self.index, 2, value)
    }

    #[getter]
    fn has_forces(&self, py: Python<'_>) -> PyResult<bool> {
        let frame = self.frame.borrow(py);
        Ok(frame.section_present_vec(&frame.store().forces))
    }

    #[getter]
    fn energy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.energy)
    }

    #[setter]
    fn set_energy(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_scalar_axis(
            ScalarSection::Energy,
            self.index,
            value,
        )
    }

    #[getter]
    fn has_energy(&self, py: Python<'_>) -> PyResult<bool> {
        let frame = self.frame.borrow(py);
        Ok(frame.section_present_scalar(&frame.store().atom_energies))
    }

    #[getter]
    fn charge(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.charge)
    }

    #[setter]
    fn set_charge(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_scalar_axis(
            ScalarSection::Charge,
            self.index,
            value,
        )
    }

    #[getter]
    fn spin(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.spin)
    }

    #[setter]
    fn set_spin(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_scalar_axis(ScalarSection::Spin, self.index, value)
    }

    #[getter]
    fn mx(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.magmom.map(|v| v[0]))
    }
    #[setter]
    fn set_mx(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Magmom, self.index, 0, value)
    }
    #[getter]
    fn my(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.magmom.map(|v| v[1]))
    }
    #[setter]
    fn set_my(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Magmom, self.index, 1, value)
    }
    #[getter]
    fn mz(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.magmom.map(|v| v[2]))
    }
    #[setter]
    fn set_mz(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Magmom, self.index, 2, value)
    }

    #[getter]
    fn dx(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.displacement.map(|v| v[0]))
    }
    #[setter]
    fn set_dx(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_vec_axis(
            VecSection::Displacement,
            self.index,
            0,
            value,
        )
    }
    #[getter]
    fn dy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.displacement.map(|v| v[1]))
    }
    #[setter]
    fn set_dy(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_vec_axis(
            VecSection::Displacement,
            self.index,
            1,
            value,
        )
    }
    #[getter]
    fn dz(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.displacement.map(|v| v[2]))
    }
    #[setter]
    fn set_dz(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame.borrow_mut(py).set_vec_axis(
            VecSection::Displacement,
            self.index,
            2,
            value,
        )
    }

    #[getter]
    fn has_displacement(&self, py: Python<'_>) -> PyResult<bool> {
        let frame = self.frame.borrow(py);
        Ok(frame.section_present_vec(&frame.store().displacements))
    }

    #[getter]
    fn sx(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.spread.map(|v| v[0]))
    }
    #[setter]
    fn set_sx(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Spread, self.index, 0, value)
    }
    #[getter]
    fn sy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.spread.map(|v| v[1]))
    }
    #[setter]
    fn set_sy(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Spread, self.index, 1, value)
    }
    #[getter]
    fn sz(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        Ok(self.snapshot(py)?.spread.map(|v| v[2]))
    }
    #[setter]
    fn set_sz(&self, py: Python<'_>, value: Option<f64>) -> PyResult<()> {
        self.frame
            .borrow_mut(py)
            .set_vec_axis(VecSection::Spread, self.index, 2, value)
    }

    #[getter]
    fn has_spread(&self, py: Python<'_>) -> PyResult<bool> {
        let frame = self.frame.borrow(py);
        Ok(frame.section_present_vec(&frame.store().spreads))
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let snap = self.snapshot(py)?;
        Ok(format!(
            "AtomView(symbol='{}', x={}, y={}, z={}, atom_id={}, index={})",
            snap.symbol, snap.x, snap.y, snap.z, snap.atom_id, self.index
        ))
    }
}

/// Iterator of [`PyAtomView`] over a frame, forward or reversed.
#[pyclass(name = "AtomIterator", unsendable)]
struct PyAtomIter {
    frame: Py<PyConFrame>,
    index: isize,
    step: isize,
}

#[pymethods]
impl PyAtomIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<Py<PyAtomView>>> {
        let n = self.frame.borrow(py).n_atoms() as isize;
        if self.step > 0 {
            if self.index >= n {
                return Ok(None);
            }
        } else if self.index < 0 {
            return Ok(None);
        }
        let index = self.index as usize;
        self.index += self.step;
        Ok(Some(Py::new(
            py,
            PyAtomView {
                frame: self.frame.clone_ref(py),
                index,
            },
        )?))
    }
}

/// `frame.atoms`: the `Atom` projection. Mutations update the owning frame.
#[pyclass(name = "AtomSequence", unsendable)]
struct PyAtomSeq {
    frame: Py<PyConFrame>,
}

#[pymethods]
impl PyAtomSeq {
    fn __len__(&self, py: Python<'_>) -> usize {
        self.frame.borrow(py).n_atoms()
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAtomIter>> {
        Py::new(
            py,
            PyAtomIter {
                frame: self.frame.clone_ref(py),
                index: 0,
                step: 1,
            },
        )
    }

    fn __reversed__(&self, py: Python<'_>) -> PyResult<Py<PyAtomIter>> {
        let n = self.frame.borrow(py).n_atoms() as isize;
        Py::new(
            py,
            PyAtomIter {
                frame: self.frame.clone_ref(py),
                index: n - 1,
                step: -1,
            },
        )
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        sequence_getitem(&self.frame, py, key)
    }

    fn __setitem__(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        // Snapshot before borrow_mut so `atoms[i] = atoms[j]` can read a view.
        if let Ok(index) = key.extract::<isize>() {
            let snap = snap_from_bound(value)?;
            let mut frame = self.frame.borrow_mut(py);
            let i = frame.normalize_index(index)?;
            let mut snaps = frame.snapshot_atoms();
            snaps[i] = snap;
            return frame.replace_atoms(py, snaps);
        }
        if let Ok(slice) = key.cast::<PySlice>() {
            let incoming = snaps_from_iterable(value)?;
            let mut frame = self.frame.borrow_mut(py);
            return frame.set_slice_snaps(py, slice, incoming);
        }
        Err(PyTypeError::new_err(
            "ConFrame indices must be integers or slices",
        ))
    }

    fn __delitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut frame = self.frame.borrow_mut(py);
        sequence_delitem(&mut frame, py, key)
    }

    fn __contains__(&self, py: Python<'_>, item: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.frame.borrow(py).contains_atom(item)
    }

    /// Append an atom. The stored order is CON type-group order, the same
    /// order `write_con` emits, so a repeated symbol joins that symbol's group.
    fn append(&self, py: Python<'_>, atom: &Bound<'_, PyAny>) -> PyResult<()> {
        let snap = snap_from_bound(atom)?;
        let mut frame = self.frame.borrow_mut(py);
        let mut snaps = frame.snapshot_atoms();
        snaps.push(snap);
        frame.replace_atoms(py, snaps)
    }

    /// Insert an atom at `index` in the current sequence, then store the
    /// frame in CON type-group order.
    fn insert(&self, py: Python<'_>, index: isize, atom: &Bound<'_, PyAny>) -> PyResult<()> {
        let snap = snap_from_bound(atom)?;
        let mut frame = self.frame.borrow_mut(py);
        let mut snaps = frame.snapshot_atoms();
        let n = snaps.len() as isize;
        let mut i = if index < 0 { index + n } else { index };
        if i < 0 {
            i = 0;
        }
        if i > n {
            i = n;
        }
        snaps.insert(i as usize, snap);
        frame.replace_atoms(py, snaps)
    }

    fn extend(&self, py: Python<'_>, atoms: &Bound<'_, PyAny>) -> PyResult<()> {
        let extra = snaps_from_iterable(atoms)?;
        let mut frame = self.frame.borrow_mut(py);
        let mut snaps = frame.snapshot_atoms();
        snaps.extend(extra);
        frame.replace_atoms(py, snaps)
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!("AtomSequence(n={})", self.frame.borrow(py).n_atoms()))
    }
}

impl PyConFrame {
    fn contains_atom(&self, item: &Bound<'_, PyAny>) -> PyResult<bool> {
        let wanted = match snap_from_bound(item) {
            Ok(snap) => snap,
            Err(_) => return Ok(false),
        };
        Ok(self
            .snapshot_atoms()
            .iter()
            .any(|snap| same_physical_atom(snap, &wanted)))
    }
}

fn sequence_getitem(
    frame_obj: &Py<PyConFrame>,
    py: Python<'_>,
    key: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    if let Ok(index) = key.extract::<isize>() {
        let i = frame_obj.borrow(py).normalize_index(index)?;
        return Ok(Py::new(
            py,
            PyAtomView {
                frame: frame_obj.clone_ref(py),
                index: i,
            },
        )?
        .into_any());
    }
    if let Ok(slice) = key.cast::<PySlice>() {
        let frame = frame_obj.borrow(py);
        let indices = slice_indices(slice, frame.n_atoms())?;
        let snaps = frame.picked_snaps(&indices);
        let sliced = frame.assemble_like(py, snaps)?;
        return Ok(Py::new(py, sliced)?.into_any());
    }
    Err(PyTypeError::new_err(
        "ConFrame indices must be integers or slices",
    ))
}

fn sequence_delitem(
    frame: &mut PyConFrame,
    py: Python<'_>,
    key: &Bound<'_, PyAny>,
) -> PyResult<()> {
    if let Ok(index) = key.extract::<isize>() {
        let i = frame.normalize_index(index)?;
        return frame.del_at(py, i);
    }
    if let Ok(slice) = key.cast::<PySlice>() {
        return frame.del_slice(py, slice);
    }
    Err(PyTypeError::new_err(
        "ConFrame indices must be integers or slices",
    ))
}
