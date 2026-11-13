use ndarray::{Array2, Array3, ArrayView2};
use numpy::{
    IntoPyArray, PyArray1, PyArray2, PyArray3, PyArrayMethods, PyReadonlyArray2, PyReadonlyArray3,
};
use pyo3::IntoPyObjectExt;
use pyo3::exceptions::PyIOError;
use pyo3::exceptions::PyTypeError;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{IntoPyDict, PyDict, PyIterator, PyList, PySequence, PySlice, PyString, PyTuple};
use serde_json::{Number, Value};
use std::collections::BTreeMap;
use std::path::Path;

use crate::error::ParseError;
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
            x: atom.x(),
            y: atom.y(),
            z: atom.z(),
            fixed: atom.fixed(),
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
        Ok(self.py_atoms(py)?.iter().any(PyAtomDatum::has_velocity))
    }

    #[getter]
    fn has_forces(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self.py_atoms(py)?.iter().any(PyAtomDatum::has_forces))
    }

    #[getter]
    fn has_displacements(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self.py_atoms(py)?.iter().any(PyAtomDatum::has_displacement))
    }

    #[getter]
    fn has_spreads(&self, py: Python<'_>) -> PyResult<bool> {
        Ok(self.py_atoms(py)?.iter().any(PyAtomDatum::has_spread))
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
            let n = frame.velocities.nrows();
            if n == 0 {
                return Ok(None);
            }
            let mut data = Vec::with_capacity(n.saturating_mul(3));
            if let Some(src) = frame.velocities.f64_slice() {
                data.extend_from_slice(src);
            } else {
                for i in 0..n {
                    data.extend_from_slice(&frame.velocities.as_f64_row(i));
                }
            }
            let array = Array2::from_shape_vec((n, 3), data)
                .map_err(|e| PyValueError::new_err(format!("vel shape error: {e}")))?;
            return Ok(Some(array.into_pyarray(py)));
        }
        self.velocities_array(py)
    }

    #[getter]
    fn frc<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        if let Some(frame) = self.inner.as_ref() {
            let n = frame.forces.nrows();
            if n == 0 {
                return Ok(None);
            }
            let mut data = Vec::with_capacity(n.saturating_mul(3));
            if let Some(src) = frame.forces.f64_slice() {
                data.extend_from_slice(src);
            } else {
                for i in 0..n {
                    data.extend_from_slice(&frame.forces.as_f64_row(i));
                }
            }
            let array = Array2::from_shape_vec((n, 3), data)
                .map_err(|e| PyValueError::new_err(format!("frc shape error: {e}")))?;
            return Ok(Some(array.into_pyarray(py)));
        }
        self.forces_array(py)
    }

    /// Returns the per-atom xyz positions as a contiguous numpy
    /// `[N, 3] float64` array, in the type-grouped order used by the
    /// underlying frame.
    ///
    /// Always allocates a **fresh** array from the current Python atom list so
    /// in-place mutation of a previous return value cannot corrupt later
    /// calls, and edits to `atoms` are reflected immediately.
    fn coords_array<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray2<f64>>> {
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
        if !atoms.iter().any(PyAtomDatum::has_velocity) {
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
    fn forces_array<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.iter().any(PyAtomDatum::has_forces) {
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

    /// Returns the per-atom displacements (Angstrom) as a contiguous
    /// numpy `[N, 3] float64` array, or `None` when the frame declares no
    /// `"displacements"` section. A normal mode, a dimer direction.
    fn displacements_array<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let atoms = self.py_atoms(py)?;
        if !atoms.iter().any(PyAtomDatum::has_displacement) {
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
        if !atoms.iter().any(PyAtomDatum::has_spread) {
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
        if !atoms.iter().any(PyAtomDatum::has_energy) {
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
            if let Ok(pair) = item.cast::<pyo3::types::PyList>()
                && pair.len() == 2
            {
                let i: u32 = pair.get_item(0)?.extract()?;
                let j: u32 = pair.get_item(1)?.extract()?;
                out.push((i, j).into_pyobject(py)?.into_any().unbind());
                continue;
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
                if let Some(order_v) = obj.get_item("order")?
                    && !order_v.is_none()
                {
                    let order: i32 = order_v.extract()?;
                    out.push((i, j, order).into_pyobject(py)?.into_any().unbind());
                    continue;
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
        write_stamped_frame(&mut writer, &frame).map_err(|e| write_err_to_py(py, e))?;
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
                .into_pyarray(py);
            // Atom slots alias `frame.positions`. The NumPy array is the
            // coordinate storage for this frame, so retarget before the
            // parse buffer is dropped. Otherwise the first coordinate read
            // back is freed memory.
            if n_atoms > 0 {
                let base = {
                    let contiguous = unsafe { xyz.as_slice() }.map_err(|err| {
                        pyo3::exceptions::PyValueError::new_err(format!(
                            "frame coordinates are not contiguous: {err}"
                        ))
                    })?;
                    contiguous.as_ptr() as *mut f64
                };
                retarget_frames_to_slab(std::slice::from_mut(&mut frame), base, n_atoms);
            }
            frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
            Some(xyz.unbind())
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
        let metadata_map = frame.header.metadata.to_map();
        let metadata = json_map_to_py_dict(py, &metadata_map)?;
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
        let metadata_map = frame.header.metadata.to_map();
        let metadata = json_map_to_py_dict(py, &metadata_map)?;
        // Coordinates live in the slab. Atom slots still alias the parse
        // buffer, so point them at this frame's row before that buffer goes.
        if n_atoms > 0 {
            let origin = {
                let bound = slab.bind(py);
                let contiguous = unsafe { bound.as_slice() }.map_err(|err| {
                    pyo3::exceptions::PyValueError::new_err(format!(
                        "coordinate slab is not contiguous: {err}"
                    ))
                })?;
                let stride = n_atoms.saturating_mul(3);
                unsafe { contiguous.as_ptr().add(index.saturating_mul(stride)) as *mut f64 }
            };
            retarget_frames_to_slab(std::slice::from_mut(&mut frame), origin, n_atoms);
        }
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
            .map_err(|e| parse_err_to_py(py, &e, e.line(), 0))
    }
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
            metadata: crate::types::FrameMeta::from_map(metadata),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: true,
        },
        atom_data,
        column_tails: Vec::new(),
        positions: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        ),
        velocities: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        )
        .into(),
        forces: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        )
        .into(),
        atom_energies: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        )
        .into(),
        charges: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        )
        .into(),
        spins: crate::storage_dtype::Array1Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
        )
        .into(),
        magmoms: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        )
        .into(),
        displacements: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        )
        .into(),
        spreads: crate::storage_dtype::Array2Storage::zeros(
            crate::storage_dtype::ElementKind::Float64,
            0,
            3,
        )
        .into(),
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
/// coordinate block moved into NumPy. Per-frame cell, masses, column 5, and
/// the fixed mask travel beside that array. `species` is one `(symbol, count)`
/// run-length list when every frame uses that element order, and one list per
/// frame when a later frame does not. `parse_s`, `convert_s` and `copy_s`
/// split the time.
#[pyfunction]
fn read_coords(py: Python<'_>, path: &str) -> PyResult<Py<PyDict>> {
    let path_owned = path.to_owned();
    let parse_start = std::time::Instant::now();
    let columns = py
        .detach(|| {
            crate::iterators::read_coord_columns(Path::new(&path_owned), None)
                .map_err(box_to_count_fail)
        })
        .map_err(count_fail_to_py)?;
    let parse_s = parse_start.elapsed().as_secs_f64();
    let convert_start = std::time::Instant::now();
    let n_frames = columns.block.n_frames;
    let n_atoms = columns.block.n_atoms;
    if columns.masses.len() != n_frames * n_atoms || columns.cells.len() != n_frames * 6 {
        return Err(PyValueError::new_err(
            "read_coords needs the same atom count in every frame",
        ));
    }
    let positions = columns.block.values;
    let masses = columns.masses;
    let cell = columns.cells;
    let atom_ids = columns.atom_ids;
    let fixed = columns.fixed;
    let species = columns.species;
    let has_section = columns.has_section;
    let partial_fixed = columns.partial_fixed;
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
    if atom_ids.len() == n_frames * n_atoms && fixed.len() == n_frames * n_atoms {
        let ids = ndarray::Array2::from_shape_vec((n_frames, n_atoms), atom_ids)
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        let mask = ndarray::Array2::from_shape_vec((n_frames, n_atoms), fixed)
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        dict.set_item("atom_ids", ids.into_pyarray(py))?;
        dict.set_item("fixed", mask.into_pyarray(py))?;
    }
    dict.set_item("species", species)?;
    dict.set_item("has_section", has_section)?;
    dict.set_item("partial_fixed", partial_fixed)?;
    dict.set_item("n_frames", n_frames)?;
    dict.set_item("n_atoms", n_atoms)?;
    dict.set_item("parse_s", parse_s)?;
    dict.set_item("convert_s", convert_s)?;
    let copy_s = copy_start.elapsed().as_secs_f64();
    dict.set_item("copy_s", copy_s)?;
    Ok(dict.unbind())
}

struct PackedColumns {
    n_frames: usize,
    n_atoms: usize,
    positions: Vec<f64>,
    masses: Vec<f64>,
    fixed: Vec<f64>,
    cell: Vec<f64>,
    velocities: Option<Vec<f64>>,
    forces: Option<Vec<f64>>,
}

fn frame_has_vel(frame: &ConFrame) -> bool {
    frame.velocities.nrows() == frame.atom_data.len() && !frame.atom_data.is_empty()
        || frame
            .atom_data
            .first()
            .is_some_and(|atom| atom.has_velocity())
}

fn frame_has_force(frame: &ConFrame) -> bool {
    frame.forces.nrows() == frame.atom_data.len() && !frame.atom_data.is_empty()
        || frame
            .atom_data
            .first()
            .is_some_and(|atom| atom.has_forces())
}

fn push_masses(frame: &ConFrame, into: &mut Vec<f64>) {
    if let Some(slice) = frame.masses.f64_slice() {
        if slice.len() == frame.atom_data.len() {
            into.extend_from_slice(slice);
            return;
        }
    }
    let mut written = 0usize;
    for (type_idx, &count) in frame.header.natms_per_type.iter().enumerate() {
        let mass = frame
            .header
            .masses_per_type
            .get(type_idx)
            .copied()
            .unwrap_or(0.0);
        into.extend(std::iter::repeat_n(mass, count));
        written += count;
    }
    if written < frame.atom_data.len() {
        let mass = *into.last().unwrap_or(&0.0);
        into.extend(std::iter::repeat_n(mass, frame.atom_data.len() - written));
    }
}

fn push_vec3(
    storage: &crate::storage_dtype::Array2Storage,
    frame: &ConFrame,
    into: &mut Vec<f64>,
    from_atom: impl Fn(&crate::types::AtomDatum) -> Option<[f64; 3]>,
) {
    let n = frame.atom_data.len();
    if let Some(slice) = storage.f64_slice() {
        if slice.len() == n * 3 {
            into.extend_from_slice(slice);
            return;
        }
    }
    if storage.nrows() == n {
        for row in 0..n {
            into.extend_from_slice(&storage.as_f64_row(row));
        }
        return;
    }
    for atom in &frame.atom_data {
        into.extend_from_slice(&from_atom(atom).unwrap_or([0.0; 3]));
    }
}

fn pack_frame_columns<'a>(
    frames: impl Iterator<Item = &'a ConFrame>,
    pack_positions: bool,
) -> Option<PackedColumns> {
    let frames: Vec<&ConFrame> = frames.collect();
    if frames.is_empty() {
        return Some(PackedColumns {
            n_frames: 0,
            n_atoms: 0,
            positions: Vec::new(),
            masses: Vec::new(),
            fixed: Vec::new(),
            cell: Vec::new(),
            velocities: None,
            forces: None,
        });
    }
    let n_atoms = frames[0].atom_data.len();
    if frames.iter().any(|frame| frame.atom_data.len() != n_atoms) {
        return None;
    }
    let n_frames = frames.len();
    let mut masses = Vec::with_capacity(n_frames * n_atoms);
    let mut fixed = Vec::with_capacity(n_frames * n_atoms * 3);
    let mut cell = Vec::with_capacity(n_frames * 6);
    let mut positions = Vec::new();
    if pack_positions {
        positions.reserve(n_frames * n_atoms * 3);
    }
    let any_vel = frames.iter().any(|frame| frame_has_vel(frame));
    let any_force = frames.iter().any(|frame| frame_has_force(frame));
    let mut velocities = any_vel.then(|| Vec::with_capacity(n_frames * n_atoms * 3));
    let mut forces = any_force.then(|| Vec::with_capacity(n_frames * n_atoms * 3));
    for frame in frames {
        if pack_positions {
            for atom in &frame.atom_data {
                positions.extend_from_slice(&[atom.x(), atom.y(), atom.z()]);
            }
        }
        push_masses(frame, &mut masses);
        for atom in &frame.atom_data {
            let flags = atom.fixed();
            fixed.push(if flags[0] { 1.0 } else { 0.0 });
            fixed.push(if flags[1] { 1.0 } else { 0.0 });
            fixed.push(if flags[2] { 1.0 } else { 0.0 });
        }
        cell.extend_from_slice(&frame.header.boxl);
        cell.extend_from_slice(&frame.header.angles);
        if let Some(dest) = velocities.as_mut() {
            push_vec3(&frame.velocities, frame, dest, |atom| atom.velocity());
        }
        if let Some(dest) = forces.as_mut() {
            push_vec3(&frame.forces, frame, dest, |atom| atom.force());
        }
    }
    Some(PackedColumns {
        n_frames,
        n_atoms,
        positions,
        masses,
        fixed,
        cell,
        velocities,
        forces,
    })
}

/// Write one contiguous column dict, the shape returned by
/// ``ConFrameList.columns``.
///
/// Arrays are borrowed once. Frame shells are built and the file is
/// formatted with the GIL released. There is no per-atom Python loop.
#[pyfunction]
#[pyo3(signature = (path, columns, symbol="Cu", n_threads=None))]
fn write_columns(
    py: Python<'_>,
    path: &str,
    columns: &Bound<'_, PyDict>,
    symbol: &str,
    n_threads: Option<usize>,
) -> PyResult<()> {
    let positions = columns
        .get_item("positions")?
        .ok_or_else(|| PyValueError::new_err("positions"))?;
    let masses = columns
        .get_item("masses")?
        .ok_or_else(|| PyValueError::new_err("masses"))?;
    let cell = columns
        .get_item("cell")?
        .ok_or_else(|| PyValueError::new_err("cell"))?;
    let pos = positions.cast::<PyArray3<f64>>()?.readonly();
    let mass = masses.cast::<PyArray2<f64>>()?.readonly();
    let cell_arr = cell.cast::<PyArray2<f64>>()?.readonly();
    let shape = pos.dims();
    if shape[2] != 3 {
        return Err(PyValueError::new_err("positions"));
    }
    let n_frames = shape[0];
    let n_atoms = shape[1];
    let pos_slice = pos.as_slice()?;
    let mass_slice = mass.as_slice()?;
    let cell_slice = cell_arr.as_slice()?;
    if mass_slice.len() != n_frames.saturating_mul(n_atoms)
        || cell_slice.len() != n_frames.saturating_mul(6)
    {
        return Err(PyValueError::new_err("positions, masses and cell disagree"));
    }
    let fixed_owned = match columns.get_item("fixed")? {
        Some(value) if !value.is_none() => {
            let arr = value.cast::<PyArray3<f64>>()?.readonly();
            let slice = arr.as_slice()?;
            if slice.len() != n_frames.saturating_mul(n_atoms).saturating_mul(3) {
                return Err(PyValueError::new_err("fixed"));
            }
            Some(slice.to_vec())
        }
        _ => None,
    };
    let vel_owned = optional_vec3(columns, "velocities", n_frames, n_atoms)?;
    let force_owned = optional_vec3(columns, "forces", n_frames, n_atoms)?;
    // Copy before the file write. The NumPy borrows must not stay alive
    // across `detach`: another thread that already holds the GIL and
    // touches these arrays waits on the borrow, and this thread then
    // waits to reacquire the GIL.
    let pos_owned = pos_slice.to_vec();
    let mass_owned = mass_slice.to_vec();
    let cell_owned = cell_slice.to_vec();
    drop(pos);
    drop(mass);
    drop(cell_arr);
    let path_owned = path.to_owned();
    let symbol_owned = symbol.to_owned();
    let workers = n_threads.unwrap_or(1);
    py.detach(move || {
        let frames = frames_from_columns(
            &pos_owned,
            &mass_owned,
            &cell_owned,
            fixed_owned.as_deref(),
            vel_owned.as_deref(),
            force_owned.as_deref(),
            n_frames,
            n_atoms,
            &symbol_owned,
        )?;
        let refs: Vec<&ConFrame> = frames.iter().collect();
        crate::writer::write_frame_refs_to_path(
            Path::new(&path_owned),
            &refs,
            workers,
            None,
            false,
            true,
        )
        .map_err(|err| err.to_string())
    })
    .map_err(PyIOError::new_err)
}

