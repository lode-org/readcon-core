use ndarray::Array2;
use numpy::{IntoPyArray, PyArray1, PyArray2};
use pyo3::IntoPyObjectExt;
use pyo3::exceptions::PyIOError;
use pyo3::exceptions::PyTypeError;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{IntoPyDict, PyDict, PyIterator, PyList, PyTuple};
use serde_json::{Number, Value};
use std::collections::BTreeMap;
use std::path::Path;

use crate::iterators::ConFrameIterator;
use crate::types::{AtomDatum, ConFrame, ConFrameBuilder, meta};
use crate::writer::ConFrameWriter;

/// Python-visible atom data.
#[pyclass(name = "Atom", from_py_object)]
#[derive(Clone)]
pub struct PyAtomDatum {
    #[pyo3(get, set)]
    pub symbol: String,
    #[pyo3(get, set)]
    pub x: f64,
    #[pyo3(get, set)]
    pub y: f64,
    #[pyo3(get, set)]
    pub z: f64,
    #[pyo3(get, set)]
    pub fixed: [bool; 3],
    #[pyo3(get, set)]
    pub atom_id: u64,
    #[pyo3(get, set)]
    pub mass: Option<f64>,
    #[pyo3(get, set)]
    pub vx: Option<f64>,
    #[pyo3(get, set)]
    pub vy: Option<f64>,
    #[pyo3(get, set)]
    pub vz: Option<f64>,
    #[pyo3(get, set)]
    pub fx: Option<f64>,
    #[pyo3(get, set)]
    pub fy: Option<f64>,
    #[pyo3(get, set)]
    pub fz: Option<f64>,
    /// Per-atom energy contribution; populated when the file declares an
    /// `"energies"` section. None for ordinary frames where only the
    /// per-frame total energy (`metadata['energy']`) is meaningful.
    #[pyo3(get, set)]
    pub energy: Option<f64>,
}

#[pymethods]
impl PyAtomDatum {
    #[new]
    #[pyo3(signature = (symbol, x, y, z, fixed=None, atom_id=0, mass=None, vx=None, vy=None, vz=None, fx=None, fy=None, fz=None, energy=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        symbol: String,
        x: f64,
        y: f64,
        z: f64,
        fixed: Option<[bool; 3]>,
        atom_id: u64,
        mass: Option<f64>,
        vx: Option<f64>,
        vy: Option<f64>,
        vz: Option<f64>,
        fx: Option<f64>,
        fy: Option<f64>,
        fz: Option<f64>,
        energy: Option<f64>,
    ) -> Self {
        PyAtomDatum {
            symbol,
            x,
            y,
            z,
            fixed: fixed.unwrap_or([false, false, false]),
            atom_id,
            mass,
            vx,
            vy,
            vz,
            fx,
            fy,
            fz,
            energy,
        }
    }

    /// Backward-compatible property: true if any direction is fixed.
    #[getter]
    fn is_fixed(&self) -> bool {
        self.fixed[0] || self.fixed[1] || self.fixed[2]
    }

    #[getter]
    fn has_velocity(&self) -> bool {
        self.vx.is_some() && self.vy.is_some() && self.vz.is_some()
    }

    #[getter]
    fn has_forces(&self) -> bool {
        self.fx.is_some() && self.fy.is_some() && self.fz.is_some()
    }

    #[getter]
    fn has_energy(&self) -> bool {
        self.energy.is_some()
    }

    fn __repr__(&self) -> String {
        format!(
            "Atom(symbol='{}', x={}, y={}, z={}, atom_id={})",
            self.symbol, self.x, self.y, self.z, self.atom_id
        )
    }
}

impl PyAtomDatum {
    fn from_atom_with_mass(atom: &AtomDatum, mass: f64) -> Self {
        let (vx, vy, vz) = match atom.velocity {
            Some([x, y, z]) => (Some(x), Some(y), Some(z)),
            None => (None, None, None),
        };
        let (fx, fy, fz) = match atom.force {
            Some([x, y, z]) => (Some(x), Some(y), Some(z)),
            None => (None, None, None),
        };
        PyAtomDatum {
            symbol: atom.symbol.to_string(),
            x: atom.x,
            y: atom.y,
            z: atom.z,
            fixed: atom.fixed,
            atom_id: atom.atom_id,
            mass: Some(mass),
            vx,
            vy,
            vz,
            fx,
            fy,
            fz,
            energy: atom.energy,
        }
    }
}

fn py_metadata_to_json_map(obj: &Bound<'_, PyAny>) -> PyResult<BTreeMap<String, Value>> {
    if obj.is_none() {
        return Ok(BTreeMap::new());
    }

    let dict = obj
        .cast::<PyDict>()
        .map_err(|_| PyValueError::new_err("metadata must be a dict"))?;

    let mut metadata = BTreeMap::new();
    for (key, value) in dict.iter() {
        let key: String = key
            .extract()
            .map_err(|_| PyValueError::new_err("metadata keys must be strings"))?;
        if key == meta::CON_SPEC_VERSION || key == meta::SECTIONS {
            continue;
        }
        metadata.insert(key, py_to_json_value(&value)?);
    }
    Ok(metadata)
}

fn py_to_json_value(obj: &Bound<'_, PyAny>) -> PyResult<Value> {
    if obj.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(value) = obj.extract::<bool>() {
        return Ok(Value::Bool(value));
    }
    if let Ok(value) = obj.extract::<i64>() {
        return Ok(Value::Number(Number::from(value)));
    }
    if let Ok(value) = obj.extract::<u64>() {
        return Ok(Value::Number(Number::from(value)));
    }
    if let Ok(value) = obj.extract::<f64>() {
        let number = Number::from_f64(value)
            .ok_or_else(|| PyValueError::new_err("metadata floats must be finite"))?;
        return Ok(Value::Number(number));
    }
    if let Ok(value) = obj.extract::<String>() {
        return Ok(Value::String(value));
    }
    if let Ok(dict) = obj.cast::<PyDict>() {
        let entries: PyResult<serde_json::Map<String, Value>> = dict
            .iter()
            .map(|(key, value)| {
                let key: String = key
                    .extract()
                    .map_err(|_| PyValueError::new_err("metadata keys must be strings"))?;
                Ok((key, py_to_json_value(&value)?))
            })
            .collect();
        return Ok(Value::Object(entries?));
    }
    if let Ok(list) = obj.cast::<PyList>() {
        let values: PyResult<Vec<Value>> =
            list.iter().map(|item| py_to_json_value(&item)).collect();
        return Ok(Value::Array(values?));
    }
    if let Ok(tuple) = obj.cast::<PyTuple>() {
        let values: PyResult<Vec<Value>> =
            tuple.iter().map(|item| py_to_json_value(&item)).collect();
        return Ok(Value::Array(values?));
    }

    let type_name = obj
        .get_type()
        .name()
        .map(|name| name.to_string())
        .unwrap_or_else(|_| "unknown".to_string());
    Err(PyValueError::new_err(format!(
        "metadata values must be JSON-compatible, got {type_name}"
    )))
}

fn json_map_to_py_dict(py: Python<'_>, metadata: &BTreeMap<String, Value>) -> PyResult<Py<PyDict>> {
    let dict = PyDict::new(py);
    for (key, value) in metadata {
        dict.set_item(key, json_value_to_py(py, value)?)?;
    }
    Ok(dict.unbind())
}

