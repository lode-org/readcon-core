use ndarray::{Array2, Array3, ArrayView2};
use numpy::{
    IntoPyArray, PyArray1, PyArray2, PyArray3, PyArrayMethods, PyReadonlyArray2, PyReadonlyArray3,
};
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
    #[pyo3(get, set)]
    pub charge: Option<f64>,
    #[pyo3(get, set)]
    pub spin: Option<f64>,
    #[pyo3(get, set)]
    pub mx: Option<f64>,
    #[pyo3(get, set)]
    pub my: Option<f64>,
    #[pyo3(get, set)]
    pub mz: Option<f64>,
    /// Displacement vector components (Angstrom); populated when the file
    /// declares a `"displacements"` section.
    #[pyo3(get, set)]
    pub dx: Option<f64>,
    #[pyo3(get, set)]
    pub dy: Option<f64>,
    #[pyo3(get, set)]
    pub dz: Option<f64>,
    /// Root-mean-square spread components (Angstrom) about `x`, `y`, `z`; populated when the file
    /// declares a `"spreads"` section.
    #[pyo3(get, set)]
    pub sx: Option<f64>,
    #[pyo3(get, set)]
    pub sy: Option<f64>,
    #[pyo3(get, set)]
    pub sz: Option<f64>,
}

#[pymethods]
impl PyAtomDatum {
    #[new]
    #[pyo3(signature = (symbol, x, y, z, fixed=None, atom_id=0, mass=None, vx=None, vy=None, vz=None, fx=None, fy=None, fz=None, energy=None, charge=None, spin=None, mx=None, my=None, mz=None, dx=None, dy=None, dz=None, sx=None, sy=None, sz=None))]
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
        charge: Option<f64>,
        spin: Option<f64>,
        mx: Option<f64>,
        my: Option<f64>,
        mz: Option<f64>,
        dx: Option<f64>,
        dy: Option<f64>,
        dz: Option<f64>,
        sx: Option<f64>,
        sy: Option<f64>,
        sz: Option<f64>,
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
            charge,
            spin,
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

    #[getter]
    fn has_displacement(&self) -> bool {
        self.dx.is_some() && self.dy.is_some() && self.dz.is_some()
    }

    #[getter]
    fn has_spread(&self) -> bool {
        self.sx.is_some() && self.sy.is_some() && self.sz.is_some()
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
        let (vx, vy, vz) = match atom.velocity() {
            Some([x, y, z]) => (Some(x), Some(y), Some(z)),
            None => (None, None, None),
        };
        let (fx, fy, fz) = match atom.force() {
            Some([x, y, z]) => (Some(x), Some(y), Some(z)),
            None => (None, None, None),
        };
        let (mx, my, mz) = match atom.magmom() {
            Some([x, y, z]) => (Some(x), Some(y), Some(z)),
            None => (None, None, None),
        };
        let (dx, dy, dz) = match atom.displacement() {
            Some([x, y, z]) => (Some(x), Some(y), Some(z)),
            None => (None, None, None),
        };
        let (sx, sy, sz) = match atom.spread() {
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
            energy: atom.energy(),
            charge: atom.charge(),
            spin: atom.spin(),
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
    /// Parsed frames leave this false and fill `atoms` on first use.
    /// `xyz` reads `inner` and does not build the Python atom list.
    atoms_ready: std::sync::atomic::AtomicBool,
    #[pyo3(get)]
    pub spec_version: u32,
    metadata: Py<PyDict>,
    /// Rust SoA when this frame came from the parser. The positions
    /// column is empty: coordinates live in `xyz_owned` or in `slab`.
    inner: Option<ConFrame>,
    n_atoms: usize,
    /// One `[frames, N, 3]` array shared by every frame of a read.
    slab: Option<Py<PyArray3<f64>>>,
    slab_index: usize,
    /// Coordinates of a frame that was not part of a shared read.
    xyz_owned: Option<Py<PyArray2<f64>>>,
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
            atoms_ready: std::sync::atomic::AtomicBool::new(true),
            metadata,
            inner: None,
            n_atoms: 0,
            slab: None,
            slab_index: 0,
            xyz_owned: None,
        })
    }

    #[getter]
    fn atoms(&self, py: Python<'_>) -> PyResult<Py<PyList>> {
        self.ensure_atoms(py)?;
        Ok(self.atoms.clone_ref(py))
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
        self.has_vector_section(py, true)
    }

    #[getter]
    fn has_forces(&self, py: Python<'_>) -> PyResult<bool> {
        self.has_vector_section(py, false)
    }

    #[getter]
    fn has_displacements(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self
            .py_atoms(py)?
            .first()
            .is_some_and(PyAtomDatum::has_displacement))
    }

    #[getter]
    fn has_spreads(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self
            .py_atoms(py)?
            .first()
            .is_some_and(PyAtomDatum::has_spread))
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let natoms = self.atom_count(py);
        Ok(format!(
            "ConFrame(cell={:?}, angles={:?}, natoms={}, has_velocities={})",
            self.cell,
            self.angles,
            natoms,
            self.has_velocities(py)?
        ))
    }

    fn __len__(&self, py: Python<'_>) -> usize {
        self.atom_count(py)
    }

    /// Atoms in file order. The file cursor is `iter_con`, not this.
    fn __iter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyIterator>> {
        self.ensure_atoms(py)?;
        self.atoms.bind(py).try_iter()
    }

    fn __getitem__<'py>(&self, py: Python<'py>, index: isize) -> PyResult<Bound<'py, PyAny>> {
        self.ensure_atoms(py)?;
        let atoms = self.atoms.bind(py);
        let n = atoms.len() as isize;
        let resolved = if index < 0 { n + index } else { index };
        if resolved < 0 || resolved >= n {
            return Err(pyo3::exceptions::PyIndexError::new_err(
                "atom index out of range",
            ));
        }
        atoms.get_item(resolved as usize)
    }

    // --- NumPy array views ---
    //
    // Each method materialises a fresh contiguous f64 ndarray sized
    // [N, 3] (coords / velocities / forces) or [N] (energies). NumPy
    // arrays since 1.22 implement `__dlpack__`, so the returned
    // arrays are zero-copy interoperable with torch / jax / cupy via
    // `torch.from_dlpack(frame.coords_array())` etc.

    /// Coordinates as a numpy `[N, 3] float64` view.
    ///
    /// A frame from `read_con` views one row of the trajectory slab.
    /// A later read of `xyz` returns that same view. `coords_array()`
    /// still walks `.atoms` so in-place Atom edits show up.
    #[getter]
    fn xyz<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray2<f64>>> {
        if let Some(slab) = &self.slab {
            let item = slab.bind(py).get_item(self.slab_index)?;
            return Ok(item.cast::<PyArray2<f64>>()?.clone());
        }
        if let Some(owned) = &self.xyz_owned {
            return Ok(owned.bind(py).clone());
        }
        self.coords_array(py)
    }

    #[getter]
    fn vel<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        if let Some(frame) = self.inner.as_ref() {
            if frame.velocities.nrows() == 0 {
                return Ok(None);
            }
            return Ok(Some(array2_from_storage(py, &frame.velocities)?));
        }
        self.velocities_array(py)
    }

    #[getter]
    fn frc<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        if let Some(frame) = self.inner.as_ref() {
            if frame.forces.nrows() == 0 {
                return Ok(None);
            }
            return Ok(Some(array2_from_storage(py, &frame.forces)?));
        }
        self.forces_array(py)
    }

    /// Returns the per-atom xyz positions as a contiguous numpy
    /// `[N, 3] float64` array, in the type-grouped order used by the
    /// underlying frame.
    ///
    /// Allocates a **fresh** array. Before `.atoms` is built, the values
    /// are copied once from the coordinate slab or the parsed SoA. After
    /// that, the copy walks the Python atoms so edits show up, and
    /// mutating a previous return value does not affect the next call.
    fn coords_array<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray2<f64>>> {
        if !self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            if let Some(copied) = self.copy_positions(py)? {
                return Ok(copied);
            }
        }
        let atoms = self.py_atoms(py)?;
        let mut data: Vec<f64> = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            data.extend_from_slice(&[atom.x, atom.y, atom.z]);
        }
        array2_from_f64(py, atoms.len(), 3, data)
    }

    /// Returns the per-atom velocity vectors as a contiguous numpy
    /// `[N, 3] float64` array. Returns `None` if the frame has no
    /// velocity data.
    fn velocities_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        self.vector_section_array(py, true)
    }

    /// Returns the per-atom force vectors as a contiguous numpy
    /// `[N, 3] float64` array. Returns `None` if the frame has no
    /// force data.
    fn forces_array<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        self.vector_section_array(py, false)
    }

    /// Returns the per-atom displacements (Angstrom) as a contiguous
    /// numpy `[N, 3] float64` array, or `None` when the frame declares no
    /// `"displacements"` section. A normal mode, a dimer direction.
    fn displacements_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.first().is_some_and(PyAtomDatum::has_displacement) {
            return Ok(None);
        }
        let mut data: Vec<f64> = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            data.push(atom.dx.unwrap_or(0.0));
            data.push(atom.dy.unwrap_or(0.0));
            data.push(atom.dz.unwrap_or(0.0));
        }
        let array = Array2::from_shape_vec((atoms.len(), 3), data)
            .map_err(|e| PyValueError::new_err(format!("displacements_array shape error: {e}")))?;
        Ok(Some(array.into_pyarray(py)))
    }

    /// `[N, 3]` displacements, or `None`; the same array as
    /// `displacements_array()`.
    #[getter]
    fn disp<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        self.displacements_array(py)
    }

    /// Returns the per-atom root-mean-square spreads (Angstrom) about the
    /// written coordinates as a contiguous numpy `[N, 3] float64` array,
    /// or `None` when the frame declares no `"spreads"` section.
    fn spreads_array<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.first().is_some_and(PyAtomDatum::has_spread) {
            return Ok(None);
        }
        let mut data: Vec<f64> = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            data.push(atom.sx.unwrap_or(0.0));
            data.push(atom.sy.unwrap_or(0.0));
            data.push(atom.sz.unwrap_or(0.0));
        }
        let array = Array2::from_shape_vec((atoms.len(), 3), data)
            .map_err(|e| PyValueError::new_err(format!("spreads_array shape error: {e}")))?;
        Ok(Some(array.into_pyarray(py)))
    }

    /// `[N, 3]` spreads, or `None`; the same array as
    /// `spreads_array()`.
    #[getter]
    fn spread<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        self.spreads_array(py)
    }

    /// Returns the per-atom energy contributions as a contiguous
    /// numpy `[N] float64` array. Returns `None` if the frame has no
    /// per-atom energies (only a frame-total energy in metadata).
    fn energies_array<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray1<f64>>>> {
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
    fn atom_ids_array<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<u64>>> {
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
        Ok(self.py_atoms(py)?.iter().position(|a| a.atom_id == atom_id))
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
    fn atom_count(&self, py: Python<'_>) -> usize {
        if self.n_atoms > 0 {
            return self.n_atoms;
        }
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            return self.atoms.bind(py).len();
        }
        self.inner
            .as_ref()
            .map(|frame| frame.atom_data.len())
            .unwrap_or(0)
    }

    fn has_vector_section(&self, py: Python<'_>, velocity: bool) -> PyResult<bool> {
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            let atoms = self.atoms.bind(py);
            if atoms.is_empty() {
                return Ok(false);
            }
            let first = atoms.get_item(0)?.extract::<PyAtomDatum>()?;
            return Ok(if velocity {
                first.has_velocity()
            } else {
                first.has_forces()
            });
        }
        let Some(frame) = self.inner.as_ref() else {
            return Ok(false);
        };
        let rows = if velocity {
            frame.velocities.nrows()
        } else {
            frame.forces.nrows()
        };
        if rows > 0 {
            return Ok(true);
        }
        Ok(frame.atom_data.first().is_some_and(|atom| {
            if velocity {
                atom.has_velocity()
            } else {
                atom.has_forces()
            }
        }))
    }

    fn copy_positions<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        if let Some(slab) = &self.slab {
            let row = slab.bind(py).get_item(self.slab_index)?;
            let arr = row.cast::<PyArray2<f64>>()?;
            return Ok(Some(copy_pyarray2(py, arr)?));
        }
        if let Some(owned) = &self.xyz_owned {
            return Ok(Some(copy_pyarray2(py, owned.bind(py))?));
        }
        if let Some(frame) = self.inner.as_ref() {
            if frame.positions.nrows() > 0 {
                return Ok(Some(array2_from_storage(py, &frame.positions)?));
            }
        }
        Ok(None)
    }

    fn vector_section_array<'py>(
        &self,
        py: Python<'py>,
        velocity: bool,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        if !self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            if let Some(frame) = self.inner.as_ref() {
                let storage = if velocity {
                    &frame.velocities
                } else {
                    &frame.forces
                };
                if storage.nrows() > 0 {
                    return Ok(Some(array2_from_storage(py, storage)?));
                }
                let present = frame.atom_data.first().is_some_and(|atom| {
                    if velocity {
                        atom.has_velocity()
                    } else {
                        atom.has_forces()
                    }
                });
                if !present {
                    return Ok(None);
                }
            } else {
                return Ok(None);
            }
        }
        let atoms = self.py_atoms(py)?;
        let present = atoms.first().is_some_and(|atom| {
            if velocity {
                atom.has_velocity()
            } else {
                atom.has_forces()
            }
        });
        if !present {
            return Ok(None);
        }
        let mut data = Vec::with_capacity(atoms.len() * 3);
        for atom in &atoms {
            if velocity {
                data.push(atom.vx.unwrap_or(0.0));
                data.push(atom.vy.unwrap_or(0.0));
                data.push(atom.vz.unwrap_or(0.0));
            } else {
                data.push(atom.fx.unwrap_or(0.0));
                data.push(atom.fy.unwrap_or(0.0));
                data.push(atom.fz.unwrap_or(0.0));
            }
        }
        Ok(Some(array2_from_f64(py, atoms.len(), 3, data)?))
    }

    fn from_con_frame(py: Python<'_>, frame: &ConFrame) -> PyResult<Self> {
        Self::from_owned(py, frame.clone())
    }

    fn from_owned(py: Python<'_>, mut frame: ConFrame) -> PyResult<Self> {
        let n_atoms = frame.positions.nrows();
        // The coordinate view is a NumPy array. Building it calls the
        // NumPy C API, which panics when the numpy module is absent.
        // A read that only writes the frames back keeps the parser's
        // coordinates on the frame instead.
        let xyz_owned = if py.import("numpy").is_ok() {
            let mut data = Vec::with_capacity(n_atoms.saturating_mul(3));
            if let Some(src) = frame.positions.f64_slice() {
                data.extend_from_slice(src);
            } else {
                for i in 0..n_atoms {
                    data.extend_from_slice(&frame.positions.as_f64_row(i));
                }
            }
            let xyz = Array2::from_shape_vec((n_atoms, 3), data)
                .map_err(|e| PyValueError::new_err(format!("xyz shape error: {e}")))?
                .into_pyarray(py)
                .unbind();
            frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
            Some(xyz)
        } else {
            None
        };
        let cell = frame.header.boxl;
        let angles = frame.header.angles;
        let prebox_header = [
            frame.header.prebox_header.user.clone(),
            frame.header.prebox_header.metadata_line().to_string(),
        ];
        let postbox_header = frame.header.postbox_header.clone();
        let spec_version = frame.header.spec_version;
        let metadata = json_map_to_py_dict(py, &frame.header.metadata)?;
        Ok(PyConFrame {
            cell,
            angles,
            prebox_header,
            postbox_header,
            atoms: PyList::empty(py).unbind(),
            atoms_ready: std::sync::atomic::AtomicBool::new(false),
            spec_version,
            metadata,
            inner: Some(frame),
            n_atoms,
            slab: None,
            slab_index: 0,
            xyz_owned,
        })
    }

    fn from_slab(
        py: Python<'_>,
        mut frame: ConFrame,
        slab: Py<PyArray3<f64>>,
        index: usize,
        n_atoms: usize,
    ) -> PyResult<Self> {
        let cell = frame.header.boxl;
        let angles = frame.header.angles;
        let prebox_header = [
            frame.header.prebox_header.user.clone(),
            frame.header.prebox_header.metadata_line().to_string(),
        ];
        let postbox_header = frame.header.postbox_header.clone();
        let spec_version = frame.header.spec_version;
        let metadata = json_map_to_py_dict(py, &frame.header.metadata)?;
        // Coordinates live in the slab. Moving the frame avoids cloning
        // every atom onto the GIL thread after the parallel parse.
        frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
        Ok(PyConFrame {
            cell,
            angles,
            prebox_header,
            postbox_header,
            atoms: PyList::empty(py).unbind(),
            atoms_ready: std::sync::atomic::AtomicBool::new(false),
            spec_version,
            metadata,
            inner: Some(frame),
            n_atoms,
            slab: Some(slab),
            slab_index: index,
            xyz_owned: None,
        })
    }

    fn ensure_atoms(&self, py: Python<'_>) -> PyResult<()> {
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            return Ok(());
        }
        let Some(frame) = self.inner.as_ref() else {
            self.atoms_ready
                .store(true, std::sync::atomic::Ordering::Release);
            return Ok(());
        };
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
        let list = self.atoms.bind(py);
        for (i, atom) in frame.atom_data.iter().enumerate() {
            let mass = per_atom_mass.get(i).copied().unwrap_or(0.0);
            list.append(PyAtomDatum::from_atom_with_mass(atom, mass))?;
        }
        self.atoms_ready
            .store(true, std::sync::atomic::Ordering::Release);
        Ok(())
    }

    fn py_atoms(&self, py: Python<'_>) -> PyResult<Vec<PyAtomDatum>> {
        self.ensure_atoms(py)?;
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
        let mut meta = self.metadata_map(py)?;
        let atoms = self.py_atoms(py)?;
        // v1 and v2 velocities are in the natural time unit (CON-units.8).
        // The builder writes minor 1, which requires units.time (CON-units.11).
        crate::writer::stamp_legacy_velocity_time(
            &mut meta,
            self.spec_version,
            atoms.iter().any(PyAtomDatum::has_velocity),
        );

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
            if let Some(charge) = py_atom.charge {
                builder.with_charge(charge);
            }
            if let Some(spin) = py_atom.spin {
                builder.with_spin(spin);
            }
            if py_atom.mx.is_some() && py_atom.my.is_some() && py_atom.mz.is_some() {
                builder.with_magmom([
                    py_atom.mx.unwrap_or(0.0),
                    py_atom.my.unwrap_or(0.0),
                    py_atom.mz.unwrap_or(0.0),
                ]);
            }
            if py_atom.has_displacement() {
                builder.with_displacement([
                    py_atom.dx.unwrap_or(0.0),
                    py_atom.dy.unwrap_or(0.0),
                    py_atom.dz.unwrap_or(0.0),
                ]);
            }
            if py_atom.has_spread() {
                builder.with_spread([
                    py_atom.sx.unwrap_or(0.0),
                    py_atom.sy.unwrap_or(0.0),
                    py_atom.sz.unwrap_or(0.0),
                ]);
            }
        }

        builder
            .build()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }
}