fn optional_vec3(
    columns: &Bound<'_, PyDict>,
    name: &str,
    n_frames: usize,
    n_atoms: usize,
) -> PyResult<Option<Vec<f64>>> {
    match columns.get_item(name)? {
        Some(value) if !value.is_none() => {
            let arr = value.cast::<PyArray3<f64>>()?.readonly();
            let slice = arr.as_slice()?;
            if slice.len() != n_frames * n_atoms * 3 {
                return Err(PyValueError::new_err(name.to_string()));
            }
            Ok(Some(slice.to_vec()))
        }
        _ => Ok(None),
    }
}

fn frames_from_columns(
    positions: &[f64],
    masses: &[f64],
    cell: &[f64],
    fixed: Option<&[f64]>,
    velocities: Option<&[f64]>,
    forces: Option<&[f64]>,
    n_frames: usize,
    n_atoms: usize,
    symbol: &str,
) -> Result<Vec<ConFrame>, String> {
    let mut frames = Vec::with_capacity(n_frames);
    for index in 0..n_frames {
        let p = index * n_atoms * 3;
        let m = index * n_atoms;
        let c = index * 6;
        frames.push(frame_from_column_slice(
            &positions[p..p + n_atoms * 3],
            &masses[m..m + n_atoms],
            &cell[c..c + 6],
            fixed.map(|flags| &flags[p..p + n_atoms * 3]),
            velocities.map(|vals| &vals[p..p + n_atoms * 3]),
            forces.map(|vals| &vals[p..p + n_atoms * 3]),
            symbol,
        )?);
    }
    Ok(frames)
}

fn frame_from_column_slice(
    positions: &[f64],
    masses: &[f64],
    cell: &[f64],
    fixed: Option<&[f64]>,
    velocities: Option<&[f64]>,
    forces: Option<&[f64]>,
    symbol: &str,
) -> Result<ConFrame, String> {
    let n = masses.len();
    if positions.len() != n * 3 || cell.len() != 6 || n == 0 {
        return Err("positions, masses and cell disagree".to_string());
    }
    let shared: std::sync::Arc<str> = std::sync::Arc::from(symbol);
    let (type_counts, type_masses) = mass_runs(masses);
    let mut metadata = BTreeMap::new();
    metadata.insert(meta::CON_SPEC_MINOR.to_string(), serde_json::json!(1));
    metadata.insert(meta::CON_SPEC_VERSION.to_string(), serde_json::json!(2));
    let mut pos_storage = crate::storage_dtype::Array2Storage::zeros_f64(n, 3);
    for i in 0..n {
        let base = i * 3;
        pos_storage.set_f64_row(
            i,
            [positions[base], positions[base + 1], positions[base + 2]],
        );
    }
    let slot = pos_storage.f64_slice().ok_or("positions")?.as_ptr() as *mut f64;
    let mut atom_data = Vec::with_capacity(n);
    for i in 0..n {
        let flags = match fixed {
            Some(flags) => {
                let base = i * 3;
                [
                    flags[base] != 0.0,
                    flags[base + 1] != 0.0,
                    flags[base + 2] != 0.0,
                ]
            }
            None => [false, false, false],
        };
        let atom = crate::types::AtomDatum::at_slot(
            std::sync::Arc::clone(&shared),
            unsafe { slot.add(i * 3) },
            flags,
            i as u64,
        );
        atom_data.push(atom);
    }
    if let Some(vel) = velocities {
        for (i, atom) in atom_data.iter_mut().enumerate() {
            let base = i * 3;
            atom.set_velocity(Some([vel[base], vel[base + 1], vel[base + 2]]));
        }
    }
    if let Some(force) = forces {
        for (i, atom) in atom_data.iter_mut().enumerate() {
            let base = i * 3;
            atom.set_force(Some([force[base], force[base + 1], force[base + 2]]));
        }
    }
    let mut velocities_storage = crate::storage_dtype::Array2Storage::zeros_f64(0, 3);
    if velocities.is_some() {
        velocities_storage = crate::storage_dtype::Array2Storage::zeros_f64(n, 3);
        for i in 0..n {
            let base = i * 3;
            let vel = velocities.unwrap();
            velocities_storage.set_f64_row(i, [vel[base], vel[base + 1], vel[base + 2]]);
        }
    }
    let mut forces_storage = crate::storage_dtype::Array2Storage::zeros_f64(0, 3);
    if let Some(force) = forces {
        forces_storage = crate::storage_dtype::Array2Storage::zeros_f64(n, 3);
        for i in 0..n {
            let base = i * 3;
            forces_storage.set_f64_row(i, [force[base], force[base + 1], force[base + 2]]);
        }
    }
    Ok(ConFrame {
        header: crate::types::FrameHeader {
            prebox_header: crate::types::PreboxHeader::new("readcon"),
            boxl: [cell[0], cell[1], cell[2]],
            angles: [cell[3], cell[4], cell[5]],
            postbox_header: ["0 0".to_string(), "0 0".to_string()],
            natm_types: type_counts.len(),
            natms_per_type: type_counts,
            masses_per_type: type_masses,
            spec_version: 2,
            metadata: crate::types::FrameMeta::from_map(metadata),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: true,
        },
        atom_data,
        column_tails: Vec::new(),
        positions: pos_storage,
        velocities: velocities_storage.into(),
        forces: forces_storage.into(),
        atom_energies: crate::storage_dtype::Array1Storage::zeros_f64(0).into(),
        charges: crate::storage_dtype::Array1Storage::zeros_f64(0).into(),
        spins: crate::storage_dtype::Array1Storage::zeros_f64(0).into(),
        magmoms: crate::storage_dtype::Array2Storage::zeros_f64(0, 3).into(),
        displacements: crate::storage_dtype::Array2Storage::zeros_f64(0, 3).into(),
        spreads: crate::storage_dtype::Array2Storage::zeros_f64(0, 3).into(),
        masses: crate::storage_dtype::Array1Storage::from_f64_vec(masses.to_vec()),
        atom_ids: ndarray::Array1::from_iter(0..n as u64).into_shared(),
    })
}

/// One CON component per run of equal masses. A uniform frame stays one
/// component. The file stores a mass per component, not per atom, so a
/// single component would keep only `masses[0]`.
fn mass_runs(masses: &[f64]) -> (Vec<usize>, Vec<f64>) {
    let mut counts = Vec::new();
    let mut values = Vec::new();
    let mut index = 0usize;
    while index < masses.len() {
        let mass = masses[index];
        let bits = mass.to_bits();
        let mut count = 1usize;
        while index + count < masses.len() && masses[index + count].to_bits() == bits {
            count += 1;
        }
        counts.push(count);
        values.push(mass);
        index += count;
    }
    (counts, values)
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
            let mut out = Vec::with_capacity(ind.slicelength);
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

    /// Positions, masses, constraint flags, cell, and any velocity or
    /// force block as one contiguous NumPy array each.
    ///
    /// `positions` is the coordinate slab from the read, the same array
    /// object on every call. The other arrays are copied from the parsed
    /// frames while this call holds the list lock and the GIL. Releasing
    /// the GIL while that lock is held deadlocks a thread that already
    /// has the GIL and is waiting to index a frame. Indexing a frame
    /// takes that frame out of the list, and a later call then fails.
    /// Call this before `frames[i]`. `write_columns` writes the dict
    /// back. Indexing a frame still builds Python atoms; this does not.
    fn columns(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let pack_positions = self.slab.is_none();
        let packed = {
            let frames = self.frames.lock().expect("frames");
            if frames.iter().any(|slot| slot.is_none()) {
                return Err(PyIOError::new_err(
                    "columns() needs every frame still stored; indexing a frame borrows it",
                ));
            }
            pack_frame_columns(
                frames.iter().map(|slot| slot.as_ref().unwrap()),
                pack_positions,
            )
        };
        let Some(packed) = packed else {
            return Err(PyValueError::new_err(
                "columns() needs the same atom count in every frame",
            ));
        };
        let dict = PyDict::new(py);
        if let Some(slab) = &self.slab {
            dict.set_item("positions", slab.clone_ref(py))?;
        } else {
            let pos = ndarray::Array3::from_shape_vec(
                (packed.n_frames, packed.n_atoms, 3),
                packed.positions,
            )
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
            dict.set_item("positions", pos.into_pyarray(py))?;
        }
        let masses =
            ndarray::Array2::from_shape_vec((packed.n_frames, packed.n_atoms), packed.masses)
                .map_err(|err| PyValueError::new_err(err.to_string()))?;
        let fixed =
            ndarray::Array3::from_shape_vec((packed.n_frames, packed.n_atoms, 3), packed.fixed)
                .map_err(|err| PyValueError::new_err(err.to_string()))?;
        let cell = ndarray::Array2::from_shape_vec((packed.n_frames, 6), packed.cell)
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        dict.set_item("masses", masses.into_pyarray(py))?;
        dict.set_item("fixed", fixed.into_pyarray(py))?;
        dict.set_item("cell", cell.into_pyarray(py))?;
        dict.set_item("n_frames", packed.n_frames)?;
        dict.set_item("n_atoms", packed.n_atoms)?;
        if let Some(values) = packed.velocities {
            let arr = ndarray::Array3::from_shape_vec((packed.n_frames, packed.n_atoms, 3), values)
                .map_err(|err| PyValueError::new_err(err.to_string()))?;
            dict.set_item("velocities", arr.into_pyarray(py))?;
        } else {
            dict.set_item("velocities", py.None())?;
        }
        if let Some(values) = packed.forces {
            let arr = ndarray::Array3::from_shape_vec((packed.n_frames, packed.n_atoms, 3), values)
                .map_err(|err| PyValueError::new_err(err.to_string()))?;
            dict.set_item("forces", arr.into_pyarray(py))?;
        } else {
            dict.set_item("forces", py.None())?;
        }
        Ok(dict.unbind())
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

/// Point coordinate slots at `base`, laid out `[frame, atom, xyz]`.
///
/// The slots alias `frame.positions` until the shared slab takes over.
/// Owned boxes are left in place: they do not alias that buffer.
fn retarget_frames_to_slab(frames: &mut [ConFrame], base: *mut f64, n_atoms: usize) {
    if n_atoms == 0 || base.is_null() {
        return;
    }
    let stride = n_atoms * 3;
    for (frame_index, frame) in frames.iter_mut().enumerate() {
        let origin = unsafe { base.add(frame_index * stride) };
        for (atom_index, atom) in frame.atom_data.iter_mut().enumerate() {
            if atom_index >= n_atoms {
                break;
            }
            atom.retarget(unsafe { origin.add(atom_index * 3) });
        }
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

#[allow(clippy::too_many_arguments)]
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
    // One wide frame already parsed into a contiguous f64 block. Moving
    // that block into the NumPy array skips the extra SoA memcpy and the
    // pointer walk that followed it.
    let adopted = if numpy_ok && n_frames == 1 {
        frames[0].positions.take_contiguous_f64()
    } else {
        None
    };
    let adopted_ptr = adopted.as_ref().map(|values| values.as_ptr());
    let packed = if adopted.is_some() {
        None
    } else if numpy_ok {
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
    let n_atoms = if let Some(values) = adopted.as_ref() {
        values.len() / 3
    } else {
        match packed.as_ref() {
            Some(values) if n_frames > 0 => values.len() / n_frames / 3,
            _ => 0,
        }
    };
    let t_build = std::time::Instant::now();
    let slab = if let Some(values) = adopted {
        Some(slab_from_values(py, values, 1, n_atoms)?)
    } else {
        match packed {
            Some(values) => Some(slab_from_values(py, values, n_frames, n_atoms)?),
            None => None,
        }
    };
    let python_build_s = t_build.elapsed().as_secs_f64();
    // The writer reads atom slots, not the empty position column. Those
    // slots have to address the slab before the parse buffer is freed.
    // An adopted buffer already has that address, so the walk is skipped.
    if let Some(slab) = &slab {
        let contiguous = unsafe { slab.bind(py).as_slice() }.map_err(|err| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "coordinate slab is not contiguous: {err}"
            ))
        })?;
        let new_ptr = contiguous.as_ptr() as *mut f64;
        if adopted_ptr != Some(new_ptr as *const f64) {
            retarget_frames_to_slab(&mut frames, new_ptr, n_atoms);
        }
    }
    let t_release = std::time::Instant::now();
    if slab.is_some() {
        py.detach(|| match pool.as_ref() {
            Some(pool) if workers >= 2 => {
                pool.install(|| clear_packed_positions(&mut frames, workers))
            }
            _ => clear_packed_positions(&mut frames, 1),
        });
    }
    let release_s = t_release.elapsed().as_secs_f64();
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
    let obj = Py::new(
        py,
        ConFrameList {
            frames: std::sync::Mutex::new(stored),
            cache: std::sync::Mutex::new(cache),
            slab,
            n_atoms,
            workers,
            phases: std::sync::Mutex::new(record),
            pool: std::sync::Mutex::new(pool),
        },
    )?;
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

#[allow(clippy::type_complexity)]
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
                .map_err(box_to_count_fail)
        })
        .map_err(count_fail_to_py)?;
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
    read_con(py, path, n_threads, comm, mode, None)
}