fn json_value_to_py(py: Python<'_>, value: &Value) -> PyResult<Py<PyAny>> {
    match value {
        Value::Null => Ok(py.None()),
        Value::Bool(value) => value.into_py_any(py),
        Value::Number(value) => {
            if let Some(value) = value.as_i64() {
                value.into_py_any(py)
            } else if let Some(value) = value.as_u64() {
                value.into_py_any(py)
            } else if let Some(value) = value.as_f64() {
                value.into_py_any(py)
            } else {
                Err(PyValueError::new_err("unsupported metadata number"))
            }
        }
        Value::String(value) => value.into_py_any(py),
        Value::Array(values) => {
            let list = PyList::empty(py);
            for value in values {
                list.append(json_value_to_py(py, value)?)?;
            }
            Ok(list.into_any().unbind())
        }
        Value::Object(values) => {
            let dict = PyDict::new(py);
            for (key, value) in values {
                dict.set_item(key, json_value_to_py(py, value)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
}

fn py_atoms_to_list(py: Python<'_>, atoms: Vec<PyAtomDatum>) -> PyResult<Py<PyList>> {
    let list = PyList::empty(py);
    for atom in atoms {
        list.append(Py::new(py, atom)?)?;
    }
    Ok(list.unbind())
}

/// Python-visible simulation frame.
#[pyclass(name = "ConFrame")]
pub struct PyConFrame {
    #[pyo3(get)]
    pub cell: [f64; 3],
    #[pyo3(get)]
    pub angles: [f64; 3],
    #[pyo3(get)]
    pub prebox_header: [String; 2],
    #[pyo3(get)]
    pub postbox_header: [String; 2],
    atoms: Py<PyList>,
    #[pyo3(get)]
    pub spec_version: u32,
    metadata: Py<PyDict>,
}

#[pymethods]
impl PyConFrame {
    #[new]
    #[pyo3(signature = (cell, angles, atoms, prebox_header=None, postbox_header=None, metadata=None))]
    fn new(
        py: Python<'_>,
        cell: [f64; 3],
        angles: [f64; 3],
        atoms: Vec<PyAtomDatum>,
        prebox_header: Option<[String; 2]>,
        postbox_header: Option<[String; 2]>,
        metadata: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let atoms = py_atoms_to_list(py, atoms)?;
        let metadata = match metadata {
            Some(obj) => json_map_to_py_dict(py, &py_metadata_to_json_map(obj)?)?,
            None => PyDict::new(py).unbind(),
        };
        Ok(PyConFrame {
            cell,
            angles,
            prebox_header: prebox_header.unwrap_or_default(),
            postbox_header: postbox_header.unwrap_or_default(),
            spec_version: crate::CON_SPEC_VERSION,
            atoms,
            metadata,
        })
    }

    #[getter]
    fn atoms(&self, py: Python<'_>) -> Py<PyList> {
        self.atoms.clone_ref(py)
    }

    #[getter]
    fn metadata(&self, py: Python<'_>) -> Py<PyDict> {
        self.metadata.clone_ref(py)
    }

    #[setter]
    fn set_metadata(&mut self, py: Python<'_>, metadata: &Bound<'_, PyAny>) -> PyResult<()> {
        self.metadata = json_map_to_py_dict(py, &py_metadata_to_json_map(metadata)?)?;
        Ok(())
    }

    #[getter]
    fn has_velocities(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self
            .py_atoms(py)?
            .first()
            .is_some_and(PyAtomDatum::has_velocity))
    }

    #[getter]
    fn has_forces(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self
            .py_atoms(py)?
            .first()
            .is_some_and(PyAtomDatum::has_forces))
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!(
            "ConFrame(cell={:?}, angles={:?}, natoms={}, has_velocities={})",
            self.cell,
            self.angles,
            self.atoms.bind(py).len(),
            self.has_velocities(py)?
        ))
    }

    fn __len__(&self, py: Python<'_>) -> usize {
        self.atoms.bind(py).len()
    }

    // --- NumPy array views ---
    //
    // Each method materialises a fresh contiguous f64 ndarray sized
    // [N, 3] (coords / velocities / forces) or [N] (energies). NumPy
    // arrays since 1.22 implement `__dlpack__`, so the returned
    // arrays are zero-copy interoperable with torch / jax / cupy via
    // `torch.from_dlpack(frame.coords_array())` etc.

    /// Returns the per-atom xyz positions as a contiguous numpy
    /// `[N, 3] float64` array, in the type-grouped order used by the
    /// underlying frame.
    ///
    /// Always allocates a **fresh** array from the current Python atom list so
    /// in-place mutation of a previous return value cannot corrupt later
    /// calls, and edits to `atoms` are reflected immediately.
    fn coords_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyArray2<f64>>> {
        let atoms = self.py_atoms(py)?;
        let mut data: Vec<f64> = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            data.extend_from_slice(&[atom.x, atom.y, atom.z]);
        }
        let array = Array2::from_shape_vec((atoms.len(), 3), data)
            .map_err(|e| PyValueError::new_err(format!("coords_array shape error: {e}")))?;
        Ok(array.into_pyarray(py))
    }

    /// Returns the per-atom velocity vectors as a contiguous numpy
    /// `[N, 3] float64` array. Returns `None` if the frame has no
    /// velocity data.
    fn velocities_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.first().is_some_and(PyAtomDatum::has_velocity) {
            return Ok(None);
        }
        let mut data: Vec<f64> = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            data.push(atom.vx.unwrap_or(0.0));
            data.push(atom.vy.unwrap_or(0.0));
            data.push(atom.vz.unwrap_or(0.0));
        }
        let array = Array2::from_shape_vec((atoms.len(), 3), data)
            .map_err(|e| PyValueError::new_err(format!("velocities_array shape error: {e}")))?;
        Ok(Some(array.into_pyarray(py)))
    }

    /// Returns the per-atom force vectors as a contiguous numpy
    /// `[N, 3] float64` array. Returns `None` if the frame has no
    /// force data.
    fn forces_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.first().is_some_and(PyAtomDatum::has_forces) {
            return Ok(None);
        }
        let mut data: Vec<f64> = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            data.push(atom.fx.unwrap_or(0.0));
            data.push(atom.fy.unwrap_or(0.0));
            data.push(atom.fz.unwrap_or(0.0));
        }
        let array = Array2::from_shape_vec((atoms.len(), 3), data)
            .map_err(|e| PyValueError::new_err(format!("forces_array shape error: {e}")))?;
        Ok(Some(array.into_pyarray(py)))
    }

    /// Returns the per-atom energy contributions as a contiguous
    /// numpy `[N] float64` array. Returns `None` if the frame has no
    /// per-atom energies (only a frame-total energy in metadata).
    fn energies_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray1<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.first().is_some_and(PyAtomDatum::has_energy) {
            return Ok(None);
        }
        let data: Vec<f64> = atoms
            .iter()
            .map(|atom| atom.energy.unwrap_or(0.0))
            .collect();
        Ok(Some(data.into_pyarray(py)))
    }

    /// Returns the per-atom atomic numbers as a numpy `[N] uint64`
    /// array, useful for filtering / one-hot encoding workflows.
    fn atom_ids_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyArray1<u64>>> {
        let atoms = self.py_atoms(py)?;
        let data: Vec<u64> = atoms.iter().map(|a| a.atom_id).collect();
        Ok(data.into_pyarray(py))
    }

    // --- atom_id index ---

    /// Returns the position of an atom in the frame's atom list whose
    /// `atom_id` equals the given id, or None if no such atom exists.
    ///
    /// O(N) per call. For repeated lookups, build a dict once with
    /// `build_atom_id_index()` and look up there.
    fn atom_index_by_id(&self, py: Python<'_>, atom_id: u64) -> PyResult<Option<usize>> {
        Ok(self
            .py_atoms(py)?
            .iter()
            .position(|a| a.atom_id == atom_id))
    }

    /// Builds a fresh `dict[int, int]` mapping `atom_id -> position`
    /// for every atom in the frame.
    fn build_atom_id_index<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (i, atom) in self.py_atoms(py)?.iter().enumerate() {
            dict.set_item(atom.atom_id, i)?;
        }
        Ok(dict)
    }

    // --- Typed metadata accessors ---

    /// Per-frame total energy (from JSON metadata), or None.
    #[getter]
    fn energy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        self.metadata_get_f64(py, meta::ENERGY)
    }

    /// Campaign screening projection (`readcon_core::index_proj`), same fields as
    /// `readcon-db` secondary indexes. Prefer over ad-hoc metadata parsing for corpus work.
    fn index_projection(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        use crate::index_proj::FrameIndexProjection;
        let frame = self.to_con_frame(py)?;
        let p = FrameIndexProjection::from_frame(&frame);
        let dict = PyDict::new(py);
        dict.set_item("n_atoms", p.n_atoms)?;
        dict.set_item("formula", p.formula)?;
        dict.set_item("energy", p.energy)?;
        dict.set_item("fmax", p.fmax)?;
        dict.set_item("total_mass", p.total_mass)?;
        dict.set_item("cell_volume", p.cell_volume)?;
        dict.set_item("sections_mask", p.sections_mask)?;
        dict.set_item("has_forces", p.has_forces)?;
        dict.set_item("has_velocities", p.has_velocities)?;
        dict.set_item("has_energy", p.has_energy)?;
        dict.set_item("symbols", p.symbols)?;
        dict.set_item("species_counts", p.species_counts)?;
        dict.set_item("time", p.time)?;
        dict.set_item("timestep", p.timestep)?;
        dict.set_item("frame_index", p.frame_index)?;
        dict.set_item("neb_bead", p.neb_bead)?;
        dict.set_item("neb_band", p.neb_band)?;
        dict.set_item("charge", p.charge)?;
        dict.set_item("magmom", p.magmom)?;
        if let Some(pbc) = p.pbc {
            dict.set_item("pbc", (pbc[0], pbc[1], pbc[2]))?;
        } else {
            dict.set_item("pbc", py.None())?;
        }
        Ok(dict.into())
    }

    /// Canonical multiset formula (`Cu:2|H:2`) for campaign composition index.
    #[getter]
    fn composition_formula(&self, py: Python<'_>) -> PyResult<String> {
        let frame = self.to_con_frame(py)?;
        Ok(crate::index_proj::frame_composition_formula(&frame))
    }

    /// Sections presence mask: bit0 forces, bit1 velocities, bit2 energies.
    #[getter]
    fn sections_mask(&self, py: Python<'_>) -> PyResult<u8> {
        let frame = self.to_con_frame(py)?;
        Ok(crate::index_proj::sections_present_mask(&frame))
    }

    /// Campaign finite energy (None if missing or non-finite); aligns with readcon-db energy index.
    #[getter]
    fn index_energy(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        let frame = self.to_con_frame(py)?;
        Ok(crate::index_proj::finite_energy(&frame))
    }

    /// Total mass Σ m_i n_i when finite.
    #[getter]
    fn total_mass(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        let frame = self.to_con_frame(py)?;
        Ok(crate::index_proj::frame_total_mass(&frame))
    }

    /// Cell volume when finite.
    #[getter]
    fn cell_volume(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        let frame = self.to_con_frame(py)?;
        Ok(crate::index_proj::frame_cell_volume(&frame))
    }

    /// Max force magnitude when forces present.
    #[getter]
    fn fmax(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        let frame = self.to_con_frame(py)?;
        Ok(crate::index_proj::frame_fmax(&frame))
    }

    /// Atom count for campaign `idx_natoms`.
    #[getter]
    fn index_natoms(&self, py: Python<'_>) -> PyResult<u32> {
        let frame = self.to_con_frame(py)?;
        Ok(frame.atom_data.len() as u32)
    }

    /// Full projection as JSON string (same payload as `rkr_frame_index_projection_json`).
    fn index_projection_json(&self, py: Python<'_>) -> PyResult<String> {
        use crate::index_proj::FrameIndexProjection;
        let frame = self.to_con_frame(py)?;
        let p = FrameIndexProjection::from_frame(&frame);
        let v = serde_json::json!({
            "n_atoms": p.n_atoms,
            "formula": p.formula,
            "energy": p.energy,
            "fmax": p.fmax,
            "total_mass": p.total_mass,
            "cell_volume": p.cell_volume,
            "sections_mask": p.sections_mask,
            "has_forces": p.has_forces,
            "has_velocities": p.has_velocities,
            "has_energy": p.has_energy,
            "symbols": p.symbols,
            "species_counts": p.species_counts.iter().map(|(s,c)| serde_json::json!([s, c])).collect::<Vec<_>>(),
            "time": p.time,
            "timestep": p.timestep,
            "frame_index": p.frame_index,
            "neb_bead": p.neb_bead,
            "neb_band": p.neb_band,
            "charge": p.charge,
            "magmom": p.magmom,
        });
        Ok(v.to_string())
    }

    /// Potential type string (e.g. "EMT"), or None.
    #[getter]
    fn potential_type(&self, py: Python<'_>) -> PyResult<Option<String>> {
        let dict = self.metadata.bind(py);
        let Some(potential) = dict.get_item(meta::POTENTIAL)? else {
            return Ok(None);
        };
        if potential.is_none() {
            return Ok(None);
        }
        let pot_dict = match potential.cast::<PyDict>() {
            Ok(d) => d,
            Err(_) => return Ok(None),
        };
        match pot_dict.get_item("type")? {
            Some(value) if !value.is_none() => Ok(Some(value.extract()?)),
            _ => Ok(None),
        }
    }

    /// Zero-based frame index within a trajectory, or None.
    #[getter]
    fn frame_index(&self, py: Python<'_>) -> PyResult<Option<u64>> {
        self.metadata_get_u64(py, meta::FRAME_INDEX)
    }

    /// Simulation time of this frame, or None.
    #[getter]
    fn time(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        self.metadata_get_f64(py, meta::TIME)
    }

    /// Integration timestep of this frame, or None.
    #[getter]
    fn timestep(&self, py: Python<'_>) -> PyResult<Option<f64>> {
        self.metadata_get_f64(py, meta::TIMESTEP)
    }

    /// Optional frame topology from ``metadata['bonds']`` as a list of
    /// ``(i, j)`` or ``(i, j, order)`` tuples (0-based ``atom_data`` indices).
    /// Empty list when absent. Enables chemfiles bond/angle selection when
    /// the library is built with the ``chemfiles`` feature.
    #[getter]
    fn bonds(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let dict = self.metadata.bind(py);
        let Some(raw) = dict.get_item(meta::BONDS)? else {
            return Ok(Vec::new());
        };
        if raw.is_none() {
            return Ok(Vec::new());
        }
        let arr = match raw.cast::<pyo3::types::PyList>() {
            Ok(a) => a,
            Err(_) => return Ok(Vec::new()),
        };
        let mut out = Vec::with_capacity(arr.len());
        for item in arr.iter() {
            if let Ok(pair) = item.cast::<pyo3::types::PyList>() {
                if pair.len() == 2 {
                    let i: u32 = pair.get_item(0)?.extract()?;
                    let j: u32 = pair.get_item(1)?.extract()?;
                    out.push((i, j).into_pyobject(py)?.into_any().unbind());
                    continue;
                }
            }
            if let Ok(obj) = item.cast::<PyDict>() {
                let i: u32 = obj
                    .get_item("i")?
                    .ok_or_else(|| PyValueError::new_err("bonds entry missing i"))?
                    .extract()?;
                let j: u32 = obj
                    .get_item("j")?
                    .ok_or_else(|| PyValueError::new_err("bonds entry missing j"))?
                    .extract()?;
                if let Some(order_v) = obj.get_item("order")? {
                    if !order_v.is_none() {
                        let order: i32 = order_v.extract()?;
                        out.push((i, j, order).into_pyobject(py)?.into_any().unbind());
                        continue;
                    }
                }
                out.push((i, j).into_pyobject(py)?.into_any().unbind());
                continue;
            }
        }
        Ok(out)
    }

    /// True when ``metadata['bonds']`` is present and non-empty.
    #[getter]
    fn has_bonds(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(!self.bonds(py)?.is_empty())
    }

    /// NEB bead index for this frame, or None.
    #[getter]
    fn neb_bead(&self, py: Python<'_>) -> PyResult<Option<u64>> {
        self.metadata_get_u64(py, meta::NEB_BEAD)
    }

    /// NEB band index for this frame, or None.
    #[getter]
    fn neb_band(&self, py: Python<'_>) -> PyResult<Option<u64>> {
        self.metadata_get_u64(py, meta::NEB_BAND)
    }

    /// Replace metadata from a raw JSON object string.
    ///
    /// The schema is validated up front: malformed entries (e.g. a
    /// non-bool `pbc`, a 3x4 `lattice_vectors`) raise ValueError rather
    /// than silently dropping the value.
    fn set_metadata_json(&mut self, py: Python<'_>, metadata_json: &str) -> PyResult<()> {
        let obj: serde_json::Map<String, serde_json::Value> =
            serde_json::from_str(metadata_json)
                .map_err(|e| PyValueError::new_err(format!("invalid metadata JSON: {e}")))?;
        crate::parser::validate_metadata_schema(&obj)
            .map_err(|e| PyValueError::new_err(format!("invalid metadata: {e}")))?;
        let mut metadata = BTreeMap::new();
        for (key, value) in obj {
            if key == meta::CON_SPEC_VERSION || key == meta::SECTIONS {
                continue;
            }
            metadata.insert(key, value);
        }
        self.metadata = json_map_to_py_dict(py, &metadata)?;
        Ok(())
    }

    /// Set a numeric metadata key.
    fn set_scalar_metadata(&mut self, py: Python<'_>, key: &str, value: f64) -> PyResult<()> {
        let number = Number::from_f64(value)
            .ok_or_else(|| PyValueError::new_err("metadata floats must be finite"))?;
        self.metadata
            .bind(py)
            .set_item(key, json_value_to_py(py, &Value::Number(number))?)?;
        Ok(())
    }

    /// Set a string metadata key.
    fn set_string_metadata(&mut self, py: Python<'_>, key: &str, value: &str) -> PyResult<()> {
        self.metadata.bind(py).set_item(key, value)?;
        Ok(())
    }

    /// Set the per-frame total energy metadata.
    fn set_energy(&mut self, py: Python<'_>, energy: f64) -> PyResult<()> {
        self.set_scalar_metadata(py, meta::ENERGY, energy)
    }

    /// Set the zero-based frame index metadata.
    fn set_frame_index(&mut self, py: Python<'_>, idx: u64) -> PyResult<()> {
        self.metadata.bind(py).set_item(meta::FRAME_INDEX, idx)?;
        Ok(())
    }

    /// Set the simulation time metadata.
    fn set_time(&mut self, py: Python<'_>, time: f64) -> PyResult<()> {
        self.set_scalar_metadata(py, meta::TIME, time)
    }

    /// Set the integration timestep metadata.
    fn set_timestep(&mut self, py: Python<'_>, dt: f64) -> PyResult<()> {
        self.set_scalar_metadata(py, meta::TIMESTEP, dt)
    }

    /// Set the NEB bead index metadata.
    fn set_neb_bead(&mut self, py: Python<'_>, bead: u64) -> PyResult<()> {
        self.metadata.bind(py).set_item(meta::NEB_BEAD, bead)?;
        Ok(())
    }

    /// Set the NEB band index metadata.
    fn set_neb_band(&mut self, py: Python<'_>, band: u64) -> PyResult<()> {
        self.metadata.bind(py).set_item(meta::NEB_BAND, band)?;
        Ok(())
    }

    /// Convert this frame to an ASE Atoms object (requires ase package).
    fn to_ase(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        ase_from_pyconframe(py, self)
    }

    /// Create a ConFrame from an ASE Atoms object.
    #[staticmethod]
    fn from_ase(py: Python<'_>, ase_atoms: &Bound<'_, PyAny>) -> PyResult<Self> {
        pyconframe_from_ase(py, ase_atoms)
    }

    /// Chemfiles selection on this frame (see module :func:`select_on_frame`).
    ///
    /// Requires a chemfiles-linked build (``readcon-chemfiles`` / ``--features chemfiles``).
    fn select(&self, py: Python<'_>, selection: &str) -> PyResult<Py<PyAny>> {
        select_on_frame(py, self, selection)
    }

    /// Atom-context chemfiles selection → sorted unique ``atom_data`` indices.
    fn select_atoms(&self, py: Python<'_>, selection: &str) -> PyResult<Vec<usize>> {
        select_atom_indices(py, self, selection)
    }

    /// Write this frame to a CON path (single-frame convenience).
    #[pyo3(signature = (path, *, canonical=false))]
    fn write_con(&self, py: Python<'_>, path: &str, canonical: bool) -> PyResult<()> {
        let frame = self.to_con_frame(py)?;
        let mut writer = ConFrameWriter::from_path(Path::new(path))
            .map_err(|e| PyIOError::new_err(e.to_string()))?
            .canonical(canonical);
        writer
            .write_frame(&frame)
            .map_err(|e| PyIOError::new_err(e.to_string()))?;
        Ok(())
    }
}