fn array2_from_f64<'py>(
    py: Python<'py>,
    rows: usize,
    cols: usize,
    data: Vec<f64>,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let array = Array2::from_shape_vec((rows, cols), data)
        .map_err(|e| PyValueError::new_err(format!("array shape error: {e}")))?;
    Ok(array.into_pyarray(py))
}

fn array2_from_storage<'py>(
    py: Python<'py>,
    storage: &crate::storage_dtype::Array2Storage,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let rows = storage.nrows();
    let cols = storage.ncols();
    let mut data = Vec::with_capacity(rows.saturating_mul(cols));
    if let Some(src) = storage.f64_slice() {
        data.extend_from_slice(src);
    } else {
        for row in 0..rows {
            let values = storage.as_f64_row(row);
            let n = cols.min(values.len());
            data.extend_from_slice(&values[..n]);
            data.resize(data.len() + cols - n, 0.0);
        }
    }
    array2_from_f64(py, rows, cols, data)
}

fn copy_pyarray2<'py>(
    py: Python<'py>,
    arr: &Bound<'py, PyArray2<f64>>,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let dims = arr.dims();
    let rows = dims[0];
    let cols = dims[1];
    let ro = arr.readonly();
    let data = if let Ok(slice) = ro.as_slice() {
        slice.to_vec()
    } else {
        ro.as_array().iter().copied().collect()
    };
    array2_from_f64(py, rows, cols, data)
}

fn push_positions(storage: crate::storage_dtype::Array2Storage, out: &mut Vec<f64>) {
    match storage {
        crate::storage_dtype::Array2Storage::F64(arr) => {
            if let Some(slice) = arr.as_slice() {
                out.extend_from_slice(slice);
            } else {
                for row in arr.rows() {
                    out.extend(row.iter().copied());
                }
            }
        }
        other => {
            for i in 0..other.nrows() {
                out.extend_from_slice(&other.as_f64_row(i));
            }
        }
    }
}

fn expand_masses(frame: &ConFrame) -> Vec<f64> {
    let mut masses = Vec::with_capacity(frame.atom_data.len());
    for (type_index, &count) in frame.header.natms_per_type.iter().enumerate() {
        let mass = frame
            .header
            .masses_per_type
            .get(type_index)
            .copied()
            .unwrap_or(0.0);
        masses.extend(std::iter::repeat_n(mass, count));
    }
    masses
}

fn frame_from_arrays(
    positions: &[f64],
    masses: &[f64],
    cell: &[f64],
    symbol: &str,
) -> Result<ConFrame, String> {
    let n = masses.len();
    if positions.len() != n * 3 || cell.len() != 6 || n == 0 {
        return Err("positions, masses and cell disagree".to_string());
    }
    let shared: std::sync::Arc<str> = std::sync::Arc::from(symbol);
    let mut atom_data = Vec::with_capacity(n);
    for i in 0..n {
        let base = i * 3;
        atom_data.push(AtomDatum::coords(
            std::sync::Arc::clone(&shared),
            positions[base],
            positions[base + 1],
            positions[base + 2],
            [false, false, false],
            i as u64,
        ));
    }
    let mut metadata = BTreeMap::new();
    metadata.insert(meta::CON_SPEC_MINOR.to_string(), serde_json::json!(1));
    metadata.insert(meta::CON_SPEC_VERSION.to_string(), serde_json::json!(2));
    Ok(ConFrame {
        header: crate::types::FrameHeader {
            prebox_header: crate::types::PreboxHeader::new("readcon"),
            boxl: [cell[0], cell[1], cell[2]],
            angles: [cell[3], cell[4], cell[5]],
            postbox_header: ["0 0".to_string(), "0 0".to_string()],
            natm_types: 1,
            natms_per_type: vec![n],
            masses_per_type: vec![masses[0]],
            spec_version: 2,
            metadata,
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: true,
        },
        atom_data,
        positions: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        velocities: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        forces: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        atom_energies: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        ),
        charges: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        ),
        spins: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        ),
        magmoms: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        displacements: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        spreads: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        masses: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        ),
        atom_ids: ndarray::ArcArray1::zeros(0),
    })
}