/// Read frames from a .con or .convel file path.
///
/// `n_threads` is `None`, `0`, or `1` for the calling thread, and
/// `n >= 2` for a Rayon pool of that size. A plain file of 64 KiB or
/// more stays mapped. `.gz` and `.zst` are chosen from the extension
/// and from the magic bytes. A pipe, including `/dev/stdin`, is read
/// through the same open: it is not mapped.
///
/// With `comm` (an mpi4py communicator, needs the `mpi` build feature)
/// this is collective and returns only this rank's block of frames;
/// concatenating the blocks of ranks `0..size` in rank order gives the
/// serial result. `mode` is `"auto"`, `"shared"` or `"scatter"`.
#[pyfunction]
#[pyo3(signature = (path, n_threads=None, *, comm=None, mode="auto", decode_threads=None))]
fn read_con(
    py: Python<'_>,
    path: &str,
    n_threads: Option<usize>,
    comm: Option<&Bound<'_, PyAny>>,
    mode: &str,
    decode_threads: Option<usize>,
) -> PyResult<Py<ConFrameList>> {
    if let Some(comm) = comm {
        return read_con_mpi(py, path, n_threads, comm, mode);
    }
    // The GIL stays released across the map, the scan, and the parse.
    // Python frame objects are built on first use.
    // `decode_threads=1` inflates a multi-member file on this thread.
    // A larger count inflates that many members at once and, when it
    // exceeds `n_threads`, parses the wide frame on the same workers.
    let parse_threads = match (n_threads, decode_threads) {
        (Some(parse), Some(decode)) if decode >= 2 => Some(parse.max(decode)),
        (parse, _) => parse,
    };
    let run = || read_con_lazy(py, path, parse_threads);
    match decode_threads {
        Some(1) => crate::compression::with_serial_decode(run),
        Some(threads) if threads >= 2 => crate::compression::with_decode_threads(threads, run),
        _ => run(),
    }
}

/// One `[frames, atoms, 3]` float64 array of coordinates.
///
/// The array is allocated once. Parsing writes each frame at its offset
/// from the boundary walk. NumPy views that buffer (`base` is the
/// container, `OWNDATA` is false). The doubles are not copied into a
/// second allocation before the function returns. No per-frame Python
/// object is built.
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
                .map_err(box_to_count_fail)
        })
        .map_err(count_fail_to_py)?;
    let array = Array3::from_shape_vec((block.n_frames, block.n_atoms, 3), block.values)
        .map_err(|e| PyValueError::new_err(format!("positions shape error: {e}")))?;
    // The coordinate buffer is already the NumPy array. Copying it into
    // the Python heap added a few milliseconds on a million-atom frame.
    Ok(PyArray3::from_owned_array(py, array).unbind())
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
    // Parse failures keep the ConError contract of the serial read: the
    // rank that met the failure raises its class with the global frame
    // index, the other ranks raise ConError; everything else is I/O.
    let t_parse = std::time::Instant::now();
    let rf =
        crate::distrib_read::read_block(&c, Path::new(path), mode, n_threads).map_err(|e| {
            match e.downcast::<crate::error::LocatedParseError>() {
                Ok(located) => located_to_py(*located),
                Err(e) if e.is::<crate::distrib_read::PeerParseError>() => {
                    ConError::new_err(e.to_string())
                }
                Err(e) => PyIOError::new_err(e.to_string()),
            }
        })?;
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
        .detach(|| crate::iterators::read_first_frame_located(Path::new(&path_owned)))
        .map_err(load_err_to_py)?;
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
            crate::iterators::frames_from_bytes_phased(owned.as_bytes(), n_threads).map_err(|e| {
                if utf8_failure(&e) {
                    return CountFail::Io(e.to_string());
                }
                let located = crate::iterators::frames_from_text_located(&owned, n_threads).err();
                if let Some(loc) = located {
                    CountFail::Parse {
                        class: loc.error.class_name(),
                        message: loc.error.to_string(),
                        line: loc.line,
                        frame: loc.frame_index,
                    }
                } else {
                    CountFail::Parse {
                        class: e.class_name(),
                        message: e.to_string(),
                        line: e.line(),
                        frame: 0,
                    }
                }
            })
        })
        .map_err(count_fail_to_py)?;
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
    /// Newlines before the next frame. A fresh cursor on the remainder
    /// reports a line within that slice; this offset makes it a file line.
    line_base: u32,
    /// 0-based index of the frame the cursor points at.
    frame_index: u64,
}

enum FrameSource {
    /// Full file text: owned, or mapped with `iter_con(path, mmap=True)`,
    /// and the byte offset of the next frame start within it.
    Text(crate::compression::ForwardText, usize),
    /// Decoded and parsed as it is read, with `iter_con(path, stream=True)`.
    Stream(std::sync::Mutex<crate::stream::ConFrameReader<Box<dyn std::io::Read + Send>>>),
}

fn stream_error(
    py: Python<'_>,
    _what: &str,
    e: crate::stream::StreamError,
    frame_index: u64,
) -> PyErr {
    if let Some(parse) = e.downcast_ref::<ParseError>() {
        parse_err_to_py(py, parse, parse.line(), frame_index)
    } else {
        PyIOError::new_err(format!("read error: {e}"))
    }
}

/// 1-based file line for a cursor whose slice starts after `line_base` newlines.
fn file_line(line_base: u32, cursor_line: u32) -> u32 {
    if cursor_line == 0 {
        line_base.saturating_add(1)
    } else {
        line_base.saturating_add(cursor_line)
    }
}

fn newlines_in(text: &str) -> u32 {
    text.bytes().filter(|&byte| byte == b'\n').count() as u32
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
                    Some(Ok(frame)) => {
                        self.frame_index = self.frame_index.saturating_add(1);
                        Ok(Some(PyConFrame::from_owned(py, frame)?))
                    }
                    Some(Err(e)) => Err(stream_error(py, "parse", e, self.frame_index)),
                    None => Ok(None),
                };
            }
        };
        if *pos >= contents.as_str().len() {
            return Ok(None);
        }
        // An empty line 1 is the user line (CON-header.4). The core iterator
        // owns that boundary and trailing whitespace. The cursor is rebuilt
        // on the remainder, so the file line is `line_base` plus its line.
        let slice = &contents.as_str()[*pos..];
        let mut iter = ConFrameIterator::new(slice);
        match iter.next_with_raw_span(slice) {
            Some(Ok((frame, span))) => {
                let consumed =
                    (span.as_ptr() as usize).saturating_sub(slice.as_ptr() as usize) + span.len();
                let lines = newlines_in(span);
                *pos += consumed;
                self.line_base = self.line_base.saturating_add(lines);
                self.frame_index = self.frame_index.saturating_add(1);
                contents
                    .release_before(*pos)
                    .map_err(|e| PyIOError::new_err(format!("release error: {e}")))?;
                Ok(Some(PyConFrame::from_owned(py, frame)?))
            }
            Some(Err(e)) => {
                let line = file_line(self.line_base, iter.lines.line_no());
                Err(parse_err_to_py(py, &e, line, self.frame_index))
            }
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
                    Some(Ok(())) => {
                        self.frame_index = self.frame_index.saturating_add(1);
                        Ok(true)
                    }
                    Some(Err(e)) => Err(stream_error(py, "skip", e, self.frame_index)),
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
                let consumed = iter.byte_pos();
                let lines = newlines_in(&slice[..consumed]);
                *pos += consumed;
                self.line_base = self.line_base.saturating_add(lines);
                self.frame_index = self.frame_index.saturating_add(1);
                contents
                    .release_before(*pos)
                    .map_err(|e| PyIOError::new_err(format!("release error: {e}")))?;
                Ok(true)
            }
            Some(Err(e)) => {
                let line = file_line(self.line_base, iter.lines.line_no());
                Err(parse_err_to_py(py, &e, line, self.frame_index))
            }
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
    Ok(PyConFrameIterator {
        source,
        line_base: 0,
        frame_index: 0,
    })
}

/// Count frames without building atom / Python objects (skip walk).
#[pyfunction]
fn count_frames(py: Python<'_>, path: &str) -> PyResult<usize> {
    let path_owned = path.to_owned();
    py.detach(|| crate::iterators::count_frames(Path::new(&path_owned)))
        .map_err(load_err_to_py)
}

/// Skip `index` frames (no atom parse), then return that frame.
#[pyfunction]
fn read_nth_frame(py: Python<'_>, path: &str, index: usize) -> PyResult<PyConFrame> {
    let path_owned = path.to_owned();
    let frame = py
        .detach(|| crate::iterators::read_nth_frame_located(Path::new(&path_owned), index))
        .map_err(load_err_to_py)?;
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

enum OutputCodec {
    Plain,
    Gzip,
    Zstd,
}

fn output_codec(path: &str, compression: Option<&str>) -> PyResult<OutputCodec> {
    match compression {
        Some("none") => Ok(OutputCodec::Plain),
        Some("gzip") => Ok(OutputCodec::Gzip),
        Some("zstd") => Ok(OutputCodec::Zstd),
        Some(other) => Err(PyIOError::new_err(format!(
            "unknown compression: {other}. Use \"gzip\", \"zstd\" or \"none\"."
        ))),
        None => Ok(
            match crate::compression::detect_compression_from_extension(Path::new(path)) {
                crate::compression::Compression::Gzip => OutputCodec::Gzip,
                crate::compression::Compression::Zstd => OutputCodec::Zstd,
                crate::compression::Compression::None => OutputCodec::Plain,
            },
        ),
    }
}

/// Convert and write one frame at a time. The Rust frame is dropped before
/// the next Python frame is converted.
fn stream_frames(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    write: impl FnMut(&ConFrame) -> PyResult<()>,
) -> PyResult<()> {
    stream_frames_range(py, frames, 0, None, write)
}

fn stream_frames_range(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    start: usize,
    stop: Option<usize>,
    write: impl FnMut(&ConFrame) -> PyResult<()>,
) -> PyResult<()> {
    if let Ok(list) = frames.cast::<ConFrameList>() {
        return stream_frame_list(py, list, start, stop, write);
    }
    stream_python_frames(py, frames, start, stop, write)
}

/// `read_con` stores the parsed frames and builds a Python frame only when
/// that index is touched. Writing walks the stored frames, so the write does
/// not fill that cache and does not keep a second trajectory.
fn stream_frame_list(
    py: Python<'_>,
    list: &Bound<'_, ConFrameList>,
    start: usize,
    stop: Option<usize>,
    mut write: impl FnMut(&ConFrame) -> PyResult<()>,
) -> PyResult<()> {
    let n = list.borrow().len_frames();
    let end = stop.unwrap_or(n).min(n);
    for index in start..end {
        let stored = {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            slots.get(index).and_then(|slot| slot.as_ref()).is_some()
        };
        if stored {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            let frame = slots
                .get(index)
                .and_then(|slot| slot.as_ref())
                .expect("stored frame");
            write(frame)?;
            continue;
        }
        let obj = list.borrow().frame_obj(py, index)?;
        let frame = obj.bind(py).borrow();
        write_python_frame(py, &frame, &mut write)?;
    }
    Ok(())
}

fn stream_python_frames(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    start: usize,
    stop: Option<usize>,
    mut write: impl FnMut(&ConFrame) -> PyResult<()>,
) -> PyResult<()> {
    for (index, item) in PyIterator::from_object(frames)?.enumerate() {
        if index < start {
            continue;
        }
        if stop.is_some_and(|end| index >= end) {
            break;
        }
        let item = item?;
        let frame = item.extract::<PyRef<'_, PyConFrame>>().map_err(|_| {
            PyTypeError::new_err("frames must be an iterable of readcon.ConFrame objects")
        })?;
        write_python_frame(py, &frame, &mut write)?;
    }
    Ok(())
}

fn write_python_frame(
    py: Python<'_>,
    frame: &PyRef<'_, PyConFrame>,
    write: &mut impl FnMut(&ConFrame) -> PyResult<()>,
) -> PyResult<()> {
    if !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
        && let Some(inner) = frame.inner.as_ref()
        && inner.positions.nrows() > 0
    {
        write(inner)?;
        return Ok(());
    }
    let rust_frame = frame.to_con_frame(py)?;
    write(&rust_frame)
}

fn flush_writer<W: std::io::Write>(writer: &mut ConFrameWriter<W>) -> PyResult<()> {
    writer
        .flush()
        .map_err(|err| PyIOError::new_err(format!("flush error: {err}")))
}

/// Write one frame with the header the C, Fortran, and Julia rewrites emit.
///
/// The atoms stay on `frame`. The stamp is the current spec, `con_spec_minor`
/// when the file omitted it, and default units when the file omitted them.
/// A spec 1 constraint flag is then written as the spec 2 mask. The caller's
/// frame is left as it was.
fn write_stamped_frame<W: std::io::Write>(
    writer: &mut ConFrameWriter<W>,
    frame: &ConFrame,
) -> Result<(), crate::writer::WriteError> {
    let mut stamped = frame.clone();
    writer.write_frame_binding(&mut stamped)
}

/// Stored frames from a `read_con` result, in order.
///
/// A slot that is still held is cloned. A slot already moved into a Python
/// frame is rebuilt from that frame. Collective and serial writes of the
/// same result then start from the same frames.
fn con_frame_list_stored(
    py: Python<'_>,
    list: &Bound<'_, ConFrameList>,
) -> PyResult<Vec<ConFrame>> {
    let n = list.borrow().len_frames();
    let mut out = Vec::with_capacity(n);
    for index in 0..n {
        let cloned = {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            slots.get(index).and_then(|slot| slot.clone())
        };
        if let Some(frame) = cloned {
            out.push(frame);
            continue;
        }
        let obj = list.borrow().frame_obj(py, index)?;
        out.push(obj.borrow(py).to_con_frame(py)?);
    }
    Ok(out)
}

/// Write frames to a .con or .convel file path.
///
/// One frame is converted and written, then dropped, before the next frame
/// is converted. A `read_con` result is written from the stored frames, so
/// the write does not build a Python frame per index or a second trajectory.
/// Those stored frames receive the same header stamp as a C, Fortran, or
/// Julia rewrite, and a collective write of the same result uses those
/// frames too, so the serial file and the collective file hash the same.
/// The caller keeps the input frames. The writer buffer is flushed before
/// this function returns.
///
/// CON text for a compressed write.
///
/// The bytes match a binding rewrite. Compression then splits a large
/// payload into independent members; formatting itself still follows
/// `n_threads`.
/// One wide frame is split across members. Many frames stay one stream so
/// the plaintext of every frame is not resident at once.
fn chunk_wide_frame(frames: &Bound<'_, PyAny>, compression_members: Option<usize>) -> bool {
    if matches!(compression_members, Some(1)) {
        return false;
    }
    let atoms = if let Ok(list) = frames.cast::<ConFrameList>() {
        if list.borrow().len_frames() != 1 {
            return false;
        }
        let borrowed = list.borrow();
        let slots = borrowed.frames.lock().expect("frames");
        slots
            .first()
            .and_then(|slot| slot.as_ref())
            .map(|frame| frame.atom_data.len())
            .unwrap_or(0)
    } else if frames.len().ok() == Some(1) {
        // A one-element Python list still goes through the chunk path only
        // when the formatted text is large. `plain_binding_bytes` decides
        // the member count from that size, so a single small frame is one
        // member. Many frames never reach this arm.
        return true;
    } else {
        return false;
    };
    atoms >= 4096 || compression_members.is_some_and(|count| count > 1)
}

fn write_bound_frames<W: std::io::Write>(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    writer: &mut ConFrameWriter<W>,
) -> PyResult<()> {
    if let Ok(list) = frames.cast::<ConFrameList>() {
        let all_stored = {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            slots.iter().all(|slot| slot.is_some())
        };
        if all_stored {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            for slot in slots.iter() {
                writer
                    .write_frame_bound(slot.as_ref().expect("stored frame"))
                    .map_err(|err| write_err_to_py(py, err))?;
            }
            return Ok(());
        }
    }
    stream_frames(py, frames, |frame| {
        writer
            .write_frame_bound(frame)
            .map_err(|err| write_err_to_py(py, err))
    })
}