impl PyConFrame {
    fn from_con_frame(py: Python<'_>, frame: &ConFrame) -> PyResult<Self> {
        // Build per-atom mass lookup from per-type header data
        let mut per_atom_mass: Vec<f64> = Vec::with_capacity(frame.atom_data.len());
        for (type_idx, &count) in frame.header.natms_per_type.iter().enumerate() {
            let mass = frame
                .header
                .masses_per_type
                .get(type_idx)
                .copied()
                .unwrap_or(0.0);
            for _ in 0..count {
                per_atom_mass.push(mass);
            }
        }

        let atoms: Vec<PyAtomDatum> = frame
            .atom_data
            .iter()
            .enumerate()
            .map(|(i, atom)| {
                let mass = per_atom_mass.get(i).copied().unwrap_or(0.0);
                PyAtomDatum::from_atom_with_mass(atom, mass)
            })
            .collect();

        Ok(PyConFrame {
            cell: frame.header.boxl,
            angles: frame.header.angles,
            prebox_header: [
                frame.header.prebox_header.user.clone(),
                frame.header.prebox_header.metadata_line().to_string(),
            ],
            postbox_header: frame.header.postbox_header.clone(),
            atoms: py_atoms_to_list(py, atoms)?,
            spec_version: frame.header.spec_version,
            metadata: json_map_to_py_dict(py, &frame.header.metadata)?,
        })
    }