/// Read coordinates as one contiguous array.
///
/// The parse runs without the GIL. The returned positions are the parser's
/// coordinate block moved into NumPy. Per-frame cell and masses travel beside
/// that array. `parse_s`, `convert_s` and `copy_s` split the time.
#[pyfunction]
fn read_coords(py: Python<'_>, path: &str) -> PyResult<Py<PyDict>> {
    let path_owned = path.to_owned();
    let parse_start = std::time::Instant::now();
    let frames = py
        .detach(|| {
            crate::iterators::read_all_frames_with_threads(Path::new(&path_owned), None)
                .map_err(|err| err.to_string())
        })
        .map_err(PyIOError::new_err)?;
    let parse_s = parse_start.elapsed().as_secs_f64();
    let convert_start = std::time::Instant::now();
    let n_frames = frames.len();
    let n_atoms = frames
        .first()
        .map(|frame| frame.atom_data.len())
        .unwrap_or(0);
    let uniform = frames.iter().all(|frame| frame.atom_data.len() == n_atoms);
    if !uniform {
        return Err(PyValueError::new_err(
            "read_coords needs the same atom count in every frame",
        ));
    }
    let mut positions = Vec::with_capacity(n_frames * n_atoms * 3);
    let mut masses = Vec::with_capacity(n_frames * n_atoms);
    let mut cell = Vec::with_capacity(n_frames * 6);
    for frame in frames {
        cell.extend_from_slice(&frame.header.boxl);
        cell.extend_from_slice(&frame.header.angles);
        masses.extend(expand_masses(&frame));
        push_positions(frame.positions, &mut positions);
    }
    let convert_s = convert_start.elapsed().as_secs_f64();
    let copy_start = std::time::Instant::now();
    let pos = ndarray::Array3::from_shape_vec((n_frames, n_atoms, 3), positions)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    let mass = ndarray::Array2::from_shape_vec((n_frames, n_atoms), masses)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    let cell_arr = ndarray::Array2::from_shape_vec((n_frames, 6), cell)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    let dict = PyDict::new(py);
    dict.set_item("positions", pos.into_pyarray(py))?;
    dict.set_item("masses", mass.into_pyarray(py))?;
    dict.set_item("cell", cell_arr.into_pyarray(py))?;
    dict.set_item("n_frames", n_frames)?;
    dict.set_item("n_atoms", n_atoms)?;
    dict.set_item("parse_s", parse_s)?;
    dict.set_item("convert_s", convert_s)?;
    let copy_s = copy_start.elapsed().as_secs_f64();
    dict.set_item("copy_s", copy_s)?;
    Ok(dict.unbind())
}

/// Write coordinates from contiguous arrays.
///
/// `positions` is `(frames, atoms, 3)`, `masses` is `(frames, atoms)` and
/// `cell` is `(frames, 6)` with lengths then angles. The GIL is released
/// while the file is formatted.
#[pyfunction]
#[pyo3(signature = (path, positions, masses, cell, symbol="Cu"))]
fn write_coords(
    py: Python<'_>,
    path: &str,
    positions: PyReadonlyArray3<'_, f64>,
    masses: PyReadonlyArray2<'_, f64>,
    cell: PyReadonlyArray2<'_, f64>,
    symbol: &str,
) -> PyResult<Py<PyDict>> {
    let copy_start = std::time::Instant::now();
    let pos = positions.as_slice()?;
    let mass = masses.as_slice()?;
    let cell_s = cell.as_slice()?;
    let shape = positions.dims();
    let n_frames = shape[0];
    let n_atoms = shape[1];
    if mass.len() != n_frames * n_atoms || cell_s.len() != n_frames * 6 {
        return Err(PyValueError::new_err("positions, masses and cell disagree"));
    }
    let pos_owned = pos.to_vec();
    let mass_owned = mass.to_vec();
    let cell_owned = cell_s.to_vec();
    let copy_s = copy_start.elapsed().as_secs_f64();
    let path_owned = path.to_owned();
    let symbol_owned = symbol.to_owned();
    let convert_start = std::time::Instant::now();
    py.detach(move || {
        let mut frames = Vec::with_capacity(n_frames);
        for index in 0..n_frames {
            let p = index * n_atoms * 3;
            let m = index * n_atoms;
            let c = index * 6;
            let frame = frame_from_arrays(
                &pos_owned[p..p + n_atoms * 3],
                &mass_owned[m..m + n_atoms],
                &cell_owned[c..c + 6],
                &symbol_owned,
            )?;
            frames.push(frame);
        }
        let convert_s = convert_start.elapsed().as_secs_f64();
        let write_start = std::time::Instant::now();
        let mut writer =
            ConFrameWriter::from_path(Path::new(&path_owned)).map_err(|err| err.to_string())?;
        writer
            .extend(frames.iter())
            .map_err(|err| err.to_string())?;
        let write_s = write_start.elapsed().as_secs_f64();
        Ok::<_, String>((convert_s, write_s))
    })
    .map_err(PyIOError::new_err)
    .and_then(|(convert_s, write_s)| {
        let dict = PyDict::new(py);
        dict.set_item("copy_s", copy_s)?;
        dict.set_item("convert_s", convert_s)?;
        dict.set_item("write_s", write_s)?;
        Ok(dict.unbind())
    })
}

/// Phase seconds for one `read_con` call.
struct ReadCallPhases {
    open_mmap_s: f64,
    pool_s: f64,
    pool_join_s: f64,
    schedule_s: f64,
    scan_s: f64,
    slot_alloc_s: f64,
    worker_parse_s: f64,
    finish_s: f64,
    worker_sum_s: f64,
    worker_max_s: f64,
    close_s: f64,
    slab_s: f64,
    release_s: f64,
    list_rest_s: f64,
    python_build_s: f64,
    return_s: f64,
    touch_s: f64,
    teardown_s: f64,
    scan_minflt: i64,
    parse_minflt: i64,
    numa_remote: i64,
    worker_minflt: Vec<i64>,
    share_frames: Vec<u64>,
    share_bytes: Vec<u64>,
    slab_minflt: i64,
    touch_minflt: i64,
    mapped: bool,
    n_bytes: usize,
    n_frames: usize,
    build: &'static str,
    chunk_s: Vec<f64>,
    scan_kind: &'static str,
}

impl ReadCallPhases {
    fn from_rust(
        phases: crate::iterators::ReadPhaseTimes,
        n_bytes: usize,
        n_frames: usize,
        build: &'static str,
    ) -> Self {
        Self {
            open_mmap_s: phases.open_mmap_s,
            pool_s: phases.pool_s,
            pool_join_s: phases.pool_join_s,
            schedule_s: phases.schedule_s,
            scan_s: phases.scan_s,
            slot_alloc_s: phases.slot_alloc_s,
            worker_parse_s: phases.worker_parse_s,
            finish_s: phases.finish_s,
            worker_sum_s: phases.worker_sum_s,
            worker_max_s: phases.worker_max_s,
            close_s: phases.close_s,
            slab_s: 0.0,
            release_s: 0.0,
            list_rest_s: 0.0,
            python_build_s: 0.0,
            return_s: 0.0,
            touch_s: 0.0,
            teardown_s: 0.0,
            scan_minflt: phases.scan_minflt,
            parse_minflt: phases.parse_minflt,
            numa_remote: phases.numa_remote,
            worker_minflt: Vec::new(),
            share_frames: Vec::new(),
            share_bytes: Vec::new(),
            slab_minflt: phases.slab_minflt,
            touch_minflt: phases.touch_minflt,
            mapped: phases.mapped,
            n_bytes,
            n_frames,
            build,
            chunk_s: Vec::new(),
            scan_kind: "serial",
        }
    }

    fn dict(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("open_mmap_s", self.open_mmap_s)?;
        dict.set_item("pool_s", self.pool_s)?;
        dict.set_item("pool_join_s", self.pool_join_s)?;
        dict.set_item("schedule_s", self.schedule_s)?;
        dict.set_item("scan_s", self.scan_s)?;
        dict.set_item("slot_alloc_s", self.slot_alloc_s)?;
        dict.set_item("worker_parse_s", self.worker_parse_s)?;
        dict.set_item("parse_s", self.slot_alloc_s + self.worker_parse_s)?;
        dict.set_item("finish_s", self.finish_s)?;
        dict.set_item("worker_sum_s", self.worker_sum_s)?;
        dict.set_item("worker_max_s", self.worker_max_s)?;
        dict.set_item("close_s", self.close_s)?;
        dict.set_item("slab_s", self.slab_s)?;
        dict.set_item("release_s", self.release_s)?;
        dict.set_item("list_rest_s", self.list_rest_s)?;
        dict.set_item("python_build_s", self.python_build_s)?;
        dict.set_item("return_s", self.return_s)?;
        dict.set_item("touch_s", self.touch_s)?;
        dict.set_item("teardown_s", self.teardown_s)?;
        dict.set_item("scan_minflt", self.scan_minflt)?;
        dict.set_item("parse_minflt", self.parse_minflt)?;
        dict.set_item("numa_remote", self.numa_remote)?;
        dict.set_item(
            "fault_proxy",
            "minor faults per worker; the guest denies perf_event_open",
        )?;
        dict.set_item("worker_minflt", &self.worker_minflt)?;
        dict.set_item("share_frames", &self.share_frames)?;
        dict.set_item("share_bytes", &self.share_bytes)?;
        dict.set_item("slab_minflt", self.slab_minflt)?;
        dict.set_item("touch_minflt", self.touch_minflt)?;
        dict.set_item("mapped", self.mapped)?;
        dict.set_item("n_bytes", self.n_bytes)?;
        dict.set_item("n_frames", self.n_frames)?;
        dict.set_item("build", self.build)?;
        dict.set_item("chunk_s", &self.chunk_s)?;
        dict.set_item("scan_kind", self.scan_kind)?;
        Ok(dict.unbind())
    }
}

/// Parsed frames. Indexing builds one [`PyConFrame`].
///
/// `read_con` returns this. The coordinate slab is one array shared by
/// every rectangular frame. A frame's Python object, including its
/// metadata dict, is built the first time that frame is indexed.
#[pyclass(name = "ConFrameList")]
struct ConFrameList {
    frames: std::sync::Mutex<Vec<Option<ConFrame>>>,
    cache: std::sync::Mutex<Vec<Option<Py<PyConFrame>>>>,
    slab: Option<Py<PyArray3<f64>>>,
    n_atoms: usize,
    workers: usize,
    phases: std::sync::Mutex<ReadCallPhases>,
    /// The pool from the read. Touch and teardown reuse it.
    pool: std::sync::Mutex<Option<std::sync::Arc<rayon::ThreadPool>>>,
}

#[pyclass(name = "ConFrameListIterator")]
struct ConFrameListIter {
    inner: Py<ConFrameList>,
    pos: usize,
}

impl ConFrameList {
    fn len_frames(&self) -> usize {
        self.frames.lock().expect("frames").len()
    }

    fn frame_obj(&self, py: Python<'_>, index: usize) -> PyResult<Py<PyConFrame>> {
        {
            let cache = self.cache.lock().expect("cache");
            if let Some(hit) = cache.get(index).and_then(|slot| slot.as_ref()) {
                return Ok(hit.clone_ref(py));
            }
        }
        let frame = self.frames.lock().expect("frames")[index]
            .take()
            .ok_or_else(|| PyIOError::new_err(format!("frame {index} is already borrowed")))?;
        let built = if let Some(slab) = &self.slab {
            PyConFrame::from_slab(py, frame, slab.clone_ref(py), index, self.n_atoms)?
        } else {
            PyConFrame::from_owned(py, frame)?
        };
        let obj = Py::new(py, built)?;
        self.cache.lock().expect("cache")[index] = Some(obj.clone_ref(py));
        Ok(obj)
    }
}

#[pymethods]
impl ConFrameList {
    fn __len__(&self) -> usize {
        self.len_frames()
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let n = self.len_frames();
        if let Ok(slice) = key.cast::<pyo3::types::PySlice>() {
            let ind = slice.indices(n as isize)?;
            let mut out = Vec::with_capacity(ind.slicelength as usize);
            for step in 0..ind.slicelength as isize {
                let index = (ind.start + step * ind.step) as usize;
                out.push(self.frame_obj(py, index)?);
            }
            return out.into_py_any(py);
        }
        let index: isize = key.extract()?;
        let resolved = if index < 0 { index + n as isize } else { index };
        if resolved < 0 || resolved as usize >= n {
            return Err(pyo3::exceptions::PyIndexError::new_err(format!(
                "frame index {index} is out of range for {n} frames"
            )));
        }
        self.frame_obj(py, resolved as usize)?.into_py_any(py)
    }