fn plain_binding_bytes(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    precision: Option<usize>,
    canonical: bool,
    n_threads: Option<usize>,
) -> PyResult<Vec<u8>> {
    let workers = n_threads.filter(|count| *count >= 2).unwrap_or(1);
    let mut buffer = Vec::new();
    if let Ok(list) = frames.cast::<ConFrameList>() {
        let all_stored = {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            slots.iter().all(|slot| slot.is_some())
        };
        if all_stored {
            let borrowed = list.borrow();
            let slots = borrowed.frames.lock().expect("frames");
            let refs: Vec<&ConFrame> = slots
                .iter()
                .map(|slot| slot.as_ref().expect("stored frame"))
                .collect();
            {
                let mut writer = match precision {
                    Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
                    None => ConFrameWriter::new(&mut buffer),
                }
                .canonical(canonical);
                if workers >= 2 {
                    writer = writer.parallel_atoms(workers);
                }
                for frame in refs {
                    writer
                        .write_frame_bound(frame)
                        .map_err(|err| write_err_to_py(py, err))?;
                }
                flush_writer(&mut writer)?;
            }
            return Ok(buffer);
        }
    }
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
            None => ConFrameWriter::new(&mut buffer),
        }
        .canonical(canonical);
        if workers >= 2 {
            writer = writer.parallel_atoms(workers);
        }
        stream_frames(py, frames, |frame| {
            writer
                .write_frame_bound(frame)
                .map_err(|err| write_err_to_py(py, err))
        })?;
        flush_writer(&mut writer)?;
    }
    Ok(buffer)
}

fn frame_is_one_coord_block(frame: &crate::types::ConFrame) -> bool {
    frame.header.natm_types == 1
        && frame.header.sections.is_empty()
        && !frame.has_velocities()
        && !frame.has_forces()
        && !frame.has_energies()
        && !frame.has_charges()
        && !frame.has_spins()
        && !frame.has_magmoms()
        && !frame.has_displacements()
        && !frame.has_spreads()
}

/// Format and deflate each member on `n_threads` workers.
///
/// `false` keeps the caller on the format-then-compress path. One member
/// stays there so its bytes match the streaming encoder. One worker
/// still fuses: it walks the same members, so the thread count changes
/// the speed and not the bytes.
fn try_fused_members(
    path: &str,
    frames: &Bound<'_, PyAny>,
    compression_members: Option<usize>,
    n_threads: Option<usize>,
    gzip: bool,
) -> PyResult<bool> {
    let Some(threads) = n_threads.filter(|count| *count >= 1) else {
        return Ok(false);
    };
    let Ok(list) = frames.cast::<ConFrameList>() else {
        return Ok(false);
    };
    let borrowed = list.borrow();
    let slots = borrowed.frames.lock().expect("frames");
    if slots.len() != 1 {
        return Ok(false);
    }
    let Some(frame) = slots[0].as_ref() else {
        return Ok(false);
    };
    if !frame_is_one_coord_block(frame) {
        return Ok(false);
    }
    let mut members = compression_members.unwrap_or_else(|| {
        crate::compression::compression_workers(frame.atom_data.len().saturating_mul(32))
    });
    if members <= 1 {
        return Ok(false);
    }
    if threads > members {
        members = threads;
    }
    let write = if gzip {
        crate::compression::write_fused_gzip_frame(Path::new(path), frame, members, threads)
    } else {
        #[cfg(feature = "zstd")]
        {
            crate::compression::write_fused_zstd_frame(Path::new(path), frame, members, threads)
        }
        #[cfg(not(feature = "zstd"))]
        {
            return Ok(false);
        }
    };
    write.map_err(|err| PyIOError::new_err(format!("failed to create compressed writer: {err}")))?;
    Ok(true)
}

/// The `compression` argument controls output compression:
/// - `None` (default): codec from the path extension (`.gz` gzip, `.zst` zstd)
/// - `"gzip"`, `"zstd"`, or `"none"`
///
/// `append=True` extends an existing uncompressed file instead of replacing
/// it. The bytes match one `write_con` of the old frames followed by these
/// frames when the existing file was written by readcon. Gzip, zstd, and
/// `comm=` are refused.
/// `write_con_string` serializes the same default bytes without a file.
#[pyfunction]
#[pyo3(signature = (path, frames, precision=None, compression=None, *, canonical=false, comm=None, mode="auto", append=false, n_threads=None, compression_members=None))]
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
    append: bool,
    n_threads: Option<usize>,
    compression_members: Option<usize>,
) -> PyResult<()> {
    if append && comm.is_some() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "append is not supported with comm=",
        ));
    }
    let codec = output_codec(path, compression)?;
    if let Some(comm) = comm {
        if !matches!(codec, OutputCodec::Plain) || canonical {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "comm= writes uncompressed, non-canonical output only",
            ));
        }
        // A read_con result keeps the parser's frames. Rebuilding each one
        // through ConFrameBuilder changes the bytes the collective writer
        // hashes against the serial write of the same result.
        let rust_frames = if let Ok(list) = frames.cast::<ConFrameList>() {
            con_frame_list_stored(py, list)?
        } else {
            py_frames_to_rust(py, frames)?
        };
        return write_con_mpi(py, path, &rust_frames, precision, comm, mode);
    }
    if append && !matches!(codec, OutputCodec::Plain) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "append is only supported for an uncompressed file",
        ));
    }

    match codec {
        OutputCodec::Gzip => {
            if chunk_wide_frame(frames, compression_members) {
                if try_fused_members(path, frames, compression_members, n_threads, true)? {
                    return Ok(());
                }
                let t_fmt = std::time::Instant::now();
                let plain = plain_binding_bytes(py, frames, precision, canonical, n_threads)?;
                if std::env::var_os("READCON_WRITE_TRACE").is_some() {
                    eprintln!(
                        "gzip-format {:.4} plain_bytes={}",
                        t_fmt.elapsed().as_secs_f64(),
                        plain.len()
                    );
                }
                let members = compression_members
                    .unwrap_or_else(|| crate::compression::compression_workers(plain.len()));
                // An explicit count is the worker count. The default keeps
                // the wide member split and caps deflate at one thread per
                // logical CPU.
                let threads = n_threads.filter(|count| *count >= 1).unwrap_or_else(|| {
                    crate::compression::default_deflate_threads(members)
                });
                crate::compression::write_gzip_members_limited(
                    Path::new(path),
                    &plain,
                    members,
                    threads,
                )
                .map_err(|err| {
                    PyIOError::new_err(format!("failed to create gzip writer: {err}"))
                })?;
                return Ok(());
            }
            let mut writer = match precision {
                Some(precision) => ConFrameWriter::from_path_gzip_with_precision(path, precision)
                    .map_err(|err| {
                    PyIOError::new_err(format!("failed to create gzip writer: {err}"))
                })?,
                None => ConFrameWriter::from_path_gzip(path).map_err(|err| {
                    PyIOError::new_err(format!("failed to create gzip writer: {err}"))
                })?,
            }
            .canonical(canonical);
            write_bound_frames(py, frames, &mut writer)?;
            flush_writer(&mut writer)
        }
        OutputCodec::Zstd => {
            #[cfg(feature = "zstd")]
            {
                if chunk_wide_frame(frames, compression_members) {
                    if try_fused_members(path, frames, compression_members, n_threads, false)? {
                        return Ok(());
                    }
                    let t_fmt = std::time::Instant::now();
                    let plain = plain_binding_bytes(py, frames, precision, canonical, n_threads)?;
                    if std::env::var_os("READCON_WRITE_TRACE").is_some() {
                        eprintln!(
                            "zstd-format {:.4} plain_bytes={}",
                            t_fmt.elapsed().as_secs_f64(),
                            plain.len()
                        );
                    }
                    let members = compression_members
                        .unwrap_or_else(|| crate::compression::compression_workers(plain.len()));
                    let threads = n_threads.filter(|count| *count >= 1).unwrap_or_else(|| {
                        crate::compression::default_deflate_threads(members)
                    });
                    crate::compression::write_zstd_members_limited(
                        Path::new(path),
                        &plain,
                        members,
                        threads,
                    )
                    .map_err(|err| {
                        PyIOError::new_err(format!("failed to create zstd writer: {err}"))
                    })?;
                    return Ok(());
                }
                let mut writer = match precision {
                    Some(precision) => ConFrameWriter::from_path_zstd_with_precision(
                        path, precision,
                    )
                    .map_err(|err| {
                        PyIOError::new_err(format!("failed to create zstd writer: {err}"))
                    })?,
                    None => ConFrameWriter::from_path_zstd(path).map_err(|err| {
                        PyIOError::new_err(format!("failed to create zstd writer: {err}"))
                    })?,
                }
                .canonical(canonical);
                write_bound_frames(py, frames, &mut writer)?;
                flush_writer(&mut writer)
            }
            #[cfg(not(feature = "zstd"))]
            {
                let _ = (
                    precision,
                    canonical,
                    frames,
                    py,
                    n_threads,
                    compression_members,
                );
                Err(pyo3::exceptions::PyValueError::new_err(
                    "zstd compression requires readcon built with the zstd feature",
                ))
            }
        }
        OutputCodec::Plain => {
            let workers = n_threads.unwrap_or(1);
            if !append {
                if let Ok(list) = frames.cast::<ConFrameList>() {
                    let all_stored = {
                        let borrowed = list.borrow();
                        let slots = borrowed.frames.lock().expect("frames");
                        slots.iter().all(|slot| slot.is_some())
                    };
                    if all_stored {
                        let borrowed = list.borrow();
                        let slots = borrowed.frames.lock().expect("frames");
                        let refs: Vec<&ConFrame> = slots
                            .iter()
                            .map(|slot| slot.as_ref().expect("stored frame"))
                            .collect();
                        crate::writer::write_frame_refs_to_path(
                            Path::new(path),
                            &refs,
                            workers,
                            precision,
                            canonical,
                            true,
                        )
                        .map_err(|err| write_err_to_py(py, err))?;
                    } else {
                        // Indexing a frame moves it into the Python cache.
                        // The write then uses that object instead of the slot.
                        let mut writer = if let Some(precision) = precision {
                            crate::writer::ConFrameWriter::from_path_with_precision(path, precision)
                                .map_err(|e| {
                                    PyIOError::new_err(format!("failed to create writer: {e}"))
                                })?
                        } else {
                            crate::writer::ConFrameWriter::from_path(path).map_err(|e| {
                                PyIOError::new_err(format!("failed to create writer: {e}"))
                            })?
                        }
                        .canonical(canonical);
                        stream_frames(py, frames, |frame| {
                            write_stamped_frame(&mut writer, frame)
                                .map_err(|e| write_err_to_py(py, e))
                        })?;
                        flush_writer(&mut writer)?;
                    }
                } else {
                    let rust_frames = py_frames_to_rust(py, frames)?;
                    let refs: Vec<&ConFrame> = rust_frames.iter().collect();
                    crate::writer::write_frame_refs_to_path(
                        Path::new(path),
                        &refs,
                        workers,
                        precision,
                        canonical,
                        true,
                    )
                    .map_err(|err| write_err_to_py(py, err))?;
                }
                return Ok(());
            }
            let mut writer = if append {
                match precision {
                    Some(precision) => {
                        ConFrameWriter::from_path_append_with_precision(path, precision)
                            .map_err(|e| PyIOError::new_err(format!("failed to append: {e}")))?
                    }
                    None => ConFrameWriter::from_path_append(path)
                        .map_err(|e| PyIOError::new_err(format!("failed to append: {e}")))?,
                }
            } else {
                match precision {
                    Some(precision) => ConFrameWriter::from_path_with_precision(path, precision)
                        .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?,
                    None => ConFrameWriter::from_path(path)
                        .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?,
                }
            }
            .canonical(canonical);
            stream_frames(py, frames, |frame| {
                write_stamped_frame(&mut writer, frame).map_err(|e| write_err_to_py(py, e))
            })?;
            flush_writer(&mut writer)
        }
    }
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
///
/// `start` and `stop` select a half-open index range. A `read_con` result
/// is written from the stored frames, so the range does not build a Python
/// frame per index. One frame is serialized and dropped before the next.
#[pyfunction]
#[pyo3(signature = (frames, precision=None, *, canonical=false, start=0, stop=None))]
fn write_con_string(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    precision: Option<usize>,
    canonical: bool,
    start: usize,
    stop: Option<usize>,
) -> PyResult<String> {
    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
            None => ConFrameWriter::new(&mut buffer),
        }
        .canonical(canonical);
        stream_frames_range(py, frames, start, stop, |frame| {
            write_stamped_frame(&mut writer, frame).map_err(|e| write_err_to_py(py, e))
        })?;
    }
    String::from_utf8(buffer).map_err(|e| PyIOError::new_err(format!("utf8 error: {e}")))
}

/// Read a .con file and return a list of ASE Atoms objects.
/// Requires the ase package.
#[pyfunction]
fn read_con_as_ase(py: Python<'_>, path: &str) -> PyResult<Vec<Py<PyAny>>> {
    let frames = read_con(py, path, None, None, "auto", None)?;
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

    // Set velocities if present. ASE stores the natural time unit (D10).
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
            (
                [cellpar[0], cellpar[1], cellpar[2]],
                [cellpar[3], cellpar[4], cellpar[5]],
            )
        } else {
            (lengths, raw_angles)
        }
    } else {
        (
            lengths,
            [
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
            ],
        )
    };
    let pbc = ase_pbc(ase_atoms)?;

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
    metadata.set_item(meta::PBC, pbc.to_vec())?;
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