    fn py_atoms(&self, py: Python<'_>) -> PyResult<Vec<PyAtomDatum>> {
        self.atoms
            .bind(py)
            .iter()
            .map(|item| {
                item.extract::<PyAtomDatum>().map_err(|_| {
                    PyTypeError::new_err("ConFrame.atoms entries must be readcon.Atom objects")
                })
            })
            .collect()
    }

    fn metadata_map(&self, py: Python<'_>) -> PyResult<BTreeMap<String, Value>> {
        py_metadata_to_json_map(self.metadata.bind(py).as_any())
    }

    /// Extract an `Option<f64>` metadata value directly from the underlying
    /// PyDict, without round-tripping through serde_json::Value.
    fn metadata_get_f64(&self, py: Python<'_>, key: &str) -> PyResult<Option<f64>> {
        let dict = self.metadata.bind(py);
        match dict.get_item(key)? {
            Some(value) if !value.is_none() => Ok(Some(value.extract::<f64>()?)),
            _ => Ok(None),
        }
    }

    /// Extract an `Option<u64>` metadata value directly from the underlying
    /// PyDict, without round-tripping through serde_json::Value.
    fn metadata_get_u64(&self, py: Python<'_>, key: &str) -> PyResult<Option<u64>> {
        let dict = self.metadata.bind(py);
        match dict.get_item(key)? {
            Some(value) if !value.is_none() => Ok(Some(value.extract::<u64>()?)),
            _ => Ok(None),
        }
    }