    fn __iter__(slf: Py<Self>) -> ConFrameListIter {
        ConFrameListIter { inner: slf, pos: 0 }
    }

    /// Seconds for open, the pool, scan, slot allocation, worker parse,
    /// the finish move, the slab, position release, Python object
    /// construction, the return, and a later touch.
    #[getter]
    fn phases(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        self.phases.lock().expect("phases").dict(py)
    }

    /// XOR of every frame's positions, cell lengths, and atom-type symbols.
    ///
    /// The read walks the coordinate slab and each stored symbol. The
    /// returned seconds are that walk. A second call walks again.
    fn touch_checksum(&self, py: Python<'_>) -> PyResult<(u64, f64)> {
        let frames = self.frames.lock().expect("frames");
        let Some(slab) = &self.slab else {
            return Err(PyIOError::new_err(
                "touch_checksum needs the shared coordinate slab",
            ));
        };
        let values = slab.bind(py).readonly();
        let slice = values.as_slice()?;
        let fault0 = crate::iterators::process_minflt();
        let t_touch = std::time::Instant::now();
        let workers = self.workers;
        let digest = {
            let pool = self.pool.lock().expect("pool");
            let run = || crate::iterators::touch_option_checksum(&frames, slice, workers);
            match pool.as_ref() {
                Some(pool) if workers >= 2 => pool.install(run),
                _ => run(),
            }
        }
        .ok_or_else(|| PyIOError::new_err("touch_checksum could not read every frame"))?;
        let touch_s = t_touch.elapsed().as_secs_f64();
        let touch_minflt = crate::iterators::process_minflt().saturating_sub(fault0);
        drop(frames);
        {
            let mut phases = self.phases.lock().expect("phases");
            phases.touch_s = touch_s;
            phases.touch_minflt = touch_minflt;
        }
        Ok((digest, touch_s))
    }

    /// Return each frame's position buffer and symbol storage to the
    /// worker recycle lists, then join the pool.
    ///
    /// The seconds cover that return and the pool join. A later drop
    /// of this object is empty.
    fn release_frames(&mut self, py: Python<'_>) -> f64 {
        let (teardown_s, pool_join_s) = py.detach(|| self.teardown());
        let mut phases = self.phases.lock().expect("phases");
        phases.teardown_s = teardown_s;
        phases.pool_join_s = pool_join_s;
        teardown_s
    }
}

impl ConFrameList {
    fn teardown(&mut self) -> (f64, f64) {
        let t0 = std::time::Instant::now();
        let mut frames = std::mem::take(&mut *self.frames.lock().expect("frames"));
        let pool = self.pool.lock().expect("pool").take();
        let workers = self.workers.max(1);
        if let Some(pool) = pool {
            if frames.len() >= 2 {
                // Drop each share in place. Moving every frame into a
                // parallel iterator copies the frame header before the
                // free, and that copy sat inside this clock.
                let share = frames.len().div_ceil(pool.current_num_threads()).max(1);
                let ptr = frames.as_mut_ptr() as usize;
                let len = frames.len();
                pool.broadcast(move |ctx| {
                    let start = ctx.index().saturating_mul(share);
                    if start >= len {
                        return;
                    }
                    let end = (start + share).min(len);
                    let base = ptr as *mut Option<ConFrame>;
                    for index in start..end {
                        unsafe {
                            std::ptr::drop_in_place(base.add(index));
                        }
                    }
                });
                let mut frames = std::mem::ManuallyDrop::new(frames);
                unsafe {
                    frames.set_len(0);
                    drop(std::mem::ManuallyDrop::into_inner(frames));
                }
            } else {
                drop(frames);
            }
            // Dropping this handle does not join the workers. The process
            // keeps one pool per width so the next file reuses the pages
            // those workers just freed.
            let t_join = std::time::Instant::now();
            drop(pool);
            let pool_join_s = t_join.elapsed().as_secs_f64();
            return (t0.elapsed().as_secs_f64(), pool_join_s);
        }
        if workers >= 2 && frames.len() >= 2 {
            let chunk = frames.len().div_ceil(workers).max(1);
            let mut chunks = Vec::new();
            let mut rest = frames;
            while !rest.is_empty() {
                let take = chunk.min(rest.len());
                let tail = rest.split_off(take);
                chunks.push(rest);
                rest = tail;
            }
            std::thread::scope(|scope| {
                for chunk in chunks {
                    scope.spawn(move || drop(chunk));
                }
            });
        } else {
            drop(frames);
        }
        (t0.elapsed().as_secs_f64(), 0.0)
    }
}

impl Drop for ConFrameList {
    fn drop(&mut self) {
        self.teardown();
    }
}

#[pymethods]
impl ConFrameListIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<Py<PyConFrame>>> {
        let n = self.inner.borrow(py).len_frames();
        if self.pos >= n {
            return Ok(None);
        }
        let index = self.pos;
        self.pos += 1;
        self.inner.borrow(py).frame_obj(py, index).map(Some)
    }
}

fn clear_packed_positions(frames: &mut [ConFrame], workers: usize) {
    let clear = |frame: &mut ConFrame| {
        frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
    };
    #[cfg(feature = "parallel")]
    if workers >= 2 && frames.len() >= 2 {
        // The read's pool is already installed by the caller. This does
        // not build another one.
        if rayon::current_thread_index().is_some() {
            use rayon::prelude::*;
            frames.par_iter_mut().for_each(clear);
            return;
        }
        let chunk = frames.len().div_ceil(workers).max(1);
        std::thread::scope(|scope| {
            let mut rest = frames;
            while !rest.is_empty() {
                let take = chunk.min(rest.len());
                let (head, tail) = rest.split_at_mut(take);
                rest = tail;
                scope.spawn(move || {
                    for frame in head.iter_mut() {
                        frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
                    }
                });
            }
        });
        return;
    }
    frames.iter_mut().for_each(clear);
}

fn slab_from_values(
    py: Python<'_>,
    values: Vec<f64>,
    n_frames: usize,
    n_atoms: usize,
) -> PyResult<Py<PyArray3<f64>>> {
    let array = Array3::from_shape_vec((n_frames, n_atoms, 3), values)
        .map_err(|e| PyValueError::new_err(format!("positions shape error: {e}")))?;
    Ok(array.into_pyarray(py).unbind())
}

/// Move `frames` into a lazy list. The coordinate copy runs without the GIL.
fn scan_kind_name(kind: u8) -> &'static str {
    #[cfg(feature = "parallel")]
    {
        if kind == crate::iterators::SCAN_EQUAL_SPAN {
            return "equal-span";
        }
        if kind == crate::iterators::SCAN_INDEXED {
            return "indexed";
        }
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = kind;
    }
    "serial"
}

fn con_frame_list(
    py: Python<'_>,
    mut frames: Vec<ConFrame>,
    phases: crate::iterators::ReadPhaseTimes,
    n_bytes: usize,
    n_threads: Option<usize>,
    build: &'static str,
    chunk_s: Vec<f64>,
    worker_minflt: Vec<i64>,
    share_frames: Vec<u64>,
    share_bytes: Vec<u64>,
    scan_kind: &'static str,
    pool: Option<std::sync::Arc<rayon::ThreadPool>>,
) -> PyResult<Py<ConFrameList>> {
    let t_list = std::time::Instant::now();
    let n_frames = frames.len();
    let workers = n_threads.filter(|n| *n >= 2).unwrap_or(1);
    let fault0 = crate::iterators::process_minflt();
    let t_slab = std::time::Instant::now();
    // `into_pyarray` panics if the numpy module is not installed. The
    // shared slab is the coordinate view; the frames still hold the
    // parsed coordinates when that view cannot be built.
    let numpy_ok = py.import("numpy").is_ok();
    let packed = if numpy_ok {
        py.detach(|| match pool.as_ref() {
            Some(pool) if workers >= 2 => {
                pool.install(|| crate::iterators::pack_position_slab(&frames, workers))
            }
            _ => crate::iterators::pack_position_slab(&frames, 1),
        })
    } else {
        None
    };
    let slab_s = t_slab.elapsed().as_secs_f64();
    let slab_minflt = crate::iterators::process_minflt().saturating_sub(fault0);
    let n_atoms = match packed.as_ref() {
        Some(values) if n_frames > 0 => values.len() / n_frames / 3,
        _ => 0,
    };
    let t_release = std::time::Instant::now();
    if packed.is_some() {
        py.detach(|| match pool.as_ref() {
            Some(pool) if workers >= 2 => {
                pool.install(|| clear_packed_positions(&mut frames, workers))
            }
            _ => clear_packed_positions(&mut frames, 1),
        });
    }
    let release_s = t_release.elapsed().as_secs_f64();
    let t_build = std::time::Instant::now();
    let slab = match packed {
        Some(values) => Some(slab_from_values(py, values, n_frames, n_atoms)?),
        None => None,
    };
    let python_build_s = t_build.elapsed().as_secs_f64();
    let mut record = ReadCallPhases::from_rust(phases, n_bytes, n_frames, build);
    record.slab_s = slab_s;
    record.slab_minflt = slab_minflt;
    record.release_s = release_s;
    record.python_build_s = python_build_s;
    record.chunk_s = chunk_s;
    record.worker_minflt = worker_minflt;
    record.share_frames = share_frames;
    record.share_bytes = share_bytes;
    record.scan_kind = scan_kind;
    let mut cache = Vec::with_capacity(n_frames);
    cache.resize_with(n_frames, || None);
    let stored: Vec<Option<ConFrame>> = py.detach(|| match pool.as_ref() {
        Some(pool) if workers >= 2 => {
            use rayon::prelude::*;
            pool.install(|| frames.into_par_iter().map(Some).collect())
        }
        _ => frames.into_iter().map(Some).collect(),
    });
    let t_return = std::time::Instant::now();
    let obj = Py::new(py, ConFrameList {
        frames: std::sync::Mutex::new(stored),
        cache: std::sync::Mutex::new(cache),
        slab,
        n_atoms,
        workers,
        phases: std::sync::Mutex::new(record),
        pool: std::sync::Mutex::new(pool),
    })?;
    let return_s = t_return.elapsed().as_secs_f64();
    let list_s = t_list.elapsed().as_secs_f64();
    let accounted = slab_s + release_s + python_build_s + return_s;
    let list_rest_s = (list_s - accounted).max(0.0);
    obj.borrow_mut(py).phases.lock().expect("phases").return_s = return_s;
    obj.borrow_mut(py)
        .phases
        .lock()
        .expect("phases")
        .list_rest_s = list_rest_s;
    Ok(obj)
}

fn load_phased(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
) -> PyResult<(
    Vec<ConFrame>,
    crate::iterators::ReadPhaseTimes,
    usize,
    Vec<f64>,
    &'static str,
    Option<std::sync::Arc<rayon::ThreadPool>>,
    Vec<i64>,
    Vec<u64>,
    Vec<u64>,
)> {
    let path_owned = path.to_owned();
    let t_enter = std::time::Instant::now();
    let mut loaded = py
        .detach(|| {
            crate::iterators::read_all_frames_phased(Path::new(&path_owned), n_threads)
                .map(|phased| {
                    (
                        phased.frames,
                        phased.phases,
                        phased.n_bytes,
                        phased.chunk_s,
                        scan_kind_name(phased.scan_kind),
                        phased.pool,
                        phased.worker_minflt,
                        phased.share_frames,
                        phased.share_bytes,
                    )
                })
                .map_err(|err| err.to_string())
        })
        .map_err(PyIOError::new_err)?;
    let elapsed = t_enter.elapsed().as_secs_f64();
    let phases = &loaded.1;
    let named = phases.open_mmap_s
        + phases.pool_s
        + phases.pool_join_s
        + phases.scan_s
        + phases.slot_alloc_s
        + phases.worker_parse_s
        + phases.finish_s
        + phases.close_s
        + phases.schedule_s;
    loaded.1.schedule_s += (elapsed - named).max(0.0);
    Ok(loaded)
}