fn ase_pbc(ase_atoms: &Bound<'_, PyAny>) -> PyResult<[bool; 3]> {
    let pbc = ase_atoms.getattr("pbc")?;
    if let Ok(flag) = pbc.extract::<bool>() {
        return Ok([flag, flag, flag]);
    }
    let values: Vec<bool> = if let Ok(list) = pbc.call_method0("tolist") {
        list.extract()?
    } else {
        pbc.extract()?
    };
    if values.len() != 3 {
        return Err(PyValueError::new_err("ASE pbc must have length 3"));
    }
    Ok([values[0], values[1], values[2]])
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

#[allow(clippy::type_complexity)]
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
#[allow(clippy::type_complexity)]
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

pyo3::create_exception!(readcon, ConError, pyo3::exceptions::PyValueError);
pyo3::create_exception!(readcon, NonFiniteValue, ConError);
pyo3::create_exception!(readcon, InvalidFixedFlag, ConError);
pyo3::create_exception!(readcon, InvalidCount, ConError);
pyo3::create_exception!(readcon, InvalidUnits, ConError);
pyo3::create_exception!(readcon, IncompleteHeader, ConError);
pyo3::create_exception!(readcon, IncompleteFrame, ConError);
pyo3::create_exception!(readcon, IncompleteSection, ConError);
pyo3::create_exception!(readcon, IncompleteVelocitySection, ConError);
pyo3::create_exception!(readcon, IncompleteForceSection, ConError);
pyo3::create_exception!(readcon, IncompleteEnergySection, ConError);
pyo3::create_exception!(readcon, InvalidNumberFormat, ConError);
pyo3::create_exception!(readcon, InvalidVectorLength, ConError);
pyo3::create_exception!(readcon, UnknownSection, ConError);
pyo3::create_exception!(readcon, UnsupportedVersion, ConError);
pyo3::create_exception!(readcon, ValidationError, ConError);
pyo3::create_exception!(readcon, MissingSpecVersion, ConError);
pyo3::create_exception!(readcon, InvalidMetadataJson, ConError);
pyo3::create_exception!(readcon, IndexOutOfBounds, ConError);
pyo3::create_exception!(readcon, MassMismatch, ConError);

fn correspondence_to_py(err: crate::correspondence::CorrespondenceError) -> PyErr {
    Python::attach(|py| {
        let ty = py.get_type::<ValidationError>();
        let inst = match ty.call1((err.to_string(),)) {
            Ok(inst) => inst,
            Err(err) => return err,
        };
        let _ = inst.setattr("line", 0u32);
        if let Some(frame) = err.frame_index() {
            let _ = inst.setattr("frame_index", frame);
        }
        if let Some(atom_id) = err.atom_id() {
            let _ = inst.setattr("atom_id", atom_id);
        }
        if let Some(atom_index) = err.atom_index() {
            let _ = inst.setattr("atom_index", atom_index);
        }
        PyErr::from_value(inst)
    })
}

fn identity_check(strict: bool) -> crate::correspondence::IdentityCheck {
    if strict {
        crate::correspondence::IdentityCheck::Strict
    } else {
        crate::correspondence::IdentityCheck::Lenient
    }
}

/// `perm[i]` is the index in `other` of the atom with the same `atom_id`
/// as `reference` atom `i`.
///
/// `strict` (default true) also requires the mass and the fixed mask to
/// agree. Duplicate ids, missing or extra ids, and a symbol mismatch fail
/// in both modes. Failures raise `ValidationError` with `frame_index`,
/// `atom_id`, and `atom_index` attributes when those name the failure.
#[pyfunction]
#[pyo3(signature = (reference, other, *, strict=true))]
fn atom_id_permutation(
    py: Python<'_>,
    reference: &PyConFrame,
    other: &PyConFrame,
    strict: bool,
) -> PyResult<Vec<usize>> {
    let reference = reference.to_con_frame(py)?;
    let other = other.to_con_frame(py)?;
    crate::correspondence::atom_id_permutation(&reference, &other, identity_check(strict))
        .map_err(correspondence_to_py)
}

/// Return `other` with its atoms stored in `reference` order.
///
/// Positions, velocities, forces, and the other per-atom sections move
/// with each atom. Bond endpoints are remapped.
#[pyfunction]
#[pyo3(signature = (reference, other, *, strict=true))]
fn reorder_like(
    py: Python<'_>,
    reference: &PyConFrame,
    other: &PyConFrame,
    strict: bool,
) -> PyResult<PyConFrame> {
    let reference = reference.to_con_frame(py)?;
    let other = other.to_con_frame(py)?;
    let frame = crate::correspondence::reorder_like(&reference, &other, identity_check(strict))
        .map_err(correspondence_to_py)?;
    PyConFrame::from_owned(py, frame)
}

/// Check that every frame names the same atoms as `frames[0]`.
///
/// The error is the first frame that disagrees, and the atom. A single
/// frame checks that its ids are unique.
#[pyfunction]
#[pyo3(signature = (frames, *, strict=true))]
fn check_atom_id_consistency(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    strict: bool,
) -> PyResult<()> {
    let rust_frames = py_frames_to_con(py, frames)?;
    crate::correspondence::check_atom_id_consistency(&rust_frames, identity_check(strict))
        .map_err(correspondence_to_py)
}

/// Minimum-image displacement of each reference atom toward the atom in
/// `other` with the same `atom_id`. Shape `(N, 3)`, reference order.
///
/// The cell and the periodic flags are the reference frame's.
#[pyfunction]
#[pyo3(signature = (reference, other, *, strict=true))]
fn minimum_image_displacements<'py>(
    py: Python<'py>,
    reference: &PyConFrame,
    other: &PyConFrame,
    strict: bool,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let reference = reference.to_con_frame(py)?;
    let other = other.to_con_frame(py)?;
    let rows = crate::correspondence::minimum_image_displacements(
        &reference,
        &other,
        identity_check(strict),
    )
    .map_err(correspondence_to_py)?;
    let mut data = Vec::with_capacity(rows.len().saturating_mul(3));
    for row in rows {
        data.extend_from_slice(&row);
    }
    let array = Array2::from_shape_vec((data.len() / 3, 3), data)
        .map_err(|e| PyValueError::new_err(format!("displacement shape error: {e}")))?;
    Ok(array.into_pyarray(py))
}

fn class_err_to_py(
    py: Python<'_>,
    class_name: &str,
    message: String,
    line: u32,
    frame_index: u64,
) -> PyErr {
    let ty = match class_name {
        "NonFiniteValue" => py.get_type::<NonFiniteValue>().into_any(),
        "InvalidFixedFlag" => py.get_type::<InvalidFixedFlag>().into_any(),
        "InvalidCount" => py.get_type::<InvalidCount>().into_any(),
        "InvalidUnits" => py.get_type::<InvalidUnits>().into_any(),
        "IncompleteHeader" => py.get_type::<IncompleteHeader>().into_any(),
        "IncompleteFrame" => py.get_type::<IncompleteFrame>().into_any(),
        "IncompleteSection" => py.get_type::<IncompleteSection>().into_any(),
        "IncompleteVelocitySection" => py.get_type::<IncompleteVelocitySection>().into_any(),
        "IncompleteForceSection" => py.get_type::<IncompleteForceSection>().into_any(),
        "IncompleteEnergySection" => py.get_type::<IncompleteEnergySection>().into_any(),
        "InvalidNumberFormat" => py.get_type::<InvalidNumberFormat>().into_any(),
        "InvalidVectorLength" => py.get_type::<InvalidVectorLength>().into_any(),
        "UnknownSection" => py.get_type::<UnknownSection>().into_any(),
        "UnsupportedVersion" => py.get_type::<UnsupportedVersion>().into_any(),
        "ValidationError" => py.get_type::<ValidationError>().into_any(),
        "MissingSpecVersion" => py.get_type::<MissingSpecVersion>().into_any(),
        "InvalidMetadataJson" => py.get_type::<InvalidMetadataJson>().into_any(),
        "IndexOutOfBounds" => py.get_type::<IndexOutOfBounds>().into_any(),
        "MassMismatch" => py.get_type::<MassMismatch>().into_any(),
        _ => py.get_type::<ConError>().into_any(),
    };
    match ty.call1((message,)) {
        Ok(inst) => {
            let _ = inst.setattr("line", line);
            let _ = inst.setattr("frame_index", frame_index);
            PyErr::from_value(inst)
        }
        Err(err) => err,
    }
}

fn parse_err_to_py(py: Python<'_>, err: &ParseError, line: u32, frame_index: u64) -> PyErr {
    if utf8_failure(err) {
        return PyIOError::new_err(err.to_string());
    }
    class_err_to_py(py, err.class_name(), err.to_string(), line, frame_index)
}

fn utf8_failure(err: &ParseError) -> bool {
    matches!(err, ParseError::ValidationError(msg) if msg.contains("invalid UTF-8"))
}

fn located_to_py(err: crate::error::LocatedParseError) -> PyErr {
    Python::attach(|py| parse_err_to_py(py, &err.error, err.line, err.frame_index))
}

fn load_err_to_py(err: crate::iterators::LoadError) -> PyErr {
    use crate::iterators::LoadError;
    match err {
        LoadError::Io(io) => PyIOError::new_err(io.to_string()),
        LoadError::Utf8(utf) => PyIOError::new_err(utf.to_string()),
        LoadError::Parse(located) => {
            if utf8_failure(&located.error) {
                PyIOError::new_err(located.error.to_string())
            } else {
                located_to_py(located)
            }
        }
        LoadError::Empty => {
            Python::attach(|py| parse_err_to_py(py, &ParseError::IncompleteHeader, 1, 0))
        }
    }
}

enum CountFail {
    Io(String),
    Parse {
        class: &'static str,
        message: String,
        line: u32,
        frame: u64,
    },
    Other(String),
}

fn count_fail_to_py(err: CountFail) -> PyErr {
    Python::attach(|py| match err {
        CountFail::Io(msg) | CountFail::Other(msg) => PyIOError::new_err(msg),
        CountFail::Parse {
            class,
            message,
            line,
            frame,
        } => class_err_to_py(py, class, message, line, frame),
    })
}

fn count_fail_located(located: &crate::error::LocatedParseError) -> CountFail {
    CountFail::Parse {
        class: located.error.class_name(),
        message: located.error.to_string(),
        line: located.line,
        frame: located.frame_index,
    }
}

/// Map a boxed reader error onto [`CountFail`].
///
/// `read_all_frames_with_threads`, `read_all_frames_phased`, and
/// `read_positions_with_threads` return the [`crate::error::LocatedParseError`]
/// from the parse that failed. The line and frame are already on that
/// error, so this does not open the path again.
fn box_to_count_fail(err: Box<dyn std::error::Error>) -> CountFail {
    if err.downcast_ref::<std::io::Error>().is_some() || err.to_string().contains("invalid UTF-8") {
        return CountFail::Io(err.to_string());
    }
    if let Some(located) = err.downcast_ref::<crate::error::LocatedParseError>() {
        return count_fail_located(located);
    }
    if let Some(parse) = err.downcast_ref::<ParseError>() {
        return CountFail::Parse {
            class: parse.class_name(),
            message: parse.to_string(),
            line: parse.line(),
            frame: 0,
        };
    }
    CountFail::Other(err.to_string())
}

#[cfg(test)]
mod batch_location_tests {
    use super::{CountFail, box_to_count_fail};

    fn later_frame_path() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "readcon-batch-later-{}-{}.con",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        let good = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        let bad = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n-1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        std::fs::write(&path, format!("{good}{bad}")).unwrap();
        path
    }

    fn assert_later(fail: CountFail) {
        match fail {
            CountFail::Parse {
                class, line, frame, ..
            } => {
                assert_eq!(class, "InvalidCount");
                assert_eq!(line, 20, "file line of the bad count");
                assert_eq!(frame, 1, "0-based frame index");
            }
            CountFail::Io(msg) => panic!("expected InvalidCount, got io: {msg}"),
            CountFail::Other(msg) => panic!("expected InvalidCount, got: {msg}"),
        }
    }

    /// `read_con`, `read_all_frames`, `read_coords`, and `read_positions`
    /// all map these readers through `box_to_count_fail`. A count error
    /// in the second frame is file line 20, frame 1.
    #[test]
    #[allow(clippy::type_complexity)]
    fn batch_readers_keep_the_later_frame_location() {
        let path = later_frame_path();
        let cases: [(
            Option<usize>,
            fn(&std::path::Path, Option<usize>) -> CountFail,
        ); 5] = [
            (None, fail_read_all),
            (None, fail_phased),
            (Some(2), fail_phased),
            (None, fail_positions),
            (Some(2), fail_positions),
        ];
        for (threads, fail_of) in cases {
            assert_later(fail_of(&path, threads));
        }
        let _ = std::fs::remove_file(&path);
    }

    fn fail_of(result: Result<(), Box<dyn std::error::Error>>) -> CountFail {
        match result {
            Err(err) => box_to_count_fail(err),
            Ok(()) => panic!("expected a parse error"),
        }
    }

    fn fail_read_all(path: &std::path::Path, threads: Option<usize>) -> CountFail {
        fail_of(crate::iterators::read_all_frames_with_threads(path, threads).map(|_| ()))
    }

    fn fail_phased(path: &std::path::Path, threads: Option<usize>) -> CountFail {
        fail_of(crate::iterators::read_all_frames_phased(path, threads).map(|_| ()))
    }

    fn fail_positions(path: &std::path::Path, threads: Option<usize>) -> CountFail {
        fail_of(crate::iterators::read_positions_with_threads(path, threads).map(|_| ()))
    }

    fn later_frame_bytes() -> Vec<u8> {
        let good = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        let bad = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n-1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        format!("{good}{bad}").into_bytes()
    }

    fn write_temp(bytes: &[u8]) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "readcon-batch-class-{}-{}.con",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        std::fs::write(&path, bytes).unwrap();
        path
    }

    #[allow(clippy::type_complexity)]
    fn class_cases() -> [(
        Option<usize>,
        fn(&std::path::Path, Option<usize>) -> CountFail,
    ); 6] {
        [
            (None, fail_read_all),
            (Some(2), fail_read_all),
            (None, fail_phased),
            (Some(2), fail_phased),
            (None, fail_positions),
            (Some(2), fail_positions),
        ]
    }

    /// A byte the whole-file UTF-8 check would reject must not replace the
    /// count error the batch parser already produced. The file is past the
    /// map threshold, so the first read parses bytes and a second open
    /// would fail the mapped buffer as UTF-8.
    #[test]
    fn trailing_non_utf8_keeps_the_parse_class() {
        let mut bytes = later_frame_bytes();
        bytes.resize(64 * 1024, b' ');
        bytes.push(0xff);
        let path = write_temp(&bytes);
        for (threads, fail_of_reader) in class_cases() {
            assert_later(fail_of_reader(&path, threads));
        }
        let _ = std::fs::remove_file(&path);
    }

    /// The path is gone before a second open could map it. The count error
    /// from the first read is the one that is reported.
    #[test]
    fn deleted_path_keeps_the_parse_class() {
        let mut bytes = later_frame_bytes();
        bytes.resize(64 * 1024, b' ');
        for (threads, read_err) in [
            (
                None,
                err_read_all as fn(&std::path::Path, Option<usize>) -> Box<dyn std::error::Error>,
            ),
            (Some(2), err_read_all),
            (None, err_phased),
            (Some(2), err_phased),
            (None, err_positions),
            (Some(2), err_positions),
        ] {
            let path = write_temp(&bytes);
            let err = read_err(&path, threads);
            std::fs::remove_file(&path).unwrap();
            assert_later(box_to_count_fail(err));
        }
    }

    fn err_read_all(path: &std::path::Path, threads: Option<usize>) -> Box<dyn std::error::Error> {
        match crate::iterators::read_all_frames_with_threads(path, threads) {
            Err(err) => err,
            Ok(_) => panic!("expected a parse error"),
        }
    }

    fn err_phased(path: &std::path::Path, threads: Option<usize>) -> Box<dyn std::error::Error> {
        match crate::iterators::read_all_frames_phased(path, threads) {
            Err(err) => err,
            Ok(_) => panic!("expected a parse error"),
        }
    }

    fn err_positions(path: &std::path::Path, threads: Option<usize>) -> Box<dyn std::error::Error> {
        match crate::iterators::read_positions_with_threads(path, threads) {
            Err(err) => err,
            Ok(_) => panic!("expected a parse error"),
        }
    }
}

fn write_err_to_py(py: Python<'_>, err: crate::writer::WriteError) -> PyErr {
    match err {
        crate::writer::WriteError::Io(io) => PyIOError::new_err(io.to_string()),
        crate::writer::WriteError::Format(parse) => parse_err_to_py(py, &parse, parse.line(), 0),
    }
}