    fn to_con_frame(&self, py: Python<'_>) -> PyResult<ConFrame> {
        let meta = self.metadata_map(py)?;
        let atoms = self.py_atoms(py)?;

        let mut builder = ConFrameBuilder::new(self.cell, self.angles);
        builder
            .prebox_header(self.prebox_header[0].as_str())
            .postbox_header(self.postbox_header.clone())
            .metadata(meta);

        for py_atom in &atoms {
            let mass = py_atom.mass.unwrap_or(0.0);
            builder.add_atom(
                &py_atom.symbol,
                py_atom.x,
                py_atom.y,
                py_atom.z,
                py_atom.fixed,
                py_atom.atom_id,
                mass,
            );
            if py_atom.has_velocity() {
                builder.with_velocity([
                    py_atom.vx.unwrap_or(0.0),
                    py_atom.vy.unwrap_or(0.0),
                    py_atom.vz.unwrap_or(0.0),
                ]);
            }
            if py_atom.has_forces() {
                builder.with_force([
                    py_atom.fx.unwrap_or(0.0),
                    py_atom.fy.unwrap_or(0.0),
                    py_atom.fz.unwrap_or(0.0),
                ]);
            }
            if let Some(energy) = py_atom.energy {
                builder.with_energy(energy);
            }
        }

        Ok(builder.build())
    }
}

/// Read frames from a .con or .convel file path.
#[pyfunction]
#[pyo3(name = "read_all_frames")]
fn read_all_frames(py: Python<'_>, path: &str) -> PyResult<Vec<PyConFrame>> {
    read_con(py, path)
}