fn read_con_lazy(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
) -> PyResult<Py<ConFrameList>> {
    let (
        frames,
        phases,
        n_bytes,
        chunk_s,
        scan_kind,
        pool,
        worker_minflt,
        share_frames,
        share_bytes,
    ) = load_phased(py, path, n_threads)?;
    con_frame_list(
        py,
        frames,
        phases,
        n_bytes,
        n_threads,
        "lazy",
        chunk_s,
        worker_minflt,
        share_frames,
        share_bytes,
        scan_kind,
        pool,
    )
}

fn read_con_eager(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
) -> PyResult<(Py<PyAny>, Py<PyDict>)> {
    let (
        frames,
        phases,
        n_bytes,
        chunk_s,
        scan_kind,
        pool,
        worker_minflt,
        share_frames,
        share_bytes,
    ) = load_phased(py, path, n_threads)?;
    drop(pool);
    drop(worker_minflt);
    drop(share_frames);
    drop(share_bytes);
    let n_frames = frames.len();
    let mut record = ReadCallPhases::from_rust(phases, n_bytes, n_frames, "eager");
    record.chunk_s = chunk_s;
    record.scan_kind = scan_kind;
    let t_build = std::time::Instant::now();
    let built = frames_from_parsed(py, frames)?;
    record.python_build_s = t_build.elapsed().as_secs_f64();
    let t_return = std::time::Instant::now();
    let obj = built.into_py_any(py)?;
    record.return_s = t_return.elapsed().as_secs_f64();
    let dict = record.dict(py)?;
    Ok((obj, dict))
}

/// Phase split of [`read_con`].
///
/// `build="lazy"` is the default path. `build="eager"` builds every
/// Python frame before returning, which is the previous wrapper.
#[pyfunction]
#[pyo3(name = "read_con_phases", signature = (path, n_threads=None, *, build="lazy"))]
fn read_con_phases(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
    build: &str,
) -> PyResult<(Py<PyAny>, Py<PyDict>)> {
    match build {
        "lazy" => {
            let frames = read_con_lazy(py, path, n_threads)?;
            let dict = frames.borrow(py).phases(py)?;
            Ok((frames.into_py_any(py)?, dict))
        }
        "eager" => read_con_eager(py, path, n_threads),
        other => Err(PyValueError::new_err(format!(
            "unknown build {other:?}; use \"lazy\" or \"eager\""
        ))),
    }
}

/// Newline-scan probe. The pool is built before the timer.
///
/// Returns the frame-start count, the seconds, and whether those starts
/// match the serial walk.
#[pyfunction]
#[pyo3(signature = (path, threads, chunked))]
fn scan_probe(path: &str, threads: usize, chunked: bool) -> PyResult<(usize, f64, bool)> {
    let text = std::fs::read_to_string(path).map_err(|err| PyIOError::new_err(err.to_string()))?;
    let (offsets, seconds) = crate::iterators::measure_newline_scan(&text, threads, chunked);
    let serial = crate::iterators::frame_start_offsets_serial(&text);
    Ok((offsets.len(), seconds, offsets == serial))
}

/// Read frames from a .con or .convel file path.
///
/// `n_threads` is `None`, `0`, or `1` for the calling thread, and
/// `n >= 2` for a Rayon pool of that size.
#[pyfunction]
#[pyo3(name = "read_all_frames", signature = (path, n_threads=None, *, comm=None, mode="auto"))]
fn read_all_frames(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
    comm: Option<&Bound<'_, PyAny>>,
    mode: &str,
) -> PyResult<Py<ConFrameList>> {
    read_con(py, path, n_threads, comm, mode)
}

/// Read frames from a .con or .convel file path.
///
/// With `comm` (an mpi4py communicator, needs the `mpi` build feature)
/// this is collective and returns only this rank's block of frames;
/// concatenating the blocks of ranks `0..size` in rank order gives the
/// serial result. `mode` is `"auto"`, `"shared"` or `"scatter"`.
#[pyfunction]
#[pyo3(signature = (path, n_threads=None, *, comm=None, mode="auto"))]
fn read_con(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
    comm: Option<&Bound<'_, PyAny>>,
    mode: &str,
) -> PyResult<Py<ConFrameList>> {
    if let Some(comm) = comm {
        return read_con_mpi(py, path, n_threads, comm, mode);
    }
    // The GIL stays released across the map, the scan, and the parse.
    // Python frame objects are built on first use.
    read_con_lazy(py, path, n_threads)
}

/// One `[frames, atoms, 3]` float64 array of coordinates.
///
/// The array is allocated once. Parsing writes each frame at its offset
/// from the boundary walk. No per-frame Python object is built.
#[pyfunction]
#[pyo3(name = "read_positions", signature = (path, n_threads=None))]
fn read_positions(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
) -> PyResult<Py<PyArray3<f64>>> {
    let path_owned = path.to_owned();
    let block = py
        .detach(|| {
            crate::iterators::read_positions_with_threads(Path::new(&path_owned), n_threads)
                .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    let array = Array3::from_shape_vec((block.n_frames, block.n_atoms, 3), block.values)
        .map_err(|e| PyValueError::new_err(format!("positions shape error: {e}")))?;
    Ok(array.into_pyarray(py).unbind())
}

fn frames_from_parsed(py: Python<'_>, frames: Vec<ConFrame>) -> PyResult<Vec<PyConFrame>> {
    let n_atoms = frames
        .first()
        .map(|frame| frame.positions.nrows())
        .unwrap_or(0);
    let rectangular = !frames.is_empty()
        && n_atoms > 0
        && frames
            .iter()
            .all(|frame| frame.positions.nrows() == n_atoms);
    if !rectangular || py.import("numpy").is_err() {
        return frames
            .into_iter()
            .map(|frame| PyConFrame::from_owned(py, frame))
            .collect();
    }
    let mut values = Vec::with_capacity(frames.len().saturating_mul(n_atoms).saturating_mul(3));
    for frame in &frames {
        if let Some(src) = frame.positions.f64_slice() {
            values.extend_from_slice(src);
        } else {
            for row in 0..n_atoms {
                values.extend_from_slice(&frame.positions.as_f64_row(row));
            }
        }
    }
    let slab = Array3::from_shape_vec((frames.len(), n_atoms, 3), values)
        .map_err(|e| PyValueError::new_err(format!("positions shape error: {e}")))?
        .into_pyarray(py)
        .unbind();
    frames
        .into_iter()
        .enumerate()
        .map(|(index, frame)| PyConFrame::from_slab(py, frame, slab.clone_ref(py), index, n_atoms))
        .collect()
}

/// Fortran handle of an mpi4py communicator (`comm.py2f()`).
#[cfg(feature = "mpi")]
fn comm_from_py(comm: &Bound<'_, PyAny>) -> PyResult<crate::distrib::Comm> {
    let f: i32 = comm.call_method0("py2f")?.extract()?;
    unsafe { crate::distrib::Comm::dup_fint(f as ::mpi::ffi::RSMPI_Fint) }
        .map_err(|rc| PyIOError::new_err(format!("MPI_Comm_dup failed with MPI error {rc}")))
}

#[cfg(feature = "mpi")]
fn read_con_mpi(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
    comm: &Bound<'_, PyAny>,
    mode: &str,
) -> PyResult<Py<ConFrameList>> {
    use crate::distrib_read::ReadMode;
    let mode = match mode {
        "auto" => ReadMode::Auto,
        "shared" => ReadMode::Shared,
        "scatter" => ReadMode::Scatter,
        m => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown read mode {m:?}; use \"auto\", \"shared\" or \"scatter\""
            )));
        }
    };
    let c = comm_from_py(comm)?;
    // MPI handles are not Send, so the GIL stays held for the collective.
    let t_parse = std::time::Instant::now();
    let rf = crate::distrib_read::read_block(&c, Path::new(path), mode, n_threads)
        .map_err(|e| PyIOError::new_err(e.to_string()))?;
    let worker_parse_s = t_parse.elapsed().as_secs_f64();
    let phases = crate::iterators::ReadPhaseTimes {
        worker_parse_s,
        ..crate::iterators::ReadPhaseTimes::default()
    };
    con_frame_list(
        py,
        rf.frames,
        phases,
        0,
        n_threads,
        "lazy",
        Vec::new(),
        Vec::new(),
        Vec::new(),
        Vec::new(),
        "serial",
        None,
    )
}