/// readcon Python module implemented in Rust.
#[pymodule]
fn readcon(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("ConError", py.get_type::<ConError>())?;
    m.add("NonFiniteValue", py.get_type::<NonFiniteValue>())?;
    m.add("InvalidFixedFlag", py.get_type::<InvalidFixedFlag>())?;
    m.add("InvalidCount", py.get_type::<InvalidCount>())?;
    m.add("InvalidUnits", py.get_type::<InvalidUnits>())?;
    m.add("IncompleteHeader", py.get_type::<IncompleteHeader>())?;
    m.add("IncompleteFrame", py.get_type::<IncompleteFrame>())?;
    m.add("IncompleteSection", py.get_type::<IncompleteSection>())?;
    m.add(
        "IncompleteVelocitySection",
        py.get_type::<IncompleteVelocitySection>(),
    )?;
    m.add(
        "IncompleteForceSection",
        py.get_type::<IncompleteForceSection>(),
    )?;
    m.add(
        "IncompleteEnergySection",
        py.get_type::<IncompleteEnergySection>(),
    )?;
    m.add("InvalidNumberFormat", py.get_type::<InvalidNumberFormat>())?;
    m.add("InvalidVectorLength", py.get_type::<InvalidVectorLength>())?;
    m.add("UnknownSection", py.get_type::<UnknownSection>())?;
    m.add("UnsupportedVersion", py.get_type::<UnsupportedVersion>())?;
    m.add("ValidationError", py.get_type::<ValidationError>())?;
    m.add("MissingSpecVersion", py.get_type::<MissingSpecVersion>())?;
    m.add("InvalidMetadataJson", py.get_type::<InvalidMetadataJson>())?;
    m.add("IndexOutOfBounds", py.get_type::<IndexOutOfBounds>())?;
    m.add("MassMismatch", py.get_type::<MassMismatch>())?;
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
    m.add_function(wrap_pyfunction!(write_columns, m)?)?;
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
    m.add_class::<SpeciesFrames>()?;
    m.add_class::<SpeciesRow>()?;
    m.add_class::<SpeciesIter>()?;
    m.add_class::<SpeciesFramesIter>()?;
    m.add_function(wrap_pyfunction!(read_extxyz, m)?)?;
    m.add_function(wrap_pyfunction!(write_extxyz, m)?)?;
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
    m.add_function(wrap_pyfunction!(atom_id_permutation, m)?)?;
    m.add_function(wrap_pyfunction!(reorder_like, m)?)?;
    m.add_function(wrap_pyfunction!(check_atom_id_consistency, m)?)?;
    m.add_function(wrap_pyfunction!(minimum_image_displacements, m)?)?;
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

fn interned_symbol<'a>(
    py: Python<'_>,
    intern: &mut std::collections::HashMap<&'a str, Py<pyo3::types::PyString>>,
    token: &'a str,
) -> Py<pyo3::types::PyString> {
    if let Some(found) = intern.get(token) {
        return found.clone_ref(py);
    }
    let created = pyo3::types::PyString::new(py, token).unbind();
    intern.insert(token, created.clone_ref(py));
    created
}

/// One tuple per frame. A repeated symbol is one string object, and a
/// frame that matches the previous frame is that same tuple. Tuples are
/// immutable, so sharing a row cannot let one frame change another.
fn py_text_frames<'py>(
    py: Python<'py>,
    text: &[String],
    n_atoms: usize,
    width: usize,
) -> PyResult<Bound<'py, PyList>> {
    let frames = PyList::empty(py);
    if n_atoms == 0 || width == 0 || text.is_empty() {
        return Ok(frames);
    }
    let stride = n_atoms.saturating_mul(width);
    if width == 1 && text.len().is_multiple_of(stride) {
        let symbol = text[0].as_str();
        if text.iter().all(|item| item == symbol) {
            let py_symbol = pyo3::types::PyString::new(py, symbol).unbind();
            let row = pyo3::types::PyTuple::new(py, (0..n_atoms).map(|_| py_symbol.clone_ref(py)))?
                .unbind();
            let n_frames = text.len() / stride;
            return Ok(pyo3::types::PyList::new(
                py,
                (0..n_frames).map(|_| row.clone_ref(py)),
            )?);
        }
    }
    let mut intern = std::collections::HashMap::<&str, Py<pyo3::types::PyString>>::new();
    let mut prev: Option<&[String]> = None;
    let mut prev_row: Option<Py<pyo3::types::PyTuple>> = None;
    for frame in text.chunks(stride) {
        if let (Some(old), Some(row)) = (prev, prev_row.as_ref())
            && old == frame
        {
            frames.append(row.clone_ref(py))?;
            continue;
        }
        let row = if width == 1 {
            pyo3::types::PyTuple::new(
                py,
                frame
                    .iter()
                    .map(|token| interned_symbol(py, &mut intern, token)),
            )?
        } else {
            let mut groups = Vec::with_capacity(frame.len() / width);
            for group in frame.chunks(width) {
                groups.push(pyo3::types::PyTuple::new(
                    py,
                    group
                        .iter()
                        .map(|token| interned_symbol(py, &mut intern, token)),
                )?);
            }
            pyo3::types::PyTuple::new(py, groups)?
        };
        let owned = row.unbind();
        frames.append(owned.clone_ref(py))?;
        prev = Some(frame);
        prev_row = Some(owned);
    }
    Ok(frames)
}

fn species_list_from_batches(
    rx: std::sync::mpsc::Receiver<crate::extxyz_scan::SpeciesBatch>,
) -> Option<pyo3::Py<pyo3::types::PyList>> {
    pyo3::Python::attach(|py| {
        let mut waiting = std::collections::BTreeMap::new();
        let mut next = 0u16;
        let mut rows: Vec<pyo3::Py<pyo3::types::PyTuple>> = Vec::new();
        let mut partials: Vec<Vec<pyo3::Py<pyo3::types::PyString>>> = Vec::new();
        let mut shared: Option<(String, usize, pyo3::Py<pyo3::types::PyTuple>)> = None;
        let mut prev_ids: Vec<u32> = Vec::new();
        let mut prev_tuple: Option<pyo3::Py<pyo3::types::PyTuple>> = None;
        while let Ok(batch) = rx.recv() {
            waiting.insert(batch.worker, batch);
            while let Some(batch) = waiting.remove(&next) {
                if batch.frames == 0 {
                    partials.push(slice_symbols(py, &batch)?);
                } else if let Some(symbol) = batch.uniform.clone() {
                    let tuple = if shared.as_ref().is_some_and(|(known, atoms, _)| {
                        known == &symbol && *atoms == batch.n_atoms
                    }) {
                        shared.as_ref().unwrap().2.clone_ref(py)
                    } else {
                        let py_symbol = pyo3::types::PyString::new(py, &symbol).unbind();
                        let tuple = pyo3::types::PyTuple::new(
                            py,
                            (0..batch.n_atoms).map(|_| py_symbol.clone_ref(py)),
                        )?
                        .unbind();
                        shared = Some((symbol, batch.n_atoms, tuple.clone_ref(py)));
                        tuple
                    };
                    for _ in 0..batch.frames {
                        rows.push(tuple.clone_ref(py));
                    }
                } else {
                    let symbols = pool_symbols(py, &batch)?;
                    let width = batch.n_atoms.max(1);
                    for frame in 0..batch.frames {
                        let start = frame * width;
                        let row = &batch.ids[start..start + width];
                        if prev_tuple.is_some() && prev_ids == row {
                            rows.push(prev_tuple.as_ref().unwrap().clone_ref(py));
                            continue;
                        }
                        let tuple = pyo3::types::PyTuple::new(
                            py,
                            row.iter().map(|id| symbols[*id as usize].clone_ref(py)),
                        )?
                        .unbind();
                        prev_ids = row.to_vec();
                        prev_tuple = Some(tuple.clone_ref(py));
                        rows.push(tuple);
                    }
                }
                next += 1;
            }
        }
        if !partials.is_empty() {
            let flat: Vec<_> = partials.into_iter().flatten().collect();
            rows.push(pyo3::types::PyTuple::new(py, flat)?.unbind());
        }
        if rows.is_empty() {
            return Ok::<_, pyo3::PyErr>(None);
        }
        Ok(Some(pyo3::types::PyList::new(py, rows)?.unbind()))
    })
    .ok()
    .flatten()
}

fn pool_symbols<'py>(
    py: Python<'py>,
    batch: &crate::extxyz_scan::SpeciesBatch,
) -> PyResult<Vec<pyo3::Py<pyo3::types::PyString>>> {
    Ok(batch
        .pool
        .iter()
        .map(|symbol| pyo3::types::PyString::new(py, symbol).unbind())
        .collect())
}

fn slice_symbols<'py>(
    py: Python<'py>,
    batch: &crate::extxyz_scan::SpeciesBatch,
) -> PyResult<Vec<pyo3::Py<pyo3::types::PyString>>> {
    if let Some(symbol) = &batch.uniform {
        let py_symbol = pyo3::types::PyString::new(py, symbol).unbind();
        return Ok((0..batch.n_atoms)
            .map(|_| py_symbol.clone_ref(py))
            .collect());
    }
    let pool = pool_symbols(py, batch)?;
    Ok(batch
        .ids
        .iter()
        .map(|id| pool[*id as usize].clone_ref(py))
        .collect())
}

fn indexed_symbol_frames<'py>(
    py: Python<'py>,
    pool: &[String],
    ids: &[u32],
    n_frames: usize,
    n_atoms: usize,
) -> PyResult<Bound<'py, PyList>> {
    let symbols: Vec<pyo3::Py<pyo3::types::PyString>> = pool
        .iter()
        .map(|symbol| pyo3::types::PyString::new(py, symbol).unbind())
        .collect();
    let mut rows: Vec<pyo3::Py<pyo3::types::PyTuple>> = Vec::with_capacity(n_frames);
    for frame in 0..n_frames {
        let row = &ids[frame * n_atoms..(frame + 1) * n_atoms];
        if frame > 0 && row == &ids[(frame - 1) * n_atoms..frame * n_atoms] {
            rows.push(rows[frame - 1].clone_ref(py));
            continue;
        }
        let tuple = pyo3::types::PyTuple::new(
            py,
            row.iter().map(|id| symbols[*id as usize].clone_ref(py)),
        )?
        .unbind();
        rows.push(tuple);
    }
    pyo3::types::PyList::new(py, rows)
}

fn uniform_symbol_frames<'py>(
    py: Python<'py>,
    symbol: &str,
    n_frames: usize,
    n_atoms: usize,
) -> PyResult<Bound<'py, PyList>> {
    let py_symbol = pyo3::types::PyString::new(py, symbol).unbind();
    let row =
        pyo3::types::PyTuple::new(py, (0..n_atoms).map(|_| py_symbol.clone_ref(py)))?.unbind();
    pyo3::types::PyList::new(py, (0..n_frames).map(|_| row.clone_ref(py)))
}

fn species_index(index: isize, len: usize) -> PyResult<usize> {
    let resolved = if index < 0 {
        index + len as isize
    } else {
        index
    };
    if resolved < 0 || resolved as usize >= len {
        return Err(pyo3::exceptions::PyIndexError::new_err("species index"));
    }
    Ok(resolved as usize)
}

/// Wide-frame species: one interned string per distinct symbol, and the
/// per-atom ids. A frame below 4096 atoms is still a tuple. A wide frame
/// is this view, so the read does not build a million-item tuple.
///
/// ``len(frames)`` is the frame count. ``frames[i]`` is a
/// :class:`SpeciesRow`. ``frames.ids()`` is a ``uint32`` array of shape
/// ``(frames, atoms)``. The sequence compares equal to a list or tuple of
/// per-frame symbol sequences, slices to a tuple of rows, pickles, and
/// hashes as that tuple of rows.
#[pyclass(module = "readcon", name = "SpeciesFrames")]
struct SpeciesFrames {
    n_frames: usize,
    n_atoms: usize,
    pool: Vec<Py<PyString>>,
    /// Empty when every atom uses `pool[0]`.
    ids: Vec<u32>,
}

/// One frame of interned species symbols.
///
/// Behaves as a tuple of strings: ``len``, index, iteration, a slice that
/// is a tuple, equality with a tuple or a list, pickle, and hash.
#[pyclass(module = "readcon", name = "SpeciesRow")]
struct SpeciesRow {
    parent: Py<SpeciesFrames>,
    frame: usize,
}

#[pyclass(module = "readcon")]
struct SpeciesIter {
    parent: Py<SpeciesFrames>,
    frame: usize,
    index: usize,
}

#[pyclass(module = "readcon")]
struct SpeciesFramesIter {
    parent: Py<SpeciesFrames>,
    index: usize,
}

#[pymethods]
impl SpeciesFrames {
    #[new]
    fn new(
        py: Python<'_>,
        symbols: Vec<String>,
        ids: Vec<u32>,
        n_frames: usize,
        n_atoms: usize,
    ) -> Self {
        let mut pool = Vec::with_capacity(symbols.len().max(1));
        for symbol in symbols {
            pool.push(PyString::new(py, &symbol).unbind());
        }
        if pool.is_empty() {
            pool.push(PyString::new(py, "").unbind());
        }
        let ids = if pool.len() == 1 { Vec::new() } else { ids };
        Self {
            n_frames,
            n_atoms,
            pool,
            ids,
        }
    }

    fn __len__(&self) -> usize {
        self.n_frames
    }

    fn __getitem__(slf: &Bound<'_, Self>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let n_frames = slf.borrow().n_frames;
        if let Ok(index) = key.extract::<isize>() {
            let frame = species_index(index, n_frames)?;
            let row = Py::new(
                py,
                SpeciesRow {
                    parent: slf.clone().unbind(),
                    frame,
                },
            )?;
            return Ok(row.into_any());
        }
        let slice = key
            .cast::<PySlice>()
            .map_err(|_| PyTypeError::new_err("species index"))?;
        let indices = slice.indices(n_frames as isize)?;
        let mut rows = Vec::with_capacity(indices.slicelength);
        let mut cursor = indices.start;
        for _ in 0..indices.slicelength {
            let frame = species_index(cursor, n_frames)?;
            rows.push(Py::new(
                py,
                SpeciesRow {
                    parent: slf.clone().unbind(),
                    frame,
                },
            )?);
            cursor += indices.step;
        }
        Ok(PyTuple::new(py, rows)?.into_any().unbind())
    }

    fn __iter__(slf: &Bound<'_, Self>) -> PyResult<Py<SpeciesFramesIter>> {
        Py::new(
            slf.py(),
            SpeciesFramesIter {
                parent: slf.clone().unbind(),
                index: 0,
            },
        )
    }

    fn __eq__(slf: &Bound<'_, Self>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        let py = slf.py();
        if slf.is(other) {
            return Ok(true);
        }
        if let Ok(frames) = other.cast::<SpeciesFrames>() {
            return frames_equal(py, slf, frames);
        }
        if !other.is_instance_of::<PyList>() && !other.is_instance_of::<PyTuple>() {
            return Ok(false);
        }
        let seq = other.cast::<PySequence>()?;
        let n_frames = slf.borrow().n_frames;
        if seq.len()? != n_frames {
            return Ok(false);
        }
        for frame in 0..n_frames {
            let row = seq.get_item(frame)?;
            if !frame_matches(py, slf, frame, &row)? {
                return Ok(false);
            }
        }
        Ok(true)
    }

    fn __hash__(slf: &Bound<'_, Self>) -> PyResult<isize> {
        let py = slf.py();
        let borrowed = slf.borrow();
        let mut rows = Vec::with_capacity(borrowed.n_frames);
        for frame in 0..borrowed.n_frames {
            rows.push(row_tuple(py, &borrowed, frame)?);
        }
        drop(borrowed);
        PyTuple::new(py, rows)?.hash()
    }