#[pyfunction]
fn read_con(py: Python<'_>, path: &str) -> PyResult<Vec<PyConFrame>> {
    // Release the GIL for file I/O + (optional) Rayon multi-frame parse.
    let path_owned = path.to_owned();
    // `detach` requires Ungil; map errors to String inside the closure.
    let frames = py
        .detach(|| {
            crate::iterators::read_all_frames(Path::new(&path_owned)).map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    frames
        .iter()
        .map(|frame| PyConFrame::from_con_frame(py, frame))
        .collect()
}

/// Read only the first frame from a .con or .convel file path.
#[pyfunction]
fn read_first_frame(py: Python<'_>, path: &str) -> PyResult<PyConFrame> {
    let path_owned = path.to_owned();
    let frame = py
        .detach(|| {
            crate::iterators::read_first_frame(Path::new(&path_owned)).map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    PyConFrame::from_con_frame(py, &frame)
}

/// Read frames from a string containing .con or .convel data.
#[pyfunction]
fn read_con_string(py: Python<'_>, contents: &str) -> PyResult<Vec<PyConFrame>> {
    // Clone so parsing can release the GIL (contents may be a borrowed Py str).
    let owned = contents.to_owned();
    let frames = py
        .detach(|| {
            let iter = ConFrameIterator::new(&owned);
            iter.collect::<Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    frames
        .iter()
        .map(|frame| PyConFrame::from_con_frame(py, frame))
        .collect()
}

/// Streaming frame iterator: parses one frame per `__next__` (does not
/// materialize the full trajectory as `PyConFrame` up front).
#[pyclass(name = "ConFrameIterator")]
struct PyConFrameIterator {
    /// Full file text (owned so the iterator is independent of the caller's path).
    contents: String,
    /// Byte offset of the next frame start within `contents`.
    pos: usize,
}

#[pymethods]
impl PyConFrameIterator {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<PyConFrame>> {
        if self.pos >= self.contents.len() {
            return Ok(None);
        }
        // Skip leading blank lines between frames.
        let bytes = self.contents.as_bytes();
        while self.pos < bytes.len()
            && (bytes[self.pos] == b'\n' || bytes[self.pos] == b'\r' || bytes[self.pos] == b' ')
        {
            self.pos += 1;
        }
        if self.pos >= self.contents.len() {
            return Ok(None);
        }
        let slice = &self.contents[self.pos..];
        let mut iter = ConFrameIterator::new(slice);
        match iter.next_with_raw_span(slice) {
            Some(Ok((frame, span))) => {
                let consumed =
                    (span.as_ptr() as usize).saturating_sub(slice.as_ptr() as usize) + span.len();
                self.pos += consumed;
                Ok(Some(PyConFrame::from_con_frame(py, &frame)?))
            }
            Some(Err(e)) => Err(PyIOError::new_err(format!("parse error: {e}"))),
            None => {
                self.pos = self.contents.len();
                Ok(None)
            }
        }
    }
}

/// Return a **streaming** iterator over frames from a path.
///
/// Prefer this over [`read_all_frames`] when you process frames one at a time:
/// only one `ConFrame` / `PyConFrame` is built per `__next__` call.
#[pyfunction]
fn iter_con(py: Python<'_>, path: &str) -> PyResult<PyConFrameIterator> {
    let path_owned = path.to_owned();
    let text = py
        .detach(|| {
            let contents = crate::compression::read_file_contents(Path::new(&path_owned))
                .map_err(|e| e.to_string())?;
            contents
                .as_str()
                .map(|s| s.to_owned())
                .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    Ok(PyConFrameIterator {
        contents: text,
        pos: 0,
    })
}

/// Count frames without building atom / Python objects (skip walk).
#[pyfunction]
fn count_frames(py: Python<'_>, path: &str) -> PyResult<usize> {
    let path_owned = path.to_owned();
    py.detach(|| {
        crate::iterators::count_frames(Path::new(&path_owned)).map_err(|e| e.to_string())
    })
    .map_err(PyIOError::new_err)
}

/// Write frames to a .con or .convel file path.
///
/// The `compression` argument controls output compression:
/// - `None` (default): auto-detect from extension (.gz = gzip, else uncompressed)
/// - `"gzip"`: force gzip compression
/// - `"none"`: force uncompressed
#[pyfunction]
#[pyo3(signature = (path, frames, precision=6, compression=None, *, canonical=false))]
fn write_con(
    py: Python<'_>,
    path: &str,
    frames: &Bound<'_, PyAny>,
    precision: usize,
    compression: Option<&str>,
    canonical: bool,
) -> PyResult<()> {
    let rust_frames = py_frames_to_rust(py, frames)?;

    let use_gzip = match compression {
        Some("gzip") => true,
        Some("none") => false,
        Some(other) => {
            return Err(PyIOError::new_err(format!(
                "unknown compression: {other}. Use \"gzip\" or \"none\"."
            )));
        }
        None => path.ends_with(".gz"),
    };

    if use_gzip {
        let mut writer = ConFrameWriter::from_path_gzip_with_precision(path, precision)
            .map_err(|e| PyIOError::new_err(format!("failed to create gzip writer: {e}")))?
            .canonical(canonical);
        writer
            .extend(rust_frames.iter())
            .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    } else {
        let mut writer = ConFrameWriter::from_path_with_precision(path, precision)
            .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?
            .canonical(canonical);
        writer
            .extend(rust_frames.iter())
            .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    }
    Ok(())
}

/// Write frames to a string in .con format.
#[pyfunction]
#[pyo3(signature = (frames, precision=6, *, canonical=false))]
fn write_con_string(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    precision: usize,
    canonical: bool,
) -> PyResult<String> {
    let rust_frames = py_frames_to_rust(py, frames)?;
    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, precision).canonical(canonical);
        writer
            .extend(rust_frames.iter())
            .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    }
    String::from_utf8(buffer).map_err(|e| PyIOError::new_err(format!("utf8 error: {e}")))
}

/// Read a .con file and return a list of ASE Atoms objects.
/// Requires the ase package.
#[pyfunction]
fn read_con_as_ase(py: Python<'_>, path: &str) -> PyResult<Vec<Py<PyAny>>> {
    let frames = read_con(py, path)?;
    frames.iter().map(|f| ase_from_pyconframe(py, f)).collect()
}

fn py_frames_to_rust(py: Python<'_>, frames: &Bound<'_, PyAny>) -> PyResult<Vec<ConFrame>> {
    let iterator = PyIterator::from_object(frames)?;
    let mut rust_frames = Vec::new();
    for item in iterator {
        let item = item?;
        let frame = item.extract::<PyRef<'_, PyConFrame>>().map_err(|_| {
            PyTypeError::new_err("frames must be an iterable of readcon.ConFrame objects")
        })?;
        rust_frames.push(frame.to_con_frame(py)?);
    }
    Ok(rust_frames)
}

// --- ASE conversion helpers (runtime import, no compile-time dep) ---

fn ase_from_pyconframe(py: Python<'_>, frame: &PyConFrame) -> PyResult<Py<PyAny>> {
    let ase = py.import("ase")?;
    let ase_atoms_cls = ase.getattr("Atoms")?;
    let frame_atoms = frame.py_atoms(py)?;

    // Build symbols list and positions array
    let symbols: Vec<&str> = frame_atoms.iter().map(|a| a.symbol.as_str()).collect();
    let positions: Vec<[f64; 3]> = frame_atoms.iter().map(|a| [a.x, a.y, a.z]).collect();

    // Build cell from lengths + angles using ASE's cellpar_to_cell
    let cellpar: Vec<f64> = frame
        .cell
        .iter()
        .chain(frame.angles.iter())
        .copied()
        .collect();

    let ase_cell_mod = py.import("ase.geometry.cell")?;
    let cell = ase_cell_mod.getattr("cellpar_to_cell")?.call1((cellpar,))?;

    let atoms = ase_atoms_cls.call(
        (),
        Some(
            &[
                ("symbols", symbols.into_pyobject(py)?.into_any()),
                ("positions", positions.into_pyobject(py)?.into_any()),
                ("cell", cell.into_any()),
                ("pbc", true.into_pyobject(py)?.to_owned().into_any()),
            ]
            .into_py_dict(py)?,
        ),
    )?;

    let np = py.import("numpy")?;

    // Store atom_id as a custom per-atom array (not tags, which may be in use)
    let atom_ids: Vec<u64> = frame_atoms.iter().map(|a| a.atom_id).collect();
    let atom_id_array = np.call_method1("array", (atom_ids,))?;
    atoms.call_method1("set_array", ("atom_id", atom_id_array))?;

    // Set masses if present (overrides ASE's atomic-number defaults)
    if frame_atoms.iter().any(|a| a.mass.is_some()) {
        let masses: Vec<f64> = frame_atoms.iter().map(|a| a.mass.unwrap_or(0.0)).collect();
        let mass_array = np.call_method1("array", (masses,))?;
        atoms.call_method1("set_masses", (mass_array,))?;
    }

    // Set velocities if present
    if frame.has_velocities(py)? {
        let velocities: Vec<[f64; 3]> = frame_atoms
            .iter()
            .map(|a| {
                [
                    a.vx.unwrap_or(0.0),
                    a.vy.unwrap_or(0.0),
                    a.vz.unwrap_or(0.0),
                ]
            })
            .collect();
        let vel_array = np.call_method1("array", (velocities,))?;
        atoms.call_method1("set_velocities", (vel_array,))?;
    }

    // Set forces via SinglePointCalculator if present
    if frame.has_forces(py)? {
        let ase_calc = py.import("ase.calculators.singlepoint")?;
        let forces: Vec<[f64; 3]> = frame_atoms
            .iter()
            .map(|a| {
                [
                    a.fx.unwrap_or(0.0),
                    a.fy.unwrap_or(0.0),
                    a.fz.unwrap_or(0.0),
                ]
            })
            .collect();
        let force_array = np.call_method1("array", (forces,))?;
        // Get energy from metadata if present
        let energy = frame.energy(py)?;
        let calc = if let Some(e) = energy {
            ase_calc
                .getattr("SinglePointCalculator")?
                .call1((atoms.clone(), e, force_array))?
        } else {
            ase_calc.getattr("SinglePointCalculator")?.call(
                (),
                Some(
                    &[
                        ("atoms", atoms.clone().into_any()),
                        ("forces", force_array.into_any()),
                    ]
                    .into_py_dict(py)?,
                ),
            )?
        };
        atoms.setattr("calc", calc)?;
    }

    // Preserve all-fixed atoms and per-axis masks as native ASE constraints.
    let fixed_indices: Vec<usize> = frame_atoms
        .iter()
        .enumerate()
        .filter(|(_, a)| a.fixed == [true, true, true])
        .map(|(i, _)| i)
        .collect();

    let partial_fixed: Vec<(usize, [bool; 3])> = frame_atoms
        .iter()
        .enumerate()
        .filter(|(_, a)| a.is_fixed() && a.fixed != [true, true, true])
        .map(|(i, a)| (i, a.fixed))
        .collect();

    if !fixed_indices.is_empty() || !partial_fixed.is_empty() {
        let ase_constraints = py.import("ase.constraints")?;
        let mut constraints: Vec<Py<PyAny>> = Vec::new();
        if !fixed_indices.is_empty() {
            let fix_atoms = ase_constraints.getattr("FixAtoms")?.call(
                (),
                Some(&[("indices", fixed_indices.into_pyobject(py)?.into_any())].into_py_dict(py)?),
            )?;
            constraints.push(fix_atoms.unbind());
        }
        for (index, mask) in partial_fixed {
            let fix_cartesian = ase_constraints
                .getattr("FixCartesian")?
                .call1((index, mask))?;
            constraints.push(fix_cartesian.unbind());
        }
        atoms.call_method1("set_constraint", (constraints,))?;
    }

    Ok(atoms.unbind())
}

fn py_usize_values(obj: &Bound<'_, PyAny>) -> PyResult<Vec<usize>> {
    if let Ok(list) = obj.call_method0("tolist") {
        if let Ok(values) = list.extract::<Vec<usize>>() {
            return Ok(values);
        }
        if let Ok(value) = list.extract::<usize>() {
            return Ok(vec![value]);
        }
    }
    if let Ok(values) = obj.extract::<Vec<usize>>() {
        return Ok(values);
    }
    if let Ok(value) = obj.extract::<usize>() {
        return Ok(vec![value]);
    }
    Err(PyValueError::new_err(
        "constraint index must be an integer or sequence",
    ))
}

fn py_bool_mask(obj: &Bound<'_, PyAny>) -> PyResult<[bool; 3]> {
    let values: Vec<bool> = if let Ok(list) = obj.call_method0("tolist") {
        list.extract()?
    } else {
        obj.extract()?
    };
    if values.len() != 3 {
        return Err(PyValueError::new_err("constraint mask must have length 3"));
    }
    Ok([values[0], values[1], values[2]])
}

fn pyconframe_from_ase(py: Python<'_>, ase_atoms: &Bound<'_, PyAny>) -> PyResult<PyConFrame> {
    // Extract symbols
    let symbols: Vec<String> = ase_atoms.call_method0("get_chemical_symbols")?.extract()?;

    // Extract positions
    let positions: Vec<Vec<f64>> = ase_atoms
        .call_method0("get_positions")?
        .call_method0("tolist")?
        .extract()?;

    // Extract cell parameters (lengths + angles)
    let cell_obj = ase_atoms.call_method0("get_cell")?;
    let cellpar: Vec<f64> = cell_obj
        .call_method0("cellpar")?
        .call_method0("tolist")?
        .extract()?;

    let cell = [cellpar[0], cellpar[1], cellpar[2]];
    let angles = [cellpar[3], cellpar[4], cellpar[5]];

    // Extract fixed atom info from constraints
    let n_atoms = symbols.len();
    let constraints = ase_atoms.getattr("constraints")?;
    let constraints_list: Vec<Bound<'_, PyAny>> = constraints.extract()?;
    let mut fixed_masks = vec![[false, false, false]; n_atoms];

    for constraint in &constraints_list {
        let type_name = constraint
            .getattr("__class__")?
            .getattr("__name__")?
            .extract::<String>()?;
        if type_name == "FixAtoms" {
            let index_obj = constraint.getattr("index")?;
            for index in py_usize_values(&index_obj)? {
                if let Some(mask) = fixed_masks.get_mut(index) {
                    *mask = [true, true, true];
                }
            }
        } else if type_name == "FixCartesian" {
            let index_obj = constraint.getattr("index")?;
            let mask_obj = constraint.getattr("mask")?;
            let mask = py_bool_mask(&mask_obj)?;
            for index in py_usize_values(&index_obj)? {
                if let Some(fixed_mask) = fixed_masks.get_mut(index) {
                    *fixed_mask = mask;
                }
            }
        }
    }

    // Extract masses from ASE (optional, may not be set)
    let masses: Option<Vec<f64>> = ase_atoms
        .call_method0("get_masses")
        .ok()
        .and_then(|m| m.call_method0("tolist").ok())
        .and_then(|m| m.extract().ok());

    // Extract atom_id: prefer custom array, fall back to tags, then sequential
    let atom_ids: Vec<u64> = if let Ok(arr) = ase_atoms.call_method1("get_array", ("atom_id",)) {
        arr.call_method0("tolist")?
            .extract::<Vec<i64>>()?
            .into_iter()
            .map(|v| v as u64)
            .collect()
    } else if let Ok(tags_obj) = ase_atoms.call_method0("get_tags") {
        let tags: Vec<i64> = tags_obj
            .call_method0("tolist")
            .ok()
            .and_then(|t| t.extract().ok())
            .unwrap_or_default();
        if tags.iter().any(|&t| t != 0) {
            tags.into_iter().map(|t| t as u64).collect()
        } else {
            (0..n_atoms).map(|i| i as u64).collect()
        }
    } else {
        (0..n_atoms).map(|i| i as u64).collect()
    };

    // Extract velocities from ASE (None if not set or all zero)
    let velocities: Option<Vec<Vec<f64>>> = ase_atoms
        .call_method0("get_velocities")
        .ok()
        .and_then(|v| {
            // get_velocities() returns None when not set
            if v.is_none() {
                return None;
            }
            v.call_method0("tolist").ok()
        })
        .and_then(|v| v.extract().ok());

    let has_velocities = velocities
        .as_ref()
        .is_some_and(|vels| vels.iter().any(|v| v.iter().any(|&c| c != 0.0)));

    // Extract forces from ASE (via calculator results, None if no calculator)
    let forces: Option<Vec<Vec<f64>>> = ase_atoms
        .call_method0("get_forces")
        .ok()
        .and_then(|f| {
            if f.is_none() {
                return None;
            }
            f.call_method0("tolist").ok()
        })
        .and_then(|f| f.extract().ok());

    let has_forces = forces.as_ref().is_some_and(|frc| !frc.is_empty());

    // Build PyAtomDatum list
    let atoms: Vec<PyAtomDatum> = symbols
        .iter()
        .zip(positions.iter())
        .enumerate()
        .map(|(i, (sym, pos))| {
            let (vx, vy, vz) = if has_velocities {
                let v = &velocities.as_ref().unwrap()[i];
                (Some(v[0]), Some(v[1]), Some(v[2]))
            } else {
                (None, None, None)
            };
            let (fx, fy, fz) = if has_forces {
                let f = &forces.as_ref().unwrap()[i];
                (Some(f[0]), Some(f[1]), Some(f[2]))
            } else {
                (None, None, None)
            };
            PyAtomDatum {
                symbol: sym.clone(),
                x: pos[0],
                y: pos[1],
                z: pos[2],
                fixed: fixed_masks[i],
                atom_id: atom_ids[i],
                mass: masses.as_ref().map(|m| m[i]),
                vx,
                vy,
                vz,
                fx,
                fy,
                fz,
                energy: None,
            }
        })
        .collect();

    Ok(PyConFrame {
        cell,
        angles,
        prebox_header: Default::default(),
        postbox_header: Default::default(),
        atoms: py_atoms_to_list(py, atoms)?,
        spec_version: crate::CON_SPEC_VERSION,
        metadata: PyDict::new(py).unbind(),
    })
}

/// readcon Python module implemented in Rust.
#[pymodule]
fn readcon(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("CON_SPEC_VERSION", crate::CON_SPEC_VERSION)?;
    m.add_class::<PyAtomDatum>()?;
    m.add_class::<PyConFrame>()?;
    m.add_class::<PyConFrameIterator>()?;
    m.add_function(wrap_pyfunction!(read_con, m)?)?;
    // Ergonomic alias for multi-language matrix (batch all frames).
    m.add_function(wrap_pyfunction!(read_all_frames, m)?)?;
    m.add_function(wrap_pyfunction!(read_first_frame, m)?)?;
    m.add_function(wrap_pyfunction!(iter_con, m)?)?;
    m.add_function(wrap_pyfunction!(count_frames, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(write_con, m)?)?;
    m.add_function(wrap_pyfunction!(write_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_as_ase, m)?)?;
    m.add_function(wrap_pyfunction!(has_chemfiles_support, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles_first, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles_memory, m)?)?;
    m.add_function(wrap_pyfunction!(select_on_frame, m)?)?;
    m.add_function(wrap_pyfunction!(select_atom_indices, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_selection_on_frames, m)?)?;
    m.add_function(wrap_pyfunction!(select_atom_positions_on_frames, m)?)?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Chemfiles import + selection (always registered; stubs if built without feature)
// ---------------------------------------------------------------------------

/// True when this extension was built with the Rust ``chemfiles`` feature
/// (links libchemfiles). Lean ``readcon`` wheels return False; use
/// ``readcon-chemfiles`` on PyPI (or a source build with the feature).
#[pyfunction]
fn has_chemfiles_support() -> bool {
    crate::chemfiles_import::chemfiles_enabled()
}

fn chemfiles_err_to_py(e: crate::chemfiles_import::ChemfilesImportError) -> PyErr {
    use crate::chemfiles_import::ChemfilesImportError;
    match e {
        ChemfilesImportError::FeatureDisabled => {
            pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
        }
        ChemfilesImportError::Io(io) => PyIOError::new_err(io.to_string()),
        ChemfilesImportError::InvalidFrame(msg) => PyValueError::new_err(msg),
        #[cfg(feature = "chemfiles")]
        ChemfilesImportError::Chemfiles(ch) => PyValueError::new_err(format!("chemfiles: {ch}")),
    }
}

fn selection_result_to_py(
    py: Python<'_>,
    result: crate::chemfiles_selection::SelectionResult,
) -> PyResult<Py<PyAny>> {
    let matches: Vec<Vec<usize>> = result
        .matches
        .iter()
        .map(|m| m.indices().to_vec())
        .collect();
    let primary: Vec<usize> = result.primary_indices();
    let dict = PyDict::new(py);
    dict.set_item("selection", result.selection)?;
    dict.set_item("context_size", result.context_size)?;
    dict.set_item("matches", matches)?;
    dict.set_item("primary_indices", primary)?;
    Ok(dict.into())
}

/// Read **all** frames from a chemfiles-supported path (XYZ, PDB, GRO, …)
/// into CON :class:`ConFrame` values.
///
/// This is the Python entry point for **format conversion into CON**: chemfiles
/// chooses the reader from the path; topology becomes optional
/// ``metadata['bonds']`` when present.
///
/// Raises ``RuntimeError`` if this wheel was built without chemfiles (install
/// ``readcon-chemfiles``), ``OSError`` on I/O failure, ``ValueError`` on bad frames.
#[pyfunction]
fn read_chemfiles(py: Python<'_>, path: &str) -> PyResult<Vec<PyConFrame>> {
    use crate::chemfiles_import::con_frames_from_trajectory_path;
    let frames = con_frames_from_trajectory_path(Path::new(path)).map_err(chemfiles_err_to_py)?;
    frames
        .iter()
        .map(|f| PyConFrame::from_con_frame(py, f))
        .collect()
}

/// Read the **first** frame only from a chemfiles-supported path.
///
/// Prefer this for single-structure XYZ/PDB/GRO files.
#[pyfunction]
fn read_chemfiles_first(py: Python<'_>, path: &str) -> PyResult<PyConFrame> {
    use crate::chemfiles_import::con_frame_from_trajectory_path;
    let frame = con_frame_from_trajectory_path(Path::new(path)).map_err(chemfiles_err_to_py)?;
    PyConFrame::from_con_frame(py, &frame)
}

/// Read all frames from an in-memory trajectory buffer.
///
/// ``format`` is a chemfiles format name such as ``"XYZ"``, ``"PDB"``, or ``"GRO"``.
#[pyfunction]
fn read_chemfiles_memory(py: Python<'_>, data: &str, format: &str) -> PyResult<Vec<PyConFrame>> {
    use crate::chemfiles_import::con_frames_from_memory;
    let frames = con_frames_from_memory(data, format).map_err(chemfiles_err_to_py)?;
    frames
        .iter()
        .map(|f| PyConFrame::from_con_frame(py, f))
        .collect()
}

/// Evaluate a chemfiles selection string on a `ConFrame` (module-level).
///
/// Prefer :meth:`ConFrame.select` for idiomatic method-call style.
///
/// Returns a dict with keys:
/// - `selection`: str
/// - `context_size`: int (1=atom, 2=pair, ...)
/// - `matches`: list[list[int]] each inner list has 1-4 atom indices
/// - `primary_indices`: list[int] first atom of each match
#[pyfunction]
fn select_on_frame(py: Python<'_>, frame: &PyConFrame, selection: &str) -> PyResult<Py<PyAny>> {
    use crate::chemfiles_selection::evaluate_selection_on_con_frame;
    let rust_frame = frame.to_con_frame(py)?;
    let result =
        evaluate_selection_on_con_frame(selection, &rust_frame).map_err(chemfiles_err_to_py)?;
    selection_result_to_py(py, result)
}

/// Atom-context selection: sorted unique atom indices (e.g. ``name O``).
///
/// Prefer :meth:`ConFrame.select_atoms` for idiomatic method-call style.
#[pyfunction]
fn select_atom_indices(py: Python<'_>, frame: &PyConFrame, selection: &str) -> PyResult<Vec<usize>> {
    use crate::chemfiles_selection::select_atom_indices as rust_select;
    let rust_frame = frame.to_con_frame(py)?;
    rust_select(selection, &rust_frame).map_err(chemfiles_err_to_py)
}

fn multi_frame_selection_to_py(
    py: Python<'_>,
    multi: crate::chemfiles_selection::MultiFrameSelectionResult,
) -> PyResult<Py<PyAny>> {
    let frames_list = PyList::empty(py);
    for slice in multi.frames {
        let result_dict = selection_result_to_py(py, slice.result)?;
        let positions: Vec<Vec<f64>> = slice
            .positions
            .iter()
            .map(|p| vec![p[0], p[1], p[2]])
            .collect();
        let frame_dict = PyDict::new(py);
        frame_dict.set_item("frame_index", slice.frame_index)?;
        frame_dict.set_item("result", result_dict)?;
        frame_dict.set_item("atom_indices", slice.atom_indices)?;
        frame_dict.set_item("positions", positions)?;
        frames_list.append(frame_dict)?;
    }
    let dict = PyDict::new(py);
    dict.set_item("selection", multi.selection)?;
    dict.set_item("frames", frames_list)?;
    Ok(dict.into())
}

fn py_frames_to_con(py: Python<'_>, frames: &Bound<'_, PyAny>) -> PyResult<Vec<ConFrame>> {
    let seq = frames.extract::<Vec<PyRef<'_, PyConFrame>>>()?;
    seq.iter()
        .map(|f| f.to_con_frame(py))
        .collect()
}

/// Evaluate a chemfiles selection on **each** frame (trajectory-safe).
///
/// For atom-context selections, each frame entry includes ``atom_indices`` and
/// ``positions`` (xyz of selected atoms on that frame) so callers can collect
/// e.g. hydrogen trajectories without re-selecting in Python.
///
/// Returns ``{"selection": str, "frames": [{"frame_index", "result", "atom_indices", "positions"}, ...]}``.
#[pyfunction]
fn evaluate_selection_on_frames(
    py: Python<'_>,
    selection: &str,
    frames: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    use crate::chemfiles_selection::evaluate_selection_on_frames as rust_eval;
    let rust_frames = py_frames_to_con(py, frames)?;
    let multi = rust_eval(selection, &rust_frames).map_err(chemfiles_err_to_py)?;
    multi_frame_selection_to_py(py, multi)
}

/// Atom-context multi-frame selection: positions of selected atoms per frame.
///
/// Errors if the selection is not atom context (size 1) on the first frame.
/// Typical use::
///
///     frames = readcon.read_all_frames("traj.con")
///     out = readcon.select_atom_positions_on_frames("name H", frames)
///     # out["frames"][i]["positions"] — H xyz on frame i
#[pyfunction]
fn select_atom_positions_on_frames(
    py: Python<'_>,
    selection: &str,
    frames: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    use crate::chemfiles_selection::select_atom_positions_on_frames as rust_sel;
    let rust_frames = py_frames_to_con(py, frames)?;
    let multi = rust_sel(selection, &rust_frames).map_err(chemfiles_err_to_py)?;
    multi_frame_selection_to_py(py, multi)
}