#[cfg(not(feature = "mpi"))]
fn read_con_mpi(
    _py: Python<'_>,
    _path: &str,
    _n_threads: Option<usize>,
    _comm: &Bound<'_, PyAny>,
    _mode: &str,
) -> PyResult<Py<ConFrameList>> {
    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "comm= needs readcon built with the mpi feature",
    ))
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
#[pyo3(signature = (contents, n_threads=None))]
fn read_con_string(
    py: Python<'_>,
    contents: &str,
    n_threads: Option<usize>,
) -> PyResult<Py<ConFrameList>> {
    // Clone so parsing can release the GIL (contents may be a borrowed Py str).
    let t_open = std::time::Instant::now();
    let owned = contents.to_owned();
    let open_mmap_s = t_open.elapsed().as_secs_f64();
    let n_bytes = owned.len();
    let parsed = py
        .detach(|| {
            crate::iterators::frames_from_bytes_phased(owned.as_bytes(), n_threads)
                .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    let phases = crate::iterators::ReadPhaseTimes {
        open_mmap_s,
        pool_s: parsed.pool_s,
        pool_join_s: parsed.pool_join_s,
        schedule_s: 0.0,
        scan_s: parsed.scan_s,
        slot_alloc_s: parsed.slot_alloc_s,
        worker_parse_s: parsed.worker_parse_s,
        finish_s: parsed.finish_s,
        worker_sum_s: parsed.worker_sum_s,
        worker_max_s: parsed.worker_max_s,
        close_s: 0.0,
        scan_minflt: parsed.scan_minflt,
        parse_minflt: parsed.worker_minflt.iter().copied().sum(),
        numa_remote: parsed.numa_remote,
        mapped: false,
        ..crate::iterators::ReadPhaseTimes::default()
    };
    con_frame_list(
        py,
        parsed.frames,
        phases,
        n_bytes,
        n_threads,
        "lazy",
        parsed.chunk_s,
        parsed.worker_minflt,
        parsed.share_frames,
        parsed.share_bytes,
        scan_kind_name(parsed.scan_kind),
        parsed.pool,
    )
}

/// Streaming frame iterator: parses one frame per `__next__` (does not
/// materialize the full trajectory as `PyConFrame` up front).
#[pyclass(name = "ConFrameIterator")]
struct PyConFrameIterator {
    source: FrameSource,
}

enum FrameSource {
    /// Full file text: owned, or mapped with `iter_con(path, mmap=True)`,
    /// and the byte offset of the next frame start within it.
    Text(crate::compression::ForwardText, usize),
    /// Decoded and parsed as it is read, with `iter_con(path, stream=True)`.
    Stream(std::sync::Mutex<crate::stream::ConFrameReader<Box<dyn std::io::Read + Send>>>),
}

fn stream_error(what: &str, e: crate::stream::StreamError) -> PyErr {
    if e.is::<crate::error::ParseError>() {
        PyIOError::new_err(format!("{what} error: {e}"))
    } else {
        PyIOError::new_err(format!("read error: {e}"))
    }
}

#[pymethods]
impl PyConFrameIterator {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<PyConFrame>> {
        let (contents, pos) = match &mut self.source {
            FrameSource::Text(contents, pos) => (contents, pos),
            FrameSource::Stream(reader) => {
                let reader = reader.get_mut().unwrap_or_else(|e| e.into_inner());
                return match py.detach(|| reader.next()) {
                    Some(Ok(frame)) => Ok(Some(PyConFrame::from_owned(py, frame)?)),
                    Some(Err(e)) => Err(stream_error("parse", e)),
                    None => Ok(None),
                };
            }
        };
        if *pos >= contents.as_str().len() {
            return Ok(None);
        }
        // An empty line 1 is the user line (CON-header.4). The core iterator
        // owns that boundary and trailing whitespace.
        let slice = &contents.as_str()[*pos..];
        let mut iter = ConFrameIterator::new(slice);
        match iter.next_with_raw_span(slice) {
            Some(Ok((frame, span))) => {
                let consumed =
                    (span.as_ptr() as usize).saturating_sub(slice.as_ptr() as usize) + span.len();
                *pos += consumed;
                contents
                    .release_before(*pos)
                    .map_err(|e| PyIOError::new_err(format!("release error: {e}")))?;
                Ok(Some(PyConFrame::from_owned(py, frame)?))
            }
            Some(Err(e)) => Err(PyIOError::new_err(format!("parse error: {e}"))),
            None => {
                *pos = contents.as_str().len();
                Ok(None)
            }
        }
    }

    /// Skip one frame without building a `ConFrame`. False at EOF.
    fn forward(&mut self, py: Python<'_>) -> PyResult<bool> {
        let (contents, pos) = match &mut self.source {
            FrameSource::Text(contents, pos) => (contents, pos),
            FrameSource::Stream(reader) => {
                let reader = reader.get_mut().unwrap_or_else(|e| e.into_inner());
                return match py.detach(|| reader.forward()) {
                    Some(Ok(())) => Ok(true),
                    Some(Err(e)) => Err(stream_error("skip", e)),
                    None => Ok(false),
                };
            }
        };
        if *pos >= contents.as_str().len() {
            return Ok(false);
        }
        let slice = &contents.as_str()[*pos..];
        let mut iter = ConFrameIterator::new(slice);
        match iter.forward() {
            Some(Ok(())) => {
                *pos += iter.byte_pos();
                contents
                    .release_before(*pos)
                    .map_err(|e| PyIOError::new_err(format!("release error: {e}")))?;
                Ok(true)
            }
            Some(Err(e)) => Err(PyIOError::new_err(format!("skip error: {e}"))),
            None => Ok(false),
        }
    }

    /// Skip `n` frames without parsing atoms. Returns how many were skipped.
    fn skip(&mut self, py: Python<'_>, n: usize) -> PyResult<usize> {
        let mut skipped = 0usize;
        for _ in 0..n {
            if !self.forward(py)? {
                break;
            }
            skipped += 1;
        }
        Ok(skipped)
    }

    /// Skip `index` frames, then parse the next.
    fn nth(&mut self, py: Python<'_>, index: usize) -> PyResult<Option<PyConFrame>> {
        self.skip(py, index)?;
        self.__next__(py)
    }
}

/// Return a **streaming** iterator over frames from a path.
///
/// Prefer this over [`read_all_frames`] when you process frames one at a time:
/// only one `ConFrame` / `PyConFrame` is built per `__next__` call.
///
/// The file is read into memory once. With ``mmap=True`` an uncompressed
/// file of 64 KiB or more is mapped instead, and the pages already read are
/// released. On Linux about 32 MiB of the file then stays resident. On macOS
/// the release does not discard pages, and outside Unix it is a no-op, so
/// there memory can grow to the file size. The mapped file must not change
/// until the iterator is dropped. A truncation can end the process with
/// ``SIGBUS``, which is a signal and not an ``OSError``.
///
/// With ``stream=True`` the file is decompressed and parsed as it is read,
/// so memory stays near one frame plus 1 MiB, for gzip input as for plain.
/// Frames are the same.
/// The iterator raises a parse error or invalid UTF-8 (Unicode
/// Transformation Format, 8-bit) at the bad frame.
/// The error comes after the frames before it, not when the iterator is
/// opened.
#[pyfunction]
#[pyo3(signature = (path, *, mmap=false, stream=false))]
fn iter_con(py: Python<'_>, path: &str, mmap: bool, stream: bool) -> PyResult<PyConFrameIterator> {
    if mmap && stream {
        return Err(PyValueError::new_err("mmap and stream cannot both be true"));
    }
    let path_owned = path.to_owned();
    let source = py
        .detach(|| {
            let path = Path::new(&path_owned);
            if stream {
                crate::stream::ConFrameReader::open(path)
                    .map(|r| FrameSource::Stream(std::sync::Mutex::new(r)))
            } else {
                crate::compression::ForwardText::open(path, mmap).map(|t| FrameSource::Text(t, 0))
            }
            .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    Ok(PyConFrameIterator { source })
}

/// Count frames without building atom / Python objects (skip walk).
#[pyfunction]
fn count_frames(py: Python<'_>, path: &str) -> PyResult<usize> {
    let path_owned = path.to_owned();
    py.detach(|| crate::iterators::count_frames(Path::new(&path_owned)).map_err(|e| e.to_string()))
        .map_err(PyIOError::new_err)
}

/// Skip `index` frames (no atom parse), then return that frame.
#[pyfunction]
fn read_nth_frame(py: Python<'_>, path: &str, index: usize) -> PyResult<PyConFrame> {
    let path_owned = path.to_owned();
    let frame = py
        .detach(|| {
            crate::iterators::read_nth_frame(Path::new(&path_owned), index)
                .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    PyConFrame::from_con_frame(py, &frame)
}

/// Random access to the frames of one file: ``len(t)``, ``t[i]``,
/// ``t[-1]``, ``t[a:b:c]`` and ``for f in t``.
///
/// The file is read once and its frame index is kept, so ``t[i]`` parses
/// only frame ``i``. An uncompressed file reuses a valid ``path.rcidx``;
/// with ``write_index=True`` a fresh scan is written there. gzip and zstd
/// input is indexed in memory only.
#[pyclass(name = "ConTrajectory", frozen)]
struct PyConTrajectory {
    inner: crate::trajectory::ConTrajectory,
}

fn frame_out_of_range(index: impl std::fmt::Display, len: usize) -> PyErr {
    pyo3::exceptions::PyIndexError::new_err(format!(
        "frame index {index} is out of range for a trajectory of {len} frames"
    ))
}

impl PyConTrajectory {
    fn frame_at(&self, py: Python<'_>, i: usize) -> PyResult<PyConFrame> {
        let frame = py.detach(|| self.inner.frame(i)).map_err(|e| match e {
            crate::error::ParseError::IndexOutOfBounds { index, len } => {
                frame_out_of_range(index, len)
            }
            e => PyIOError::new_err(format!("parse error in frame {i}: {e}")),
        })?;
        PyConFrame::from_owned(py, frame)
    }
}

#[pymethods]
impl PyConTrajectory {
    #[new]
    #[pyo3(signature = (path, write_index=true))]
    fn new(py: Python<'_>, path: std::path::PathBuf, write_index: bool) -> PyResult<Self> {
        let inner = py
            .detach(|| {
                crate::trajectory::ConTrajectory::open(&path, write_index)
                    .map_err(|e| e.to_string())
            })
            .map_err(PyIOError::new_err)?;
        Ok(Self { inner })
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let n = self.inner.len();
        if let Ok(slice) = key.cast::<pyo3::types::PySlice>() {
            let ind = slice.indices(n as isize)?;
            let frames = (0..ind.slicelength as isize)
                .map(|k| self.frame_at(py, (ind.start + k * ind.step) as usize))
                .collect::<PyResult<Vec<_>>>()?;
            return frames.into_py_any(py);
        }
        let i: isize = key.extract()?;
        let j = if i < 0 { i + n as isize } else { i };
        if j < 0 || j as usize >= n {
            return Err(frame_out_of_range(i, n));
        }
        self.frame_at(py, j as usize)?.into_py_any(py)
    }

    fn __iter__(slf: Py<Self>) -> PyConTrajectoryIter {
        PyConTrajectoryIter { traj: slf, pos: 0 }
    }
}

#[pyclass(name = "ConTrajectoryIterator")]
struct PyConTrajectoryIter {
    traj: Py<PyConTrajectory>,
    pos: usize,
}

#[pymethods]
impl PyConTrajectoryIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<PyConFrame>> {
        let traj = self.traj.get();
        if self.pos >= traj.inner.len() {
            return Ok(None);
        }
        self.pos += 1;
        traj.frame_at(py, self.pos - 1).map(Some)
    }
}

/// Convert a structure/trajectory path to CON (migration one-liner).
///
/// - ``.con`` / ``.convel`` (optional ``.gz`` / ``.zst``): native reader
/// - other formats: chemfiles-linked build only (``readcon-chemfiles`` /
///   ``maturin develop --features python,chemfiles``)
///
/// Returns a dict: ``n_frames``, ``n_atoms_last``, ``native_con``.
#[pyfunction]
fn convert_to_con(py: Python<'_>, input_path: &str, output_path: &str) -> PyResult<Py<PyAny>> {
    use crate::convert::convert_path_to_con;
    use std::path::Path;
    let report = py
        .detach(|| convert_path_to_con(Path::new(input_path), Path::new(output_path)))
        .map_err(|e| PyIOError::new_err(e.to_string()))?;
    let dict = PyDict::new(py);
    dict.set_item("n_frames", report.n_frames)?;
    dict.set_item("n_atoms_last", report.n_atoms_last)?;
    dict.set_item("native_con", report.native_con)?;
    Ok(dict.into())
}

/// Write frames to a .con or .convel file path.
///
/// The `compression` argument controls output compression:
/// - `None` (default): auto-detect from extension (.gz = gzip, else uncompressed)
/// - `"gzip"`: force gzip compression
/// - `"none"`: force uncompressed
#[pyfunction]
#[pyo3(signature = (path, frames, precision=None, compression=None, *, canonical=false, comm=None, mode="auto"))]
#[allow(clippy::too_many_arguments)]
fn write_con(
    py: Python<'_>,
    path: &str,
    frames: &Bound<'_, PyAny>,
    precision: Option<usize>,
    compression: Option<&str>,
    canonical: bool,
    comm: Option<&Bound<'_, PyAny>>,
    mode: &str,
) -> PyResult<()> {
    let rust_frames = py_frames_to_rust(py, frames)?;
    if let Some(comm) = comm {
        if compression.is_some_and(|c| c != "none") || path.ends_with(".gz") || canonical {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "comm= writes uncompressed, non-canonical output only",
            ));
        }
        return write_con_mpi(py, path, &rust_frames, precision, comm, mode);
    }

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
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::from_path_gzip_with_precision(path, precision)
                .map_err(|e| PyIOError::new_err(format!("failed to create gzip writer: {e}")))?,
            None => ConFrameWriter::from_path_gzip(path)
                .map_err(|e| PyIOError::new_err(format!("failed to create gzip writer: {e}")))?,
        }
        .canonical(canonical);
        writer
            .extend(rust_frames.iter())
            .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    } else {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::from_path_with_precision(path, precision)
                .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?,
            None => ConFrameWriter::from_path(path)
                .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?,
        }
        .canonical(canonical);
        writer
            .extend(rust_frames.iter())
            .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    }
    Ok(())
}

/// Collective write: every rank passes its own frames (possibly none)
/// and the file holds them in rank order.
#[cfg(feature = "mpi")]
fn write_con_mpi(
    py: Python<'_>,
    path: &str,
    frames: &[ConFrame],
    precision: Option<usize>,
    comm: &Bound<'_, PyAny>,
    mode: &str,
) -> PyResult<()> {
    use crate::distrib_write::WriteMode;
    let mode = match mode {
        "auto" => WriteMode::Auto,
        "mpiio" => WriteMode::MpiIo,
        "gather" => WriteMode::Gather,
        m => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown write mode {m:?}; use \"auto\", \"mpiio\" or \"gather\""
            )));
        }
    };
    let c = comm_from_py(comm)?;
    let _ = py;
    crate::distrib_write::write_block(&c, Path::new(path), frames, mode, precision)
        .map(|_| ())
        .map_err(|e| PyIOError::new_err(e.to_string()))
}

#[cfg(not(feature = "mpi"))]
fn write_con_mpi(
    _py: Python<'_>,
    _path: &str,
    _frames: &[ConFrame],
    _precision: Option<usize>,
    _comm: &Bound<'_, PyAny>,
    _mode: &str,
) -> PyResult<()> {
    Err(pyo3::exceptions::PyNotImplementedError::new_err(
        "comm= needs readcon built with the mpi feature",
    ))
}