    fn __reduce__<'py>(
        slf: &Bound<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyTuple>)> {
        let cls = slf.get_type().into_any();
        let this = slf.borrow();
        let mut symbols = Vec::with_capacity(this.pool.len());
        for symbol in &this.pool {
            symbols.push(symbol.bind(py).to_str()?.to_string());
        }
        let symbols = symbols.into_py_any(py)?;
        let ids = this.ids.clone().into_py_any(py)?;
        let n_frames = this.n_frames.into_py_any(py)?;
        let n_atoms = this.n_atoms.into_py_any(py)?;
        Ok((cls, PyTuple::new(py, [symbols, ids, n_frames, n_atoms])?))
    }

    /// Per-atom species ids, shape `(frames, atoms)`. Zeros when the file
    /// is one symbol.
    fn ids<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray2<u32>>> {
        if self.ids.is_empty() {
            let flat = vec![0u32; self.n_frames.saturating_mul(self.n_atoms)];
            let array = Array2::from_shape_vec((self.n_frames, self.n_atoms), flat)
                .map_err(|err| PyValueError::new_err(err.to_string()))?;
            return Ok(array.into_pyarray(py));
        }
        let array = Array2::from_shape_vec((self.n_frames, self.n_atoms), self.ids.clone())
            .map_err(|err| PyValueError::new_err(err.to_string()))?;
        Ok(array.into_pyarray(py))
    }
}

impl SpeciesFrames {
    fn id_at(&self, frame: usize, atom: usize) -> u32 {
        if self.ids.is_empty() {
            0
        } else {
            self.ids[frame * self.n_atoms + atom]
        }
    }

    fn symbol_at(&self, py: Python<'_>, frame: usize, atom: usize) -> PyResult<Py<PyString>> {
        let id = self.id_at(frame, atom) as usize;
        self.pool
            .get(id)
            .map(|symbol| symbol.clone_ref(py))
            .ok_or_else(|| PyValueError::new_err("species id"))
    }

    fn owned_text(&self, py: Python<'_>) -> PyResult<OwnedText> {
        let mut symbols = Vec::with_capacity(self.pool.len());
        for symbol in &self.pool {
            symbols.push(symbol.bind(py).to_str()?.to_string());
        }
        let total = self.n_frames.saturating_mul(self.n_atoms);
        let ids = if self.ids.is_empty() {
            vec![0u32; total]
        } else {
            self.ids.clone()
        };
        Ok(OwnedText { symbols, ids })
    }
}

fn row_tuple<'py>(
    py: Python<'py>,
    frames: &SpeciesFrames,
    frame: usize,
) -> PyResult<Bound<'py, PyTuple>> {
    let mut items = Vec::with_capacity(frames.n_atoms);
    for atom in 0..frames.n_atoms {
        items.push(frames.symbol_at(py, frame, atom)?);
    }
    PyTuple::new(py, items)
}

fn frame_symbol<'py>(
    py: Python<'py>,
    frames: &Bound<'py, SpeciesFrames>,
    frame: usize,
    atom: usize,
) -> PyResult<Py<PyString>> {
    frames.borrow().symbol_at(py, frame, atom)
}

fn frame_matches(
    py: Python<'_>,
    frames: &Bound<'_, SpeciesFrames>,
    frame: usize,
    other: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let n_atoms = frames.borrow().n_atoms;
    if let Ok(row) = other.cast::<SpeciesRow>() {
        if row.is(frames) {
            return Ok(false);
        }
        let (parent, other_frame) = {
            let borrowed = row.borrow();
            (borrowed.parent.clone_ref(py), borrowed.frame)
        };
        if parent.bind(py).is(frames) {
            let table = frames.borrow();
            if table.n_atoms != n_atoms {
                return Ok(false);
            }
            for atom in 0..n_atoms {
                if table.id_at(frame, atom) != table.id_at(other_frame, atom) {
                    return Ok(false);
                }
            }
            return Ok(true);
        }
        let other_atoms = parent.bind(py).borrow().n_atoms;
        if other_atoms != n_atoms {
            return Ok(false);
        }
        for atom in 0..n_atoms {
            let left = frame_symbol(py, frames, frame, atom)?;
            let right = parent.bind(py).borrow().symbol_at(py, other_frame, atom)?;
            if left.bind(py).to_str()? != right.bind(py).to_str()? {
                return Ok(false);
            }
        }
        return Ok(true);
    }
    if !other.is_instance_of::<PyList>() && !other.is_instance_of::<PyTuple>() {
        return Ok(false);
    }
    let seq = other.cast::<PySequence>()?;
    if seq.len()? != n_atoms {
        return Ok(false);
    }
    for atom in 0..n_atoms {
        let symbol = frame_symbol(py, frames, frame, atom)?;
        let item = seq.get_item(atom)?;
        if !PyAnyMethods::eq(&item, symbol.bind(py))? {
            return Ok(false);
        }
    }
    Ok(true)
}

fn frames_equal(
    py: Python<'_>,
    left: &Bound<'_, SpeciesFrames>,
    right: &Bound<'_, SpeciesFrames>,
) -> PyResult<bool> {
    let (left_frames, left_atoms) = {
        let borrowed = left.borrow();
        (borrowed.n_frames, borrowed.n_atoms)
    };
    let (right_frames, right_atoms) = {
        let borrowed = right.borrow();
        (borrowed.n_frames, borrowed.n_atoms)
    };
    if left_frames != right_frames || left_atoms != right_atoms {
        return Ok(false);
    }
    for frame in 0..left_frames {
        for atom in 0..left_atoms {
            let a = frame_symbol(py, left, frame, atom)?;
            let b = frame_symbol(py, right, frame, atom)?;
            if a.bind(py).to_str()? != b.bind(py).to_str()? {
                return Ok(false);
            }
        }
    }
    Ok(true)
}

#[pymethods]
impl SpeciesRow {
    #[new]
    fn new(parent: Py<SpeciesFrames>, frame: usize) -> Self {
        Self { parent, frame }
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        Ok(self.parent.bind(py).borrow().n_atoms)
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let frames = self.parent.bind(py).borrow();
        let n_atoms = frames.n_atoms;
        if let Ok(index) = key.extract::<isize>() {
            let atom = species_index(index, n_atoms)?;
            let symbol = frames.symbol_at(py, self.frame, atom)?;
            return Ok(symbol.into_any());
        }
        let slice = key
            .cast::<PySlice>()
            .map_err(|_| PyTypeError::new_err("species index"))?;
        let indices = slice.indices(n_atoms as isize)?;
        let mut items = Vec::with_capacity(indices.slicelength);
        let mut cursor = indices.start;
        for _ in 0..indices.slicelength {
            let atom = species_index(cursor, n_atoms)?;
            items.push(frames.symbol_at(py, self.frame, atom)?);
            cursor += indices.step;
        }
        drop(frames);
        Ok(PyTuple::new(py, items)?.into_any().unbind())
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<SpeciesIter>> {
        Py::new(
            py,
            SpeciesIter {
                parent: self.parent.clone_ref(py),
                frame: self.frame,
                index: 0,
            },
        )
    }

    fn __eq__(slf: &Bound<'_, Self>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        let py = slf.py();
        if slf.is(other) {
            return Ok(true);
        }
        let (parent, frame) = {
            let this = slf.borrow();
            (this.parent.clone_ref(py), this.frame)
        };
        frame_matches(py, &parent.bind(py), frame, other)
    }

    fn __hash__(&self, py: Python<'_>) -> PyResult<isize> {
        let frames = self.parent.bind(py).borrow();
        let row = row_tuple(py, &frames, self.frame)?;
        drop(frames);
        row.hash()
    }

    fn __reduce__<'py>(
        slf: &Bound<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyTuple>)> {
        let cls = slf.get_type().into_any();
        let this = slf.borrow();
        let parent = this.parent.clone_ref(py).into_any();
        let frame = this.frame.into_py_any(py)?;
        Ok((cls, PyTuple::new(py, [parent, frame])?))
    }
}

#[pymethods]
impl SpeciesFramesIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Option<Py<SpeciesRow>>> {
        let n_frames = self.parent.bind(py).borrow().n_frames;
        if self.index >= n_frames {
            return Ok(None);
        }
        let frame = self.index;
        self.index += 1;
        Ok(Some(Py::new(
            py,
            SpeciesRow {
                parent: self.parent.clone_ref(py),
                frame,
            },
        )?))
    }
}

#[pymethods]
impl SpeciesIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> Option<Py<pyo3::types::PyString>> {
        let frames = self.parent.bind(py).borrow();
        if self.index >= frames.n_atoms {
            return None;
        }
        let id = if frames.ids.is_empty() {
            0
        } else {
            frames.ids[self.frame * frames.n_atoms + self.index]
        };
        let symbol = frames.pool.get(id as usize)?.clone_ref(py);
        drop(frames);
        self.index += 1;
        Some(symbol)
    }
}

fn species_view<'py>(
    py: Python<'py>,
    pool: &[String],
    ids: Vec<u32>,
    n_frames: usize,
    n_atoms: usize,
) -> PyResult<Py<SpeciesFrames>> {
    let mut py_pool = Vec::with_capacity(pool.len().max(1));
    for symbol in pool {
        py_pool.push(pyo3::types::PyString::new(py, symbol).unbind());
    }
    if py_pool.is_empty() {
        py_pool.push(pyo3::types::PyString::new(py, "").unbind());
    }
    let ids = if py_pool.len() == 1 { Vec::new() } else { ids };
    Py::new(
        py,
        SpeciesFrames {
            n_frames,
            n_atoms,
            pool: py_pool,
            ids,
        },
    )
}

/// Read an extended XYZ file.
///
/// The comment line gives the lattice and the column order. The returned
/// dict holds ``positions`` with shape `(frames, atoms, 3)`, ``masses``
/// with shape `(frames, atoms)`, ``cell`` with shape `(frames, 6)`,
/// ``species`` as one symbol sequence per frame, and ``arrays``, a dict of
/// every per-atom `Properties` column. A real column is one float array.
/// A text column is a list of tuples. A repeated symbol is one string
/// object, and a frame whose symbols match the previous frame is that
/// same tuple when the frame has fewer than 4096 atoms. A wider frame is
/// a ``SpeciesRow`` inside ``SpeciesFrames``: an immutable sequence over
/// interned symbols. ``species.ids()`` is the ``(frames, atoms)`` id
/// array. A row supports len, index, iteration, slicing, equality with a
/// tuple or a list, pickling, and hashing. ``arrays['species']`` is
/// ``species``.
/// ``arrays['pos']`` and ``arrays['masses']`` are the top-level slabs.
/// `n_threads` of `None` or `1` is the serial scan. `n >= 2` splits frames.
#[pyfunction]
#[pyo3(signature = (path, n_threads=None))]
fn read_extxyz<'py>(
    py: Python<'py>,
    path: &str,
    n_threads: Option<usize>,
) -> PyResult<Bound<'py, PyDict>> {
    let path_owned = path.to_string();
    let workers = n_threads.unwrap_or(1);
    let mut tables = py
        .detach(move || -> Result<_, String> {
            use std::io::Read;
            let mut file = std::fs::File::open(&path_owned).map_err(|_| "read".to_string())?;
            let mut magic = [0u8; 4];
            let nmagic = file.read(&mut magic).map_err(|_| "read".to_string())?;
            if !matches!(
                crate::compression::detect_compression(&magic[..nmagic]),
                crate::compression::Compression::None
            ) {
                drop(file);
                let bytes = crate::compression::read_file_bytes(std::path::Path::new(&path_owned))
                    .map_err(|err| err.to_string())?;
                return crate::extxyz_scan::tables_from_extxyz_bytes_with_threads(&bytes, workers);
            }
            let meta = file.metadata().map_err(|_| "read".to_string())?;
            // A pipe has no map. A proc file can report size 0 and still
            // return bytes from read; mapping it fails or yields an empty
            // slice. A regular file with a size is mapped. Truncating that
            // file while the map is alive is still a SIGBUS.
            if meta.is_file() && meta.len() > 0 {
                // SAFETY: `file` is a regular file of nonzero length. The
                // slice is the parse input and is dropped before return.
                if let Ok(bytes) = unsafe { memmap2::Mmap::map(&file) } {
                    return crate::extxyz_scan::tables_from_extxyz_bytes_with_threads(
                        &bytes, workers,
                    );
                }
            }
            let mut bytes = Vec::new();
            bytes.extend_from_slice(&magic[..nmagic]);
            file.read_to_end(&mut bytes)
                .map_err(|_| "read".to_string())?;
            crate::extxyz_scan::tables_from_extxyz_bytes_with_threads(&bytes, workers)
        })
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let n_frames = tables.n_frames;
    let n_atoms = tables.n_atoms;
    let positions = ndarray::Array3::from_shape_vec(
        (n_frames, n_atoms, 3),
        std::mem::take(&mut tables.positions),
    )
    .unwrap()
    .into_pyarray(py);
    let masses =
        ndarray::Array2::from_shape_vec((n_frames, n_atoms), std::mem::take(&mut tables.masses))
            .unwrap()
            .into_pyarray(py);
    let cell = ndarray::Array2::from_shape_vec((n_frames, 6), std::mem::take(&mut tables.cell))
        .unwrap()
        .into_pyarray(py);
    let arrays = PyDict::new(py);
    let mut shared_species: Option<Bound<'py, PyList>> = None;
    for column in tables.columns.drain(..) {
        if column.kind == b'S' {
            if column.name == "species" && column.width == 1 && column.text.is_empty() {
                continue;
            }
            let built = py_text_frames(py, &column.text, n_atoms, column.width)?;
            if column.name == "species" && column.width == 1 {
                shared_species = Some(built.clone());
            }
            arrays.set_item(column.name, built)?;
        } else if column.name == "pos" && column.width == 3 {
            // The top-level slab is this column. One array, not a second copy.
            arrays.set_item(column.name, &positions)?;
        } else if (column.name == "masses" || column.name == "mass") && column.width == 1 {
            arrays.set_item(column.name, &masses)?;
        } else if column.width == 1 {
            let values = ndarray::Array2::from_shape_vec((n_frames, n_atoms), column.real).unwrap();
            arrays.set_item(column.name, values.into_pyarray(py))?;
        } else {
            let values =
                ndarray::Array3::from_shape_vec((n_frames, n_atoms, column.width), column.real)
                    .unwrap();
            arrays.set_item(column.name, values.into_pyarray(py))?;
        }
    }
    let species: Bound<'_, PyAny> = match shared_species {
        Some(found) => found.into_any(),
        None if n_atoms >= 4096
            && (tables.uniform_species.is_some() || !tables.species_ids.is_empty()) =>
        {
            let pool = if let Some(symbol) = tables.uniform_species.take() {
                vec![symbol]
            } else {
                std::mem::take(&mut tables.species_pool)
            };
            let ids = std::mem::take(&mut tables.species_ids);
            let built = species_view(py, &pool, ids, n_frames, n_atoms)?;
            let bound = built.bind(py).clone();
            arrays.set_item("species", &bound)?;
            bound.into_any()
        }
        None => {
            let built = if let Some(symbol) = tables.uniform_species.as_deref() {
                uniform_symbol_frames(py, symbol, n_frames, n_atoms)?
            } else if !tables.species_ids.is_empty() {
                indexed_symbol_frames(
                    py,
                    &tables.species_pool,
                    &tables.species_ids,
                    n_frames,
                    n_atoms,
                )?
            } else {
                py_text_frames(py, &tables.species, n_atoms, 1)?
            };
            arrays.set_item("species", &built)?;
            built.into_any()
        }
    };
    let dict = PyDict::new(py);
    dict.set_item("positions", positions)?;
    dict.set_item("masses", masses)?;
    dict.set_item("cell", cell)?;
    dict.set_item("species", species)?;
    dict.set_item("arrays", arrays)?;
    Ok(dict)
}

struct OwnedText {
    symbols: Vec<String>,
    ids: Vec<u32>,
}

fn intern_text_column(value: &Bound<'_, PyAny>) -> PyResult<OwnedText> {
    if let Ok(table) = value.cast::<SpeciesFrames>() {
        return table.borrow().owned_text(value.py());
    }
    let frames = match frame_tuples(value) {
        Some(frames) => frames,
        None => return intern_text_iter(value),
    };
    let total: usize = frames.iter().map(|frame| frame.len()).sum();
    let mut uniq = Vec::new();
    let mut ids = Vec::with_capacity(total);
    for frame in &frames {
        let base = frame.as_ptr();
        for index in 0..frame.len() {
            let ptr = unsafe { pyo3::ffi::PyTuple_GET_ITEM(base, index as isize) } as usize;
            if let Some(id) = uniq.iter().position(|known| *known == ptr) {
                ids.push(id as u32);
                continue;
            }
            if uniq.len() == 64 {
                return intern_text_iter(value);
            }
            uniq.push(ptr);
            ids.push((uniq.len() - 1) as u32);
        }
    }
    let mut symbols = Vec::with_capacity(uniq.len());
    let py = value.py();
    for ptr in uniq {
        let obj = unsafe { Bound::from_borrowed_ptr(py, ptr as *mut pyo3::ffi::PyObject) };
        symbols.push(obj.cast::<pyo3::types::PyString>()?.to_str()?.to_string());
    }
    Ok(OwnedText { symbols, ids })
}

fn frame_tuples<'a>(value: &Bound<'a, PyAny>) -> Option<Vec<Bound<'a, pyo3::types::PyTuple>>> {
    if let Ok(tuple) = value.cast::<pyo3::types::PyTuple>() {
        if tuple.is_empty() {
            return Some(Vec::new());
        }
        if tuple
            .get_item(0)
            .ok()?
            .cast::<pyo3::types::PyString>()
            .is_ok()
        {
            return Some(vec![tuple.clone()]);
        }
    }
    let mut frames = Vec::new();
    for frame in value.try_iter().ok()? {
        let frame = frame.ok()?;
        let tuple = frame.cast::<pyo3::types::PyTuple>().ok()?.clone();
        if !tuple.is_empty()
            && tuple
                .get_item(0)
                .ok()?
                .cast::<pyo3::types::PyString>()
                .is_err()
        {
            return None;
        }
        frames.push(tuple);
    }
    Some(frames)
}

fn intern_text_iter(value: &Bound<'_, PyAny>) -> PyResult<OwnedText> {
    let mut symbols_py: Vec<pyo3::Py<pyo3::types::PyString>> = Vec::new();
    let mut ptrs: Vec<usize> = Vec::new();
    let mut ids = Vec::new();
    for frame in value.try_iter()? {
        let frame = frame?;
        for atom in frame.try_iter()? {
            let atom = atom?;
            let text = atom.cast::<pyo3::types::PyString>()?;
            let ptr = text.as_ptr() as usize;
            if let Some(index) = ptrs.iter().position(|known| *known == ptr) {
                ids.push(index as u32);
                continue;
            }
            if ptrs.len() == 64 {
                return owned_text_flat(value);
            }
            ptrs.push(ptr);
            ids.push((ptrs.len() - 1) as u32);
            symbols_py.push(text.clone().unbind());
        }
    }
    let mut symbols = Vec::with_capacity(symbols_py.len());
    for item in symbols_py {
        symbols.push(item.bind(value.py()).to_str()?.to_string());
    }
    Ok(OwnedText { symbols, ids })
}

fn owned_text_flat(value: &Bound<'_, PyAny>) -> PyResult<OwnedText> {
    let mut symbols = Vec::new();
    for frame in value.try_iter()? {
        let frame = frame?;
        for atom in frame.try_iter()? {
            symbols.push(atom?.cast::<pyo3::types::PyString>()?.to_str()?.to_string());
        }
    }
    Ok(OwnedText {
        symbols,
        ids: Vec::new(),
    })
}

struct TextColumn<'a> {
    name: &'a str,
    /// Unique spellings, or one spelling per atom when `ids` is empty.
    tokens: &'a [String],
    /// Index into `tokens` for each atom. Empty means `tokens[base]`.
    ids: &'a [u32],
}

struct RealColumn<'a> {
    name: &'a str,
    width: usize,
    values: &'a [f64],
}

impl crate::extxyz_scan::ExtxyzSource for TextColumn<'_> {
    fn column_name(&self) -> &str {
        self.name
    }

    fn column_kind(&self) -> u8 {
        b'S'
    }

    fn column_width(&self) -> usize {
        1
    }

    fn write_fields(&self, base: usize, out: &mut Vec<u8>) {
        let text = if self.ids.is_empty() {
            self.tokens[base].as_str()
        } else {
            self.tokens[self.ids[base] as usize].as_str()
        };
        out.extend_from_slice(text.as_bytes());
    }
}

impl crate::extxyz_scan::ExtxyzSource for RealColumn<'_> {
    fn column_name(&self) -> &str {
        self.name
    }

    fn column_kind(&self) -> u8 {
        b'R'
    }

    fn column_width(&self) -> usize {
        self.width
    }

    fn write_fields(&self, base: usize, out: &mut Vec<u8>) {
        for slot in 0..self.width {
            if slot > 0 {
                out.push(b' ');
            }
            crate::extxyz_scan::append_extxyz_number(out, self.values[base + slot]);
        }
    }
}

/// Write an extended XYZ file from the dict returned by ``read_extxyz``.
///
/// Species, positions, the lattice, ``pbc`` and every per-atom column,
/// including forces, are written. Numeric columns are borrowed from the
/// caller's arrays. The binding does not allocate a second copy of them.
#[pyfunction]
#[pyo3(signature = (path, data, n_threads=None))]
fn write_extxyz(path: &str, data: &Bound<'_, PyDict>, n_threads: Option<usize>) -> PyResult<()> {
    let positions = data
        .get_item("positions")?
        .ok_or_else(|| PyValueError::new_err("positions"))?;
    let pos = positions.cast::<PyArray3<f64>>()?;
    let shape = {
        let view = pos.readonly();
        view.as_array().shape().to_vec()
    };
    if shape.len() != 3 || shape[2] != 3 {
        return Err(PyValueError::new_err("positions"));
    }
    let n_frames = shape[0];
    let n_atoms = shape[1];
    if data.get_item("species")?.is_none() {
        return Err(PyValueError::new_err("species"));
    }
    let cell_obj = data
        .get_item("cell")?
        .ok_or_else(|| PyValueError::new_err("cell"))?;
    let cell_array = cell_obj.cast::<PyArray2<f64>>()?.clone();
    let arrays_obj = data
        .get_item("arrays")?
        .ok_or_else(|| PyValueError::new_err("arrays"))?;
    let arrays = arrays_obj.cast::<PyDict>()?;
    let mut text_names = Vec::new();
    let mut text_items: Vec<OwnedText> = Vec::new();
    let mut real3_meta: Vec<(String, usize)> = Vec::new();
    let mut real3_arrays: Vec<Bound<'_, PyArray3<f64>>> = Vec::new();
    let mut real2_names = Vec::new();
    let mut real2_arrays: Vec<Bound<'_, PyArray2<f64>>> = Vec::new();
    let mut order = Vec::new();
    for (key, value) in arrays.iter() {
        let name: String = key.extract()?;
        if let Ok(wide) = value.cast::<PyArray3<f64>>() {
            let view = wide.readonly();
            let width = *view.as_array().shape().get(2).unwrap_or(&1);
            if view.as_slice().is_err() {
                return Err(PyValueError::new_err(format!("column {name}")));
            }
            drop(view);
            real3_meta.push((name, width));
            real3_arrays.push(wide.clone());
            order.push(1u8);
        } else if let Ok(thin) = value.cast::<PyArray2<f64>>() {
            let view = thin.readonly();
            if view.as_slice().is_err() {
                return Err(PyValueError::new_err(format!("column {name}")));
            }
            drop(view);
            real2_names.push(name);
            real2_arrays.push(thin.clone());
            order.push(2u8);
        } else {
            text_names.push(name);
            text_items.push(intern_text_column(&value)?);
            order.push(0u8);
        }
    }
    let cell_view = cell_array.readonly();
    let cell = cell_view.as_slice()?;
    let real3_views: Vec<_> = real3_arrays.iter().map(|array| array.readonly()).collect();
    let real2_views: Vec<_> = real2_arrays.iter().map(|array| array.readonly()).collect();
    let mut real3_slices = Vec::with_capacity(real3_views.len());
    for view in &real3_views {
        real3_slices.push(view.as_slice()?);
    }
    let mut real2_slices = Vec::with_capacity(real2_views.len());
    for view in &real2_views {
        real2_slices.push(view.as_slice()?);
    }
    let mut texts = Vec::new();
    let mut reals = Vec::new();
    let mut plan = Vec::new();
    let mut text_index = 0;
    let mut real3_index = 0;
    let mut real2_index = 0;
    for kind in &order {
        match kind {
            0 => {
                texts.push(TextColumn {
                    name: &text_names[text_index],
                    tokens: &text_items[text_index].symbols,
                    ids: &text_items[text_index].ids,
                });
                plan.push((0u8, texts.len() - 1));
                text_index += 1;
            }
            1 => {
                reals.push(RealColumn {
                    name: &real3_meta[real3_index].0,
                    width: real3_meta[real3_index].1,
                    values: real3_slices[real3_index],
                });
                plan.push((1u8, reals.len() - 1));
                real3_index += 1;
            }
            _ => {
                reals.push(RealColumn {
                    name: &real2_names[real2_index],
                    width: 1,
                    values: real2_slices[real2_index],
                });
                plan.push((1u8, reals.len() - 1));
                real2_index += 1;
            }
        }
    }
    let sources: Vec<&(dyn crate::extxyz_scan::ExtxyzSource + Sync)> = plan
        .iter()
        .map(|(kind, index)| {
            if *kind == 0 {
                &texts[*index] as &(dyn crate::extxyz_scan::ExtxyzSource + Sync)
            } else {
                &reals[*index] as &(dyn crate::extxyz_scan::ExtxyzSource + Sync)
            }
        })
        .collect();
    let workers = n_threads.unwrap_or(1);
    let codec = crate::compression::detect_compression_from_extension(std::path::Path::new(path));
    if !matches!(codec, crate::compression::Compression::None) {
        if let Some(parent) = std::path::Path::new(path).parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent).map_err(|_| PyValueError::new_err("write"))?;
        }
        let bytes = crate::extxyz_scan::extxyz_bytes_with_threads(
            n_frames, n_atoms, cell, &sources, workers,
        )
        .map_err(PyValueError::new_err)?;
        let members = crate::compression::compression_workers(bytes.len());
        let threads = match n_threads {
            Some(count) if count >= 1 => count,
            _ => crate::compression::default_deflate_threads(members),
        };
        let written = match codec {
            crate::compression::Compression::Gzip => {
                crate::compression::write_gzip_members_limited(
                    std::path::Path::new(path),
                    &bytes,
                    members,
                    threads,
                )
            }
            crate::compression::Compression::Zstd => {
                #[cfg(feature = "zstd")]
                {
                    crate::compression::write_zstd_members_limited(
                        std::path::Path::new(path),
                        &bytes,
                        members,
                        threads,
                    )
                }
                #[cfg(not(feature = "zstd"))]
                {
                    let _ = (members, threads);
                    Err(std::io::Error::new(
                        std::io::ErrorKind::Unsupported,
                        "zstd compression requires readcon built with the zstd feature",
                    ))
                }
            }
            crate::compression::Compression::None => unreachable!("plain extxyz already returned"),
        };
        return written
            .map(|_| ())
            .map_err(|err| PyValueError::new_err(err.to_string()));
    }
    if workers >= 2 {
        if let Some(parent) = std::path::Path::new(path).parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent).map_err(|_| PyValueError::new_err("write"))?;
        }
        return crate::extxyz_scan::extxyz_path_with_threads(
            std::path::Path::new(path),
            n_frames,
            n_atoms,
            cell,
            &sources,
            workers,
        )
        .map_err(PyValueError::new_err);
    }
    let bytes =
        crate::extxyz_scan::extxyz_bytes_with_threads(n_frames, n_atoms, cell, &sources, workers)
            .map_err(PyValueError::new_err)?;
    if let Some(parent) = std::path::Path::new(path).parent()
        && !parent.as_os_str().is_empty()
    {
        std::fs::create_dir_all(parent).map_err(|_| PyValueError::new_err("write"))?;
    }
    write_bytes_parallel(path, &bytes, n_threads.unwrap_or(1))
        .map_err(|_| PyValueError::new_err("write"))
}

fn write_bytes_parallel(path: &str, bytes: &[u8], workers: usize) -> std::io::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut opts = std::fs::OpenOptions::new();
    opts.write(true).create(true).truncate(true);
    let _ = OpenOptionsExt::mode(&mut opts, 0o644);
    let file = opts.open(path)?;
    file.set_len(bytes.len() as u64)?;
    if workers < 2 || bytes.len() < (1 << 20) {
        use std::io::Write;
        let mut file = file;
        return file.write_all(bytes);
    }
    let chunk = bytes.len().div_ceil(workers);
    std::thread::scope(|scope| {
        let mut handles = Vec::new();
        for worker in 0..workers {
            let from = worker * chunk;
            if from >= bytes.len() {
                break;
            }
            let to = (from + chunk).min(bytes.len());
            let cloned = file.try_clone()?;
            handles.push(scope.spawn(move || pwrite_all(&cloned, &bytes[from..to], from as u64)));
        }
        for handle in handles {
            handle
                .join()
                .unwrap_or_else(|_| Err(std::io::Error::other("write")))?;
        }
        Ok(())
    })
}

fn pwrite_all(file: &std::fs::File, buf: &[u8], mut offset: u64) -> std::io::Result<()> {
    use std::os::unix::io::AsRawFd;
    if buf.is_empty() {
        return Ok(());
    }
    let fd = file.as_raw_fd();
    let mut written = 0usize;
    while written < buf.len() {
        let n = unsafe {
            libc::pwrite(
                fd,
                buf[written..].as_ptr() as *const libc::c_void,
                buf.len() - written,
                offset as libc::off_t,
            )
        };
        if n < 0 {
            let err = std::io::Error::last_os_error();
            if err.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(err);
        }
        if n == 0 {
            return Err(std::io::Error::new(std::io::ErrorKind::WriteZero, "pwrite"));
        }
        written += n as usize;
        offset += n as u64;
    }
    Ok(())
}

/// Read a PDB file into positions, masses and the cell.
///
/// Positions have shape `(frames, atoms, 3)`. Masses have shape
/// `(frames, atoms)`. The cell has shape `(frames, 6)` and stores
/// lengths then angles. One scan fills those arrays.
#[pyfunction]
#[allow(clippy::type_complexity)]
fn read_pdb<'py>(
    py: Python<'py>,
    path: &str,
) -> PyResult<(
    Bound<'py, numpy::PyArray3<f64>>,
    Bound<'py, numpy::PyArray2<f64>>,
    Bound<'py, numpy::PyArray2<f64>>,
)> {
    let tables = crate::pdb_scan::tables_from_pdb_path(std::path::Path::new(path))
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
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
#[allow(clippy::too_many_arguments)]
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
/// Typical use:
///
/// ```python
/// frames = readcon.read_all_frames("traj.con")
/// out = readcon.select_atom_positions_on_frames("name H", frames)
/// # out["frames"][i]["positions"] — H xyz on frame i
/// ```
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