/// Write frames to a string in .con format.
#[pyfunction]
#[pyo3(signature = (frames, precision=None, *, canonical=false))]
fn write_con_string(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    precision: Option<usize>,
    canonical: bool,
) -> PyResult<String> {
    let rust_frames = py_frames_to_rust(py, frames)?;
    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
            None => ConFrameWriter::new(&mut buffer),
        }
        .canonical(canonical);
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
    let frames = read_con(py, path, None, None, "auto")?;
    let n = frames.borrow(py).len_frames();
    let mut out = Vec::with_capacity(n);
    for index in 0..n {
        let frame = frames.borrow(py).frame_obj(py, index)?;
        let view = frame.borrow(py);
        out.push(ase_from_pyconframe(py, &view)?);
    }
    Ok(out)
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
    let metadata = frame.metadata_map(py)?;
    let scale = |quantity: &str, target: &str| -> PyResult<f64> {
        let source = metadata
            .get(meta::UNITS)
            .and_then(|units| units.get(quantity))
            .and_then(Value::as_str)
            .unwrap_or(target);
        crate::units::unit_conversion_factor(source, target)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    };
    let length_scale = scale("length", "angstrom")?;
    let energy_scale = scale("energy", "eV")?;
    let mass_scale = scale("mass", "amu")?;

    // Build symbols list and positions array
    let symbols: Vec<&str> = frame_atoms.iter().map(|a| a.symbol.as_str()).collect();
    let positions: Vec<[f64; 3]> = frame_atoms
        .iter()
        .map(|a| [a.x * length_scale, a.y * length_scale, a.z * length_scale])
        .collect();

    // Full row vectors retain the orientation of a triclinic cell.
    let cell = if let Some(vectors) = metadata.get(meta::LATTICE_VECTORS) {
        let mut rows: [[f64; 3]; 3] = serde_json::from_value(vectors.clone())
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        for row in &mut rows {
            for value in row {
                *value *= length_scale;
            }
        }
        rows.into_pyobject(py)?.into_any()
    } else {
        let cellpar: Vec<f64> = frame
            .cell
            .iter()
            .map(|v| v * length_scale)
            .chain(frame.angles.iter().copied())
            .collect();
        py.import("ase.geometry.cell")?
            .getattr("cellpar_to_cell")?
            .call1((cellpar,))?
    };
    let pbc: [bool; 3] = match metadata.get(meta::PBC) {
        Some(flags) => serde_json::from_value(flags.clone())
            .map_err(|error| PyValueError::new_err(error.to_string()))?,
        None => [true; 3],
    };

    let atoms = ase_atoms_cls.call(
        (),
        Some(
            &[
                ("symbols", symbols.into_pyobject(py)?.into_any()),
                ("positions", positions.into_pyobject(py)?.into_any()),
                ("cell", cell.into_any()),
                ("pbc", pbc.into_pyobject(py)?.into_any()),
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
        let masses: Vec<f64> = frame_atoms
            .iter()
            .map(|a| a.mass.unwrap_or(0.0) * mass_scale)
            .collect();
        let mass_array = np.call_method1("array", (masses,))?;
        atoms.call_method1("set_masses", (mass_array,))?;
    }

    // Set velocities if present
    if frame.has_velocities(py)? {
        let time_unit = crate::units::velocity_file_time_unit(
            frame.spec_version,
            &metadata.clone().into_iter().collect(),
            None,
        )
        .map_err(|error| PyValueError::new_err(error.to_string()))?;
        let velocity_scale = length_scale
            * crate::units::velocity_scale_to_natural(&time_unit)
                .map_err(|error| PyValueError::new_err(error.to_string()))?;
        let velocities: Vec<[f64; 3]> = frame_atoms
            .iter()
            .map(|a| {
                [
                    a.vx.unwrap_or(0.0) * velocity_scale,
                    a.vy.unwrap_or(0.0) * velocity_scale,
                    a.vz.unwrap_or(0.0) * velocity_scale,
                ]
            })
            .collect();
        let vel_array = np.call_method1("array", (velocities,))?;
        atoms.call_method1("set_velocities", (vel_array,))?;
    }

    // A stored energy is useful even when the frame has no force section.
    let energy = frame.energy(py)?.map(|value| value * energy_scale);
    if frame.has_forces(py)? || energy.is_some() {
        let ase_calc = py.import("ase.calculators.singlepoint")?;
        let kwargs = [("atoms", atoms.clone().into_any())].into_py_dict(py)?;
        if frame.has_forces(py)? {
            let force_scale = energy_scale / length_scale;
            let forces: Vec<[f64; 3]> = frame_atoms
                .iter()
                .map(|a| {
                    [
                        a.fx.unwrap_or(0.0) * force_scale,
                        a.fy.unwrap_or(0.0) * force_scale,
                        a.fz.unwrap_or(0.0) * force_scale,
                    ]
                })
                .collect();
            kwargs.set_item("forces", np.call_method1("array", (forces,))?)?;
        }
        if let Some(e) = energy {
            kwargs.set_item("energy", e)?;
            atoms.getattr("info")?.set_item("energy", e)?;
        }
        let calc = ase_calc
            .getattr("SinglePointCalculator")?
            .call((), Some(&kwargs))?;
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

    // Lines 3-4 are lengths and angles. `lengths_and_angles` has no
    // angle for a zero-length edge and returns a non-finite value. The
    // writer rebuilds those lines from `lattice_vectors`, so a zero
    // matrix would be written as a non-finite angle and rejected on read.
    // A zero edge keeps its length and takes a right angle, and that
    // matrix stays out of the metadata. Periodic flags still come from
    // the Atoms object, so a cell that was never set stays non-periodic.
    let cell_obj = ase_atoms.call_method0("get_cell")?;
    let cell_matrix = cell_obj.call_method0("tolist")?;
    let rows: [[f64; 3]; 3] = cell_matrix
        .extract()
        .map_err(|_| PyValueError::new_err("ASE cell must be a 3x3 matrix of finite numbers"))?;
    if rows.iter().flatten().any(|value| !value.is_finite()) {
        return Err(PyValueError::new_err(
            "ASE cell must be a 3x3 matrix of finite numbers",
        ));
    }
    let (lengths, raw_angles) = crate::types::lengths_and_angles(rows);
    if lengths.iter().any(|length| !length.is_finite()) {
        return Err(PyValueError::new_err("ASE cell lengths must be finite"));
    }
    let angles_defined = raw_angles.iter().all(|angle| angle.is_finite());
    let (cell, angles) = if angles_defined {
        let cellpar: Vec<f64> = cell_obj
            .call_method0("cellpar")?
            .call_method0("tolist")?
            .extract()?;
        if cellpar.len() == 6 && cellpar.iter().all(|value| value.is_finite()) {
            ([cellpar[0], cellpar[1], cellpar[2]], [
                cellpar[3], cellpar[4], cellpar[5],
            ])
        } else {
            (lengths, raw_angles)
        }
    } else {
        (lengths, [
            if raw_angles[0].is_finite() {
                raw_angles[0]
            } else {
                90.0
            },
            if raw_angles[1].is_finite() {
                raw_angles[1]
            } else {
                90.0
            },
            if raw_angles[2].is_finite() {
                raw_angles[2]
            } else {
                90.0
            },
        ])
    };

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
        // Tags label groups (slab layers, adsorbates) and repeat freely;
        // only a set of distinct non-negative tags can stand in for ids.
        let distinct = {
            let mut seen = std::collections::HashSet::with_capacity(tags.len());
            tags.iter().all(|&t| t >= 0 && seen.insert(t))
        };
        if tags.len() == n_atoms && tags.iter().any(|&t| t != 0) && distinct {
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
                charge: None,
                spin: None,
                mx: None,
                my: None,
                mz: None,
                dx: None,
                dy: None,
                dz: None,
                sx: None,
                sy: None,
                sz: None,
            }
        })
        .collect();

    let metadata = PyDict::new(py);
    metadata.set_item(meta::PBC, ase_atoms.getattr("pbc")?.call_method0("tolist")?)?;
    if angles_defined {
        metadata.set_item(meta::LATTICE_VECTORS, cell_matrix)?;
    }
    metadata.set_item(
        meta::UNITS,
        [
            ("length", "angstrom"),
            ("energy", "eV"),
            ("mass", "amu"),
            ("time", crate::units::NATURAL_TIME_UNIT),
        ]
        .into_py_dict(py)?,
    )?;
    Ok(PyConFrame {
        cell,
        angles,
        prebox_header: Default::default(),
        postbox_header: Default::default(),
        atoms: py_atoms_to_list(py, atoms)?,
        atoms_ready: std::sync::atomic::AtomicBool::new(true),
        spec_version: crate::CON_SPEC_VERSION,
        metadata: metadata.unbind(),
        inner: None,
        n_atoms,
        slab: None,
        slab_index: 0,
        xyz_owned: None,
    })
}

/// Atomic number for a chemical symbol, or the sentinel 0 if unknown.
///
/// Coverage is hydrogen through uranium (Z = 92) plus the hydrogen
/// isotopes deuterium (``D``) and tritium (``T``), both of which map
/// to Z = 1. The reverse map always returns ``H`` for Z = 1; isotope
/// identity is out of band.
///
/// The table stops at Z = 92. Transuranic symbols (``Np`` and above),
/// lowercase tokens, ghost-atom placeholders, and any other unknown
/// string return the sentinel 0. There is no in-tree standard-mass
/// table; this helper returns Z only.
#[pyfunction]
fn symbol_to_atomic_number(symbol: &str) -> u64 {
    crate::helpers::symbol_to_atomic_number(symbol)
}

/// Chemical symbol for an atomic number, or the sentinel ``X`` if unknown.
///
/// Coverage is Z = 1 through the Z = 92 ceiling (H through U). Z = 1
/// returns ``H``, not ``D`` or ``T``. Values outside that range,
/// including the sentinel 0 and anything above Z = 92, return the
/// sentinel ``X``. There is no in-tree standard-mass table; this
/// helper returns the symbol only.
#[pyfunction]
fn atomic_number_to_symbol(atomic_number: u64) -> &'static str {
    crate::helpers::atomic_number_to_symbol(atomic_number)
}

/// The `MAP_PRIVATE` map behind the arrays `read_conbin` returns.
///
/// Both arrays hold this object as their NumPy base. The map is dropped,
/// and the address range is unmapped, when the last array is freed.
#[pyclass]
struct ConBinMapping {
    #[allow(dead_code)]
    map: memmap2::MmapMut,
}

fn arrays_from_map<'py, T>(
    py: Python<'py>,
    map: memmap2::MmapMut,
    pos: *const T,
    vel: *const T,
    n_frames: usize,
    width: usize,
    n_atoms: usize,
) -> PyResult<(Bound<'py, PyArray2<T>>, Bound<'py, PyArray2<T>>, usize)>
where
    T: numpy::Element,
{
    let owner = Py::new(py, ConBinMapping { map })?;
    let base = owner.bind(py).clone();
    let shape = (n_frames, width);
    // SAFETY: `pos` and `vel` address `n_frames * width` elements inside `map`.
    // `owner` keeps that map alive for as long as either array does, because
    // each array stores `owner` as its NumPy base.
    let (pos_arr, vel_arr) = unsafe {
        let pos_view = ArrayView2::from_shape_ptr(shape, pos);
        let vel_view = ArrayView2::from_shape_ptr(shape, vel);
        let pos_arr = PyArray2::borrow_from_array(&pos_view, base.clone().into_any());
        let vel_arr = PyArray2::borrow_from_array(&vel_view, base.into_any());
        (pos_arr, vel_arr)
    };
    Ok((pos_arr, vel_arr, n_atoms))
}

/// Read a CON-bin file as one writable position array and one writable
/// velocity array.
///
/// The arrays are a `MAP_PRIVATE` copy-on-write view of the file. A store
/// copies that page and does not modify the file. The map is the NumPy base
/// of both arrays and stays mapped until both arrays are freed.
#[pyfunction]
#[pyo3(signature = (path, n_threads=1))]
fn read_conbin<'py>(
    py: Python<'py>,
    path: &str,
    n_threads: usize,
) -> PyResult<(Bound<'py, PyArray2<f64>>, Bound<'py, PyArray2<f64>>, usize)> {
    let path_owned = path.to_owned();
    let mapped = py
        .detach(|| crate::conbin::map_file(Path::new(&path_owned), n_threads))
        .map_err(|e| PyIOError::new_err(e.to_string()))?;
    if mapped.header.binary32 {
        return Err(PyValueError::new_err(
            "CON-bin file is binary32; use read_conbin_f32",
        ));
    }
    if !mapped.header.velocities {
        return Err(PyValueError::new_err("CON-bin file has no velocity run"));
    }
    let n_frames = mapped.header.n_frames as usize;
    let n_atoms = mapped.header.n_atoms as usize;
    let width = n_atoms * 3;
    let n = mapped
        .header
        .position_len()
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    if n == 0 {
        return Ok((
            PyArray2::zeros(py, (n_frames, width), false),
            PyArray2::zeros(py, (n_frames, width), false),
            n_atoms,
        ));
    }
    let pos_ptr = mapped
        .positions_f64()
        .map_err(|e| PyValueError::new_err(e.to_string()))?
        .as_ptr();
    let vel_ptr = mapped
        .velocities_f64()
        .map_err(|e| PyValueError::new_err(e.to_string()))?
        .as_ptr();
    arrays_from_map(py, mapped.map, pos_ptr, vel_ptr, n_frames, width, n_atoms)
}

/// Stream a CON text file into a CON-bin. One frame is parsed at a time.
#[pyfunction]
#[pyo3(signature = (con_path, out_path, binary32=false))]
fn write_conbin(
    py: Python<'_>,
    con_path: &str,
    out_path: &str,
    binary32: bool,
) -> PyResult<(u64, u64)> {
    let con_path = con_path.to_owned();
    let out_path = out_path.to_owned();
    let header = py
        .detach(|| {
            crate::conbin::write_from_con(Path::new(&con_path), Path::new(&out_path), binary32)
                .map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)?;
    Ok((header.n_frames, header.n_atoms))
}

/// readcon Python module implemented in Rust.
#[pymodule]
fn readcon(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("CON_SPEC_VERSION", crate::CON_SPEC_VERSION)?;
    m.add_class::<PyAtomDatum>()?;
    m.add_class::<PyConFrame>()?;
    m.add_class::<PyConFrameIterator>()?;
    m.add_class::<PyConTrajectory>()?;
    m.add_class::<PyConTrajectoryIter>()?;
    m.add_class::<ConFrameList>()?;
    m.add_class::<ConFrameListIter>()?;
    m.add_function(wrap_pyfunction!(read_con, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_phases, m)?)?;
    m.add_function(wrap_pyfunction!(scan_probe, m)?)?;
    m.add_function(wrap_pyfunction!(read_positions, m)?)?;
    m.add_function(wrap_pyfunction!(read_coords, m)?)?;
    m.add_function(wrap_pyfunction!(write_coords, m)?)?;
    m.add_class::<ConBinMapping>()?;
    m.add_function(wrap_pyfunction!(read_conbin, m)?)?;
    m.add_function(wrap_pyfunction!(write_conbin, m)?)?;
    // Ergonomic alias for multi-language matrix (batch all frames).
    m.add_function(wrap_pyfunction!(read_all_frames, m)?)?;
    m.add_function(wrap_pyfunction!(read_first_frame, m)?)?;
    m.add_function(wrap_pyfunction!(iter_con, m)?)?;
    m.add_function(wrap_pyfunction!(count_frames, m)?)?;
    m.add_function(wrap_pyfunction!(read_nth_frame, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(write_con, m)?)?;
    m.add_function(wrap_pyfunction!(write_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(convert_to_con, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_as_ase, m)?)?;
    m.add_function(wrap_pyfunction!(has_chemfiles_support, m)?)?;
    m.add_function(wrap_pyfunction!(has_parallel_support, m)?)?;
    m.add_function(wrap_pyfunction!(has_mpi_support, m)?)?;
    m.add_function(wrap_pyfunction!(read_pdb, m)?)?;
    m.add_function(wrap_pyfunction!(read_extxyz, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles_first, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles_nth, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles_nsteps, m)?)?;
    m.add_function(wrap_pyfunction!(read_chemfiles_memory, m)?)?;
    m.add_function(wrap_pyfunction!(select_on_frame, m)?)?;
    m.add_function(wrap_pyfunction!(select_atom_indices, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_selection_on_frames, m)?)?;
    m.add_function(wrap_pyfunction!(select_atom_positions_on_frames, m)?)?;
    m.add_function(wrap_pyfunction!(symbol_to_atomic_number, m)?)?;
    m.add_function(wrap_pyfunction!(atomic_number_to_symbol, m)?)?;
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

#[pyfunction]
fn has_parallel_support() -> bool {
    cfg!(feature = "parallel")
}

/// True when built with the `mpi` feature (`comm=` on read and write).
#[pyfunction]
fn has_mpi_support() -> bool {
    cfg!(feature = "mpi")
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

fn chemfiles_opts_from_kwargs(
    skip: usize,
    step: usize,
    stop: Option<usize>,
    topology: Option<&str>,
    format: Option<&str>,
    guess_bonds: bool,
) -> crate::chemfiles_import::ChemfilesReadOpts {
    crate::chemfiles_import::ChemfilesReadOpts {
        start: skip,
        step,
        stop,
        format: format.map(str::to_string),
        topology: topology.map(std::path::PathBuf::from),
        topology_format: None,
        guess_bonds,
    }
}

/// Read an extended XYZ file into positions, masses and the cell.
///
/// The comment line gives the lattice and the column order. Positions
/// have shape `(frames, atoms, 3)`. Masses have shape `(frames, atoms)`.
/// The cell has shape `(frames, 6)`.
#[pyfunction]
fn read_extxyz<'py>(
    py: Python<'py>,
    path: &str,
) -> PyResult<(
    Bound<'py, numpy::PyArray3<f64>>,
    Bound<'py, numpy::PyArray2<f64>>,
    Bound<'py, numpy::PyArray2<f64>>,
)> {
    let tables = crate::extxyz_scan::tables_from_extxyz_path(std::path::Path::new(path))
        .map_err(|err| pyo3::exceptions::PyValueError::new_err(err))?;
    let positions =
        ndarray::Array3::from_shape_vec((tables.n_frames, tables.n_atoms, 3), tables.positions)
            .map_err(|err| pyo3::exceptions::PyValueError::new_err(err.to_string()))?;
    let masses = ndarray::Array2::from_shape_vec((tables.n_frames, tables.n_atoms), tables.masses)
        .map_err(|err| pyo3::exceptions::PyValueError::new_err(err.to_string()))?;
    let cell = ndarray::Array2::from_shape_vec((tables.n_frames, 6), tables.cell)
        .map_err(|err| pyo3::exceptions::PyValueError::new_err(err.to_string()))?;
    Ok((
        positions.into_pyarray(py),
        masses.into_pyarray(py),
        cell.into_pyarray(py),
    ))
}

/// Read a PDB file into positions, masses and the cell.
///
/// Positions have shape `(frames, atoms, 3)`. Masses have shape
/// `(frames, atoms)`. The cell has shape `(frames, 6)` and stores
/// lengths then angles. One scan fills those arrays.
#[pyfunction]
fn read_pdb<'py>(
    py: Python<'py>,
    path: &str,
) -> PyResult<(
    Bound<'py, numpy::PyArray3<f64>>,
    Bound<'py, numpy::PyArray2<f64>>,
    Bound<'py, numpy::PyArray2<f64>>,
)> {
    let tables = crate::pdb_scan::tables_from_pdb_path(std::path::Path::new(path))
        .map_err(|err| pyo3::exceptions::PyValueError::new_err(err))?;
    let positions =
        ndarray::Array3::from_shape_vec((tables.n_frames, tables.n_atoms, 3), tables.positions)
            .map_err(|err| pyo3::exceptions::PyValueError::new_err(err.to_string()))?;
    let masses = ndarray::Array2::from_shape_vec((tables.n_frames, tables.n_atoms), tables.masses)
        .map_err(|err| pyo3::exceptions::PyValueError::new_err(err.to_string()))?;
    let cell = ndarray::Array2::from_shape_vec((tables.n_frames, 6), tables.cell)
        .map_err(|err| pyo3::exceptions::PyValueError::new_err(err.to_string()))?;
    Ok((
        positions.into_pyarray(py),
        masses.into_pyarray(py),
        cell.into_pyarray(py),
    ))
}

/// Read frames from a chemfiles-supported path (XYZ, PDB, GRO, …)
/// into CON :class:`ConFrame` values.
///
/// Chemfiles chooses the reader from the path (or ``format``). Topology
/// becomes optional ``metadata['bonds']`` and ``metadata['chemfiles_residues']``
/// when present. Line-2 ``units`` is chemfiles internal (Å, ps, amu).
///
/// ``skip`` / ``step`` / ``stop`` map to chemfiles ``Trajectory.read_step``.
/// ``topology`` is a companion topology file (``set_topology_file``).
/// ``guess_bonds`` calls chemfiles bond guessing when the frame has none.
///
/// Raises ``RuntimeError`` if this wheel was built without chemfiles (install
/// ``readcon-chemfiles``), ``OSError`` on I/O failure, ``ValueError`` on bad frames.
#[pyfunction]
#[pyo3(signature = (path, *, skip=0, step=1, stop=None, topology=None, format=None, guess_bonds=false))]
fn read_chemfiles(
    py: Python<'_>,
    path: &str,
    skip: usize,
    step: usize,
    stop: Option<usize>,
    topology: Option<&str>,
    format: Option<&str>,
    guess_bonds: bool,
) -> PyResult<Vec<PyConFrame>> {
    use crate::chemfiles_import::con_frames_from_trajectory_path_with;
    let opts = chemfiles_opts_from_kwargs(skip, step, stop, topology, format, guess_bonds);
    let frames = con_frames_from_trajectory_path_with(Path::new(path), &opts)
        .map_err(chemfiles_err_to_py)?;
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

/// Read step ``index`` via chemfiles ``Trajectory.read_step``.
#[pyfunction]
fn read_chemfiles_nth(py: Python<'_>, path: &str, index: usize) -> PyResult<PyConFrame> {
    use crate::chemfiles_import::con_frame_from_trajectory_path_nth;
    let frame =
        con_frame_from_trajectory_path_nth(Path::new(path), index).map_err(chemfiles_err_to_py)?;
    PyConFrame::from_con_frame(py, &frame)
}

/// Number of steps in a chemfiles trajectory (``Trajectory.nsteps``).
#[pyfunction]
fn read_chemfiles_nsteps(path: &str) -> PyResult<usize> {
    use crate::chemfiles_import::nsteps_from_trajectory_path;
    nsteps_from_trajectory_path(Path::new(path)).map_err(chemfiles_err_to_py)
}

/// Read frames from an in-memory trajectory buffer.
///
/// ``format`` is a chemfiles format name such as ``"XYZ"``, ``"PDB"``, or ``"GRO"``.
#[pyfunction]
#[pyo3(signature = (data, format, *, skip=0, step=1, stop=None, guess_bonds=false))]
fn read_chemfiles_memory(
    py: Python<'_>,
    data: &str,
    format: &str,
    skip: usize,
    step: usize,
    stop: Option<usize>,
    guess_bonds: bool,
) -> PyResult<Vec<PyConFrame>> {
    use crate::chemfiles_import::con_frames_from_memory_with;
    let opts = chemfiles_opts_from_kwargs(skip, step, stop, None, None, guess_bonds);
    let frames = con_frames_from_memory_with(data, format, &opts).map_err(chemfiles_err_to_py)?;
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
fn select_atom_indices(
    py: Python<'_>,
    frame: &PyConFrame,
    selection: &str,
) -> PyResult<Vec<usize>> {
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
    seq.iter().map(|f| f.to_con_frame(py)).collect()
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
