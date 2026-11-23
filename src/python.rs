use ndarray::{Array1, Array2, Array3, ArrayView1, ArrayView2};
use numpy::{
    IntoPyArray, PyArray1, PyArray2, PyArray3, PyArrayMethods, PyReadonlyArray2, PyReadonlyArray3,
    PyUntypedArrayMethods,
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

include!("python_borrow.rs");

/// Python-visible atom data.
#[pyclass(name = "Atom", from_py_object)]
#[derive(Clone)]
pub struct PyAtomDatum {
    pub symbol: String,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub fixed: [bool; 3],
    pub atom_id: u64,
    pub mass: Option<f64>,
    pub vx: Option<f64>,
    pub vy: Option<f64>,
    pub vz: Option<f64>,
    pub fx: Option<f64>,
    pub fy: Option<f64>,
    pub fz: Option<f64>,
    /// Per-atom energy contribution; populated when the file declares an
    /// `"energies"` section. None for ordinary frames where only the
    /// per-frame total energy (`metadata['energy']`) is meaningful.
    pub energy: Option<f64>,
    pub charge: Option<f64>,
    pub spin: Option<f64>,
    pub mx: Option<f64>,
    pub my: Option<f64>,
    pub mz: Option<f64>,
    /// Displacement vector components (Angstrom); populated when the file
    /// declares a `"displacements"` section.
    pub dx: Option<f64>,
    pub dy: Option<f64>,
    pub dz: Option<f64>,
    /// Root-mean-square spread components (Angstrom) about `x`, `y`, `z`; populated when the file
    /// declares a `"spreads"` section.
    pub sx: Option<f64>,
    pub sy: Option<f64>,
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

    #[getter]
    fn symbol(slf: &Bound<'_, Self>) -> PyResult<String> {
        Ok(shared(slf)?.symbol.clone())
    }

    #[setter]
    fn set_symbol(slf: &Bound<'_, Self>, value: String) -> PyResult<()> {
        exclusive(slf)?.symbol = value;
        Ok(())
    }

    #[getter]
    fn x(slf: &Bound<'_, Self>) -> PyResult<f64> {
        Ok(shared(slf)?.x)
    }

    #[setter]
    fn set_x(slf: &Bound<'_, Self>, value: f64) -> PyResult<()> {
        exclusive(slf)?.x = value;
        Ok(())
    }

    #[getter]
    fn y(slf: &Bound<'_, Self>) -> PyResult<f64> {
        Ok(shared(slf)?.y)
    }

    #[setter]
    fn set_y(slf: &Bound<'_, Self>, value: f64) -> PyResult<()> {
        exclusive(slf)?.y = value;
        Ok(())
    }

    #[getter]
    fn z(slf: &Bound<'_, Self>) -> PyResult<f64> {
        Ok(shared(slf)?.z)
    }

    #[setter]
    fn set_z(slf: &Bound<'_, Self>, value: f64) -> PyResult<()> {
        exclusive(slf)?.z = value;
        Ok(())
    }

    #[getter]
    fn fixed(slf: &Bound<'_, Self>) -> PyResult<[bool; 3]> {
        Ok(shared(slf)?.fixed)
    }

    #[setter]
    fn set_fixed(slf: &Bound<'_, Self>, value: [bool; 3]) -> PyResult<()> {
        exclusive(slf)?.fixed = value;
        Ok(())
    }

    #[getter]
    fn atom_id(slf: &Bound<'_, Self>) -> PyResult<u64> {
        Ok(shared(slf)?.atom_id)
    }

    #[setter]
    fn set_atom_id(slf: &Bound<'_, Self>, value: u64) -> PyResult<()> {
        exclusive(slf)?.atom_id = value;
        Ok(())
    }

    #[getter]
    fn mass(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.mass)
    }

    #[setter]
    fn set_mass(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.mass = value;
        Ok(())
    }

    #[getter]
    fn vx(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.vx)
    }

    #[setter]
    fn set_vx(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.vx = value;
        Ok(())
    }

    #[getter]
    fn vy(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.vy)
    }

    #[setter]
    fn set_vy(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.vy = value;
        Ok(())
    }

    #[getter]
    fn vz(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.vz)
    }

    #[setter]
    fn set_vz(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.vz = value;
        Ok(())
    }

    #[getter]
    fn fx(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.fx)
    }

    #[setter]
    fn set_fx(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.fx = value;
        Ok(())
    }

    #[getter]
    fn fy(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.fy)
    }

    #[setter]
    fn set_fy(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.fy = value;
        Ok(())
    }

    #[getter]
    fn fz(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.fz)
    }

    #[setter]
    fn set_fz(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.fz = value;
        Ok(())
    }

    /// Per-atom energy contribution; populated when the file declares an
    /// `"energies"` section. None for ordinary frames where only the
    /// per-frame total energy (`metadata['energy']`) is meaningful.
    #[getter]
    fn energy(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.energy)
    }

    #[setter]
    fn set_energy(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.energy = value;
        Ok(())
    }

    #[getter]
    fn charge(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.charge)
    }

    #[setter]
    fn set_charge(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.charge = value;
        Ok(())
    }

    #[getter]
    fn spin(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.spin)
    }

    #[setter]
    fn set_spin(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.spin = value;
        Ok(())
    }

    #[getter]
    fn mx(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.mx)
    }

    #[setter]
    fn set_mx(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.mx = value;
        Ok(())
    }

    #[getter]
    fn my(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.my)
    }

    #[setter]
    fn set_my(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.my = value;
        Ok(())
    }

    #[getter]
    fn mz(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.mz)
    }

    #[setter]
    fn set_mz(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.mz = value;
        Ok(())
    }

    /// Displacement vector components (Angstrom); populated when the file
    /// declares a `"displacements"` section.
    #[getter]
    fn dx(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.dx)
    }

    #[setter]
    fn set_dx(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.dx = value;
        Ok(())
    }

    #[getter]
    fn dy(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.dy)
    }

    #[setter]
    fn set_dy(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.dy = value;
        Ok(())
    }

    #[getter]
    fn dz(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.dz)
    }

    #[setter]
    fn set_dz(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.dz = value;
        Ok(())
    }

    /// Root-mean-square spread components (Angstrom) about `x`, `y`, `z`; populated when the file
    /// declares a `"spreads"` section.
    #[getter]
    fn sx(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.sx)
    }

    #[setter]
    fn set_sx(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.sx = value;
        Ok(())
    }

    #[getter]
    fn sy(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.sy)
    }

    #[setter]
    fn set_sy(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.sy = value;
        Ok(())
    }

    #[getter]
    fn sz(slf: &Bound<'_, Self>) -> PyResult<Option<f64>> {
        Ok(shared(slf)?.sz)
    }

    #[setter]
    fn set_sz(slf: &Bound<'_, Self>, value: Option<f64>) -> PyResult<()> {
        exclusive(slf)?.sz = value;
        Ok(())
    }

    /// Backward-compatible property: true if any direction is fixed.
    #[getter(is_fixed)]
    fn py_is_fixed(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?.is_fixed())
    }

    #[getter(has_velocity)]
    fn py_has_velocity(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?.has_velocity())
    }

    #[getter(has_forces)]
    fn py_has_forces(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?.has_forces())
    }

    #[getter(has_energy)]
    fn py_has_energy(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?.has_energy())
    }

    #[getter(has_displacement)]
    fn py_has_displacement(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?.has_displacement())
    }

    #[getter(has_spread)]
    fn py_has_spread(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?.has_spread())
    }

    fn __repr__(slf: &Bound<'_, Self>) -> PyResult<String> {
        let atom = shared(slf)?;
        Ok(format!(
            "Atom(symbol='{}', x={}, y={}, z={}, atom_id={})",
            atom.symbol, atom.x, atom.y, atom.z, atom.atom_id
        ))
    }
}

impl PyAtomDatum {
    fn is_fixed(&self) -> bool {
        self.fixed[0] || self.fixed[1] || self.fixed[2]
    }

    fn has_velocity(&self) -> bool {
        self.vx.is_some() && self.vy.is_some() && self.vz.is_some()
    }

    fn has_forces(&self) -> bool {
        self.fx.is_some() && self.fy.is_some() && self.fz.is_some()
    }

    fn has_energy(&self) -> bool {
        self.energy.is_some()
    }

    fn has_displacement(&self) -> bool {
        self.dx.is_some() && self.dy.is_some() && self.dz.is_some()
    }

    fn has_spread(&self) -> bool {
        self.sx.is_some() && self.sy.is_some() && self.sz.is_some()
    }
}

impl PyAtomDatum {
    fn from_atom_with_mass(atom: &AtomDatum, xyz: [f64; 3], mass: f64) -> Self {
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
        Self {
            symbol: atom.symbol.to_string(),
            x: xyz[0],
            y: xyz[1],
            z: xyz[2],
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
    py_metadata_to_json_map_with_minor(obj).map(|(metadata, _)| metadata)
}

fn py_metadata_to_json_map_with_minor(
    obj: &Bound<'_, PyAny>,
) -> PyResult<(BTreeMap<String, Value>, Option<String>)> {
    if obj.is_none() {
        return Ok((BTreeMap::new(), None));
    }

    let dict = obj
        .cast::<PyDict>()
        .map_err(|_| PyValueError::new_err("metadata must be a dict"))?;

    let mut metadata = BTreeMap::new();
    let mut minor_raw = None;
    for (key, value) in dict.iter() {
        let key: String = key
            .extract()
            .map_err(|_| PyValueError::new_err("metadata keys must be strings"))?;
        if key == meta::CON_SPEC_VERSION || key == meta::SECTIONS {
            continue;
        }
        if key == meta::LATTICE_VECTORS {
            check_lattice_vectors_object(&value)?;
        }
        if key == meta::CON_SPEC_MINOR
            && !value.is_instance_of::<pyo3::types::PyBool>()
            && value.is_instance_of::<pyo3::types::PyInt>()
            && value.extract::<u64>().is_err()
            && value.extract::<i64>().is_err()
        {
            let text_any = value
                .py()
                .get_type::<pyo3::types::PyInt>()
                .call_method1("__str__", (&value,))?;
            let text = text_any.extract::<String>()?;
            if crate::parser::is_substitutable_huge_minor(&text) {
                minor_raw = Some(text);
                metadata.insert(
                    key,
                    Value::Number(Number::from(crate::types::SATURATED_SPEC_MINOR)),
                );
                continue;
            }
        }
        metadata.insert(key, py_to_json_value(&value)?);
    }
    Ok((metadata, minor_raw))
}

/// A `lattice_vectors` entry that is a 3 by 3 array of numbers must hold
/// finite ones. JSON cannot store a NaN, so a non-finite entry would
/// otherwise lose the whole lattice.
fn check_lattice_vectors_object(value: &Bound<'_, PyAny>) -> PyResult<()> {
    if let Ok(rows) = value.extract::<[[f64; 3]; 3]>() {
        crate::types::check_lattice_finite(&rows)
            .map_err(|err| cell_err_to_py(value.py(), &err))?;
    }
    Ok(())
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

fn filled_lock<T>(py: Python<'_>, value: T) -> pyo3::sync::PyOnceLock<T> {
    let lock = pyo3::sync::PyOnceLock::new();
    let _ = lock.set(py, value);
    lock
}

// `python_seq.rs` passes metadata through a `BTreeMap` while rebuilding a
// frame. serde_json::Number cannot hold an integer above u64, so carry the
// exact decimal token under a private key until the Python dict is rebuilt.
const PY_HUGE_MINOR_SENTINEL: &str = "\0readcon_python_huge_minor";

trait PyDictContainer: Sized {
    fn from_dict(py: Python<'_>, dict: Py<PyDict>) -> Self;
}

impl PyDictContainer for Py<PyDict> {
    fn from_dict(_py: Python<'_>, dict: Py<PyDict>) -> Self {
        dict
    }
}

impl PyDictContainer for pyo3::sync::PyOnceLock<Py<PyDict>> {
    fn from_dict(py: Python<'_>, dict: Py<PyDict>) -> Self {
        filled_lock(py, dict)
    }
}

fn json_map_to_py_dict<T: PyDictContainer>(
    py: Python<'_>,
    metadata: &BTreeMap<String, Value>,
) -> PyResult<T> {
    let dict = PyDict::new(py);
    for (key, value) in metadata {
        if key == PY_HUGE_MINOR_SENTINEL {
            continue;
        }
        dict.set_item(key, json_value_to_py(py, value)?)?;
    }
    if let Some(Value::String(digits)) = metadata.get(PY_HUGE_MINOR_SENTINEL) {
        use pyo3::PyTypeInfo;
        let py_int = pyo3::types::PyInt::type_object(py).call1((digits,))?;
        dict.set_item(meta::CON_SPEC_MINOR, py_int)?;
    }
    Ok(T::from_dict(py, dict.unbind()))
}

fn json_map_to_py_dict_with_minor(
    py: Python<'_>,
    metadata: &BTreeMap<String, Value>,
    minor_raw: Option<&str>,
) -> PyResult<Py<PyDict>> {
    let dict: Py<PyDict> = json_map_to_py_dict(py, metadata)?;
    if let Some(digits) = minor_raw {
        use pyo3::PyTypeInfo;
        let py_int = pyo3::types::PyInt::type_object(py).call1((digits,))?;
        dict.bind(py).set_item(meta::CON_SPEC_MINOR, py_int)?;
    }
    Ok(dict)
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

fn py_atoms_to_list(py: Python<'_>, atoms: &[PyAtomDatum]) -> PyResult<Py<PyList>> {
    let list = PyList::empty(py);
    for atom in atoms {
        list.append(Py::new(py, atom.clone())?)?;
    }
    Ok(list.unbind())
}

#[cfg(any(test, feature = "borrow-path-counts"))]
static BINDING_COPIES: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// A new NumPy-owned `[N, 3]` array (`OWNDATA`, no base) holding `rows`,
/// written in place with no intermediate buffer.
fn filled_rows<'py>(
    py: Python<'py>,
    rows: impl ExactSizeIterator<Item = [f64; 3]>,
) -> Bound<'py, PyArray2<f64>> {
    let array = PyArray2::<f64>::zeros(py, [rows.len(), 3], false);
    // SAFETY: the array was just created here and nothing else can reach it.
    let out = unsafe { array.as_slice_mut() }.expect("a new array is contiguous");
    for (slot, row) in out.chunks_exact_mut(3).zip(rows) {
        slot.copy_from_slice(&row);
    }
    array
}

/// Note one per-atom buffer the binding had to copy instead of sharing.
fn count_binding_copy() {
    #[cfg(any(test, feature = "borrow-path-counts"))]
    BINDING_COPIES.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
}

/// How many per-atom buffers the binding copied instead of sharing.
///
/// A parsed frame shares its parse buffers with the arrays it returns. The
/// count grows only when a buffer cannot be shared, such as a column stored
/// as float32. Tests read it before and after a call.
#[cfg(any(test, feature = "borrow-path-counts"))]
#[pyfunction]
fn binding_copy_count() -> u64 {
    BINDING_COPIES.load(std::sync::atomic::Ordering::Relaxed)
}

/// A NumPy array over memory that `owner` keeps alive. Its base is `owner`.
///
/// # Safety
///
/// `data` must address the elements of `dims`, aligned for `T`, and they
/// must stay valid while `owner` is alive. A writeable array must address
/// memory that no Rust reference covers: Rust reads it only through
/// [`crate::types::CoordSnapshot`]'s atomic copies.
unsafe fn owned_view<'py, T: numpy::Element, D: ndarray::Dimension>(
    owner: &Bound<'py, PyAny>,
    data: *const T,
    dims: D,
    writeable: bool,
) -> PyResult<Bound<'py, numpy::PyArray<T, D>>> {
    use numpy::PyArrayDescrMethods;
    use numpy::npyffi::{NPY_ARRAY_WRITEABLE, NpyTypes, PY_ARRAY_API, PyArrayObject, npy_intp};
    let py = owner.py();
    let shape: Vec<npy_intp> = dims.slice().iter().map(|&d| d as npy_intp).collect();
    let flags = if writeable { NPY_ARRAY_WRITEABLE } else { 0 };
    unsafe {
        let ptr = PY_ARRAY_API.PyArray_NewFromDescr(
            py,
            PY_ARRAY_API.get_type_object(py, NpyTypes::PyArray_Type),
            T::get_dtype(py).into_dtype_ptr(),
            shape.len() as std::os::raw::c_int,
            shape.as_ptr() as *mut npy_intp,
            std::ptr::null_mut(),
            data as *mut std::os::raw::c_void,
            flags,
            std::ptr::null_mut(),
        );
        if ptr.is_null() {
            return Err(PyErr::fetch(py));
        }
        // Steals the reference, also on failure.
        if PY_ARRAY_API.PyArray_SetBaseObject(
            py,
            ptr as *mut PyArrayObject,
            owner.clone().into_ptr(),
        ) < 0
        {
            pyo3::ffi::Py_DECREF(ptr);
            return Err(PyErr::fetch(py));
        }
        Ok(Bound::from_owned_ptr(py, ptr).cast_into_unchecked())
    }
}

/// One frame's coordinate allocation, released as the `Vec` it came from.
struct RawF64Buffer {
    ptr: *mut f64,
    len: usize,
    cap: usize,
}

// The doubles are written by Python through `xyz` and read by Rust only
// through atomic copies.
unsafe impl Send for RawF64Buffer {}
unsafe impl Sync for RawF64Buffer {}

impl RawF64Buffer {
    fn from_vec(values: Vec<f64>) -> Self {
        let mut values = std::mem::ManuallyDrop::new(values);
        Self {
            ptr: values.as_mut_ptr(),
            len: values.len(),
            cap: values.capacity(),
        }
    }
}

impl Drop for RawF64Buffer {
    fn drop(&mut self) {
        unsafe { drop(Vec::from_raw_parts(self.ptr, self.len, self.cap)) }
    }
}

/// The coordinate buffers of one read, one per frame.
///
/// Each buffer is the frame's parse allocation, moved here without a copy.
/// An atom stores no pointer. `ConFrame.xyz` is a writeable NumPy view of
/// one buffer whose base is this object, so every frame of a read shares
/// one owner and any view keeps the buffers alive. Readers load that
/// buffer; they do not walk the emptied positions column.
#[pyclass(module = "readcon", name = "_PositionStore", frozen)]
struct PositionStore {
    buffers: Vec<RawF64Buffer>,
}

impl PositionStore {
    /// Move each frame's coordinates here and leave its column empty.
    fn take_from(frames: &mut [ConFrame]) -> Self {
        let buffers = frames
            .iter_mut()
            .map(|frame| RawF64Buffer::from_vec(take_position_buffer(frame)))
            .collect();
        Self { buffers }
    }

    fn atoms(&self, index: usize) -> usize {
        self.buffers.get(index).map_or(0, |buffer| buffer.len / 3)
    }

    /// One atom, loaded one double at a time. `None` when the buffer is short.
    fn load_triple(&self, frame_index: usize, atom_index: usize) -> Option<[f64; 3]> {
        let buffer = self.buffers.get(frame_index)?;
        let at = atom_index.saturating_mul(3);
        if at.saturating_add(2) >= buffer.len {
            return None;
        }
        Some(unsafe {
            [
                crate::types::atomic_load_f64(buffer.ptr.add(at)),
                crate::types::atomic_load_f64(buffer.ptr.add(at + 1)),
                crate::types::atomic_load_f64(buffer.ptr.add(at + 2)),
            ]
        })
    }

    /// Append one frame's coordinates. `false` when that buffer is short.
    fn copy_rows(&self, frame_index: usize, n_atoms: usize, dest: &mut Vec<f64>) -> bool {
        let Some(buffer) = self.buffers.get(frame_index) else {
            return false;
        };
        let len = n_atoms.saturating_mul(3);
        if buffer.len < len {
            return false;
        }
        let start = dest.len();
        dest.resize(start + len, 0.0);
        if len > 0 {
            unsafe {
                crate::types::atomic_copy_f64(buffer.ptr, dest.as_mut_ptr().add(start), len);
            }
        }
        true
    }

    /// Pointer and length of one frame's buffer. Callers copy from it;
    /// they do not keep the pointer.
    fn origin(&self, index: usize) -> Option<(*const f64, usize)> {
        let buffer = self.buffers.get(index)?;
        if buffer.ptr.is_null() {
            return None;
        }
        Some((buffer.ptr.cast_const(), buffer.len))
    }

    /// One double of one atom. A short buffer is left unchanged.
    fn store_component(&self, frame_index: usize, atom_index: usize, axis: usize, value: f64) {
        let Some(buffer) = self.buffers.get(frame_index) else {
            return;
        };
        if axis > 2 {
            return;
        }
        let at = atom_index.saturating_mul(3).saturating_add(axis);
        if at >= buffer.len {
            return;
        }
        unsafe { crate::types::atomic_store_f64(buffer.ptr.add(at), value) };
    }

    fn view<'py>(slf: &Bound<'py, Self>, index: usize) -> PyResult<Bound<'py, PyArray2<f64>>> {
        let buffer = slf
            .get()
            .buffers
            .get(index)
            .ok_or_else(|| PyValueError::new_err("no coordinate buffer for this frame"))?;
        py_numpy(slf.py())?;
        unsafe {
            owned_view(
                slf.as_any(),
                buffer.ptr.cast_const(),
                ndarray::Ix2(buffer.len / 3, 3),
                true,
            )
        }
    }
}

/// The per-atom columns of one parsed frame.
///
/// Each field shares its allocation with the frame (an `ArcArray` clone, no
/// copy). The arrays that view them are read-only and have this object as
/// their base. An atom edit gives the frame's column its own allocation
/// before writing (`ConFrame::unshare_slot_columns`), so the doubles do not
/// change while a view exists.
#[pyclass(module = "readcon", name = "_FrameColumns", frozen)]
struct FrameColumns {
    velocities: Option<ndarray::ArcArray2<f64>>,
    forces: Option<ndarray::ArcArray2<f64>>,
    displacements: Option<ndarray::ArcArray2<f64>>,
    spreads: Option<ndarray::ArcArray2<f64>>,
    masses: Option<ndarray::ArcArray1<f64>>,
    energies: Option<ndarray::ArcArray1<f64>>,
    atom_ids: Option<ndarray::ArcArray1<u64>>,
}

fn shared_rows(
    storage: &crate::storage_dtype::Array2Storage,
    n: usize,
) -> Option<ndarray::ArcArray2<f64>> {
    match storage {
        crate::storage_dtype::Array2Storage::F64(array)
            if n > 0 && array.nrows() == n && array.ncols() == 3 && array.is_standard_layout() =>
        {
            Some(array.clone())
        }
        _ => None,
    }
}

fn shared_column(
    storage: &crate::storage_dtype::Array1Storage,
    n: usize,
) -> Option<ndarray::ArcArray1<f64>> {
    match storage {
        crate::storage_dtype::Array1Storage::F64(array)
            if n > 0 && array.len() == n && array.is_standard_layout() =>
        {
            Some(array.clone())
        }
        _ => None,
    }
}

impl FrameColumns {
    fn of(frame: &ConFrame) -> Self {
        let n = frame.atom_data.len();
        Self {
            velocities: shared_rows(&frame.velocities, n),
            forces: shared_rows(&frame.forces, n),
            displacements: shared_rows(&frame.displacements, n),
            spreads: shared_rows(&frame.spreads, n),
            masses: shared_column(&frame.masses, n),
            energies: shared_column(&frame.atom_energies, n),
            atom_ids: (n > 0 && frame.atom_ids.len() == n && frame.atom_ids.is_standard_layout())
                .then(|| frame.atom_ids.clone()),
        }
    }

    fn rows<'py>(
        slf: &Bound<'py, Self>,
        pick: fn(&Self) -> Option<&ndarray::ArcArray2<f64>>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let Some(array) = pick(slf.get()) else {
            return Ok(None);
        };
        py_numpy(slf.py())?;
        let view = unsafe {
            owned_view(
                slf.as_any(),
                array.as_ptr(),
                ndarray::Ix2(array.nrows(), 3),
                false,
            )?
        };
        Ok(Some(view))
    }

    fn column<'py, T: numpy::Element>(
        slf: &Bound<'py, Self>,
        pick: fn(&Self) -> Option<&ndarray::ArcArray1<T>>,
    ) -> PyResult<Option<Bound<'py, PyArray1<T>>>> {
        let Some(array) = pick(slf.get()) else {
            return Ok(None);
        };
        py_numpy(slf.py())?;
        let view = unsafe {
            owned_view(
                slf.as_any(),
                array.as_ptr(),
                ndarray::Ix1(array.len()),
                false,
            )?
        };
        Ok(Some(view))
    }
}

/// `[N, 3]` gathered from the atom slots of a frame whose column is not a
/// packed float64 block. `None` when no atom carries the section.
fn gathered_rows<'py>(
    py: Python<'py>,
    frame: &ConFrame,
    read: impl Fn(&AtomDatum) -> Option<[f64; 3]>,
) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
    if !frame.atom_data.iter().any(|atom| read(atom).is_some()) {
        return Ok(None);
    }
    count_binding_copy();
    let mut data = Vec::with_capacity(frame.atom_data.len() * 3);
    for atom in &frame.atom_data {
        data.extend_from_slice(&read(atom).unwrap_or([0.0; 3]));
    }
    let array = Array2::from_shape_vec((frame.atom_data.len(), 3), data)
        .map_err(|e| PyValueError::new_err(format!("column shape error: {e}")))?;
    Ok(Some(array.into_pyarray(py)))
}

/// `ImportError` instead of a panic in the NumPy C API when NumPy is absent.
fn py_numpy(py: Python<'_>) -> PyResult<()> {
    py.import("numpy").map(drop)
}

/// The frame's coordinates as one `Vec`.
///
/// A packed float64 column is taken as it is. Any other column is copied
/// once and counted. The column is left empty: the returned buffer is the
/// only copy, and the atom records do not alias it.
fn take_position_buffer(frame: &mut ConFrame) -> Vec<f64> {
    let n_atoms = frame.atom_data.len();
    let values = match frame.positions.take_contiguous_f64() {
        Some(values) if values.len() == n_atoms * 3 => values,
        Some(values) => {
            count_binding_copy();
            values
        }
        None => {
            count_binding_copy();
            let n = frame.positions.nrows().min(n_atoms);
            let mut values = Vec::with_capacity(n.saturating_mul(3));
            if let Some(src) = frame.positions.f64_slice() {
                let take = src.len().min(n.saturating_mul(3));
                values.extend_from_slice(&src[..take]);
            } else {
                for i in 0..n {
                    values.extend_from_slice(&frame.positions.as_f64_row(i));
                }
            }
            values
        }
    };
    frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
    values
}

/// Python-visible simulation frame.
#[pyclass(name = "ConFrame")]
pub struct PyConFrame {
    pub cell: [f64; 3],
    pub angles: [f64; 3],
    pub prebox_header: [String; 2],
    pub postbox_header: [String; 2],
    atoms: Py<PyList>,
    /// False while a parsed frame can use the direct Rust write path.
    /// Accessing the atom sequence or structurally editing it sets this
    /// true. `xyz` reads the store, the slab, or the owned array and does
    /// not build the Python atom list.
    atoms_ready: std::sync::atomic::AtomicBool,
    /// Successful fills of `atoms` from the parsed frame. Array getters
    /// leave this at zero.
    atoms_fills: std::sync::atomic::AtomicUsize,
    /// Serializes the one-time parsed atom projection on free-threaded builds.
    atoms_init: std::sync::Mutex<()>,
    pub spec_version: u32,
    /// Built from `inner`'s header on first use when the frame was parsed.
    metadata: pyo3::sync::PyOnceLock<Py<PyDict>>,
    /// Rust SoA for every frame. A parsed frame's positions column is empty:
    /// coordinates live in `xyz_owned`, `slab`, or `store`.
    inner: Option<ConFrame>,
    n_atoms: usize,
    /// One `[frames, N, 3]` array shared by every frame of a read.
    slab: Option<Py<PyArray3<f64>>>,
    /// Row of `slab`, or the original row of a detached position store.
    slab_index: usize,
    /// The parse buffers of the read this frame came from.
    store: Option<Py<PositionStore>>,
    /// Shares `inner`'s per-atom columns with arrays that view them.
    columns: pyo3::sync::PyOnceLock<Py<FrameColumns>>,
    /// Coordinates of a frame that was not part of a shared read.
    xyz_owned: Option<Py<PyArray2<f64>>>,
    /// Exact file substring from `iter_con`. `None` for a batch read,
    /// a constructed frame, a streamed frame, or a frame edited after read.
    source_text: Option<String>,
}

include!("python_seq.rs");

#[pymethods]
impl PyConFrame {
    #[new]
    #[pyo3(signature = (cell, angles, atoms, prebox_header=None, postbox_header=None, metadata=None))]
    fn new(
        py: Python<'_>,
        cell: [f64; 3],
        angles: [f64; 3],
        atoms: &Bound<'_, PyAny>,
        prebox_header: Option<[String; 2]>,
        postbox_header: Option<[String; 2]>,
        metadata: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        crate::types::check_cell_finite(&cell, "cell", &angles, "angles")
            .map_err(|err| cell_err_to_py(py, &err))?;
        let snaps = snaps_from_iterable(atoms)?;
        let prebox_header = prebox_header.unwrap_or_default();
        let postbox_header = postbox_header.unwrap_or_default();
        let (meta, minor_raw) = match metadata {
            Some(obj) => {
                let (map, minor_raw) = py_metadata_to_json_map_with_minor(obj)?;
                (map, minor_raw)
            }
            None => (BTreeMap::new(), None),
        };
        let mut inner = frame_for_storage(
            cell,
            angles,
            &prebox_header,
            &postbox_header,
            meta.clone(),
            &snaps,
        )?;
        if let Some(digits) = minor_raw.as_deref() {
            inner
                .header
                .metadata
                .set_con_spec_minor_str(digits)
                .map_err(|e| PyValueError::new_err(e.to_string()))?;
        }
        let metadata = json_map_to_py_dict_with_minor(py, &meta, minor_raw.as_deref())?;
        let atoms: Vec<PyAtomDatum> = snaps_from_frame(&inner)
            .iter()
            .map(datum_from_snap)
            .collect();
        Ok(PyConFrame {
            cell,
            angles,
            prebox_header,
            postbox_header,
            spec_version: crate::CON_SPEC_VERSION,
            atoms: py_atoms_to_list(py, &atoms)?,
            atoms_ready: std::sync::atomic::AtomicBool::new(true),
            atoms_fills: std::sync::atomic::AtomicUsize::new(0),
            atoms_init: std::sync::Mutex::new(()),
            metadata: filled_lock(py, metadata),
            inner: Some(inner),
            n_atoms: snaps.len(),
            slab: None,
            slab_index: 0,
            store: None,
            columns: pyo3::sync::PyOnceLock::new(),
            xyz_owned: None,
            source_text: None,
        })
    }

    #[getter]
    fn cell(slf: &Bound<'_, Self>) -> PyResult<[f64; 3]> {
        Ok(shared(slf)?.cell)
    }

    #[getter]
    fn angles(slf: &Bound<'_, Self>) -> PyResult<[f64; 3]> {
        Ok(shared(slf)?.angles)
    }

    #[getter]
    fn prebox_header(slf: &Bound<'_, Self>) -> PyResult<[String; 2]> {
        Ok(shared(slf)?.prebox_header.clone())
    }

    #[getter]
    fn postbox_header(slf: &Bound<'_, Self>) -> PyResult<[String; 2]> {
        Ok(shared(slf)?.postbox_header.clone())
    }

    #[getter]
    fn spec_version(slf: &Bound<'_, Self>) -> PyResult<u32> {
        Ok(shared(slf)?.spec_version)
    }

    /// Sequence of this frame's `Atom` projection. Its structural edits
    /// rebuild the frame; `frame[i]` is the live view of the store.
    #[getter]
    fn atoms(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAtomSeq>> {
        shared(slf.bind(py))?.ensure_atoms(py)?;
        Py::new(py, PyAtomSeq { frame: slf })
    }

    /// Exact substring `iter_con` read for this frame, including separator
    /// whitespace that preceded it.
    #[getter]
    fn source_text(slf: &Bound<'_, Self>) -> PyResult<Option<String>> {
        Ok(shared(slf)?.source_text.clone())
    }

    /// Alias of `source_text`.
    #[getter]
    fn raw(slf: &Bound<'_, Self>) -> PyResult<Option<String>> {
        Ok(shared(slf)?.source_text.clone())
    }

    #[getter]
    fn metadata(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let this = shared(slf)?;
        this.meta(py).map(|dict| dict.clone().unbind())
    }

    #[setter]
    fn set_metadata(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        metadata: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        let (map, minor_raw) = py_metadata_to_json_map_with_minor(metadata)?;
        let dict = json_map_to_py_dict_with_minor(py, &map, minor_raw.as_deref())?;
        this.metadata = filled_lock(py, dict);
        this.note_mutated();
        Ok(())
    }

    #[getter]
    fn has_velocities(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<bool> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            let n = frame.atom_data.len();
            return Ok(n > 0 && frame.velocities.nrows() == n
                || frame.atom_data.iter().any(AtomDatum::has_velocity));
        }
        Ok(this.py_atoms(py)?.iter().any(PyAtomDatum::has_velocity))
    }

    #[getter]
    fn has_forces(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<bool> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            let n = frame.atom_data.len();
            return Ok(n > 0 && frame.forces.nrows() == n
                || frame.atom_data.iter().any(AtomDatum::has_forces));
        }
        Ok(this.py_atoms(py)?.iter().any(PyAtomDatum::has_forces))
    }

    #[getter]
    fn has_displacements(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<bool> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            let n = frame.atom_data.len();
            return Ok(n > 0 && frame.displacements.nrows() == n
                || frame.atom_data.iter().any(AtomDatum::has_displacement));
        }
        Ok(this.py_atoms(py)?.iter().any(PyAtomDatum::has_displacement))
    }

    #[getter]
    fn has_spreads(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<bool> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            let n = frame.atom_data.len();
            return Ok(n > 0 && frame.spreads.nrows() == n
                || frame.atom_data.iter().any(AtomDatum::has_spread));
        }
        Ok(this.py_atoms(py)?.iter().any(PyAtomDatum::has_spread))
    }

    fn __repr__(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<String> {
        let this = shared(slf)?;
        let natoms = this.atom_count(py);
        Ok(format!(
            "ConFrame(cell={:?}, angles={:?}, natoms={}, has_velocities={})",
            this.cell,
            this.angles,
            natoms,
            Self::has_velocities(slf, py)?
        ))
    }

    fn __len__(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<usize> {
        Ok(shared(slf)?.atom_count(py))
    }

    /// Atoms in file order. The file cursor is `iter_con`, not this.
    fn __iter__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAtomIter>> {
        shared(slf.bind(py))?.ensure_atoms(py)?;
        Py::new(
            py,
            PyAtomIter {
                frame: slf,
                index: std::sync::atomic::AtomicIsize::new(0),
                step: 1,
            },
        )
    }

    fn __reversed__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAtomIter>> {
        let n = {
            let frame = shared(slf.bind(py))?;
            frame.ensure_atoms(py)?;
            frame.n_atoms() as isize
        };
        Py::new(
            py,
            PyAtomIter {
                frame: slf,
                index: std::sync::atomic::AtomicIsize::new(n - 1),
                step: -1,
            },
        )
    }

    fn __getitem__(slf: Py<Self>, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        sequence_getitem(&slf, py, key)
    }

    fn __setitem__(
        slf: Py<Self>,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        // Snapshot before borrow_mut so `frame[i] = frame[j]` can read a view.
        if let Ok(index) = key.extract::<isize>() {
            let mut snap = snap_from_bound(value)?;
            let cached = shared(slf.bind(py))?.cached_atom_index(py, value);
            let mut frame = exclusive(slf.bind(py))?;
            let i = frame.normalize_index(index)?;
            // `frame[i] = frame.atoms[i]` refills that object instead of
            // detaching it. Another slot, or another frame, stays a copy.
            carry_own_slot(&mut snap, cached, i);
            let mut snaps = frame.snapshot_atoms(py)?;
            snaps[i] = snap;
            return frame.replace_atoms(py, snaps);
        }
        if let Ok(slice) = key.cast::<PySlice>() {
            let incoming = snaps_for_assign(&slf, py, value)?;
            let mut frame = exclusive(slf.bind(py))?;
            return frame.set_slice_snaps(py, slice, incoming);
        }
        Err(PyTypeError::new_err(
            "ConFrame indices must be integers or slices",
        ))
    }

    fn __delitem__(slf: &Bound<'_, Self>, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        sequence_delitem(&mut this, py, key)
    }

    /// True when an atom or atom view has the same physical atom fields.
    fn __contains__(slf: &Bound<'_, Self>, item: &Bound<'_, PyAny>) -> PyResult<bool> {
        let this = shared(slf)?;
        this.contains_atom(item)
    }

    /// Equality of cell, angles, and physical atom content in stored order.
    fn __eq__(slf: &Bound<'_, Self>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        let this = shared(slf)?;
        match other.cast::<Self>() {
            Ok(other) => this.same_physical(other.py(), &*shared(other)?),
            Err(_) => Ok(false),
        }
    }

    /// Append an atom, then store in CON type-group order.
    fn append(slf: Py<Self>, py: Python<'_>, atom: &Bound<'_, PyAny>) -> PyResult<()> {
        let snap = snap_from_bound(atom)?;
        let mut frame = exclusive(slf.bind(py))?;
        let mut snaps = frame.snapshot_atoms(py)?;
        snaps.push(snap);
        frame.replace_atoms(py, snaps)
    }

    /// Insert an atom, then store in CON type-group order.
    fn insert(
        slf: Py<Self>,
        py: Python<'_>,
        index: isize,
        atom: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let snap = snap_from_bound(atom)?;
        let mut frame = exclusive(slf.bind(py))?;
        let mut snaps = frame.snapshot_atoms(py)?;
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

    fn extend(slf: Py<Self>, py: Python<'_>, atoms: &Bound<'_, PyAny>) -> PyResult<()> {
        let extra = snaps_from_iterable(atoms)?;
        let mut frame = exclusive(slf.bind(py))?;
        let mut snaps = frame.snapshot_atoms(py)?;
        snaps.extend(extra);
        frame.replace_atoms(py, snaps)
    }

    // --- NumPy array views ---
    //
    // Until a structural sequence edit, a frame from the parser answers
    // `vel`, `frc`, `mass_column` and the `*_array()` methods other than
    // `coords_array()` with read-only views of its parsed columns. Their
    // base owns those columns, so nothing is copied. Structurally edited
    // frames gather owned arrays from their current atom store.
    // A consumer that speaks DLPack 1.0 (`np.from_dlpack`, recent torch)
    // imports a read-only view without a copy; DLPack 0.x cannot mark an
    // array read-only, and NumPy refuses that export.

    /// Coordinates as a numpy `[N, 3] float64` view.
    ///
    /// A frame from `read_con` views its own parse buffer. Every frame of
    /// one read shares the same base object, which owns those buffers, so
    /// a view stays valid after the list and the frame are gone. A later
    /// read of `xyz` views the same memory. The view is writeable. Until
    /// `.atoms` is built, a store into it is what a later write sees.
    /// `iter_con`, `read_first_frame`, `read_nth_frame`, and the chemfiles
    /// readers return the array the parsed column was moved into.
    /// `coords_array()` is a fresh copy of that array, or of `.atoms` once
    /// that list has been built.
    #[getter]
    fn xyz<'py>(slf: &Bound<'_, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyArray2<f64>>> {
        let this = shared(slf)?;
        if let Some(store) = &this.store {
            return PositionStore::view(store.bind(py), this.slab_index);
        }
        if let Some(slab) = &this.slab {
            let item = slab.bind(py).get_item(this.slab_index)?;
            return Ok(item.cast::<PyArray2<f64>>()?.clone());
        }
        if let Some(owned) = &this.xyz_owned {
            return Ok(owned.bind(py).clone());
        }
        Self::coords_array(slf, py)
    }

    /// Per-atom masses as a numpy `[N] float64` array.
    ///
    /// Until `.atoms` exists this returns a read-only view of the parsed
    /// column without copying or building the Python atom list. Once that
    /// list exists the returned array follows it, including an edit, a
    /// pop, an append, or an insert.
    #[getter]
    fn mass_column<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray1<f64>>>> {
        let this = shared(slf)?;
        if this.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            let atoms = this.py_atoms(py)?;
            if atoms.is_empty() {
                return Ok(None);
            }
            let data: Vec<f64> = atoms.iter().map(|atom| atom.mass.unwrap_or(0.0)).collect();
            return Ok(Some(Array1::from_vec(data).into_pyarray(py)));
        }
        let Some(frame) = this.inner.as_ref() else {
            return Ok(None);
        };
        let owner = this.column_owner(py, frame)?;
        if let Some(view) = FrameColumns::column(&owner, |c| c.masses.as_ref())? {
            return Ok(Some(view));
        }
        let Some(src) = frame.masses.f64_slice() else {
            return Ok(None);
        };
        if src.is_empty() {
            return Ok(None);
        }
        count_binding_copy();
        Ok(Some(Array1::from_vec(src.to_vec()).into_pyarray(py)))
    }

    /// Velocities. Same array as `velocities_array`.
    #[getter]
    fn vel<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        Self::velocities_array(slf, py)
    }

    /// Forces. Same array as `forces_array`.
    #[getter]
    fn frc<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        Self::forces_array(slf, py)
    }

    /// Returns the per-atom xyz positions as a contiguous numpy
    /// `[N, 3] float64` array, in the type-grouped order used by the
    /// underlying frame.
    ///
    /// This accessor specifically allocates an owned snapshot, so mutating
    /// a previous return value cannot affect a later call. AtomView edits
    /// show up on the next call.
    fn coords_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyArray2<f64>>> {
        let this = shared(slf)?;
        // The atom list has not been built. The store, `xyz`, or the slab
        // holds the coordinates; the positions column was moved there.
        // A walk of the empty column would miss a later store. This path
        // does not construct one Python object per atom.
        if !this.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            // `xyz` and the read slab are the live coordinates. The positions
            // column was moved into that array, so a store is invisible to
            // a walk of the column. This return is a fresh array: one relaxed
            // load per double, and no slice over the NumPy buffer.
            if let Some(owned) = &this.xyz_owned {
                if let Some(array) = coords_from_numpy(py, owned.bind(py), 0, this.n_atoms)? {
                    return Ok(array);
                }
            }
            if let Some(slab) = &this.slab {
                let at = this
                    .slab_index
                    .saturating_mul(this.n_atoms)
                    .saturating_mul(3);
                if let Some(array) = coords_from_numpy(py, slab.bind(py), at, this.n_atoms)? {
                    return Ok(array);
                }
            }
            if let Some(store) = &this.store {
                let n = this.n_atoms;
                let mut data = Vec::new();
                if store.get().copy_rows(this.slab_index, n, &mut data) && data.len() == n * 3 {
                    return Ok(filled_rows(
                        py,
                        data.chunks_exact(3).map(|row| [row[0], row[1], row[2]]),
                    ));
                }
            }
            if let Some(frame) = this.inner.as_ref() {
                let n = frame.atom_data.len();
                if n > 0 && frame.positions.nrows() == n {
                    // NumPy allocates this buffer (`OWNDATA`, no base). The
                    // frame can be dropped and the array stays valid.
                    return Ok(filled_rows(
                        py,
                        (0..n).map(|index| frame.load_coords(index)),
                    ));
                }
            }
        }
        // A constructed or structurally edited frame snapshots its current
        // Rust atom store.
        let atoms = this.py_atoms(py)?;
        Ok(filled_rows(
            py,
            atoms.iter().map(|atom| [atom.x, atom.y, atom.z]),
        ))
    }

    /// Returns the per-atom velocity vectors as a contiguous numpy
    /// `[N, 3] float64` array. Returns `None` if the frame has no
    /// velocity data.
    ///
    /// A parsed frame reads its velocity column until `.atoms` exists.
    /// An f64 column is then a read-only view. A store raises
    /// `ValueError`. Once the list exists, the array is built from it,
    /// so an edit or an appended atom shows up here and in `write_con`.
    fn velocities_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let this = shared(slf)?;
        if let Some(owner) = this.parsed_columns(py)? {
            if let Some(view) = FrameColumns::rows(&owner, |c| c.velocities.as_ref())? {
                return Ok(Some(view));
            }
            let frame = this.inner.as_ref().expect("parsed frame");
            let n = frame.atom_data.len();
            if frame.velocities.nrows() == n && n > 0 && frame.velocities.ncols() == 3 {
                count_binding_copy();
                return Ok(Some(copy_f64_rows(py, &frame.velocities, "velocities")?));
            }
            return gathered_rows(py, frame, AtomDatum::velocity);
        }
        let atoms = this.py_atoms(py)?;
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
    ///
    /// A parsed frame reads its force column until `.atoms` exists.
    /// An f64 column is then a read-only view. A store raises
    /// `ValueError`. Once the list exists, the array is built from it,
    /// so an edit or an appended atom shows up here and in `write_con`.
    fn forces_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let this = shared(slf)?;
        if let Some(owner) = this.parsed_columns(py)? {
            if let Some(view) = FrameColumns::rows(&owner, |c| c.forces.as_ref())? {
                return Ok(Some(view));
            }
            let frame = this.inner.as_ref().expect("parsed frame");
            let n = frame.atom_data.len();
            if frame.forces.nrows() == n && n > 0 && frame.forces.ncols() == 3 {
                count_binding_copy();
                return Ok(Some(copy_f64_rows(py, &frame.forces, "forces")?));
            }
            return gathered_rows(py, frame, AtomDatum::force);
        }
        let atoms = this.py_atoms(py)?;
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
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let this = shared(slf)?;
        if let Some(owner) = this.parsed_columns(py)? {
            if let Some(view) = FrameColumns::rows(&owner, |c| c.displacements.as_ref())? {
                return Ok(Some(view));
            }
            let frame = this.inner.as_ref().expect("parsed frame");
            return gathered_rows(py, frame, AtomDatum::displacement);
        }
        let atoms = this.py_atoms(py)?;
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
    fn disp<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        Self::displacements_array(slf, py)
    }

    /// Returns the per-atom root-mean-square spreads (Angstrom) about the
    /// written coordinates as a contiguous numpy `[N, 3] float64` array,
    /// or `None` when the frame declares no `"spreads"` section.
    fn spreads_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        let this = shared(slf)?;
        if let Some(owner) = this.parsed_columns(py)? {
            if let Some(view) = FrameColumns::rows(&owner, |c| c.spreads.as_ref())? {
                return Ok(Some(view));
            }
            let frame = this.inner.as_ref().expect("parsed frame");
            return gathered_rows(py, frame, AtomDatum::spread);
        }
        let atoms = this.py_atoms(py)?;
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
    fn spread<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray2<f64>>>> {
        Self::spreads_array(slf, py)
    }

    /// Returns the per-atom energy contributions as a contiguous
    /// numpy `[N] float64` array. Returns `None` if the frame has no
    /// per-atom energies (only a frame-total energy in metadata).
    fn energies_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyArray1<f64>>>> {
        let this = shared(slf)?;
        if let Some(owner) = this.parsed_columns(py)? {
            if let Some(view) = FrameColumns::column(&owner, |c| c.energies.as_ref())? {
                return Ok(Some(view));
            }
            let frame = this.inner.as_ref().expect("parsed frame");
            if !frame.atom_data.iter().any(|atom| atom.energy().is_some()) {
                return Ok(None);
            }
            count_binding_copy();
            let data: Vec<f64> = frame
                .atom_data
                .iter()
                .map(|atom| atom.energy().unwrap_or(0.0))
                .collect();
            return Ok(Some(data.into_pyarray(py)));
        }
        let atoms = this.py_atoms(py)?;
        if !atoms.iter().any(PyAtomDatum::has_energy) {
            return Ok(None);
        }
        let data: Vec<f64> = atoms
            .iter()
            .map(|atom| atom.energy.unwrap_or(0.0))
            .collect();
        Ok(Some(data.into_pyarray(py)))
    }

    /// The chemical symbol of every atom as a :class:`FrameSymbols`, one
    /// interned string per run of equal symbols. A parsed frame answers
    /// from its per-type counts without building `atoms`; once `atoms`
    /// exists it is read, so an edited `Atom.symbol` shows up.
    #[getter]
    fn symbols(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<FrameSymbols> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            return Ok(FrameSymbols::of_parsed(py, frame));
        }
        let atoms = this.atoms.bind(py);
        let names = {
            let mut names: Vec<(String, usize)> = Vec::new();
            for atom in read_atom_list(atoms)? {
                match names.last_mut() {
                    Some((last, count)) if *last == atom.symbol => *count += 1,
                    _ => names.push((atom.symbol, 1usize)),
                }
            }
            names
        };
        Ok(FrameSymbols::from_runs(
            py,
            names.iter().map(|(name, count)| (name.as_str(), *count)),
        ))
    }

    /// Returns the per-atom ids as a numpy `[N] uint64` array.
    ///
    /// A parsed frame views its id column until `.atoms` exists. The
    /// view is read-only: a store raises `ValueError`, and
    /// `setflags(write=True)` fails. Once the list exists, the array
    /// is built from it, so an edit or an appended atom shows up here
    /// and in `write_con`.
    fn atom_ids_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyArray1<u64>>> {
        let this = shared(slf)?;
        if let Some(owner) = this.parsed_columns(py)? {
            if let Some(view) = FrameColumns::column(&owner, |c| c.atom_ids.as_ref())? {
                return Ok(view);
            }
            let frame = this.inner.as_ref().expect("parsed frame");
            if !frame.atom_data.is_empty() {
                count_binding_copy();
            }
            let data: Vec<u64> = frame.atom_data.iter().map(|atom| atom.atom_id).collect();
            return Ok(data.into_pyarray(py));
        }
        let atoms = this.py_atoms(py)?;
        let data: Vec<u64> = atoms.iter().map(|a| a.atom_id).collect();
        Ok(data.into_pyarray(py))
    }

    /// True once `.atoms` has been built. Array getters leave this false.
    #[getter]
    fn atoms_materialized(slf: &Bound<'_, Self>) -> PyResult<bool> {
        Ok(shared(slf)?
            .atoms_ready
            .load(std::sync::atomic::Ordering::Acquire))
    }

    /// Times the parsed frame was copied into Python atoms.
    #[getter]
    fn atoms_fill_count(slf: &Bound<'_, Self>) -> PyResult<usize> {
        Ok(shared(slf)?
            .atoms_fills
            .load(std::sync::atomic::Ordering::Acquire))
    }

    /// Atomic numbers in file order, numpy `[N] uint64`.
    ///
    /// Z is not stored. Until `.atoms` exists the array is filled from
    /// the type table, one lookup per species. Once the list exists it
    /// follows that list. Unknown symbols are 0.
    fn atomic_numbers<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyArray1<u64>>> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            return Ok(atomic_numbers_from_runs(&symbol_runs(frame)).into_pyarray(py));
        }
        let data: Vec<u64> = this
            .py_atoms(py)?
            .iter()
            .map(|atom| crate::helpers::symbol_to_atomic_number(&atom.symbol))
            .collect();
        Ok(data.into_pyarray(py))
    }

    /// Per-axis fixed flags as a numpy `[N, 3] uint8` array.
    ///
    /// Column 0 is x, 1 is y, 2 is z. A held axis is 1. Until `.atoms`
    /// exists the flags are copied from each parsed record. Once the
    /// list exists the array follows that list.
    fn fixed_mask_array<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyArray2<u8>>> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            let data = fixed_mask_bytes(frame.atom_data.iter().map(|atom| atom.fixed()));
            return fixed_mask_array_from(py, data, frame.atom_data.len());
        }
        let atoms = this.py_atoms(py)?;
        let data = fixed_mask_bytes(atoms.iter().map(|atom| atom.fixed));
        fixed_mask_array_from(py, data, atoms.len())
    }

    // --- atom_id index ---

    /// Returns the position of an atom in the frame's atom list whose
    /// `atom_id` equals the given id, or None if no such atom exists.
    ///
    /// O(N) per call. For repeated lookups, build a dict once with
    /// `build_atom_id_index()` and look up there.
    fn atom_index_by_id(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        atom_id: u64,
    ) -> PyResult<Option<usize>> {
        let this = shared(slf)?;
        Ok(this.py_atoms(py)?.iter().position(|a| a.atom_id == atom_id))
    }

    /// Builds a fresh `dict[int, int]` mapping `atom_id -> position`
    /// for every atom in the frame.
    fn build_atom_id_index<'py>(
        slf: &Bound<'_, Self>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let this = shared(slf)?;
        let dict = PyDict::new(py);
        for (i, atom) in this.py_atoms(py)?.iter().enumerate() {
            dict.set_item(atom.atom_id, i)?;
        }
        Ok(dict)
    }

    // --- Typed metadata accessors ---

    /// Per-frame total energy (from JSON metadata), or None.
    #[getter]
    fn energy(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        shared(slf)?.metadata_get_f64(py, meta::ENERGY)
    }

    /// Campaign screening projection (`readcon_core::index_proj`), same fields as
    /// `readcon-db` secondary indexes. Prefer over ad-hoc metadata parsing for corpus work.
    fn index_projection(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let this = shared(slf)?;
        use crate::index_proj::FrameIndexProjection;
        let frame = this.to_con_frame(py)?;
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
    ///
    /// Until `.atoms` exists the parser's atoms are counted in place.
    /// Once the list exists the formula follows it, including an edit,
    /// a pop, an append, or an insert.
    #[getter]
    fn composition_formula(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<String> {
        let this = shared(slf)?;
        if let Some(frame) = this.parsed_frame() {
            return Ok(crate::index_proj::frame_composition_formula(frame));
        }
        let frame = this.to_con_frame(py)?;
        Ok(crate::index_proj::frame_composition_formula(&frame))
    }

    /// Sections presence mask: bit0 forces, bit1 velocities, bit2 energies.
    #[getter]
    fn sections_mask(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<u8> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        Ok(crate::index_proj::sections_present_mask(&frame))
    }

    /// Campaign finite energy (None if missing or non-finite); aligns with readcon-db energy index.
    #[getter]
    fn index_energy(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        Ok(crate::index_proj::finite_energy(&frame))
    }

    /// Total mass Σ m_i n_i when finite.
    #[getter]
    fn total_mass(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        Ok(crate::index_proj::frame_total_mass(&frame))
    }

    /// Cell volume when finite.
    #[getter]
    fn cell_volume(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        Ok(crate::index_proj::frame_cell_volume(&frame))
    }

    /// Max force magnitude when forces present.
    #[getter]
    fn fmax(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        Ok(crate::index_proj::frame_fmax(&frame))
    }

    /// Atom count for campaign `idx_natoms`.
    #[getter]
    fn index_natoms(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<u32> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        Ok(frame.atom_data.len() as u32)
    }

    /// Full projection as JSON string (same payload as `rkr_frame_index_projection_json`).
    fn index_projection_json(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<String> {
        let this = shared(slf)?;
        use crate::index_proj::FrameIndexProjection;
        let frame = this.to_con_frame(py)?;
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
    fn potential_type(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<String>> {
        let this = shared(slf)?;
        let dict = this.meta(py)?;
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
    fn frame_index(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<u64>> {
        let this = shared(slf)?;
        this.metadata_get_u64(py, meta::FRAME_INDEX)
    }

    /// Simulation time of this frame, or None.
    #[getter]
    fn time(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        let this = shared(slf)?;
        this.metadata_get_f64(py, meta::TIME)
    }

    /// Integration timestep of this frame, or None.
    #[getter]
    fn timestep(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<f64>> {
        let this = shared(slf)?;
        this.metadata_get_f64(py, meta::TIMESTEP)
    }

    /// Optional frame topology from ``metadata['bonds']`` as a list of
    /// ``(i, j)`` or ``(i, j, order)`` tuples (0-based ``atom_data`` indices).
    /// Empty list when absent. Enables chemfiles bond/angle selection when
    /// the library is built with the ``chemfiles`` feature.
    #[getter]
    fn bonds(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let this = shared(slf)?;
        let dict = this.meta(py)?;
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
    fn has_bonds(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<bool> {
        Ok(!Self::bonds(slf, py)?.is_empty())
    }

    /// NEB bead index for this frame, or None.
    #[getter]
    fn neb_bead(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<u64>> {
        let this = shared(slf)?;
        this.metadata_get_u64(py, meta::NEB_BEAD)
    }

    /// NEB band index for this frame, or None.
    #[getter]
    fn neb_band(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Option<u64>> {
        let this = shared(slf)?;
        this.metadata_get_u64(py, meta::NEB_BAND)
    }

    /// Replace metadata from a raw JSON object string.
    ///
    /// The schema is validated up front: malformed entries (e.g. a
    /// non-bool `pbc`, a 3x4 `lattice_vectors`) raise ValueError rather
    /// than silently dropping the value.
    fn set_metadata_json(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        metadata_json: &str,
    ) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        let (obj, minor_raw) = crate::parser::parse_metadata_json_object_with_raw(metadata_json)
            .map_err(|e| PyValueError::new_err(format!("invalid metadata JSON: {e}")))?;
        crate::parser::validate_builder_metadata_schema(&obj)
            .map_err(|e| PyValueError::new_err(format!("invalid metadata: {e}")))?;
        let mut metadata = BTreeMap::new();
        for (key, value) in obj {
            if key == meta::CON_SPEC_VERSION || key == meta::SECTIONS {
                continue;
            }
            metadata.insert(key, value);
        }
        let dict = json_map_to_py_dict_with_minor(py, &metadata, minor_raw.as_deref())?;
        this.metadata = filled_lock(py, dict);
        this.note_mutated();
        Ok(())
    }

    /// Set a numeric metadata key.
    fn set_scalar_metadata(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        key: &str,
        value: f64,
    ) -> PyResult<()> {
        exclusive(slf)?.store_scalar_metadata(py, key, value)
    }

    /// Set a string metadata key.
    fn set_string_metadata(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        key: &str,
        value: &str,
    ) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.meta(py)?.set_item(key, value)?;
        this.note_mutated();
        Ok(())
    }

    /// Set the per-frame total energy metadata.
    fn set_energy(slf: &Bound<'_, Self>, py: Python<'_>, energy: f64) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.store_scalar_metadata(py, meta::ENERGY, energy)
    }

    /// Set the zero-based frame index metadata.
    fn set_frame_index(slf: &Bound<'_, Self>, py: Python<'_>, idx: u64) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.meta(py)?.set_item(meta::FRAME_INDEX, idx)?;
        this.note_mutated();
        Ok(())
    }

    /// Set the simulation time metadata.
    fn set_time(slf: &Bound<'_, Self>, py: Python<'_>, time: f64) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.store_scalar_metadata(py, meta::TIME, time)
    }

    /// Set the integration timestep metadata.
    fn set_timestep(slf: &Bound<'_, Self>, py: Python<'_>, dt: f64) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.store_scalar_metadata(py, meta::TIMESTEP, dt)
    }

    /// Set the NEB bead index metadata.
    fn set_neb_bead(slf: &Bound<'_, Self>, py: Python<'_>, bead: u64) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.meta(py)?.set_item(meta::NEB_BEAD, bead)?;
        this.note_mutated();
        Ok(())
    }

    /// Set the NEB band index metadata.
    fn set_neb_band(slf: &Bound<'_, Self>, py: Python<'_>, band: u64) -> PyResult<()> {
        let mut this = exclusive(slf)?;
        this.meta(py)?.set_item(meta::NEB_BAND, band)?;
        this.note_mutated();
        Ok(())
    }

    /// Convert this frame to an ASE Atoms object (requires ase package).
    fn to_ase(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let this = shared(slf)?;
        ase_from_pyconframe(py, &this)
    }

    /// Create a ConFrame from an ASE Atoms object.
    #[staticmethod]
    fn from_ase(py: Python<'_>, ase_atoms: &Bound<'_, PyAny>) -> PyResult<Self> {
        pyconframe_from_ase(py, ase_atoms)
    }

    /// Chemfiles selection on this frame (see module :func:`select_on_frame`).
    ///
    /// Requires a chemfiles-linked build (``readcon-chemfiles`` / ``--features chemfiles``).
    fn select(slf: &Bound<'_, Self>, py: Python<'_>, selection: &str) -> PyResult<Py<PyAny>> {
        select_on_frame(py, slf, selection)
    }

    /// Atom-context chemfiles selection → sorted unique ``atom_data`` indices.
    fn select_atoms(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        selection: &str,
    ) -> PyResult<Vec<usize>> {
        select_atom_indices(py, slf, selection)
    }

    /// Write this frame to a CON path (single-frame convenience).
    #[pyo3(signature = (path, *, canonical=false))]
    fn write_con(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        path: &str,
        canonical: bool,
    ) -> PyResult<()> {
        let this = shared(slf)?;
        let frame = this.to_con_frame(py)?;
        let path_owned = path.to_owned();
        py.detach(move || {
            let mut writer = ConFrameWriter::from_path(Path::new(&path_owned))
                .map_err(|e| e.to_string())?
                .canonical(canonical);
            write_stamped_frame(&mut writer, &frame).map_err(|e| e.to_string())?;
            writer.flush().map_err(|e| e.to_string())
        })
        .map_err(PyIOError::new_err)
    }
}

impl PyConFrame {
    fn store_scalar_metadata(&mut self, py: Python<'_>, key: &str, value: f64) -> PyResult<()> {
        let number = Number::from_f64(value)
            .ok_or_else(|| PyValueError::new_err("metadata floats must be finite"))?;
        self.meta(py)?
            .set_item(key, json_value_to_py(py, &Value::Number(number))?)?;
        self.note_mutated();
        Ok(())
    }

    /// `inner`'s coordinate slots address a NumPy array that `xyz`
    /// returns to Python, writable.
    fn coords_shared(&self) -> bool {
        self.slab.is_some() || self.xyz_owned.is_some() || self.store.is_some()
    }

    /// The parsed frame while it remains eligible for direct column access.
    fn parsed_frame(&self) -> Option<&ConFrame> {
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            return None;
        }
        self.inner.as_ref()
    }

    fn column_owner<'py>(
        &self,
        py: Python<'py>,
        frame: &ConFrame,
    ) -> PyResult<Bound<'py, FrameColumns>> {
        let owner = self
            .columns
            .get_or_try_init(py, || Py::new(py, FrameColumns::of(frame)))?;
        Ok(owner.bind(py).clone())
    }

    /// A zero-copy column owner while direct parsed-column access is valid.
    fn parsed_columns<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, FrameColumns>>> {
        match self.parsed_frame() {
            Some(frame) => self.column_owner(py, frame).map(Some),
            None => Ok(None),
        }
    }

    fn atom_count(&self, py: Python<'_>) -> usize {
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            // pyo3 reads `ob_size` with a plain load. Another thread's
            // append stores it inside the list's critical section.
            let list = self.atoms.bind(py);
            return pyo3::sync::critical_section::with_critical_section(list.as_any(), || {
                list.len()
            });
        }
        if self.n_atoms > 0 {
            return self.n_atoms;
        }
        self.inner
            .as_ref()
            .map(|frame| frame.atom_data.len())
            .unwrap_or(0)
    }

    fn from_owned(py: Python<'_>, mut frame: ConFrame) -> PyResult<Self> {
        let n_atoms = frame.positions.nrows();
        // The coordinate view is a NumPy array. Building it calls the
        // NumPy C API, which panics when the numpy module is absent.
        // A read that only writes the frames back keeps the parser's
        // coordinates on the frame instead.
        let xyz_owned = if py.import("numpy").is_ok() {
            // Move a contiguous f64 column into the array. A float32 column
            // is promoted, which is the one copy that conversion requires.
            // Either way the frame does not keep a second buffer.
            let data = if let Some(buf) = frame.positions.take_contiguous_f64() {
                buf
            } else {
                count_binding_copy();
                let n = frame.positions.nrows().min(n_atoms);
                let mut data = Vec::with_capacity(n.saturating_mul(3));
                if let Some(src) = frame.positions.f64_slice() {
                    let take = src.len().min(n.saturating_mul(3));
                    data.extend_from_slice(&src[..take]);
                } else {
                    for i in 0..n {
                        data.extend_from_slice(&frame.positions.as_f64_row(i));
                    }
                }
                frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
                data
            };
            let xyz = Array2::from_shape_vec((n_atoms, 3), data)
                .map_err(|e| PyValueError::new_err(format!("xyz shape error: {e}")))?
                .into_pyarray(py);
            if n_atoms > 0 && !xyz.is_c_contiguous() {
                return Err(PyValueError::new_err(
                    "frame coordinates are not contiguous",
                ));
            }
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
        Ok(PyConFrame {
            cell,
            angles,
            prebox_header,
            postbox_header,
            atoms: PyList::empty(py).unbind(),
            atoms_ready: std::sync::atomic::AtomicBool::new(false),
            atoms_fills: std::sync::atomic::AtomicUsize::new(0),
            atoms_init: std::sync::Mutex::new(()),
            spec_version,
            metadata: pyo3::sync::PyOnceLock::new(),
            inner: Some(frame),
            n_atoms,
            slab: None,
            slab_index: 0,
            store: None,
            columns: pyo3::sync::PyOnceLock::new(),
            xyz_owned,
            source_text: None,
        })
    }

    fn from_owned_with_source(
        py: Python<'_>,
        frame: ConFrame,
        source_text: Option<String>,
    ) -> PyResult<Self> {
        let mut out = Self::from_owned(py, frame)?;
        out.source_text = source_text;
        Ok(out)
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
        // Coordinates live in the slab. The parsed column is a second
        // buffer, so drop it. Atoms store no pointer; readers use the slab.
        if n_atoms > 0 && !slab.bind(py).is_c_contiguous() {
            return Err(PyValueError::new_err("coordinate slab is not contiguous"));
        }
        frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);
        Ok(PyConFrame {
            cell,
            angles,
            prebox_header,
            postbox_header,
            atoms: PyList::empty(py).unbind(),
            atoms_ready: std::sync::atomic::AtomicBool::new(false),
            atoms_fills: std::sync::atomic::AtomicUsize::new(0),
            atoms_init: std::sync::Mutex::new(()),
            spec_version,
            metadata: pyo3::sync::PyOnceLock::new(),
            inner: Some(frame),
            n_atoms,
            slab: Some(slab),
            slab_index: index,
            store: None,
            columns: pyo3::sync::PyOnceLock::new(),
            xyz_owned: None,
            source_text: None,
        })
    }

    /// A frame whose coordinates are buffer `index` of `store`. The atom
    /// slots already read that buffer.
    fn from_store(
        py: Python<'_>,
        frame: ConFrame,
        store: Py<PositionStore>,
        index: usize,
    ) -> PyResult<Self> {
        let n_atoms = store.get().atoms(index);
        let prebox_header = [
            frame.header.prebox_header.user.clone(),
            frame.header.prebox_header.metadata_line().to_string(),
        ];
        Ok(PyConFrame {
            cell: frame.header.boxl,
            angles: frame.header.angles,
            prebox_header,
            postbox_header: frame.header.postbox_header.clone(),
            atoms: PyList::empty(py).unbind(),
            atoms_ready: std::sync::atomic::AtomicBool::new(false),
            atoms_fills: std::sync::atomic::AtomicUsize::new(0),
            atoms_init: std::sync::Mutex::new(()),
            spec_version: frame.header.spec_version,
            metadata: pyo3::sync::PyOnceLock::new(),
            inner: Some(frame),
            n_atoms,
            slab: None,
            slab_index: index,
            store: Some(store),
            columns: pyo3::sync::PyOnceLock::new(),
            xyz_owned: None,
            source_text: None,
        })
    }

    fn coord_at(&self, py: Python<'_>, frame: &ConFrame, index: usize) -> [f64; 3] {
        if let Some(owned) = &self.xyz_owned
            && let Some(xyz) = load_numpy_triple(owned.bind(py), index * 3)
        {
            return xyz;
        }
        if let Some(slab) = &self.slab
            && let Some(xyz) =
                load_numpy_triple(slab.bind(py), (self.slab_index * self.n_atoms + index) * 3)
        {
            return xyz;
        }
        if let Some(store) = &self.store
            && let Some(xyz) = store.get().load_triple(self.slab_index, index)
        {
            return xyz;
        }
        if frame.positions.nrows() > index {
            return frame.xyz_at(index);
        }
        [0.0; 3]
    }

    fn ensure_atoms(&self, py: Python<'_>) -> PyResult<()> {
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            return Ok(());
        }
        // Detach while waiting. Holding this lock across `clear` and
        // `append` must not stop the world on a free-threaded build.
        let _initializing = lock_attached(py, &self.atoms_init);
        if self.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
            return Ok(());
        }
        let Some(source) = self.inner.as_ref() else {
            self.atoms_ready
                .store(true, std::sync::atomic::Ordering::Release);
            return Ok(());
        };
        // Coordinates come from the NumPy array through `coord_at`. The
        // positions column was moved into that array, so copying it here
        // would read an empty matrix.
        let frame = source;
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
        list.call_method0("clear")?;
        for (i, atom) in frame.atom_data.iter().enumerate() {
            let mass = per_atom_mass.get(i).copied().unwrap_or(0.0);
            let xyz = self.coord_at(py, frame, i);
            list.append(PyAtomDatum::from_atom_with_mass(atom, xyz, mass))?;
        }
        self.atoms_fills
            .fetch_add(1, std::sync::atomic::Ordering::Release);
        self.atoms_ready
            .store(true, std::sync::atomic::Ordering::Release);
        Ok(())
    }

    fn py_atoms(&self, py: Python<'_>) -> PyResult<Vec<PyAtomDatum>> {
        self.ensure_atoms(py)?;
        read_atom_list(self.atoms.bind(py))
    }
}

/// Copy one generation of the atom list.
///
/// `PyList::iter` and `get_item` lock the list again. On a free-threaded
/// build that suspends the outer section, so one walk can see two writes.
/// The unchecked load is valid only while this section is not re-entered.
/// Identities are copied here. Payloads are cloned afterwards with the
/// waiting shared borrow: `borrow` panics when a writer holds the atom,
/// and waiting inside the section would suspend it.
fn read_atom_list(list: &Bound<'_, PyList>) -> PyResult<Vec<PyAtomDatum>> {
    let py = list.py();
    let held = pyo3::sync::critical_section::with_critical_section(list.as_any(), || {
        let n = list.len();
        let mut held = Vec::with_capacity(n);
        for index in 0..n {
            // SAFETY: `index < len` under this critical section, and the body
            // does not lock `list` again. `Py_TYPE` does not start a section.
            let item = unsafe { list.get_item_unchecked(index) };
            if !item.is_exact_instance_of::<PyAtomDatum>() {
                return Err(PyTypeError::new_err(
                    "ConFrame atom cache must hold readcon.Atom objects",
                ));
            }
            let atom = unsafe { item.cast_unchecked::<PyAtomDatum>() };
            held.push(atom.clone().unbind());
        }
        Ok(held)
    })?;
    let mut atoms = Vec::with_capacity(held.len());
    for atom in held {
        atoms.push(shared(atom.bind(py))?.clone());
    }
    Ok(atoms)
}

impl PyConFrame {
    fn meta<'py>(&self, py: Python<'py>) -> PyResult<&Bound<'py, PyDict>> {
        let dict = self.metadata.get_or_try_init(py, || match &self.inner {
            Some(frame) => json_map_to_py_dict_with_minor(
                py,
                &frame.header.metadata.to_map(),
                frame.header.metadata.huge_minor_raw(),
            ),
            None => Ok(PyDict::new(py).unbind()),
        })?;
        Ok(dict.bind(py))
    }

    fn metadata_map(&self, py: Python<'_>) -> PyResult<BTreeMap<String, Value>> {
        let (mut metadata, minor_raw) =
            py_metadata_to_json_map_with_minor(self.meta(py)?.as_any())?;
        if let Some(digits) = minor_raw {
            metadata.insert(PY_HUGE_MINOR_SENTINEL.to_string(), Value::String(digits));
        }
        Ok(metadata)
    }

    /// Extract an `Option<f64>` metadata value directly from the underlying
    /// PyDict, without round-tripping through serde_json::Value.
    fn metadata_get_f64(&self, py: Python<'_>, key: &str) -> PyResult<Option<f64>> {
        let dict = self.meta(py)?;
        match dict.get_item(key)? {
            Some(value) if !value.is_none() => Ok(Some(value.extract::<f64>()?)),
            _ => Ok(None),
        }
    }

    /// Extract an `Option<u64>` metadata value directly from the underlying
    /// PyDict, without round-tripping through serde_json::Value.
    fn metadata_get_u64(&self, py: Python<'_>, key: &str) -> PyResult<Option<u64>> {
        let dict = self.meta(py)?;
        match dict.get_item(key)? {
            Some(value) if !value.is_none() => Ok(Some(value.extract::<u64>()?)),
            _ => Ok(None),
        }
    }

    fn to_con_frame(&self, py: Python<'_>) -> PyResult<ConFrame> {
        let (mut meta, minor_raw) = py_metadata_to_json_map_with_minor(self.meta(py)?.as_any())?;
        // The store or slab is live only until this list is built.
        // `py_atoms` builds it, so the flag has to be read first. After
        // that, an edit, pop, or append is the coordinate source. Reading
        // the buffer by the new index would pair the wrong row, or panic
        // on an appended atom.
        let atoms_are_truth = self.atoms_ready.load(std::sync::atomic::Ordering::Acquire);
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
        if let Some(digits) = minor_raw {
            builder
                .set_con_spec_minor_str(&digits)
                .map_err(|e| PyValueError::new_err(e.to_string()))?;
        }

        for (index, py_atom) in atoms.iter().enumerate() {
            let mass = py_atom.mass.unwrap_or(0.0);
            let (x, y, z) = if atoms_are_truth || !self.coords_shared() {
                (py_atom.x, py_atom.y, py_atom.z)
            } else if let Some(frame) = self.inner.as_ref() {
                let xyz = self.coord_at(py, frame, index);
                (xyz[0], xyz[1], xyz[2])
            } else {
                (py_atom.x, py_atom.y, py_atom.z)
            };
            builder.add_atom(
                &py_atom.symbol,
                x,
                y,
                z,
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
            .map_err(|e| parse_err_to_py(py, &e, e.line(), e.named_frame().unwrap_or(0)))
    }
}

/// Pointer and length of a contiguous NumPy `f64` buffer.
///
/// No slice is formed. Another thread may store into the buffer, so
/// callers load each element with [`crate::types::atomic_load_f64`].
fn numpy_f64_ptr<D>(array: &Bound<'_, numpy::PyArray<f64, D>>) -> Option<(*const f64, usize)>
where
    D: numpy::ndarray::Dimension,
{
    if !array.is_c_contiguous() {
        return None;
    }
    let len = array.len();
    if len == 0 {
        return None;
    }
    let ptr = array.data().cast_const();
    crate::types::assert_atomic_f64_alignment(ptr);
    Some((ptr, len))
}

/// `n` rows starting at double offset `at`, one relaxed load per double.
fn coords_from_numpy<'py, D>(
    py: Python<'py>,
    array: &Bound<'_, numpy::PyArray<f64, D>>,
    at: usize,
    n: usize,
) -> PyResult<Option<Bound<'py, PyArray2<f64>>>>
where
    D: numpy::ndarray::Dimension,
{
    let Some((ptr, total)) = numpy_f64_ptr(array) else {
        return Ok(None);
    };
    let len = n.saturating_mul(3);
    if n == 0 || at.saturating_add(len) > total {
        return Ok(None);
    }
    let rows = (0..n).map(|row| {
        let start = at + row * 3;
        unsafe {
            [
                crate::types::atomic_load_f64(ptr.add(start)),
                crate::types::atomic_load_f64(ptr.add(start + 1)),
                crate::types::atomic_load_f64(ptr.add(start + 2)),
            ]
        }
    });
    Ok(Some(filled_rows(py, rows)))
}

/// Three doubles at `at`, loaded one element at a time.
fn load_numpy_triple<D>(array: &Bound<'_, numpy::PyArray<f64, D>>, at: usize) -> Option<[f64; 3]>
where
    D: numpy::ndarray::Dimension,
{
    let (ptr, len) = numpy_f64_ptr(array)?;
    if at + 2 >= len {
        return None;
    }
    Some(unsafe {
        [
            crate::types::atomic_load_f64(ptr.add(at)),
            crate::types::atomic_load_f64(ptr.add(at + 1)),
            crate::types::atomic_load_f64(ptr.add(at + 2)),
        ]
    })
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
        sequential_plain: false,
        positions: crate::storage_dtype::Array2Storage::from_f64_row_major(
            n,
            3,
            positions.to_vec(),
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
    atom_ids: Vec<u64>,
    atomic_numbers: Vec<u64>,
    /// One species string repeated `count` times, in frame order.
    symbol_runs: Vec<(String, usize)>,
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
    if storage.nrows() == n && storage.ncols() == 3 {
        if let Some(slice) = storage.f64_slice()
            && slice.len() == n * 3
        {
            into.extend_from_slice(slice);
            return;
        }
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
            atom_ids: Vec::new(),
            atomic_numbers: Vec::new(),
            symbol_runs: Vec::new(),
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
    let mut atom_ids = Vec::with_capacity(n_frames * n_atoms);
    let mut atomic_numbers = Vec::with_capacity(n_frames * n_atoms);
    let mut symbol_runs = Vec::new();
    for frame in frames {
        if pack_positions && frame.positions.nrows() == n_atoms {
            for index in 0..n_atoms {
                positions.extend_from_slice(&frame.load_coords(index));
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
        push_frame_identity(frame, &mut atom_ids, &mut atomic_numbers, &mut symbol_runs);
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
        atom_ids,
        atomic_numbers,
        symbol_runs,
    })
}

/// Doubles per staged run of a column writer, about 4 MiB.
const STAGE_VALUES: usize = 1 << 19;

/// Frames per staged run when one frame holds `per_frame` doubles.
fn staged_frames(per_frame: usize) -> usize {
    (STAGE_VALUES / per_frame.max(1)).max(1)
}

/// A frame-major contiguous NumPy column kept alive by the calling binding.
///
/// Python can store into the array concurrently on a free-threaded build.
/// A column writer therefore never forms an `f64` reference or slice over
/// this pointer. It copies runs of about 4 MiB with relaxed `AtomicU64`
/// loads into a private buffer and formats that buffer detached. Every
/// copied double is untorn; there is deliberately no cross-element
/// atomicity, so stores between loads can appear in the same snapshot.
#[derive(Clone, Copy)]
struct SharedColumn {
    ptr: *const f64,
    len: usize,
    per_frame: usize,
}

// The pointer is dereferenced only in `stage_values`, which needs the
// attached thread's token.
unsafe impl Send for SharedColumn {}

impl SharedColumn {
    fn from_array(
        value: &Bound<'_, PyAny>,
        name: &str,
        per_frame: usize,
        expected: usize,
    ) -> PyResult<Self> {
        let array = value.cast::<numpy::PyArrayDyn<f64>>()?;
        if !array.is_c_contiguous() || array.len() != expected {
            return Err(PyValueError::new_err(name.to_owned()));
        }
        let ptr = array.data().cast_const();
        if expected > 0 {
            crate::types::assert_atomic_f64_alignment(ptr);
        }
        Ok(Self {
            ptr,
            len: expected,
            per_frame,
        })
    }

    /// Copy the values of `frames` into `into`.
    fn stage(&self, py: Python<'_>, frames: std::ops::Range<usize>, into: &mut Vec<f64>) {
        let per_frame = self.per_frame;
        self.stage_values(py, frames.start * per_frame..frames.end * per_frame, into);
    }

    fn snapshot(&self, py: Python<'_>) -> Vec<f64> {
        let mut out: Vec<f64> = Vec::with_capacity(self.len);
        let mut start = 0;
        while start < self.len {
            let end = (start + STAGE_VALUES).min(self.len);
            let old_len = out.len();
            unsafe {
                crate::types::atomic_copy_f64(
                    self.ptr.add(start),
                    out.as_mut_ptr().add(old_len),
                    end - start,
                );
                out.set_len(old_len + end - start);
            }
            start = end;
        }
        let _ = py;
        out
    }

    /// Copy `values` into `into` while the binding keeps the NumPy allocation
    /// alive. `_py` proves the caller has not returned the owning arguments.
    fn stage_values(&self, _py: Python<'_>, values: std::ops::Range<usize>, into: &mut Vec<f64>) {
        let len = values.len();
        assert!(values.end <= self.len);
        into.clear();
        if len == 0 {
            return;
        }
        into.reserve(len);
        unsafe {
            crate::types::atomic_copy_f64(self.ptr.add(values.start), into.as_mut_ptr(), len);
            into.set_len(len);
        }
    }
}

/// Write one contiguous column dict, the shape returned by
/// ``ConFrameList.columns``.
///
/// Runs of frames are copied with the GIL held and formatted with it
/// released. There is no per-atom Python loop. If another thread stores
/// into the same NumPy arrays during a call, each output float is one
/// untorn value from that array, but different elements can come from
/// different stores.
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
    let pos = positions.cast::<PyArray3<f64>>()?;
    let mass = masses.cast::<PyArray2<f64>>()?;
    let cell_arr = cell.cast::<PyArray2<f64>>()?;
    let shape = pos.dims();
    if shape[2] != 3 {
        return Err(PyValueError::new_err("positions"));
    }
    let n_frames = shape[0];
    let n_atoms = shape[1];
    let n_values = n_frames.saturating_mul(n_atoms);
    if mass.len() != n_values || cell_arr.len() != n_frames.saturating_mul(6) {
        return Err(PyValueError::new_err("positions, masses and cell disagree"));
    }
    let cell_owned =
        SharedColumn::from_array(&cell, "cell", 6, n_frames.saturating_mul(6))?.snapshot(py);
    check_cell_array(py, &cell_owned)?;
    let fixed_value = columns.get_item("fixed")?;
    let fixed_arr = match fixed_value.as_ref() {
        Some(value) if !value.is_none() => Some(value.cast::<PyArray3<f64>>()?),
        _ => None,
    };
    let fixed_column = match fixed_arr.as_ref() {
        Some(arr) => Some(SharedColumn::from_array(
            arr.as_any(),
            "fixed",
            n_atoms * 3,
            n_values.saturating_mul(3),
        )?),
        None => None,
    };
    let vel_value = columns.get_item("velocities")?;
    let vel_arr = match vel_value.as_ref() {
        Some(value) if !value.is_none() => Some(value.cast::<PyArray3<f64>>()?),
        _ => None,
    };
    let vel_column = match vel_arr.as_ref() {
        Some(arr) => Some(SharedColumn::from_array(
            arr.as_any(),
            "velocities",
            n_atoms * 3,
            n_values.saturating_mul(3),
        )?),
        None => None,
    };
    let force_value = columns.get_item("forces")?;
    let force_arr = match force_value.as_ref() {
        Some(value) if !value.is_none() => Some(value.cast::<PyArray3<f64>>()?),
        _ => None,
    };
    let force_column = match force_arr.as_ref() {
        Some(arr) => Some(SharedColumn::from_array(
            arr.as_any(),
            "forces",
            n_atoms * 3,
            n_values.saturating_mul(3),
        )?),
        None => None,
    };
    let xyz = n_atoms * 3;
    let columns = [
        Some(SharedColumn::from_array(
            &positions,
            "positions",
            xyz,
            n_values.saturating_mul(3),
        )?),
        Some(SharedColumn::from_array(
            &masses, "masses", n_atoms, n_values,
        )?),
        Some(SharedColumn {
            ptr: cell_owned.as_ptr(),
            len: cell_owned.len(),
            per_frame: 6,
        }),
        fixed_column,
        vel_column,
        force_column,
    ];
    let per_frame = columns
        .iter()
        .flatten()
        .map(|column| column.per_frame)
        .sum();
    let step = staged_frames(per_frame).max(2);
    let workers = n_threads.unwrap_or(0);
    let mut file_bytes = Vec::new();
    let mut staged: [Vec<f64>; 6] = Default::default();
    let mut start = 0;
    while start < n_frames {
        let end = (start + step).min(n_frames);
        for (column, into) in columns.iter().zip(staged.iter_mut()) {
            if let Some(column) = column {
                column.stage(py, start..end, into);
            }
        }
        let present = |index: usize| columns[index].map(|_| staged[index].as_slice());
        let (fixed, velocities, forces) = (present(3), present(4), present(5));
        py.detach(|| {
            crate::writer::format_binding_columns(
                &mut file_bytes,
                end - start,
                n_atoms,
                &staged[0],
                &staged[1],
                &staged[2],
                fixed,
                velocities,
                forces,
                symbol,
                workers,
            )
        })
        .map_err(|err| PyIOError::new_err(err.to_string()))?;
        start = end;
    }
    let path_owned = path.to_owned();
    py.detach(move || {
        crate::writer::publish_new(
            Path::new(&path_owned),
            crate::writer::WriteError::Io,
            |file| {
                std::io::Write::write_all(file, &file_bytes).map_err(crate::writer::WriteError::Io)
            },
        )
    })
    .map_err(|err| PyIOError::new_err(err.to_string()))
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
    let shape = positions.dims();
    let n_frames = shape[0];
    let n_atoms = shape[1];
    let n_values = n_frames.saturating_mul(n_atoms);
    if positions.len() != n_values.saturating_mul(3)
        || masses.len() != n_values
        || cell.len() != n_frames.saturating_mul(6)
    {
        return Err(PyValueError::new_err("positions, masses and cell disagree"));
    }
    let pos_owned = SharedColumn::from_array(
        positions.as_any(),
        "positions",
        n_atoms * 3,
        n_values.saturating_mul(3),
    )?
    .snapshot(py);
    let mass_owned =
        SharedColumn::from_array(masses.as_any(), "masses", n_atoms, n_values)?.snapshot(py);
    let cell_owned =
        SharedColumn::from_array(cell.as_any(), "cell", 6, n_frames.saturating_mul(6))?
            .snapshot(py);
    check_cell_array(py, &cell_owned)?;
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
/// `read_con` returns this. Every frame's coordinates stay in the buffer
/// the parse wrote, owned by one [`PositionStore`]. A frame's Python
/// object, including its metadata dict, is built the first time that
/// frame is indexed.
#[pyclass(name = "ConFrameList")]
struct ConFrameList {
    /// A write, a string, a checksum or an id check holds the read lock
    /// for the whole call, detached included, so no thread sees the list
    /// without its frames. Every lock is taken with `*_py_attached`: a
    /// thread that has to wait detaches first, so a detached holder can
    /// always attach again.
    frames: std::sync::RwLock<Vec<Option<ConFrame>>>,
    /// Lock order is `cache`, then `frames`.
    cache: std::sync::Mutex<Vec<Option<Py<PyConFrame>>>>,
    /// One `[frames, N, 3]` array, built by the first `columns()` call and
    /// set with `frames` write-locked. The stored frames then read it.
    slab: pyo3::sync::PyOnceLock<Py<PyArray3<f64>>>,
    /// The parse buffers, until `columns()` moves the coordinates to `slab`.
    store: std::sync::Mutex<Option<Py<PositionStore>>>,
    /// Python can reach stored coordinates: `columns()` returned them, or
    /// an indexed frame views them. Set with `frames` write-locked, so a
    /// reader that saw `false` finishes before Python has the array.
    slab_shared: std::sync::atomic::AtomicBool,
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

/// Run `f` on `slots` with the GIL released.
///
/// `shared` means Python can store into the coordinates those frames read,
/// through a NumPy array it holds. `f` then reads a [`CoordSnapshot`]
/// copied here, attached, instead. The copy reads each double once, and
/// under the GIL no Python store runs during it. A free-threaded build has
/// no such exclusion, so a store racing the copy lands on either side of
/// it, as with NumPy's own copies. Either way the frames `f` reads do not
/// change under it.
fn detach_slots<R, F>(py: Python<'_>, slots: &[Option<ConFrame>], shared: bool, f: F) -> R
where
    F: Send + FnOnce(&[Option<ConFrame>]) -> R,
    R: Send,
{
    if !shared {
        return py.detach(move || f(slots));
    }
    let refs: Vec<Option<&ConFrame>> = slots.iter().map(Option::as_ref).collect();
    let snapshot = crate::types::CoordSnapshot::copy_of(&refs);
    drop(refs);
    py.detach(move || crate::writer::with_price_key(snapshot.price_key(), || f(snapshot.slots())))
}

/// [`detach_slots`] for frames held one by one.
fn detach_refs<R, F>(py: Python<'_>, frames: &[&ConFrame], shared: bool, f: F) -> R
where
    F: Send + FnOnce(&[&ConFrame]) -> R,
    R: Send,
{
    if !shared {
        return py.detach(move || f(frames));
    }
    let refs: Vec<Option<&ConFrame>> = frames.iter().copied().map(Some).collect();
    let snapshot = crate::types::CoordSnapshot::copy_of(&refs);
    drop(refs);
    py.detach(move || {
        let copies: Vec<&ConFrame> = snapshot.slots().iter().flatten().collect();
        crate::writer::with_price_key(snapshot.price_key(), || f(&copies))
    })
}

/// A thread that has to wait for `mutex` detaches while it waits.
fn lock_attached<'a, T>(
    py: Python<'_>,
    mutex: &'a std::sync::Mutex<T>,
) -> std::sync::MutexGuard<'a, T> {
    use pyo3::sync::MutexExt;
    mutex
        .lock_py_attached(py)
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

impl ConFrameList {
    fn slots(&self, py: Python<'_>) -> std::sync::RwLockReadGuard<'_, Vec<Option<ConFrame>>> {
        use pyo3::sync::RwLockExt;
        self.frames
            .read_py_attached(py)
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn slots_mut(&self, py: Python<'_>) -> std::sync::RwLockWriteGuard<'_, Vec<Option<ConFrame>>> {
        use pyo3::sync::RwLockExt;
        self.frames
            .write_py_attached(py)
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn len_frames(&self, py: Python<'_>) -> usize {
        self.slots(py).len()
    }

    /// Base of the coordinate slab, shared or not.
    ///
    /// The parsed column was moved into this array, so a read of the column
    /// is empty. Callers load through this pointer.
    fn slab_data_ptr(&self, py: Python<'_>) -> Option<*const f64> {
        let slab = self.slab.get(py)?.bind(py);
        numpy_f64_ptr(slab).map(|(ptr, _)| ptr)
    }

    /// Run `f` on the stored slots under the read lock.
    ///
    /// `f` runs detached. It reads a coordinate snapshot when `reads_coords`
    /// is set and Python can reach the slab those coordinates live in.
    fn with_slots<R, F>(&self, py: Python<'_>, reads_coords: bool, f: F) -> R
    where
        F: Send + FnOnce(&[Option<ConFrame>]) -> R,
        R: Send,
    {
        let slots = self.slots(py);
        let shared = reads_coords && self.slab_shared.load(std::sync::atomic::Ordering::Acquire);
        let stored = slots.iter().all(|slot| slot.is_some());
        // Every frame is still in the list and Python has not been handed
        // the slab. Borrow each row for the write. Copying the slab here
        // is a second trajectory, which the stream writer rejects.
        if reads_coords && stored && !shared {
            if let Some(ptr) = self.slab_data_ptr(py) {
                let width = self.n_atoms.saturating_mul(3);
                let first = slots[0]
                    .as_ref()
                    .map(|frame| frame as *const ConFrame as usize);
                let stride = slots.get(1).and_then(|slot| {
                    let second = slot.as_ref()? as *const ConFrame as usize;
                    first.map(|start| second.saturating_sub(start))
                });
                if let Some(first) = first {
                    let _borrowed = crate::writer::install_borrowed_slab(
                        ptr as usize,
                        width,
                        first,
                        stride.unwrap_or(0),
                        slots.len(),
                    );
                    return detach_slots(py, &slots, false, f);
                }
            }
            let guards = {
                let store = lock_attached(py, &self.store);
                let mut guards = Vec::new();
                if let Some(held) = store.as_ref() {
                    let buffers = &held.get().buffers;
                    for (index, slot) in slots.iter().enumerate() {
                        let (Some(frame), Some(buffer)) = (slot.as_ref(), buffers.get(index))
                        else {
                            continue;
                        };
                        if buffer.len == 0 {
                            continue;
                        }
                        guards.push(crate::writer::install_borrowed_slab(
                            buffer.ptr as usize,
                            buffer.len,
                            frame as *const ConFrame as usize,
                            0,
                            1,
                        ));
                    }
                }
                guards
            };
            if !guards.is_empty() {
                let result = detach_slots(py, &slots, false, f);
                drop(guards);
                return result;
            }
        }
        // A frame Python holds, or `columns()`, can store into the slab
        // while the write runs. The snapshot is the private copy. A missing
        // slot still occupies `n_atoms` rows; the gap keeps the rest aligned.
        if reads_coords && shared {
            if let Some(ptr) = self.slab_data_ptr(py) {
                let refs: Vec<Option<&ConFrame>> = slots.iter().map(Option::as_ref).collect();
                let snapshot = crate::types::CoordSnapshot::copy_reading_gap(
                    &refs,
                    ptr,
                    self.n_atoms.saturating_mul(3),
                );
                drop(refs);
                return py.detach(move || {
                    crate::writer::with_price_key(snapshot.price_key(), || f(snapshot.slots()))
                });
            }
            let copied = {
                let store = lock_attached(py, &self.store);
                store.as_ref().map(|held| {
                    let mut data = Vec::new();
                    for (index, slot) in slots.iter().enumerate() {
                        let n = slot
                            .as_ref()
                            .map(|frame| frame.atom_data.len())
                            .unwrap_or(self.n_atoms);
                        if !held.get().copy_rows(index, n, &mut data) {
                            data.resize(data.len() + n.saturating_mul(3), 0.0);
                        }
                    }
                    data
                })
            };
            if let Some(copied) = copied
                && !copied.is_empty()
            {
                let refs: Vec<Option<&ConFrame>> = slots.iter().map(Option::as_ref).collect();
                let snapshot = crate::types::CoordSnapshot::copy_reading_gap(
                    &refs,
                    copied.as_ptr(),
                    self.n_atoms.saturating_mul(3),
                );
                drop(refs);
                return py.detach(move || {
                    crate::writer::with_price_key(snapshot.price_key(), || f(snapshot.slots()))
                });
            }
        }
        detach_slots(py, &slots, false, f)
    }

    fn frame_obj(&self, py: Python<'_>, index: usize) -> PyResult<Py<PyConFrame>> {
        // Held until the object is cached. A second thread indexing the
        // same frame waits here and then takes the cached object; it does
        // not find the slot already moved out.
        let mut cache = lock_attached(py, &self.cache);
        if let Some(hit) = cache.get(index).and_then(|slot| slot.as_ref()) {
            return Ok(hit.clone_ref(py));
        }
        let frame = {
            let mut slots = self.slots_mut(py);
            self.slab_shared
                .store(true, std::sync::atomic::Ordering::Release);
            slots.get_mut(index).and_then(Option::take)
        }
        .ok_or_else(|| PyIOError::new_err(format!("frame {index} is already borrowed")))?;
        let store = lock_attached(py, &self.store)
            .as_ref()
            .map(|store| store.clone_ref(py));
        let built = if let Some(slab) = self.slab.get(py) {
            PyConFrame::from_slab(py, frame, slab.clone_ref(py), index, self.n_atoms)?
        } else if let Some(store) = store {
            PyConFrame::from_store(py, frame, store, index)?
        } else {
            PyConFrame::from_owned(py, frame)?
        };
        let obj = Py::new(py, built)?;
        if let Some(slot) = cache.get_mut(index) {
            *slot = Some(obj.clone_ref(py));
        }
        Ok(obj)
    }
}

#[pymethods]
impl ConFrameList {
    fn __len__(&self, py: Python<'_>) -> usize {
        self.len_frames(py)
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let n = self.len_frames(py);
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
        lock_attached(py, &self.phases).dict(py)
    }

    /// XOR of every frame's positions, cell lengths, and atom-type symbols.
    ///
    /// The read walks a copy of the coordinate slab and each stored
    /// symbol. The returned seconds are that walk. A second call walks
    /// again.
    fn touch_checksum(&self, py: Python<'_>) -> PyResult<(u64, f64)> {
        let copied = if let Some(slab) = self.slab.get(py) {
            let array = slab.bind(py);
            let shape = array.shape();
            let len = shape
                .iter()
                .try_fold(1usize, |acc, dim| acc.checked_mul(*dim))
                .ok_or_else(|| PyIOError::new_err("touch_checksum slab size overflow"))?;
            let mut copied = vec![0.0f64; len];
            if len > 0 {
                if !array.is_c_contiguous() {
                    return Err(PyIOError::new_err("touch_checksum slab is not contiguous"));
                }
                let base = array.data().cast_const();
                crate::types::assert_atomic_f64_alignment(base);
                unsafe {
                    crate::types::atomic_copy_f64(base, copied.as_mut_ptr(), len);
                }
            }
            copied
        } else {
            let store = lock_attached(py, &self.store)
                .as_ref()
                .map(|store| store.clone_ref(py))
                .ok_or_else(|| {
                    PyIOError::new_err("touch_checksum needs the coordinates of the read")
                })?;
            let buffers = &store.get().buffers;
            let len = buffers.iter().map(|buffer| buffer.len).sum();
            let mut copied: Vec<f64> = Vec::with_capacity(len);
            for buffer in buffers {
                if buffer.len == 0 {
                    continue;
                }
                crate::types::assert_atomic_f64_alignment(buffer.ptr);
                unsafe {
                    crate::types::atomic_copy_f64(
                        buffer.ptr,
                        copied.as_mut_ptr().add(copied.len()),
                        buffer.len,
                    );
                    copied.set_len(copied.len() + buffer.len);
                }
            }
            copied
        };
        let workers = self.workers;
        let pool = lock_attached(py, &self.pool).clone();
        let slots = self.slots(py);
        let positions = copied;
        let frames: &[Option<ConFrame>] = &slots;
        let walk = move || {
            let fault0 = crate::iterators::process_minflt();
            let t_touch = std::time::Instant::now();
            let run = || crate::iterators::touch_option_checksum(frames, &positions, workers);
            let digest = match pool.as_ref() {
                Some(pool) if workers >= 2 => pool.install(run),
                _ => run(),
            };
            let touch_s = t_touch.elapsed().as_secs_f64();
            let touch_minflt = crate::iterators::process_minflt().saturating_sub(fault0);
            (digest, touch_s, touch_minflt)
        };
        // The walk is pure Rust over `positions`, so it can run detached.
        let (digest, touch_s, touch_minflt) = py.detach(walk);
        drop(slots);
        let digest = digest
            .ok_or_else(|| PyIOError::new_err("touch_checksum could not read every frame"))?;
        {
            let mut phases = lock_attached(py, &self.phases);
            phases.touch_s = touch_s;
            phases.touch_minflt = touch_minflt;
        }
        Ok((digest, touch_s))
    }

    /// Positions, masses, constraint flags, cell, identity, and any
    /// velocity or force block as one contiguous NumPy array each.
    ///
    /// `positions` is the coordinate slab from the read, the same array
    /// object on every call. The other arrays are copied from the parsed
    /// frames while this call holds the list lock. `atom_ids` and
    /// `atomic_numbers` are `(frames, atoms)` uint64. `symbols` is an
    /// object array of that shape, one Python string per species run.
    /// Indexing a frame takes that frame out of the list, and a later
    /// call then fails. Call this before `frames[i]`. `write_columns`
    /// writes the numeric dict back and ignores the identity keys.
    /// Indexing a frame still builds Python atoms; this does not.
    fn columns(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let (packed, slab) = {
            // The write lock waits out any detached reader of the stored
            // coordinates before Python is handed the array.
            let frames = self.slots_mut(py);
            if frames.iter().any(|slot| slot.is_none()) {
                return Err(PyIOError::new_err(
                    "columns() needs every frame still stored; indexing a frame borrows it",
                ));
            }
            let mut store = lock_attached(py, &self.store);
            // One frame's parse buffer already is the `[1, N, 3]` block.
            let single = match (self.slab.get(py), store.as_ref()) {
                (None, Some(held)) if frames.len() == 1 && held.get().buffers.len() == 1 => {
                    Some(held.clone_ref(py))
                }
                _ => None,
            };
            let pack_positions = self.slab.get(py).is_none() && single.is_none();
            let packed = pack_frame_columns(
                frames.iter().map(|slot| slot.as_ref().unwrap()),
                pack_positions,
            );
            let Some(mut packed) = packed else {
                return Err(PyValueError::new_err(
                    "columns() needs the same atom count in every frame",
                ));
            };
            if self.slab.get(py).is_none() {
                let slab = if let Some(held) = single {
                    let bound = held.bind(py);
                    let buffer = &held.get().buffers[0];
                    unsafe {
                        owned_view(
                            bound.as_any(),
                            buffer.ptr.cast_const(),
                            ndarray::Ix3(1, buffer.len / 3, 3),
                            true,
                        )?
                    }
                    .unbind()
                } else {
                    // Frames in separate parse buffers are packed once.
                    for _ in 0..packed.n_frames {
                        count_binding_copy();
                    }
                    if packed.positions.len() != packed.n_frames * packed.n_atoms * 3
                        && let Some(held) = store.as_ref()
                    {
                        let mut values = Vec::with_capacity(packed.n_frames * packed.n_atoms * 3);
                        let mut ok = true;
                        for (index, frame) in frames.iter().flatten().enumerate() {
                            if !held
                                .get()
                                .copy_rows(index, frame.atom_data.len(), &mut values)
                            {
                                ok = false;
                                break;
                            }
                        }
                        if ok {
                            packed.positions = values;
                        }
                    }
                    let values = std::mem::take(&mut packed.positions);
                    let slab = slab_from_values(py, values, packed.n_frames, packed.n_atoms)?;
                    *store = None;
                    slab
                };
                let _ = self.slab.set(py, slab);
            }
            self.slab_shared
                .store(true, std::sync::atomic::Ordering::Release);
            let slab = self.slab.get(py).expect("slab").clone_ref(py);
            (packed, slab)
        };
        let dict = PyDict::new(py);
        dict.set_item("positions", slab)?;
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
        let ids =
            ndarray::Array2::from_shape_vec((packed.n_frames, packed.n_atoms), packed.atom_ids)
                .map_err(|err| PyValueError::new_err(err.to_string()))?;
        let numbers = ndarray::Array2::from_shape_vec(
            (packed.n_frames, packed.n_atoms),
            packed.atomic_numbers,
        )
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
        dict.set_item("atom_ids", ids.into_pyarray(py))?;
        dict.set_item("atomic_numbers", numbers.into_pyarray(py))?;
        dict.set_item(
            "symbols",
            symbols_array(py, &packed.symbol_runs, Some(packed.n_frames))?,
        )?;
        Ok(dict.unbind())
    }

    /// Return each frame's position buffer and symbol storage to the
    /// worker recycle lists, then join the pool.
    ///
    /// The seconds cover that return and the pool join. A later drop
    /// of this object is empty.
    fn release_frames(&mut self, py: Python<'_>) -> f64 {
        let (teardown_s, pool_join_s) = py.detach(|| self.teardown());
        let mut phases = lock_attached(py, &self.phases);
        phases.teardown_s = teardown_s;
        phases.pool_join_s = pool_join_s;
        teardown_s
    }
}

impl ConFrameList {
    fn teardown(&mut self) -> (f64, f64) {
        let t0 = std::time::Instant::now();
        let mut frames = std::mem::take(
            self.frames
                .get_mut()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
        );
        let pool = self
            .pool
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
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
        let list = self.inner.borrow(py);
        if self.pos >= list.len_frames(py) {
            return Ok(None);
        }
        let index = self.pos;
        self.pos += 1;
        list.frame_obj(py, index).map(Some)
    }
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
    // Each frame keeps the buffer its parse wrote. Moving those buffers
    // into the store copies no coordinate. Atoms store no pointer; the
    // store is the only buffer, so there is no second trajectory to drop.
    let n_atoms = match frames.first() {
        Some(first)
            if frames
                .iter()
                .all(|frame| frame.atom_data.len() == first.atom_data.len()) =>
        {
            first.atom_data.len()
        }
        _ => 0,
    };
    let held = py.detach(|| PositionStore::take_from(&mut frames));
    let slab_s = t_slab.elapsed().as_secs_f64();
    let slab_minflt = crate::iterators::process_minflt().saturating_sub(fault0);
    let t_build = std::time::Instant::now();
    let store = Py::new(py, held)?;
    let python_build_s = t_build.elapsed().as_secs_f64();
    let release_s = 0.0;
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
            frames: std::sync::RwLock::new(stored),
            cache: std::sync::Mutex::new(cache),
            slab: pyo3::sync::PyOnceLock::new(),
            store: std::sync::Mutex::new(Some(store)),
            slab_shared: std::sync::atomic::AtomicBool::new(false),
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
fn scan_probe(
    py: Python<'_>,
    path: &str,
    threads: usize,
    chunked: bool,
) -> PyResult<(usize, f64, bool)> {
    let path_owned = path.to_owned();
    let measured = py
        .detach(|| {
            let text = std::fs::read_to_string(&path_owned).map_err(|err| err.to_string())?;
            let (offsets, seconds) =
                crate::iterators::measure_newline_scan(&text, threads, chunked);
            let serial = crate::iterators::frame_start_offsets_serial(&text);
            Ok::<_, String>((offsets.len(), seconds, offsets == serial))
        })
        .map_err(PyIOError::new_err)?;
    Ok(measured)
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
/// `n >= 2` for a Rayon pool of that size. A one-thread read inflates
/// a multi-member gzip or zstd file on that same thread unless
/// `decode_threads` says otherwise. A plain file of 64 KiB or more
/// stays mapped. `.gz` and `.zst` are chosen from the extension and
/// from the magic bytes. A pipe, including `/dev/stdin`, is read
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
    // Omitting `decode_threads` on a one-thread read does the same.
    // The unset budget is one decoder per member, and a million-atom
    // gzip file has 32 members. Each decoder thread keeps an allocator
    // arena, which was the gap between that read's peak and a plain read.
    let parse_threads = match (n_threads, decode_threads) {
        (Some(parse), Some(decode)) if decode >= 2 => Some(parse.max(decode)),
        (parse, _) => parse,
    };
    let serial_decode = match decode_threads {
        Some(1) => true,
        None => matches!(n_threads, Some(0) | Some(1)),
        _ => false,
    };
    let run = || read_con_lazy(py, path, parse_threads);
    if serial_decode {
        crate::compression::with_serial_decode(run)
    } else if let Some(threads) = decode_threads.filter(|threads| *threads >= 2) {
        crate::compression::with_decode_threads(threads, run)
    } else {
        run()
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

fn frames_from_parsed(py: Python<'_>, mut frames: Vec<ConFrame>) -> PyResult<Vec<PyConFrame>> {
    let store = Py::new(py, PositionStore::take_from(&mut frames))?;
    frames
        .into_iter()
        .enumerate()
        .map(|(index, frame)| PyConFrame::from_store(py, frame, store.clone_ref(py), index))
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
    PyConFrame::from_owned(py, frame)
}

/// Read frames from a string containing .con or .convel data.
#[pyfunction]
#[pyo3(signature = (contents, n_threads=None))]
fn read_con_string(
    py: Python<'_>,
    contents: &str,
    n_threads: Option<usize>,
) -> PyResult<Py<ConFrameList>> {
    // `contents` is the UTF-8 buffer of the argument `str`, which the call
    // keeps alive and nothing can change, so it is parsed in place detached.
    let open_mmap_s = 0.0;
    let n_bytes = contents.len();
    let parsed = py
        .detach(|| {
            crate::iterators::frames_from_bytes_phased(contents.as_bytes(), n_threads).map_err(
                |e| {
                    if utf8_failure(&e) {
                        return CountFail::Io(e.to_string());
                    }
                    let located =
                        crate::iterators::frames_from_text_located(contents, n_threads).err();
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
                },
            )
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
        parse_err_in_frame(py, parse, parse.line(), frame_index)
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
                let source_text = span.to_owned();
                let consumed =
                    (span.as_ptr() as usize).saturating_sub(slice.as_ptr() as usize) + span.len();
                let lines = newlines_in(span);
                *pos += consumed;
                self.line_base = self.line_base.saturating_add(lines);
                self.frame_index = self.frame_index.saturating_add(1);
                contents
                    .release_before(*pos)
                    .map_err(|e| PyIOError::new_err(format!("release error: {e}")))?;
                Ok(Some(PyConFrame::from_owned_with_source(
                    py,
                    frame,
                    Some(source_text),
                )?))
            }
            Some(Err(e)) => {
                let line = file_line(self.line_base, iter.lines.line_no());
                Err(parse_err_in_frame(py, &e, line, self.frame_index))
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
                Err(parse_err_in_frame(py, &e, line, self.frame_index))
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

/// Streaming iterator over frames in CON text the caller already holds.
///
/// Each frame is the same object `iter_con` yields for a path. Array
/// getters on those frames read the parsed columns and do not build
/// Python atoms. `read_con_string` parses the same text into a list.
#[pyfunction]
fn iter_con_string(contents: &str) -> PyResult<PyConFrameIterator> {
    Ok(PyConFrameIterator {
        source: FrameSource::Text(
            crate::compression::ForwardText::from_owned(contents.to_owned()),
            0,
        ),
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
    PyConFrame::from_owned(py, frame)
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

#[derive(Clone, Copy)]
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
    // `write_frame_binding` is handed the clone, so a slab borrow keyed by
    // the original address has to be copied onto that clone first. One frame.
    if stamped.positions.nrows() == 0 {
        if let Some(slice) = crate::writer::borrowed_coord_slice(frame) {
            let n = frame.atom_data.len();
            if slice.len() == n.saturating_mul(3) {
                stamped.positions =
                    crate::storage_dtype::FloatArray2::from_f64_row_major(n, 3, slice.to_vec());
            }
        }
    }
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
    let borrowed = list.borrow();
    let cache = lock_attached(py, &borrowed.cache);
    let slots = borrowed.slots(py);
    let n = slots.len();
    // Keep every cached `PyConFrame` borrowed through the snapshot and
    // conversion below. In particular, `set_metadata(&mut self)` must not
    // mutate `inner` while its coordinate pointers are being copied.
    let cached_borrows: Vec<Option<Shared<'_, PyConFrame>>> = (0..n)
        .map(|index| {
            if slots[index].is_some() {
                None
            } else {
                cache
                    .get(index)
                    .and_then(Option::as_ref)
                    .map(|frame| shared(frame.bind(py)))
            }
            .transpose()
        })
        .collect::<PyResult<_>>()?;
    #[cfg(any(test, feature = "borrow-path-counts"))]
    BORROW_FRAME_HITS.fetch_add(
        cached_borrows
            .iter()
            .flatten()
            .filter(|frame| {
                !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
                    && frame
                        .inner
                        .as_ref()
                        .is_some_and(|inner| !inner.atom_data.is_empty())
            })
            .count() as u64,
        std::sync::atomic::Ordering::Relaxed,
    );
    let refs: Vec<Option<&ConFrame>> = slots
        .iter()
        .enumerate()
        .map(|(index, slot)| {
            slot.as_ref().or_else(|| {
                let frame = cached_borrows[index].as_ref()?;
                if frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire) {
                    return None;
                }
                frame.inner.as_ref()
            })
        })
        .collect();
    let slab_ptr = borrowed.slab_data_ptr(py);
    // A missing slot still occupies one frame of the slab. Advancing by
    // that width is what keeps an untouched frame on its own coordinates.
    // With no slab, the coordinates are the position store. `copy_of`
    // would walk the emptied column.
    let store_rows = if slab_ptr.is_none() {
        let store = lock_attached(py, &borrowed.store);
        store.as_ref().map(|held| {
            let mut data = Vec::new();
            for (index, frame) in refs.iter().enumerate() {
                let n = frame
                    .map(|frame| frame.atom_data.len())
                    .unwrap_or(borrowed.n_atoms);
                if !held.get().copy_rows(index, n, &mut data) {
                    data.resize(data.len() + n.saturating_mul(3), 0.0);
                }
            }
            data
        })
    } else {
        None
    };
    let snapshot = if let Some(ptr) = slab_ptr {
        crate::types::CoordSnapshot::copy_reading_gap(
            &refs,
            ptr,
            borrowed.n_atoms.saturating_mul(3),
        )
    } else if let Some(copied) = store_rows.as_ref()
        && !copied.is_empty()
    {
        crate::types::CoordSnapshot::copy_reading_gap(
            &refs,
            copied.as_ptr(),
            borrowed.n_atoms.saturating_mul(3),
        )
    } else {
        crate::types::CoordSnapshot::copy_of(&refs)
    };
    let mut out = Vec::with_capacity(n);
    for index in 0..n {
        if slab_ptr.is_none()
            && let Some(frame) = cached_borrows[index].as_ref()
            && !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
            && frame.coords_shared()
        {
            let live = snapshot_pyframe(py, frame);
            if let Some(view) = live.slots()[0].as_ref() {
                let mut owned = view.clone();
                if let Some((meta, minor_raw)) = metadata_edit(py, frame, view)? {
                    install_metadata(&mut owned, meta, minor_raw.as_deref());
                }
                out.push(owned);
                continue;
            }
        }
        if let Some(frame) = snapshot.slots()[index].as_ref() {
            // The clone reads only the private atomic snapshot.
            let mut owned = frame.clone();
            if let Some(py_frame) = cached_borrows[index].as_ref()
                && !py_frame
                    .atoms_ready
                    .load(std::sync::atomic::Ordering::Acquire)
                && let Some((meta, minor_raw)) = metadata_edit(py, py_frame, frame)?
            {
                install_metadata(&mut owned, meta, minor_raw.as_deref());
            }
            out.push(owned);
            continue;
        }
        if let Some(frame) = cached_borrows[index].as_ref()
            && frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
        {
            out.push(frame.to_con_frame(py)?);
            continue;
        }
        if let Some(frame) = slots[index].as_ref() {
            // Empty-coordinate frames need no snapshot slot.
            out.push(frame.clone());
            continue;
        }
        return Err(PyIOError::new_err(format!(
            "frame {index} is unavailable during snapshot"
        )));
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

/// Run `f` on every stored frame under the list's read lock.
///
/// `None` when the list has given a frame to Python. The frames stay in
/// the list throughout, so a concurrent reader, a panic in `f`, or an
/// error all leave the list whole. Nothing is moved or cloned.
fn with_stored_frames<R, F>(list: &Bound<'_, ConFrameList>, reads_coords: bool, f: F) -> Option<R>
where
    F: Send + FnOnce(&[Option<ConFrame>]) -> R,
    R: Send,
{
    list.borrow().with_slots(list.py(), reads_coords, |frames| {
        frames.iter().all(|slot| slot.is_some()).then(|| f(frames))
    })
}

fn stored_frame(slot: &Option<ConFrame>) -> &ConFrame {
    slot.as_ref().expect("stored frame")
}

fn format_stamped(
    frames: &[Option<ConFrame>],
    precision: Option<usize>,
    canonical: bool,
) -> Result<Vec<u8>, crate::writer::WriteError> {
    let mut buffer = Vec::new();
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
            None => ConFrameWriter::new(&mut buffer),
        }
        .canonical(canonical);
        for frame in frames {
            write_stamped_frame(&mut writer, stored_frame(frame))?;
        }
        writer.flush().map_err(crate::writer::WriteError::Io)?;
    }
    Ok(buffer)
}

fn binding_bytes_owned(
    frames: &[Option<ConFrame>],
    precision: Option<usize>,
    canonical: bool,
    n_threads: Option<usize>,
) -> Result<Vec<u8>, crate::writer::WriteError> {
    let workers = n_threads.filter(|count| *count >= 2).unwrap_or(1);
    let mut buffer = Vec::new();
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
            None => ConFrameWriter::new(&mut buffer),
        }
        .canonical(canonical);
        if workers >= 2 {
            writer = writer.parallel_atoms(workers);
        }
        for frame in frames {
            writer.write_frame_bound(stored_frame(frame))?;
        }
        writer.flush().map_err(crate::writer::WriteError::Io)?;
    }
    Ok(buffer)
}

fn owned_is_wide(frames: &[Option<ConFrame>], compression_members: Option<usize>) -> bool {
    if matches!(compression_members, Some(1)) || frames.len() != 1 {
        return false;
    }
    stored_frame(&frames[0]).atom_data.len() >= 4096
        || compression_members.is_some_and(|count| count > 1)
}

fn try_fused_owned(
    path: &Path,
    frames: &[Option<ConFrame>],
    compression_members: Option<usize>,
    n_threads: Option<usize>,
    gzip: bool,
) -> Result<bool, crate::writer::WriteError> {
    let Some(threads) = n_threads.filter(|count| *count >= 1) else {
        return Ok(false);
    };
    if frames.len() != 1 {
        return Ok(false);
    }
    let frame = stored_frame(&frames[0]);
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
    if gzip {
        crate::compression::write_fused_gzip_frame(path, frame, members, threads)
            .map_err(crate::writer::WriteError::Io)?;
    } else {
        #[cfg(feature = "zstd")]
        {
            crate::compression::write_fused_zstd_frame(path, frame, members, threads)
                .map_err(crate::writer::WriteError::Io)?;
        }
        #[cfg(not(feature = "zstd"))]
        {
            let _ = (path, frame, members, threads);
            return Ok(false);
        }
    }
    Ok(true)
}

fn write_owned_compressed(
    path: &Path,
    frames: &[Option<ConFrame>],
    precision: Option<usize>,
    canonical: bool,
    n_threads: Option<usize>,
    compression_members: Option<usize>,
    gzip: bool,
) -> Result<(), crate::writer::WriteError> {
    if owned_is_wide(frames, compression_members) {
        if try_fused_owned(path, frames, compression_members, n_threads, gzip)? {
            return Ok(());
        }
        let t_fmt = std::time::Instant::now();
        let plain = binding_bytes_owned(frames, precision, canonical, n_threads)?;
        if std::env::var_os("READCON_WRITE_TRACE").is_some() {
            eprintln!(
                "{}-format {:.4} plain_bytes={}",
                if gzip { "gzip" } else { "zstd" },
                t_fmt.elapsed().as_secs_f64(),
                plain.len()
            );
        }
        let members = compression_members
            .unwrap_or_else(|| crate::compression::compression_workers(plain.len()));
        let threads = n_threads
            .filter(|count| *count >= 2)
            .unwrap_or_else(|| crate::compression::default_deflate_threads(members));
        if gzip {
            crate::compression::write_gzip_members_limited(path, &plain, members, threads)
                .map_err(crate::writer::WriteError::Io)?;
        } else {
            #[cfg(feature = "zstd")]
            {
                crate::compression::write_zstd_members_limited(path, &plain, members, threads)
                    .map_err(crate::writer::WriteError::Io)?;
            }
            #[cfg(not(feature = "zstd"))]
            {
                let _ = (path, plain, members, threads);
                return Err(crate::writer::WriteError::Io(std::io::Error::new(
                    std::io::ErrorKind::Unsupported,
                    "zstd compression requires readcon built with the zstd feature",
                )));
            }
        }
        return Ok(());
    }
    if gzip {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::from_path_gzip_with_precision(path, precision)
                .map_err(crate::writer::WriteError::Io)?,
            None => ConFrameWriter::from_path_gzip(path).map_err(crate::writer::WriteError::Io)?,
        }
        .canonical(canonical);
        for frame in frames {
            writer.write_frame_bound(stored_frame(frame))?;
        }
        writer.flush().map_err(crate::writer::WriteError::Io)?;
        return Ok(());
    }
    #[cfg(feature = "zstd")]
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::from_path_zstd_with_precision(path, precision)
                .map_err(crate::writer::WriteError::Io)?,
            None => ConFrameWriter::from_path_zstd(path).map_err(crate::writer::WriteError::Io)?,
        }
        .canonical(canonical);
        for frame in frames {
            writer.write_frame_bound(stored_frame(frame))?;
        }
        writer.flush().map_err(crate::writer::WriteError::Io)?;
        return Ok(());
    }
    #[cfg(not(feature = "zstd"))]
    {
        let _ = (path, frames, precision, canonical);
        Err(crate::writer::WriteError::Io(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "zstd compression requires readcon built with the zstd feature",
        )))
    }
}

fn write_owned_frames(
    path: &Path,
    frames: &[Option<ConFrame>],
    precision: Option<usize>,
    codec: OutputCodec,
    canonical: bool,
    append: bool,
    n_threads: Option<usize>,
    compression_members: Option<usize>,
    rewrite: bool,
    keep_spare: bool,
) -> Result<(), crate::writer::WriteError> {
    match codec {
        OutputCodec::Gzip => write_owned_compressed(
            path,
            frames,
            precision,
            canonical,
            n_threads,
            compression_members,
            true,
        ),
        OutputCodec::Zstd => write_owned_compressed(
            path,
            frames,
            precision,
            canonical,
            n_threads,
            compression_members,
            false,
        ),
        OutputCodec::Plain => {
            let workers = n_threads.unwrap_or(1);
            let refs: Vec<&ConFrame> = frames.iter().map(|slot| stored_frame(slot)).collect();
            if rewrite {
                return crate::writer::rewrite_frame_refs_to_path(
                    path, &refs, workers, precision, canonical, true, keep_spare,
                );
            }
            if !append {
                return crate::writer::write_frame_refs_to_path(
                    path, &refs, workers, precision, canonical, true,
                );
            }
            let mut writer = match precision {
                Some(precision) => ConFrameWriter::from_path_append_with_precision(path, precision)
                    .map_err(crate::writer::WriteError::Io)?,
                None => {
                    ConFrameWriter::from_path_append(path).map_err(crate::writer::WriteError::Io)?
                }
            }
            .canonical(canonical);
            for frame in frames {
                write_stamped_frame(&mut writer, stored_frame(frame))?;
            }
            writer.flush().map_err(crate::writer::WriteError::Io)
        }
    }
}

/// A `read_con` result still holds every frame. Format and write them
/// under the list's read lock, without the GIL while Python cannot reach
/// the coordinate slab. Nothing is cloned.
fn write_stored_list(
    py: Python<'_>,
    path: &str,
    frames: &Bound<'_, PyAny>,
    precision: Option<usize>,
    codec: OutputCodec,
    canonical: bool,
    append: bool,
    n_threads: Option<usize>,
    compression_members: Option<usize>,
    rewrite: bool,
    keep_spare: bool,
) -> PyResult<Option<()>> {
    #[cfg(not(feature = "zstd"))]
    if matches!(codec, OutputCodec::Zstd) {
        return Ok(None);
    }
    let Ok(list) = frames.cast::<ConFrameList>() else {
        return Ok(None);
    };
    let path_buf = Path::new(path).to_path_buf();
    let Some(result) = with_stored_frames(list, true, move |stored| {
        write_owned_frames(
            &path_buf,
            stored,
            precision,
            codec,
            canonical,
            append,
            n_threads,
            compression_members,
            rewrite,
            keep_spare,
        )
    }) else {
        return Ok(None);
    };
    result.map_err(|err| write_err_to_py(py, err))?;
    Ok(Some(()))
}

#[derive(Clone, Copy)]
struct RefWrite {
    rewrite: bool,
    keep_spare: bool,
    /// The frames' coordinates live in a NumPy array Python can write.
    shared: bool,
}

fn detach_frame_refs(
    py: Python<'_>,
    path: &str,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    flags: RefWrite,
) -> PyResult<()> {
    let RefWrite {
        rewrite,
        keep_spare,
        shared,
    } = flags;
    let path_buf = Path::new(path).to_path_buf();
    detach_refs(py, frames, shared, move |refs| {
        if rewrite {
            crate::writer::rewrite_frame_refs_to_path(
                &path_buf, refs, workers, precision, canonical, true, keep_spare,
            )
        } else {
            crate::writer::write_frame_refs_to_path(
                &path_buf, refs, workers, precision, canonical, true,
            )
        }
    })
    .map_err(|err| write_err_to_py(py, err))
}

fn detach_append_frame_refs(
    py: Python<'_>,
    path: &str,
    frames: &[&ConFrame],
    precision: Option<usize>,
    canonical: bool,
    shared: bool,
) -> PyResult<()> {
    let path_buf = Path::new(path).to_path_buf();
    detach_refs(py, frames, shared, move |refs| {
        let mut writer = match precision {
            Some(precision) => {
                ConFrameWriter::from_path_append_with_precision(&path_buf, precision)
            }
            None => ConFrameWriter::from_path_append(&path_buf),
        }
        .map_err(crate::writer::WriteError::Io)?
        .canonical(canonical);
        for frame in refs {
            write_stamped_frame(&mut writer, frame)?;
        }
        writer.flush().map_err(crate::writer::WriteError::Io)
    })
    .map_err(|err| write_err_to_py(py, err))
}

fn detach_compressed_frame_refs(
    py: Python<'_>,
    path: &str,
    frames: &[&ConFrame],
    precision: Option<usize>,
    canonical: bool,
    n_threads: Option<usize>,
    compression_members: Option<usize>,
    gzip: bool,
) -> PyResult<()> {
    let refs: Vec<Option<&ConFrame>> = frames.iter().copied().map(Some).collect();
    let snapshot = crate::types::CoordSnapshot::copy_of(&refs);
    let path_buf = Path::new(path).to_path_buf();
    py.detach(move || {
        write_owned_compressed(
            &path_buf,
            snapshot.slots(),
            precision,
            canonical,
            n_threads,
            compression_members,
            gzip,
        )
    })
    .map_err(|err| write_err_to_py(py, err))
}

/// The `compression` argument controls output compression:
/// - `None` (default): codec from the path extension (`.gz` gzip, `.zst` zstd)
/// - `"gzip"`, `"zstd"`, or `"none"`
///
/// `append=True` extends an existing uncompressed file instead of replacing
/// it. The bytes match one `write_con` of the old frames followed by these
/// frames when the existing file was written by readcon. Gzip, zstd, and
/// `comm=` are refused.
/// `rewrite=True` replaces an existing uncompressed file from a spare inode
/// named `path` + `.rewrite`. That spare is a second copy of the trajectory
/// while it is kept. `keep_spare=False` deletes it after the rename, so the
/// next rewrite allocates fresh pages. The published path stays the previous
/// complete file until the rename, including if the process is killed.
/// With `comm=`, the default write is a fresh file and leaves no spare.
/// `rewrite=True` is the same spare for that collective file. `append` and
/// compression are refused.
/// `write_con_string` serializes the same default bytes without a file.
#[pyfunction]
#[pyo3(signature = (path, frames, precision=None, compression=None, *, canonical=false, comm=None, mode="auto", append=false, n_threads=None, compression_members=None, rewrite=false, keep_spare=true))]
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
    rewrite: bool,
    keep_spare: bool,
) -> PyResult<()> {
    if rewrite && append {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "rewrite replaces one file and does not take append",
        ));
    }
    if append && comm.is_some() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "append is not supported with comm=",
        ));
    }
    let codec = output_codec(path, compression)?;
    if rewrite && !matches!(codec, OutputCodec::Plain) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "rewrite replaces an uncompressed file",
        ));
    }
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
        return write_con_mpi(
            py,
            path,
            &rust_frames,
            precision,
            comm,
            mode,
            rewrite,
            keep_spare,
        );
    }
    if append && !matches!(codec, OutputCodec::Plain) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "append is only supported for an uncompressed file",
        ));
    }
    if let Some(()) = write_stored_list(
        py,
        path,
        frames,
        precision,
        codec,
        canonical,
        append,
        n_threads,
        compression_members,
        rewrite,
        keep_spare,
    )? {
        return Ok(());
    }
    #[cfg(not(feature = "zstd"))]
    if matches!(codec, OutputCodec::Zstd) {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "zstd compression requires readcon built with the zstd feature",
        ));
    }

    match codec {
        OutputCodec::Gzip => {
            if let Some(held) = borrow_unmodified_frames(frames)? {
                let snapshot = held.coords_shared().then(|| held.snapshot(py));
                let owned;
                let refs = if let Some(snapshot) = snapshot.as_ref() {
                    owned = snapshot.slots().iter().flatten().collect();
                    &owned
                } else {
                    owned = held.refs();
                    &owned
                };
                return detach_compressed_frame_refs(
                    py,
                    path,
                    refs,
                    precision,
                    canonical,
                    n_threads,
                    compression_members,
                    true,
                );
            }
            let path_buf = Path::new(path).to_path_buf();
            let owned = owned_frames_from_binding(py, frames)?;
            let slots: Vec<Option<ConFrame>> = owned.into_iter().map(Some).collect();
            py.detach(move || {
                write_owned_compressed(
                    &path_buf,
                    &slots,
                    precision,
                    canonical,
                    n_threads,
                    compression_members,
                    true,
                )
            })
            .map_err(|err| write_err_to_py(py, err))
        }
        OutputCodec::Zstd => {
            #[cfg(feature = "zstd")]
            {
                if let Some(held) = borrow_unmodified_frames(frames)? {
                    let snapshot = held.coords_shared().then(|| held.snapshot(py));
                    let owned;
                    let refs = if let Some(snapshot) = snapshot.as_ref() {
                        owned = snapshot.slots().iter().flatten().collect();
                        &owned
                    } else {
                        owned = held.refs();
                        &owned
                    };
                    return detach_compressed_frame_refs(
                        py,
                        path,
                        refs,
                        precision,
                        canonical,
                        n_threads,
                        compression_members,
                        false,
                    );
                }
                let path_buf = Path::new(path).to_path_buf();
                let owned = owned_frames_from_binding(py, frames)?;
                let slots: Vec<Option<ConFrame>> = owned.into_iter().map(Some).collect();
                py.detach(move || {
                    write_owned_compressed(
                        &path_buf,
                        &slots,
                        precision,
                        canonical,
                        n_threads,
                        compression_members,
                        false,
                    )
                })
                .map_err(|err| write_err_to_py(py, err))
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
                unreachable!("checked above")
            }
        }
        OutputCodec::Plain => {
            let workers = n_threads.unwrap_or(1);
            if rewrite {
                if let Ok(list) = frames.cast::<ConFrameList>()
                    && let Some(result) = with_stored_frames(list, true, |stored| {
                        let refs: Vec<&ConFrame> = stored.iter().map(stored_frame).collect();
                        crate::writer::rewrite_frame_refs_to_path(
                            Path::new(path),
                            &refs,
                            workers,
                            precision,
                            canonical,
                            true,
                            keep_spare,
                        )
                    })
                {
                    return result.map_err(|err| write_err_to_py(py, err));
                }
                let rust_frames = py_frames_to_rust(py, frames)?;
                let refs: Vec<&ConFrame> = rust_frames.iter().collect();
                let flags = RefWrite {
                    rewrite: true,
                    keep_spare,
                    shared: false,
                };
                detach_frame_refs(py, path, &refs, workers, precision, canonical, flags)?;
                return Ok(());
            }
            if !append {
                if let Ok(list) = frames.cast::<ConFrameList>() {
                    let written = with_stored_frames(list, true, |stored| {
                        let refs: Vec<&ConFrame> = stored.iter().map(stored_frame).collect();
                        crate::writer::write_frame_refs_to_path(
                            Path::new(path),
                            &refs,
                            workers,
                            precision,
                            canonical,
                            true,
                        )
                    });
                    if let Some(result) = written {
                        result.map_err(|err| write_err_to_py(py, err))?;
                    } else {
                        // Indexing can move slots into Python objects.
                        // Rebuild owned frames attached, then write detached.
                        let owned = con_frame_list_stored(py, list)?;
                        let refs: Vec<&ConFrame> = owned.iter().collect();
                        let flags = RefWrite {
                            rewrite: false,
                            keep_spare,
                            shared: false,
                        };
                        detach_frame_refs(py, path, &refs, workers, precision, canonical, flags)?;
                    }
                } else if let Some(held) = borrow_unmodified_frames(frames)? {
                    let snapshot = held.coords_shared().then(|| held.snapshot(py));
                    let owned;
                    let refs = if let Some(snapshot) = snapshot.as_ref() {
                        owned = snapshot.slots().iter().flatten().collect();
                        &owned
                    } else {
                        owned = held.refs();
                        &owned
                    };
                    let flags = RefWrite {
                        rewrite: false,
                        keep_spare,
                        shared: false,
                    };
                    detach_frame_refs(py, path, refs, workers, precision, canonical, flags)?;
                } else {
                    let rust_frames = py_frames_to_rust(py, frames)?;
                    let refs: Vec<&ConFrame> = rust_frames.iter().collect();
                    let flags = RefWrite {
                        rewrite: false,
                        keep_spare,
                        shared: false,
                    };
                    detach_frame_refs(py, path, &refs, workers, precision, canonical, flags)?;
                }
                return Ok(());
            }
            if let Some(held) = borrow_unmodified_frames(frames)? {
                let snapshot = held.coords_shared().then(|| held.snapshot(py));
                let owned;
                let refs = if let Some(snapshot) = snapshot.as_ref() {
                    owned = snapshot.slots().iter().flatten().collect();
                    &owned
                } else {
                    owned = held.refs();
                    &owned
                };
                return detach_append_frame_refs(py, path, refs, precision, canonical, false);
            }
            let owned = owned_frames_from_binding(py, frames)?;
            let refs: Vec<&ConFrame> = owned.iter().collect();
            detach_append_frame_refs(py, path, &refs, precision, canonical, false)
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
    rewrite: bool,
    keep_spare: bool,
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
    crate::distrib_write::write_block(
        &c,
        Path::new(path),
        frames,
        mode,
        precision,
        rewrite,
        keep_spare,
    )
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
    _rewrite: bool,
    _keep_spare: bool,
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
    if let Some(text) = write_list_string(py, frames, precision, canonical, start, stop)? {
        return Ok(text);
    }
    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
            None => ConFrameWriter::new(&mut buffer),
        }
        .canonical(canonical);
        for (index, item) in PyIterator::from_object(frames)?.enumerate() {
            if index < start {
                continue;
            }
            if stop.is_some_and(|end| index >= end) {
                break;
            }
            let item = item?;
            let frame = item.cast::<PyConFrame>().map_err(|_| {
                PyTypeError::new_err("frames must be an iterable of readcon.ConFrame objects")
            })?;
            writer = detach_stamped_pyframe(py, writer, &*shared(frame)?)?;
        }
        flush_writer(&mut writer)?;
    }
    String::from_utf8(buffer).map_err(|e| PyIOError::new_err(format!("utf8 error: {e}")))
}

fn write_list_string(
    py: Python<'_>,
    frames: &Bound<'_, PyAny>,
    precision: Option<usize>,
    canonical: bool,
    start: usize,
    stop: Option<usize>,
) -> PyResult<Option<String>> {
    let Ok(list) = frames.cast::<ConFrameList>() else {
        return Ok(None);
    };
    let range = |n: usize| {
        let end = stop.unwrap_or(n).min(n);
        start.min(end)..end
    };
    if let Some(result) = with_stored_frames(list, true, |stored| {
        format_stamped(&stored[range(stored.len())], precision, canonical)
    }) {
        let buffer = result.map_err(|err| write_err_to_py(py, err))?;
        let text = String::from_utf8(buffer)
            .map_err(|err| PyIOError::new_err(format!("utf8 error: {err}")))?;
        return Ok(Some(text));
    }
    let borrowed = list.borrow();
    let mut buffer: Vec<u8> = Vec::new();
    let mut writer = match precision {
        Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
        None => ConFrameWriter::new(&mut buffer),
    }
    .canonical(canonical);
    for index in range(borrowed.len_frames(py)) {
        let written = {
            let slots = borrowed.slots(py);
            let shared = borrowed
                .slab_shared
                .load(std::sync::atomic::Ordering::Acquire);
            slots.get(index).and_then(Option::as_ref).map(|frame| {
                // The parsed column was moved into the slab or the position
                // store. Copy this row when Python can store into that
                // buffer, and also when the column is already empty. A null
                // source would panic.
                let empty = frame.positions.nrows() == 0;
                if (shared || empty)
                    && let Some(ptr) = borrowed.slab_data_ptr(py)
                {
                    let offset = index.saturating_mul(borrowed.n_atoms).saturating_mul(3);
                    let live = crate::types::CoordSnapshot::copy_reading(&[Some(frame)], unsafe {
                        ptr.add(offset)
                    });
                    let view = live.slots()[0].as_ref().unwrap_or(frame);
                    return detach_refs(py, &[view], false, |refs| {
                        write_stamped_frame(&mut writer, refs[0]).map_err(|err| err.to_string())
                    });
                }
                let n = frame.atom_data.len();
                if empty
                    && let Some(store) = lock_attached(py, &borrowed.store).as_ref()
                    && let Some((ptr, len)) = store.get().origin(index)
                    && n.saturating_mul(3) <= len
                {
                    let live = crate::types::CoordSnapshot::copy_reading(&[Some(frame)], ptr);
                    let view = live.slots()[0].as_ref().unwrap_or(frame);
                    return detach_refs(py, &[view], false, |refs| {
                        write_stamped_frame(&mut writer, refs[0]).map_err(|err| err.to_string())
                    });
                }
                detach_refs(py, &[frame], false, |refs| {
                    write_stamped_frame(&mut writer, refs[0]).map_err(|err| err.to_string())
                })
            })
        };
        if let Some(result) = written {
            result.map_err(PyIOError::new_err)?;
            continue;
        }
        let obj = borrowed.frame_obj(py, index)?;
        let view = shared(obj.bind(py))?;
        writer = detach_stamped_pyframe(py, writer, &view)?;
    }
    flush_writer(&mut writer)?;
    drop(writer);
    let text = String::from_utf8(buffer)
        .map_err(|err| PyIOError::new_err(format!("utf8 error: {err}")))?;
    Ok(Some(text))
}

/// Parsed metadata that disagrees with the frame the parser stored.
type MetaEdit = (BTreeMap<String, Value>, Option<String>);

/// `Some` when the Python metadata dict differs from `inner`.
///
/// `set_energy` and the other setters edit that dict and leave the
/// parsed frame alone. A writer that emits `inner` would keep the old
/// value.
fn metadata_edit(
    py: Python<'_>,
    frame: &PyConFrame,
    inner: &ConFrame,
) -> PyResult<Option<MetaEdit>> {
    let Some(dict) = frame.metadata.get(py) else {
        return Ok(None);
    };
    let (meta, minor_raw) = py_metadata_to_json_map_with_minor(dict.bind(py).as_any())?;
    if minor_raw.as_deref() == inner.header.metadata.huge_minor_raw() {
        let mut stored = inner.header.metadata.to_map();
        stored.remove(meta::CON_SPEC_VERSION);
        stored.remove(meta::SECTIONS);
        if stored == meta {
            return Ok(None);
        }
    }
    Ok(Some((meta, minor_raw)))
}

fn install_metadata(frame: &mut ConFrame, meta: BTreeMap<String, Value>, minor_raw: Option<&str>) {
    frame.header.metadata = crate::types::FrameMeta::from_map_with_minor_raw(meta, minor_raw);
}

fn detach_stamped_pyframe<W>(
    py: Python<'_>,
    mut writer: ConFrameWriter<W>,
    frame: &PyConFrame,
) -> PyResult<ConFrameWriter<W>>
where
    W: std::io::Write + Send,
{
    if !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
        && let Some(inner) = frame.inner.as_ref()
    {
        let snapshot = frame.coords_shared().then(|| snapshot_pyframe(py, frame));
        if let Some((meta, minor_raw)) = metadata_edit(py, frame, inner)? {
            let mut owned = snapshot
                .as_ref()
                .and_then(|snapshot| snapshot.slots()[0].as_ref())
                .unwrap_or(inner)
                .clone();
            install_metadata(&mut owned, meta, minor_raw.as_deref());
            return detach_refs(py, &[&owned], false, move |refs| {
                write_stamped_frame(&mut writer, refs[0]).map_err(|err| err.to_string())?;
                Ok::<_, String>(writer)
            })
            .map_err(PyIOError::new_err);
        }
        let inner_ref = if let Some(snapshot) = snapshot.as_ref() {
            snapshot.slots()[0].as_ref().unwrap_or(inner)
        } else {
            inner
        };
        return detach_refs(py, &[inner_ref], false, move |refs| {
            write_stamped_frame(&mut writer, refs[0]).map_err(|err| err.to_string())?;
            Ok::<_, String>(writer)
        })
        .map_err(PyIOError::new_err);
    }
    let owned = frame.to_con_frame(py)?;
    py.detach(move || {
        write_stamped_frame(&mut writer, &owned).map_err(|err| err.to_string())?;
        Ok::<_, String>(writer)
    })
    .map_err(PyIOError::new_err)
}

/// Read a .con file and return a list of ASE Atoms objects.
/// Requires the ase package.
#[pyfunction]
fn read_con_as_ase(py: Python<'_>, path: &str) -> PyResult<Vec<Py<PyAny>>> {
    // File IO and the parse run inside `read_con`'s detach. ASE `Atoms`
    // are Python objects, so they are built after the GIL is back. The
    // per-atom scaling that feeds them runs detached in `ase_from_pyconframe`.
    let frames = read_con(py, path, None, None, "auto", None)?;
    let list = frames.borrow(py);
    let n = list.len_frames(py);
    let mut out = Vec::with_capacity(n);
    for index in 0..n {
        let frame = list.frame_obj(py, index)?;
        let view = shared(frame.bind(py))?;
        out.push(ase_from_pyconframe(py, &view)?);
    }
    Ok(out)
}

struct BorrowedFrames<'py> {
    held: Vec<Shared<'py, PyConFrame>>,
    /// Parsed frames with the live metadata dict copied on. Empty when
    /// no frame's metadata was edited, so `refs` borrows `inner`.
    owned: Vec<ConFrame>,
}

impl<'py> BorrowedFrames<'py> {
    fn refs(&self) -> Vec<&ConFrame> {
        if !self.owned.is_empty() {
            return self.owned.iter().collect();
        }
        self.held
            .iter()
            .map(|frame| frame.inner.as_ref().expect("unmodified frame"))
            .collect()
    }

    fn coords_shared(&self) -> bool {
        self.held.iter().any(|frame| frame.coords_shared())
    }

    /// Coordinates a later write copies. A store into `xyz` or the read
    /// slab is in the NumPy array, not in the positions column.
    fn snapshot<'a>(&'a self, py: Python<'_>) -> crate::types::CoordSnapshot<'a> {
        let refs: Vec<Option<&ConFrame>> = if self.owned.is_empty() {
            self.held.iter().map(|frame| frame.inner.as_ref()).collect()
        } else {
            self.owned.iter().map(Some).collect()
        };
        if !self.coords_shared() {
            return crate::types::CoordSnapshot::copy_of(&refs);
        }
        let mut buf = Vec::new();
        for frame in &self.held {
            let Some(inner) = frame.inner.as_ref() else {
                continue;
            };
            for index in 0..inner.atom_data.len() {
                buf.extend_from_slice(&frame.coord_at(py, inner, index));
            }
        }
        let source = if buf.is_empty() {
            std::ptr::null()
        } else {
            buf.as_ptr()
        };
        crate::types::CoordSnapshot::copy_reading(&refs, source)
    }
}

/// Pointer of this frame's live NumPy coordinates, or `None`.
fn frame_numpy_origin(py: Python<'_>, frame: &PyConFrame) -> Option<*const f64> {
    let need = frame.n_atoms.saturating_mul(3);
    if let Some(owned) = &frame.xyz_owned {
        let (ptr, len) = numpy_f64_ptr(owned.bind(py))?;
        return (need <= len).then_some(ptr);
    }
    if let Some(slab) = &frame.slab {
        let (ptr, len) = numpy_f64_ptr(slab.bind(py))?;
        let at = frame.slab_index.saturating_mul(need);
        if at.saturating_add(need) <= len {
            return Some(unsafe { ptr.add(at) });
        }
    }
    if let Some(store) = &frame.store
        && let Some((ptr, len)) = store.get().origin(frame.slab_index)
        && need <= len
    {
        return Some(ptr);
    }
    None
}

/// One unmodified frame, read from its NumPy coordinates when it has them.
///
/// One relaxed copy into the private column. `to_ase`, `reorder_like`, and
/// `minimum_image_displacements` are the callers that need that copy.
fn snapshot_pyframe<'a>(py: Python<'_>, frame: &'a PyConFrame) -> crate::types::CoordSnapshot<'a> {
    let inner = frame.inner.as_ref();
    let refs = [inner];
    if let Some(ptr) = frame_numpy_origin(py, frame) {
        return crate::types::CoordSnapshot::copy_reading(&refs, ptr);
    }
    crate::types::CoordSnapshot::copy_of(&refs)
}

/// Parsed frames without structural sequence edits can be borrowed directly.
fn borrow_unmodified_frames<'py>(
    frames: &'py Bound<'_, PyAny>,
) -> PyResult<Option<BorrowedFrames<'py>>> {
    let py = frames.py();
    let mut held = Vec::new();
    let mut edits = Vec::new();
    for item in PyIterator::from_object(frames)? {
        let item = item?;
        let Ok(frame) = item.cast::<PyConFrame>() else {
            return Ok(None);
        };
        let frame = shared(frame)?;
        if frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire) || frame.inner.is_none() {
            return Ok(None);
        }
        let inner = frame.inner.as_ref().expect("unmodified frame");
        edits.push(metadata_edit(py, &frame, inner)?);
        held.push(frame);
    }
    if held.is_empty() {
        return Ok(None);
    }
    let owned = if edits.iter().any(Option::is_some) {
        held.iter()
            .zip(edits)
            .map(|(frame, edit)| {
                let inner = frame.inner.as_ref().expect("unmodified frame");
                let mut owned = inner.clone();
                if let Some((meta, minor_raw)) = edit {
                    install_metadata(&mut owned, meta, minor_raw.as_deref());
                }
                owned
            })
            .collect()
    } else {
        Vec::new()
    };
    #[cfg(any(test, feature = "borrow-path-counts"))]
    BORROW_LIST_HITS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    Ok(Some(BorrowedFrames { held, owned }))
}

#[cfg(any(test, feature = "borrow-path-counts"))]
static BORROW_FRAME_HITS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
#[cfg(any(test, feature = "borrow-path-counts"))]
static BORROW_LIST_HITS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// How many times the unmodified-frame writer borrowed a stored frame.
///
/// The first count is ``write_python_frame`` writing ``inner`` while atoms
/// are not built. The second is ``borrow_unmodified_frames`` handing the
/// stored frames to the path writer. Tests use the pair to see that those
/// branches ran.
#[cfg(any(test, feature = "borrow-path-counts"))]
#[pyfunction]
fn borrow_path_counts() -> (u64, u64) {
    (
        BORROW_FRAME_HITS.load(std::sync::atomic::Ordering::Relaxed),
        BORROW_LIST_HITS.load(std::sync::atomic::Ordering::Relaxed),
    )
}

fn py_frames_to_rust(py: Python<'_>, frames: &Bound<'_, PyAny>) -> PyResult<Vec<ConFrame>> {
    let iterator = PyIterator::from_object(frames)?;
    let mut rust_frames = Vec::new();
    for item in iterator {
        let item = item?;
        let frame = item.cast::<PyConFrame>().map_err(|_| {
            PyTypeError::new_err("frames must be an iterable of readcon.ConFrame objects")
        })?;
        rust_frames.push(shared(frame)?.to_con_frame(py)?);
    }
    Ok(rust_frames)
}

fn owned_frames_from_binding(py: Python<'_>, frames: &Bound<'_, PyAny>) -> PyResult<Vec<ConFrame>> {
    if let Ok(list) = frames.cast::<ConFrameList>() {
        return con_frame_list_stored(py, list);
    }
    py_frames_to_rust(py, frames)
}

// --- ASE conversion helpers (runtime import, no compile-time dep) ---

struct AseColumns {
    symbols: Vec<String>,
    positions: Vec<[f64; 3]>,
    atom_ids: Vec<u64>,
    masses: Option<Vec<f64>>,
    velocities: Option<Vec<[f64; 3]>>,
    forces: Option<Vec<[f64; 3]>>,
    fixed_indices: Vec<usize>,
    partial_fixed: Vec<(usize, [bool; 3])>,
}

fn ase_columns_from_atoms(
    atoms: &[PyAtomDatum],
    length_scale: f64,
    mass_scale: f64,
    velocity_scale: f64,
    force_scale: f64,
) -> AseColumns {
    let n = atoms.len();
    let mut symbols = Vec::with_capacity(n);
    let mut positions = Vec::with_capacity(n);
    let mut atom_ids = Vec::with_capacity(n);
    let mut fixed_indices = Vec::new();
    let mut partial_fixed = Vec::new();
    let want_mass = atoms.iter().any(|atom| atom.mass.is_some());
    let want_vel = atoms.iter().any(PyAtomDatum::has_velocity);
    let want_force = atoms.iter().any(PyAtomDatum::has_forces);
    let mut masses = want_mass.then(|| Vec::with_capacity(n));
    let mut velocities = want_vel.then(|| Vec::with_capacity(n));
    let mut forces = want_force.then(|| Vec::with_capacity(n));
    for (index, atom) in atoms.iter().enumerate() {
        symbols.push(atom.symbol.clone());
        positions.push([
            atom.x * length_scale,
            atom.y * length_scale,
            atom.z * length_scale,
        ]);
        atom_ids.push(atom.atom_id);
        if let Some(dest) = masses.as_mut() {
            dest.push(atom.mass.unwrap_or(0.0) * mass_scale);
        }
        if atom.fixed == [true, true, true] {
            fixed_indices.push(index);
        } else if atom.is_fixed() {
            partial_fixed.push((index, atom.fixed));
        }
        if let Some(dest) = velocities.as_mut() {
            dest.push([
                atom.vx.unwrap_or(0.0) * velocity_scale,
                atom.vy.unwrap_or(0.0) * velocity_scale,
                atom.vz.unwrap_or(0.0) * velocity_scale,
            ]);
        }
        if let Some(dest) = forces.as_mut() {
            dest.push([
                atom.fx.unwrap_or(0.0) * force_scale,
                atom.fy.unwrap_or(0.0) * force_scale,
                atom.fz.unwrap_or(0.0) * force_scale,
            ]);
        }
    }
    AseColumns {
        symbols,
        positions,
        atom_ids,
        masses,
        velocities,
        forces,
        fixed_indices,
        partial_fixed,
    }
}

fn ase_columns_from_frame(
    frame: &ConFrame,
    length_scale: f64,
    mass_scale: f64,
    velocity_scale: f64,
    force_scale: f64,
) -> AseColumns {
    let n = frame.atom_data.len();
    let mut per_atom_mass = Vec::with_capacity(n);
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
    let mut symbols = Vec::with_capacity(n);
    let mut positions = Vec::with_capacity(n);
    let mut atom_ids = Vec::with_capacity(n);
    let mut masses = Vec::with_capacity(n);
    let mut fixed_indices = Vec::new();
    let mut partial_fixed = Vec::new();
    let want_vel = frame.has_velocities();
    let want_force = frame.has_forces();
    let mut velocities = want_vel.then(|| Vec::with_capacity(n));
    let mut forces = want_force.then(|| Vec::with_capacity(n));
    for (index, atom) in frame.atom_data.iter().enumerate() {
        symbols.push(atom.symbol.to_string());
        let xyz = frame.xyz_at(index);
        positions.push([
            xyz[0] * length_scale,
            xyz[1] * length_scale,
            xyz[2] * length_scale,
        ]);
        atom_ids.push(atom.atom_id);
        masses.push(per_atom_mass.get(index).copied().unwrap_or(0.0) * mass_scale);
        let fixed = atom.fixed();
        if fixed == [true, true, true] {
            fixed_indices.push(index);
        } else if fixed[0] || fixed[1] || fixed[2] {
            partial_fixed.push((index, fixed));
        }
        if let Some(dest) = velocities.as_mut() {
            let value = atom.velocity().unwrap_or([0.0; 3]);
            dest.push([
                value[0] * velocity_scale,
                value[1] * velocity_scale,
                value[2] * velocity_scale,
            ]);
        }
        if let Some(dest) = forces.as_mut() {
            let value = atom.force().unwrap_or([0.0; 3]);
            dest.push([
                value[0] * force_scale,
                value[1] * force_scale,
                value[2] * force_scale,
            ]);
        }
    }
    AseColumns {
        symbols,
        positions,
        atom_ids,
        masses: Some(masses),
        velocities,
        forces,
        fixed_indices,
        partial_fixed,
    }
}

fn ase_from_pyconframe(py: Python<'_>, frame: &PyConFrame) -> PyResult<Py<PyAny>> {
    let ase = py.import("ase")?;
    let ase_atoms_cls = ase.getattr("Atoms")?;
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
    let force_scale = energy_scale / length_scale;
    let velocity_scale = |have_velocities: bool| -> PyResult<f64> {
        if !have_velocities {
            return Ok(0.0);
        }
        let time_unit = crate::units::velocity_file_time_unit(
            frame.spec_version,
            &metadata.clone().into_iter().collect(),
            None,
        )
        .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(length_scale
            * crate::units::velocity_scale_to_natural(&time_unit)
                .map_err(|error| PyValueError::new_err(error.to_string()))?)
    };
    let columns = if !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
        && let Some(inner) = frame.inner.as_ref()
    {
        let velocity_scale = velocity_scale(inner.has_velocities())?;
        // `xyz` and the slab are the live coordinates. The positions
        // column still holds the values from the read.
        if frame.coords_shared() {
            let snapshot = snapshot_pyframe(py, frame);
            let view = snapshot.slots()[0].as_ref().unwrap_or(inner);
            detach_refs(py, &[view], false, move |refs| {
                ase_columns_from_frame(
                    refs[0],
                    length_scale,
                    mass_scale,
                    velocity_scale,
                    force_scale,
                )
            })
        } else {
            detach_refs(py, &[inner], false, move |refs| {
                ase_columns_from_frame(
                    refs[0],
                    length_scale,
                    mass_scale,
                    velocity_scale,
                    force_scale,
                )
            })
        }
    } else {
        let frame_atoms = frame.py_atoms(py)?;
        let velocity_scale = velocity_scale(frame_atoms.iter().any(PyAtomDatum::has_velocity))?;
        py.detach(move || {
            ase_columns_from_atoms(
                &frame_atoms,
                length_scale,
                mass_scale,
                velocity_scale,
                force_scale,
            )
        })
    };

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
                ("symbols", columns.symbols.into_pyobject(py)?.into_any()),
                ("positions", columns.positions.into_pyobject(py)?.into_any()),
                ("cell", cell.into_any()),
                ("pbc", pbc.into_pyobject(py)?.into_any()),
            ]
            .into_py_dict(py)?,
        ),
    )?;

    let np = py.import("numpy")?;

    // Store atom_id as a custom per-atom array (not tags, which may be in use)
    let atom_id_array = np.call_method1("array", (columns.atom_ids,))?;
    atoms.call_method1("set_array", ("atom_id", atom_id_array))?;

    // Set masses if present (overrides ASE's atomic-number defaults)
    if let Some(masses) = columns.masses {
        let mass_array = np.call_method1("array", (masses,))?;
        atoms.call_method1("set_masses", (mass_array,))?;
    }

    // Set velocities if present. ASE stores the natural time unit (D10).
    if let Some(velocities) = columns.velocities {
        let vel_array = np.call_method1("array", (velocities,))?;
        atoms.call_method1("set_velocities", (vel_array,))?;
    }

    // A stored energy is useful even when the frame has no force section.
    let energy = frame
        .metadata_get_f64(py, meta::ENERGY)?
        .map(|value| value * energy_scale);
    if columns.forces.is_some() || energy.is_some() {
        let ase_calc = py.import("ase.calculators.singlepoint")?;
        let kwargs = [("atoms", atoms.clone().into_any())].into_py_dict(py)?;
        if let Some(forces) = columns.forces {
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
    let fixed_indices = columns.fixed_indices;
    let partial_fixed = columns.partial_fixed;

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
    crate::types::check_lattice_finite(&rows).map_err(|err| cell_err_to_py(py, &err))?;
    let (lengths, raw_angles) = crate::types::lengths_and_angles(rows);
    crate::types::check_cell_finite(&lengths, "cell", &[90.0; 3], "angles")
        .map_err(|err| cell_err_to_py(py, &err))?;
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
    let snaps: Vec<AtomSnap> = atoms.iter().map(snap_from_datum).collect();
    let meta = py_metadata_to_json_map(metadata.as_any())?;
    let inner = frame_for_storage(
        cell,
        angles,
        &Default::default(),
        &Default::default(),
        meta,
        &snaps,
    )?;
    Ok(PyConFrame {
        cell,
        angles,
        prebox_header: Default::default(),
        postbox_header: Default::default(),
        atoms: py_atoms_to_list(
            py,
            &snaps_from_frame(&inner)
                .iter()
                .map(datum_from_snap)
                .collect::<Vec<_>>(),
        )?,
        atoms_ready: std::sync::atomic::AtomicBool::new(true),
        atoms_fills: std::sync::atomic::AtomicUsize::new(0),
        atoms_init: std::sync::Mutex::new(()),
        spec_version: crate::CON_SPEC_VERSION,
        metadata: filled_lock(py, metadata.unbind()),
        inner: Some(inner),
        n_atoms: snaps.len(),
        slab: None,
        slab_index: 0,
        store: None,
        columns: pyo3::sync::PyOnceLock::new(),
        xyz_owned: None,
        source_text: None,
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
#[pyo3(signature = (con_path, out_path, binary32=false, n_threads=1))]
fn write_conbin(
    py: Python<'_>,
    con_path: &str,
    out_path: &str,
    binary32: bool,
    n_threads: usize,
) -> PyResult<(u64, u64)> {
    let con_path = con_path.to_owned();
    let out_path = out_path.to_owned();
    let header = py
        .detach(|| {
            crate::conbin::write_from_con_with_threads(
                Path::new(&con_path),
                Path::new(&out_path),
                binary32,
                n_threads,
            )
        })
        .map_err(|err| {
            if err.is_non_finite_cell() {
                Python::attach(|py| cell_err_to_py(py, &err))
            } else {
                PyIOError::new_err(err.to_string())
            }
        })?;
    Ok((header.n_frames, header.n_atoms))
}

/// Write a version-2 CON-bin from arrays already in memory.
///
/// `fixed` is `(frames, atoms, 3)` with a non-zero entry meaning that axis
/// is constrained. Atom ids are the index within the frame. On little-endian
/// Numeric payload columns are snapshotted into a private buffer with
/// relaxed atomic loads. Concurrent mutation during the call can therefore
/// produce a file that mixes versions across elements, but each element is
/// copied untorn before it is formatted.
#[pyfunction]
#[pyo3(signature = (path, positions, velocities, masses, cell, fixed))]
fn write_conbin_columns(
    py: Python<'_>,
    path: &str,
    positions: PyReadonlyArray3<'_, f64>,
    velocities: PyReadonlyArray3<'_, f64>,
    masses: PyReadonlyArray2<'_, f64>,
    cell: PyReadonlyArray2<'_, f64>,
    fixed: PyReadonlyArray3<'_, f64>,
) -> PyResult<()> {
    let shape = positions.dims();
    let n_frames = shape[0] as u64;
    let n_atoms = shape[1] as u64;
    let n = (n_frames as usize)
        .checked_mul(n_atoms as usize)
        .ok_or_else(|| PyValueError::new_err("CON-bin column length overflows"))?;
    let xyz = n
        .checked_mul(3)
        .ok_or_else(|| PyValueError::new_err("CON-bin column length overflows"))?;
    let atoms = n_atoms as usize;
    if shape[2] != 3
        || positions.len() != xyz
        || velocities.len() != xyz
        || masses.len() != n
        || cell.len() != (n_frames as usize).saturating_mul(6)
        || fixed.len() != xyz
    {
        return Err(PyValueError::new_err("CON-bin columns disagree"));
    }
    let cell_owned =
        SharedColumn::from_array(cell.as_any(), "cell", 6, (n_frames as usize) * 6)?.snapshot(py);
    check_cell_array(py, &cell_owned)?;
    let columns = [
        SharedColumn::from_array(positions.as_any(), "positions", atoms * 3, xyz)?,
        SharedColumn::from_array(velocities.as_any(), "velocities", atoms * 3, xyz)?,
        SharedColumn::from_array(masses.as_any(), "masses", atoms, n)?,
        SharedColumn {
            ptr: cell_owned.as_ptr(),
            len: cell_owned.len(),
            per_frame: 6,
        },
    ];
    let fixed_column = SharedColumn::from_array(fixed.as_any(), "fixed", atoms * 3, xyz)?;
    // One buffer for the masks and one for the ids. The loops only store
    // bytes; they do not allocate per atom.
    let mut masks = vec![0u8; n];
    let mut staged_flags = Vec::new();
    let mut flag_start = 0;
    while flag_start < xyz {
        let flag_end = (flag_start + STAGE_VALUES - STAGE_VALUES % 3).min(xyz);
        fixed_column.stage_values(py, flag_start..flag_end, &mut staged_flags);
        for (offset, flag) in staged_flags.chunks_exact(3).enumerate() {
            let index = flag_start / 3 + offset;
            masks[index] = u8::from(flag[0] != 0.0)
                | (u8::from(flag[1] != 0.0) << 1)
                | (u8::from(flag[2] != 0.0) << 2);
        }
        flag_start = flag_end;
    }
    let mut ids = vec![0u64; n];
    if atoms > 0 {
        for chunk in ids.chunks_mut(atoms) {
            for (atom, slot) in chunk.iter_mut().enumerate() {
                *slot = atom as u64;
            }
        }
    }
    let lengths = (
        columns[0].len,
        columns[1].len,
        columns[2].len,
        columns[3].len,
    );
    let path_owned = path.to_owned();
    py.detach(move || {
        let _cell_owned = cell_owned;
        let mut staged = Vec::new();
        let (run, emit) = (
            STAGE_VALUES,
            move |column: usize, values: std::ops::Range<usize>, file: &mut std::fs::File| {
                Python::attach(|py| columns[column].stage_values(py, values, &mut staged));
                #[cfg(all(unix, target_endian = "little"))]
                unsafe {
                    crate::conbin::write_f64_raw(file, staged.as_ptr(), staged.len())
                }
                #[cfg(not(all(unix, target_endian = "little")))]
                {
                    crate::conbin::write_f64_le(file, &staged)
                }
            },
        );
        crate::conbin::write_f64_columns_staged(
            Path::new(&path_owned),
            n_frames,
            n_atoms,
            lengths.0,
            Some(lengths.1),
            Some(lengths.2),
            Some(lengths.3),
            Some(&ids),
            Some(&masks),
            run,
            emit,
        )
        .map(|_| ())
        .map_err(|err| PyIOError::new_err(err.to_string()))
    })
}

/// Read every column a version-2 CON-bin stored, as views of the map.
#[pyfunction]
#[pyo3(signature = (path, n_threads=1))]
fn read_conbin_columns(py: Python<'_>, path: &str, n_threads: usize) -> PyResult<Py<PyDict>> {
    let path_owned = path.to_owned();
    let mapped = py
        .detach(|| crate::conbin::map_file(Path::new(&path_owned), n_threads))
        .map_err(|e| PyIOError::new_err(e.to_string()))?;
    if mapped.header.binary32 {
        return Err(PyValueError::new_err("CON-bin file is binary32"));
    }
    let n_frames = mapped.header.n_frames as usize;
    let n_atoms = mapped.header.n_atoms as usize;
    let width = n_atoms * 3;
    let ptr = |slice: &[f64]| slice.as_ptr() as usize;
    let pos = mapped
        .positions_f64()
        .map_err(|e| PyIOError::new_err(e.to_string()))?;
    let pos_ptr = ptr(pos);
    let pos_len = pos.len();
    let vel_ptr = if mapped.header.velocities {
        let vel = mapped
            .velocities_f64()
            .map_err(|e| PyIOError::new_err(e.to_string()))?;
        Some((ptr(vel), vel.len()))
    } else {
        None
    };
    let mass_ptr = match mapped
        .masses_f64()
        .map_err(|e| PyIOError::new_err(e.to_string()))?
    {
        Some(mass) => Some((ptr(mass), mass.len())),
        None => None,
    };
    let cell_ptr = match mapped.cell_f64().map_err(|e| cell_err_to_py(py, &e))? {
        Some(cell) => Some((ptr(cell), cell.len())),
        None => None,
    };
    let id_ptr = match mapped
        .atom_ids()
        .map_err(|e| PyIOError::new_err(e.to_string()))?
    {
        Some(ids) => Some((ids.as_ptr() as usize, ids.len())),
        None => None,
    };
    let mask_ptr = match mapped
        .fixed_masks()
        .map_err(|e| PyIOError::new_err(e.to_string()))?
    {
        Some(masks) => Some((masks.as_ptr() as usize, masks.len())),
        None => None,
    };
    let owner = Py::new(py, ConBinMapping { map: mapped.map })?;
    let base = owner.bind(py).clone();
    let dict = PyDict::new(py);
    dict.set_item("n_atoms", n_atoms)?;
    dict.set_item("n_frames", n_frames)?;
    dict.set_item(
        "positions",
        view_f64_ptr(
            py,
            base.clone().into_any(),
            pos_ptr,
            pos_len,
            (n_frames, width),
        )?,
    )?;
    if let Some((ptr, len)) = vel_ptr {
        dict.set_item(
            "velocities",
            view_f64_ptr(py, base.clone().into_any(), ptr, len, (n_frames, width))?,
        )?;
    }
    if let Some((ptr, len)) = mass_ptr {
        dict.set_item(
            "masses",
            view_f64_ptr(py, base.clone().into_any(), ptr, len, (n_frames, n_atoms))?,
        )?;
    }
    if let Some((ptr, len)) = cell_ptr {
        dict.set_item(
            "cell",
            view_f64_ptr(py, base.clone().into_any(), ptr, len, (n_frames, 6))?,
        )?;
    }
    if let Some((ptr, len)) = id_ptr {
        dict.set_item(
            "atom_ids",
            view_u64_ptr(py, base.clone().into_any(), ptr, len)?,
        )?;
    }
    if let Some((ptr, len)) = mask_ptr {
        dict.set_item("fixed_mask", view_u8_ptr(py, base.into_any(), ptr, len)?)?;
    }
    let _ = owner;
    Ok(dict.unbind())
}

fn view_f64_ptr<'py>(
    _py: Python<'py>,
    base: Bound<'py, PyAny>,
    ptr: usize,
    len: usize,
    shape: (usize, usize),
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    if shape.0.saturating_mul(shape.1) != len {
        return Err(PyValueError::new_err("CON-bin view shape"));
    }
    let view = unsafe { ArrayView2::from_shape_ptr(shape, ptr as *const f64) };
    Ok(unsafe { PyArray2::borrow_from_array(&view, base) })
}

fn view_u64_ptr<'py>(
    _py: Python<'py>,
    base: Bound<'py, PyAny>,
    ptr: usize,
    n: usize,
) -> PyResult<Bound<'py, PyArray1<u64>>> {
    let view = unsafe { ArrayView1::from_shape_ptr(n, ptr as *const u64) };
    Ok(unsafe { PyArray1::borrow_from_array(&view, base) })
}

fn view_u8_ptr<'py>(
    _py: Python<'py>,
    base: Bound<'py, PyAny>,
    ptr: usize,
    n: usize,
) -> PyResult<Bound<'py, PyArray1<u8>>> {
    let view = unsafe { ArrayView1::from_shape_ptr(n, ptr as *const u8) };
    Ok(unsafe { PyArray1::borrow_from_array(&view, base) })
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
    reference: &Bound<'_, PyConFrame>,
    other: &Bound<'_, PyConFrame>,
    strict: bool,
) -> PyResult<Vec<usize>> {
    let reference_guard = shared(reference)?;
    let reference: &PyConFrame = &reference_guard;
    let other_guard = shared(other)?;
    let other: &PyConFrame = &other_guard;
    let reference = frame_for_compute(py, reference)?;
    let other = frame_for_compute(py, other)?;
    let check = identity_check(strict);
    let reference_addr = reference.as_ref() as *const ConFrame as usize;
    let other_addr = other.as_ref() as *const ConFrame as usize;
    py.detach(move || {
        let reference = unsafe { &*(reference_addr as *const ConFrame) };
        let other = unsafe { &*(other_addr as *const ConFrame) };
        crate::correspondence::atom_id_permutation(reference, other, check)
    })
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
    reference: &Bound<'_, PyConFrame>,
    other: &Bound<'_, PyConFrame>,
    strict: bool,
) -> PyResult<PyConFrame> {
    let reference_guard = shared(reference)?;
    let reference: &PyConFrame = &reference_guard;
    let other_guard = shared(other)?;
    let other: &PyConFrame = &other_guard;
    let reference_live = live_coord_snapshot(py, reference);
    let other_live = live_coord_snapshot(py, other);
    let reference_frame = frame_or_live(py, reference, reference_live.as_ref())?;
    let other_frame = frame_or_live(py, other, other_live.as_ref())?;
    let check = identity_check(strict);
    let pair = [reference_frame.as_ref(), other_frame.as_ref()];
    let frame = detach_refs(py, &pair, false, move |pair| {
        let (reference, other) = (pair[0], pair[1]);
        crate::correspondence::reorder_like(reference, other, check)
    })
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
    let check = identity_check(strict);
    // Ids, symbols, masses and fixed masks only. No coordinate is read, so
    // the walk can stay detached while Python holds the slab.
    if let Ok(list) = frames.cast::<ConFrameList>()
        && let Some(result) = with_stored_frames(list, false, move |stored| {
            let refs: Vec<&ConFrame> = stored.iter().map(stored_frame).collect();
            crate::correspondence::check_atom_id_consistency_refs(&refs, check)
        })
    {
        return result.map_err(correspondence_to_py);
    }
    if let Ok(seq) = shared_frames(frames) {
        let borrowed = seq.iter().all(|frame| {
            !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire) && frame.inner.is_some()
        });
        if borrowed {
            let addrs: Vec<usize> = seq
                .iter()
                .map(|frame| frame.inner.as_ref().expect("inner") as *const ConFrame as usize)
                .collect();
            return py
                .detach(move || {
                    let refs: Vec<&ConFrame> = addrs
                        .iter()
                        .map(|addr| unsafe { &*(*addr as *const ConFrame) })
                        .collect();
                    crate::correspondence::check_atom_id_consistency_refs(&refs, check)
                })
                .map_err(correspondence_to_py);
        }
        let rust_frames = seq
            .iter()
            .map(|frame| frame.to_con_frame(py))
            .collect::<PyResult<Vec<_>>>()?;
        return py
            .detach(move || crate::correspondence::check_atom_id_consistency(&rust_frames, check))
            .map_err(correspondence_to_py);
    }
    let rust_frames = py_frames_to_con(py, frames)?;
    py.detach(move || crate::correspondence::check_atom_id_consistency(&rust_frames, check))
        .map_err(correspondence_to_py)
}

/// Snapshot of `frame` when its coordinates live in NumPy and the atom
/// list has not been built. `None` when the positions column is current.
fn live_coord_snapshot<'a>(
    py: Python<'_>,
    frame: &'a PyConFrame,
) -> Option<crate::types::CoordSnapshot<'a>> {
    if frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
        || frame.inner.is_none()
        || !frame.coords_shared()
    {
        return None;
    }
    Some(snapshot_pyframe(py, frame))
}

fn frame_or_live<'a, 'b>(
    py: Python<'_>,
    frame: &'a PyConFrame,
    live: Option<&'b crate::types::CoordSnapshot<'a>>,
) -> PyResult<std::borrow::Cow<'b, ConFrame>>
where
    'a: 'b,
{
    if let Some(view) = live.and_then(|snapshot| snapshot.slots()[0].as_ref()) {
        return Ok(std::borrow::Cow::Borrowed(view));
    }
    frame_for_compute(py, frame)
}

fn frame_for_compute<'a>(
    py: Python<'_>,
    frame: &'a PyConFrame,
) -> PyResult<std::borrow::Cow<'a, ConFrame>> {
    if !frame.atoms_ready.load(std::sync::atomic::Ordering::Acquire)
        && let Some(inner) = frame.inner.as_ref()
    {
        return Ok(std::borrow::Cow::Borrowed(inner));
    }
    Ok(std::borrow::Cow::Owned(frame.to_con_frame(py)?))
}

/// Minimum-image displacement of each reference atom toward the atom in
/// `other` with the same `atom_id`. Shape `(N, 3)`, reference order.
///
/// The cell and the periodic flags are the reference frame's.
#[pyfunction]
#[pyo3(signature = (reference, other, *, strict=true))]
fn minimum_image_displacements<'py>(
    py: Python<'py>,
    reference: &Bound<'_, PyConFrame>,
    other: &Bound<'_, PyConFrame>,
    strict: bool,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let reference_guard = shared(reference)?;
    let reference: &PyConFrame = &reference_guard;
    let other_guard = shared(other)?;
    let other: &PyConFrame = &other_guard;
    let reference_live = live_coord_snapshot(py, reference);
    let other_live = live_coord_snapshot(py, other);
    let reference_frame = frame_or_live(py, reference, reference_live.as_ref())?;
    let other_frame = frame_or_live(py, other, other_live.as_ref())?;
    let check = identity_check(strict);
    let pair = [reference_frame.as_ref(), other_frame.as_ref()];
    let rows = detach_refs(py, &pair, false, move |pair| {
        let (reference, other) = (pair[0], pair[1]);
        crate::correspondence::minimum_image_displacements(reference, other, check)
    })
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

/// [`parse_err_to_py`] for an error found while reading frame `frame_index`.
/// A non-finite cell error that does not name a frame names this one.
fn parse_err_in_frame(py: Python<'_>, err: &ParseError, line: u32, frame_index: u64) -> PyErr {
    parse_err_to_py(py, &err.clone().in_frame(frame_index), line, frame_index)
}

fn utf8_failure(err: &ParseError) -> bool {
    matches!(err, ParseError::ValidationError(msg) if msg.contains("invalid UTF-8"))
}

fn located_to_py(err: crate::error::LocatedParseError) -> PyErr {
    Python::attach(|py| parse_err_to_py(py, &err.error, err.line, err.frame_index))
}

/// The typed Python error for a non-finite cell error found outside a parse.
///
/// `frame_index` carries the frame the error names, else 0.
fn cell_err_to_py(py: Python<'_>, err: &ParseError) -> PyErr {
    parse_err_to_py(py, err, 0, err.named_frame().unwrap_or(0))
}

/// Refuse a `(frames, 6)` cell array that holds a NaN or an infinity.
fn check_cell_array(py: Python<'_>, cell: &[f64]) -> PyResult<()> {
    crate::types::check_cell_rows(cell).map_err(|err| cell_err_to_py(py, &err))
}

/// Map the `String` error of an extended-XYZ or PDB scan or write.
///
/// A non-finite cell comes back as `NonFiniteValue`; any other message is a
/// `ValueError`, as before.
fn scan_err_to_py(message: String) -> PyErr {
    match ParseError::from_cell_text(&message) {
        Some(err) => Python::attach(|py| cell_err_to_py(py, &err)),
        None => PyValueError::new_err(message),
    }
}

/// Preserve a scanner's typed parse errors at the Python boundary.
fn convert_err_to_py(err: crate::error::ConvertError) -> PyErr {
    match err {
        crate::error::ConvertError::Parse(err) => Python::attach(|py| cell_err_to_py(py, &err)),
        crate::error::ConvertError::Message(message) => PyValueError::new_err(message),
    }
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

    fn later_frame_path() -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("later.con");
        let good = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        let bad = "seed\n{\"con_spec_version\":2}\n10 10 10\n90 90 90\n0 0\n0 0 0\n1\n-1\n1.0\nH\nCoordinates of Component 1\n0 0 0 0 0\n";
        std::fs::write(&path, format!("{good}{bad}")).unwrap();
        (dir, path)
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
        let (_dir, path) = later_frame_path();
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

    fn write_temp(bytes: &[u8]) -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("case.con");
        std::fs::write(&path, bytes).unwrap();
        (dir, path)
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
        let (_dir, path) = write_temp(&bytes);
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
            let (_dir, path) = write_temp(&bytes);
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
        crate::writer::WriteError::Format(parse) => {
            parse_err_to_py(py, &parse, parse.line(), parse.named_frame().unwrap_or(0))
        }
    }
}

/// readcon Python module implemented in Rust.
#[pymodule(gil_used = false)]
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
    m.add(
        "__commit__",
        option_env!("READCON_GIT_COMMIT").unwrap_or(""),
    )?;
    m.add("__tree__", option_env!("READCON_GIT_TREE").unwrap_or(""))?;
    m.add(
        "__source_digest__",
        option_env!("READCON_SOURCE_DIGEST").unwrap_or(""),
    )?;
    m.add("CON_SPEC_VERSION", crate::CON_SPEC_VERSION)?;
    m.add_class::<PyAtomDatum>()?;
    m.add_class::<PyAtomView>()?;
    m.add_class::<PyAtomIter>()?;
    m.add_class::<PyAtomSeq>()?;
    #[cfg(feature = "race-hooks")]
    {
        m.add_class::<PyAtomListRace>()?;
        m.add_function(wrap_pyfunction!(_atom_list_race, m)?)?;
        m.add_function(wrap_pyfunction!(_hold_frame_borrow, m)?)?;
        m.add_function(wrap_pyfunction!(_append_foreign_atom, m)?)?;
    }
    m.add_class::<PyConFrame>()?;
    m.add_class::<PyConFrameIterator>()?;
    m.add_class::<PyConTrajectory>()?;
    m.add_class::<PyConTrajectoryIter>()?;
    m.add_class::<ConFrameList>()?;
    m.add_class::<ConFrameListIter>()?;
    m.add_class::<PositionStore>()?;
    m.add_class::<FrameColumns>()?;
    m.add_function(wrap_pyfunction!(read_con, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_phases, m)?)?;
    m.add_function(wrap_pyfunction!(scan_probe, m)?)?;
    m.add_function(wrap_pyfunction!(read_positions, m)?)?;
    m.add_function(wrap_pyfunction!(read_coords, m)?)?;
    m.add_function(wrap_pyfunction!(write_coords, m)?)?;
    m.add_function(wrap_pyfunction!(write_columns, m)?)?;
    m.add_class::<ConBinMapping>()?;
    m.add_function(wrap_pyfunction!(read_conbin, m)?)?;
    m.add_function(wrap_pyfunction!(read_conbin_columns, m)?)?;
    m.add_function(wrap_pyfunction!(write_conbin_columns, m)?)?;
    m.add_function(wrap_pyfunction!(write_conbin, m)?)?;
    // Ergonomic alias for multi-language matrix (batch all frames).
    m.add_function(wrap_pyfunction!(read_all_frames, m)?)?;
    m.add_function(wrap_pyfunction!(read_first_frame, m)?)?;
    m.add_function(wrap_pyfunction!(iter_con, m)?)?;
    m.add_function(wrap_pyfunction!(iter_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(count_frames, m)?)?;
    m.add_function(wrap_pyfunction!(read_nth_frame, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(write_con, m)?)?;
    #[cfg(any(test, feature = "borrow-path-counts"))]
    m.add_function(wrap_pyfunction!(borrow_path_counts, m)?)?;
    #[cfg(any(test, feature = "borrow-path-counts"))]
    m.add_function(wrap_pyfunction!(binding_copy_count, m)?)?;
    m.add_function(wrap_pyfunction!(write_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(convert_to_con, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_as_ase, m)?)?;
    m.add_function(wrap_pyfunction!(has_chemfiles_support, m)?)?;
    m.add_function(wrap_pyfunction!(has_parallel_support, m)?)?;
    m.add_function(wrap_pyfunction!(has_mpi_support, m)?)?;
    m.add_function(wrap_pyfunction!(read_pdb, m)?)?;
    m.add_class::<SpeciesFrames>()?;
    m.add_class::<SpeciesRow>()?;
    m.add_class::<FrameSymbols>()?;
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
        ChemfilesImportError::InvalidFrame(msg) => scan_err_to_py(msg),
        ChemfilesImportError::NonFiniteValue(err) => Python::attach(|py| cell_err_to_py(py, &err)),
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

/// The chemical symbols of one frame, one interned string per run of equal
/// symbols.
///
/// Behaves as a tuple of strings: ``len``, index, iteration, a slice that
/// is a tuple, equality with a tuple, a list or another
/// :class:`FrameSymbols`, pickle, and hash. ``table()`` is the distinct
/// symbols in order of first use and ``ids()`` the per-atom ``uint32``
/// index into it.
#[pyclass(frozen, module = "readcon", name = "FrameSymbols")]
struct FrameSymbols {
    runs: Vec<Py<PyString>>,
    /// Exclusive end atom of each run, increasing.
    ends: Vec<usize>,
}

#[pyclass(module = "readcon")]
struct FrameSymbolsIter {
    symbols: Py<FrameSymbols>,
    run: usize,
    index: usize,
}

impl FrameSymbols {
    fn from_runs<'a>(py: Python<'_>, runs: impl IntoIterator<Item = (&'a str, usize)>) -> Self {
        let mut names: Vec<Py<PyString>> = Vec::new();
        let mut ends: Vec<usize> = Vec::new();
        let mut total = 0usize;
        let mut last: Option<&str> = None;
        for (symbol, count) in runs {
            if count == 0 {
                continue;
            }
            total += count;
            if last == Some(symbol) {
                *ends.last_mut().expect("a run precedes") = total;
                continue;
            }
            names.push(PyString::intern(py, symbol).unbind());
            ends.push(total);
            last = Some(symbol);
        }
        Self { runs: names, ends }
    }

    fn of_parsed(py: Python<'_>, frame: &ConFrame) -> Self {
        let counts = &frame.header.natms_per_type;
        if counts.iter().sum::<usize>() == frame.atom_data.len() {
            let mut start = 0usize;
            return Self::from_runs(
                py,
                counts.iter().map(|&count| {
                    let symbol = frame
                        .atom_data
                        .get(start)
                        .map_or("", |atom| atom.symbol.as_ref());
                    start += count;
                    (symbol, count)
                }),
            );
        }
        Self::from_runs(
            py,
            frame
                .atom_data
                .iter()
                .map(|atom| (atom.symbol.as_ref(), 1usize)),
        )
    }

    fn len(&self) -> usize {
        self.ends.last().copied().unwrap_or(0)
    }

    fn run_of(&self, atom: usize) -> usize {
        self.ends.partition_point(|&end| end <= atom)
    }

    fn symbol(&self, py: Python<'_>, atom: usize) -> Py<PyString> {
        self.runs[self.run_of(atom)].clone_ref(py)
    }

    fn as_tuple<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let mut items = Vec::with_capacity(self.len());
        let mut start = 0usize;
        for (name, &end) in self.runs.iter().zip(&self.ends) {
            items.extend((start..end).map(|_| name.clone_ref(py)));
            start = end;
        }
        PyTuple::new(py, items)
    }

    fn table_ids(&self, py: Python<'_>) -> PyResult<(Vec<Py<PyString>>, Vec<u32>)> {
        let mut table: Vec<Py<PyString>> = Vec::new();
        let mut run_ids = Vec::with_capacity(self.runs.len());
        for name in &self.runs {
            let text = name.bind(py).to_str()?;
            let mut found = None;
            for (index, known) in table.iter().enumerate() {
                if known.bind(py).to_str()? == text {
                    found = Some(index);
                    break;
                }
            }
            let id = match found {
                Some(index) => index,
                None => {
                    table.push(name.clone_ref(py));
                    table.len() - 1
                }
            };
            run_ids.push(id as u32);
        }
        Ok((table, run_ids))
    }
}

#[pymethods]
impl FrameSymbols {
    #[new]
    fn new(py: Python<'_>, symbols: Vec<String>, counts: Vec<usize>) -> PyResult<Self> {
        if symbols.len() != counts.len() {
            return Err(PyValueError::new_err(
                "FrameSymbols needs one count per symbol",
            ));
        }
        Ok(Self::from_runs(
            py,
            symbols.iter().map(String::as_str).zip(counts),
        ))
    }

    fn __len__(&self) -> usize {
        self.len()
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let n_atoms = self.len();
        if let Ok(index) = key.extract::<isize>() {
            let atom = species_index(index, n_atoms)?;
            return Ok(self.symbol(py, atom).into_any());
        }
        let slice = key
            .cast::<PySlice>()
            .map_err(|_| PyTypeError::new_err("symbol index"))?;
        let indices = slice.indices(n_atoms as isize)?;
        let mut items = Vec::with_capacity(indices.slicelength);
        let mut cursor = indices.start;
        for _ in 0..indices.slicelength {
            items.push(self.symbol(py, species_index(cursor, n_atoms)?));
            cursor += indices.step;
        }
        Ok(PyTuple::new(py, items)?.into_any().unbind())
    }

    fn __iter__(slf: &Bound<'_, Self>) -> PyResult<Py<FrameSymbolsIter>> {
        Py::new(
            slf.py(),
            FrameSymbolsIter {
                symbols: slf.clone().unbind(),
                run: 0,
                index: 0,
            },
        )
    }

    fn __eq__(slf: &Bound<'_, Self>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        let py = slf.py();
        let this = slf.get();
        if let Ok(theirs) = other.cast::<FrameSymbols>() {
            let theirs = theirs.get();
            if this.ends != theirs.ends {
                return Ok(false);
            }
            for (left, right) in this.runs.iter().zip(&theirs.runs) {
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
        if seq.len()? != this.len() {
            return Ok(false);
        }
        let mut start = 0usize;
        for (name, &end) in this.runs.iter().zip(&this.ends) {
            for atom in start..end {
                if !PyAnyMethods::eq(&seq.get_item(atom)?, name.bind(py))? {
                    return Ok(false);
                }
            }
            start = end;
        }
        Ok(true)
    }

    fn __hash__(&self, py: Python<'_>) -> PyResult<isize> {
        self.as_tuple(py)?.hash()
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!("FrameSymbols({})", self.as_tuple(py)?.repr()?))
    }

    fn __reduce__<'py>(
        slf: &Bound<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyTuple>)> {
        let this = slf.get();
        let mut symbols = Vec::with_capacity(this.runs.len());
        let mut counts = Vec::with_capacity(this.runs.len());
        let mut start = 0usize;
        for (name, &end) in this.runs.iter().zip(&this.ends) {
            symbols.push(name.clone_ref(py));
            counts.push(end - start);
            start = end;
        }
        let args = PyTuple::new(py, [symbols.into_py_any(py)?, counts.into_py_any(py)?])?;
        Ok((slf.get_type().into_any(), args))
    }

    /// The symbols as a list of strings, one per atom.
    fn tolist<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, self.as_tuple(py)?)
    }

    /// The distinct symbols in order of first use.
    fn table<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        PyTuple::new(py, self.table_ids(py)?.0)
    }

    /// Per-atom index into `table()`, as a new `uint32` array.
    fn ids<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<u32>>> {
        let (_, run_ids) = self.table_ids(py)?;
        let mut ids = Vec::with_capacity(self.len());
        let mut start = 0usize;
        for (&id, &end) in run_ids.iter().zip(&self.ends) {
            ids.extend(std::iter::repeat_n(id, end - start));
            start = end;
        }
        Ok(ids.into_pyarray(py))
    }

    /// Object array of species strings, one interned string per run.
    fn __call__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let mut items: Vec<Py<PyAny>> = Vec::with_capacity(self.len());
        let mut start = 0usize;
        for (name, &end) in self.runs.iter().zip(&self.ends) {
            let text = name.clone_ref(py).into_any();
            for _ in start..end {
                items.push(text.clone_ref(py));
            }
            start = end;
        }
        let list = PyList::new(py, items)?;
        let numpy = py.import("numpy")?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("dtype", numpy.getattr("object_")?)?;
        numpy.call_method("array", (list,), Some(&kwargs))
    }
}

#[pymethods]
impl FrameSymbolsIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> Option<Py<PyString>> {
        let symbols = self.symbols.get();
        while self.run < symbols.ends.len() && self.index >= symbols.ends[self.run] {
            self.run += 1;
        }
        let name = symbols.runs.get(self.run)?.clone_ref(py);
        self.index += 1;
        Some(name)
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
        .detach(move || -> Result<_, crate::error::ConvertError> {
            use std::io::Read;
            let mut file = std::fs::File::open(&path_owned)
                .map_err(|_| crate::error::ConvertError::from("read"))?;
            let mut magic = [0u8; 4];
            let nmagic = file
                .read(&mut magic)
                .map_err(|_| crate::error::ConvertError::from("read"))?;
            if !matches!(
                crate::compression::detect_compression(&magic[..nmagic]),
                crate::compression::Compression::None
            ) {
                drop(file);
                let bytes = crate::compression::read_file_bytes(std::path::Path::new(&path_owned))
                    .map_err(|err| crate::error::ConvertError::from(err.to_string()))?;
                return crate::extxyz_scan::scan_extxyz_bytes(&bytes, workers);
            }
            let meta = file
                .metadata()
                .map_err(|_| crate::error::ConvertError::from("read"))?;
            // A pipe has no map. A proc file can report size 0 and still
            // return bytes from read; mapping it fails or yields an empty
            // slice. A regular file with a size is mapped. Truncating that
            // file while the map is alive is still a SIGBUS.
            if meta.is_file() && meta.len() > 0 {
                // SAFETY: `file` is a regular file of nonzero length. The
                // slice is the parse input and is dropped before return.
                if let Ok(bytes) = unsafe { memmap2::Mmap::map(&file) } {
                    return crate::extxyz_scan::scan_extxyz_bytes(&bytes, workers);
                }
            }
            let mut bytes = Vec::new();
            bytes.extend_from_slice(&magic[..nmagic]);
            file.read_to_end(&mut bytes)
                .map_err(|_| crate::error::ConvertError::from("read"))?;
            crate::extxyz_scan::scan_extxyz_bytes(&bytes, workers)
        })
        .map_err(convert_err_to_py)?;
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
        for index in 0..frame.len() {
            // `PyTuple_GET_ITEM` is a CPython macro. PyPy's pyo3-ffi does
            // not export it, and that is the interpreter the wheel build
            // compiles after CPython.
            let item = frame.get_item(index)?;
            let ptr = item.as_ptr() as usize;
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
    bytes: Vec<u8>,
    spans: Vec<(u32, u8)>,
    ids: Vec<u32>,
}

impl<'a> RealColumn<'a> {
    fn format(name: &'a str, width: usize, values: &[f64]) -> Self {
        let mut bytes = Vec::new();
        let mut spans = Vec::new();
        let mut ids = Vec::with_capacity(values.len());
        let mut known = std::collections::HashMap::<u64, u32>::new();
        for &value in values {
            let bits = value.to_bits();
            let id = match known.entry(bits) {
                std::collections::hash_map::Entry::Occupied(entry) => *entry.get(),
                std::collections::hash_map::Entry::Vacant(entry) => {
                    let start = bytes.len();
                    crate::extxyz_scan::append_extxyz_number(&mut bytes, value);
                    let len = bytes.len() - start;
                    debug_assert!(u32::try_from(start).is_ok() && u8::try_from(len).is_ok());
                    let id = spans.len() as u32;
                    spans.push((start as u32, len as u8));
                    entry.insert(id);
                    id
                }
            };
            ids.push(id);
        }
        Self {
            name,
            width,
            bytes,
            spans,
            ids,
        }
    }
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
            let (start, len) = self.spans[self.ids[base + slot] as usize];
            out.extend_from_slice(&self.bytes[start as usize..start as usize + len as usize]);
        }
    }
}

/// Write an extended XYZ file from the dict returned by ``read_extxyz``.
///
/// Species, positions, the lattice, ``pbc`` and every per-atom column,
/// including forces, are written. Numeric columns are copied from the
/// caller's arrays before the GIL is released. If another thread stores
/// into those arrays during a call, each output float is one untorn value
/// from an element load, but different elements can come from different
/// stores.
#[pyfunction]
#[pyo3(signature = (path, data, n_threads=None))]
fn write_extxyz(
    py: Python<'_>,
    path: &str,
    data: &Bound<'_, PyDict>,
    n_threads: Option<usize>,
) -> PyResult<()> {
    let positions = data
        .get_item("positions")?
        .ok_or_else(|| PyValueError::new_err("positions"))?;
    let pos = positions.cast::<PyArray3<f64>>()?;
    let shape = pos.shape();
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
            let width = *wide.shape().get(2).unwrap_or(&1);
            if !wide.is_c_contiguous() {
                return Err(PyValueError::new_err(format!("column {name}")));
            }
            real3_meta.push((name, width));
            real3_arrays.push(wide.clone());
            order.push(1u8);
        } else if let Ok(thin) = value.cast::<PyArray2<f64>>() {
            if !thin.is_c_contiguous() {
                return Err(PyValueError::new_err(format!("column {name}")));
            }
            real2_names.push(name);
            real2_arrays.push(thin.clone());
            order.push(2u8);
        } else {
            text_names.push(name);
            text_items.push(intern_text_column(&value)?);
            order.push(0u8);
        }
    }
    // Python can store into these arrays once the thread detaches. Runs
    // of frames are copied attached and formatted detached.
    if n_frames == 0 || n_atoms == 0 || order.is_empty() {
        return Err(PyValueError::new_err("frames"));
    }
    if cell_array.len() < n_frames * 6 {
        return Err(PyValueError::new_err("cell"));
    }
    let cell_owned =
        SharedColumn::from_array(cell_array.as_any(), "cell", 6, cell_array.len())?.snapshot(py);
    check_cell_array(py, &cell_owned[..n_frames * 6])?;
    let cell = SharedColumn {
        ptr: cell_owned.as_ptr(),
        len: cell_owned.len(),
        per_frame: 6,
    };
    let shared_real =
        |name: &str, array: &Bound<'_, PyAny>, width: usize| -> PyResult<SharedColumn> {
            let values = array.cast::<numpy::PyArrayDyn<f64>>()?;
            let expected = n_frames
                .checked_mul(n_atoms)
                .and_then(|count| count.checked_mul(width))
                .ok_or_else(|| PyValueError::new_err(format!("column {name}")))?;
            if values.len() != expected {
                return Err(PyValueError::new_err(format!("column {name}")));
            }
            SharedColumn::from_array(array, name, n_atoms * width, expected)
        };
    let mut reals = Vec::with_capacity(real3_arrays.len() + real2_arrays.len());
    let mut texts = Vec::with_capacity(text_items.len());
    let mut plan = Vec::with_capacity(order.len());
    let (mut wide, mut thin, mut text) = (0, 0, 0);
    for kind in &order {
        match kind {
            0 => {
                texts.push((text_names[text].as_str(), &text_items[text]));
                plan.push((0u8, texts.len() - 1));
                text += 1;
            }
            1 => {
                let (name, width) = &real3_meta[wide];
                let column = shared_real(name, real3_arrays[wide].as_any(), *width)?;
                reals.push((name.as_str(), *width, column));
                plan.push((1u8, reals.len() - 1));
                wide += 1;
            }
            _ => {
                let name = &real2_names[thin];
                let column = shared_real(name, real2_arrays[thin].as_any(), 1)?;
                reals.push((name.as_str(), 1, column));
                plan.push((1u8, reals.len() - 1));
                thin += 1;
            }
        }
    }
    let workers = n_threads.unwrap_or(1);
    let bytes = staged_extxyz_bytes(py, n_frames, n_atoms, cell, &texts, &reals, &plan, workers)
        .map_err(scan_err_to_py)?;
    if let Some(parent) = std::path::Path::new(path).parent()
        && !parent.as_os_str().is_empty()
    {
        std::fs::create_dir_all(parent).map_err(|_| PyValueError::new_err("write"))?;
    }
    let codec = crate::compression::detect_compression_from_extension(std::path::Path::new(path));
    let path_owned = path.to_owned();
    if matches!(codec, crate::compression::Compression::None) {
        return py
            .detach(|| write_bytes_parallel(&path_owned, &bytes, workers))
            .map_err(|_| PyValueError::new_err("write"));
    }
    let members = crate::compression::compression_workers(bytes.len());
    let threads = match n_threads {
        Some(count) if count >= 1 => count,
        _ => crate::compression::default_deflate_threads(members),
    };
    let written = py.detach(|| match codec {
        crate::compression::Compression::Gzip => crate::compression::write_gzip_members_limited(
            std::path::Path::new(&path_owned),
            &bytes,
            members,
            threads,
        ),
        crate::compression::Compression::Zstd => {
            #[cfg(feature = "zstd")]
            {
                crate::compression::write_zstd_members_limited(
                    std::path::Path::new(&path_owned),
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
    });
    written
        .map(|_| ())
        .map_err(|err| PyValueError::new_err(err.to_string()))
}

/// The bytes of `extxyz_bytes_with_threads` over these columns, formatted
/// one run of frames at a time from copies taken attached.
///
/// A run of a longer trajectory always holds two frames or more: one
/// frame alone takes the wide single-frame path.
#[allow(clippy::too_many_arguments)]
fn staged_extxyz_bytes(
    py: Python<'_>,
    n_frames: usize,
    n_atoms: usize,
    cell: SharedColumn,
    texts: &[(&str, &OwnedText)],
    reals: &[(&str, usize, SharedColumn)],
    plan: &[(u8, usize)],
    workers: usize,
) -> Result<Vec<u8>, String> {
    let per_frame = 6 + reals.iter().map(|real| real.2.per_frame).sum::<usize>();
    let step = staged_frames(per_frame).max(2);
    // Growing run by run copies the text written so far at each doubling.
    let mut out = Vec::with_capacity(n_frames.saturating_mul(n_atoms).saturating_mul(64));
    let mut cell_run = Vec::new();
    let mut real_runs = vec![Vec::new(); reals.len()];
    let mut start = 0;
    while start < n_frames {
        let mut end = (start + step).min(n_frames);
        if n_frames - end == 1 {
            end = n_frames;
        }
        cell.stage(py, start..end, &mut cell_run);
        for ((_, _, column), run) in reals.iter().zip(real_runs.iter_mut()) {
            column.stage(py, start..end, run);
        }
        let atoms = start * n_atoms..end * n_atoms;
        let text_runs: Vec<TextColumn<'_>> = texts
            .iter()
            .map(|(name, owned)| {
                if owned.ids.is_empty() {
                    TextColumn {
                        name,
                        tokens: &owned.symbols[atoms.clone()],
                        ids: &[],
                    }
                } else {
                    TextColumn {
                        name,
                        tokens: &owned.symbols,
                        ids: &owned.ids[atoms.clone()],
                    }
                }
            })
            .collect();
        let real_specs: Vec<(&str, usize)> = reals
            .iter()
            .map(|(name, width, _)| (*name, *width))
            .collect();
        py.detach(|| {
            let real_columns: Vec<RealColumn<'_>> = real_specs
                .iter()
                .zip(&real_runs)
                .map(|((name, width), values)| RealColumn::format(name, *width, values))
                .collect();
            let sources: Vec<&(dyn crate::extxyz_scan::ExtxyzSource + Sync)> = plan
                .iter()
                .map(|(kind, index)| {
                    if *kind == 0 {
                        &text_runs[*index] as &(dyn crate::extxyz_scan::ExtxyzSource + Sync)
                    } else {
                        &real_columns[*index] as &(dyn crate::extxyz_scan::ExtxyzSource + Sync)
                    }
                })
                .collect();
            crate::extxyz_scan::extxyz_append_with_threads(
                &mut out,
                end - start,
                n_atoms,
                &cell_run,
                &sources,
                workers,
            )
        })?;
        start = end;
    }
    Ok(out)
}

fn write_bytes_parallel(path: &str, bytes: &[u8], workers: usize) -> std::io::Result<()> {
    let mut opts = std::fs::OpenOptions::new();
    opts.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let _ = OpenOptionsExt::mode(&mut opts, 0o644);
    }
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
    if buf.is_empty() {
        return Ok(());
    }
    #[cfg(unix)]
    {
        use std::os::unix::io::AsRawFd;
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
        return Ok(());
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::FileExt;
        file.seek_write(buf, offset)?;
        Ok(())
    }
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
    let path_owned = path.to_owned();
    let tables = py
        .detach(|| crate::pdb_scan::scan_pdb_path(std::path::Path::new(&path_owned)))
        .map_err(convert_err_to_py)?;
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
    let path_owned = path.to_owned();
    let frames = py
        .detach(|| con_frames_from_trajectory_path_with(Path::new(&path_owned), &opts))
        .map_err(chemfiles_err_to_py)?;
    // Move the frames. Cloning would box a coordinate triple per atom.
    frames
        .into_iter()
        .map(|frame| PyConFrame::from_owned(py, frame))
        .collect()
}

/// Read the **first** frame only from a chemfiles-supported path.
///
/// Prefer this for single-structure XYZ/PDB/GRO files.
#[pyfunction]
fn read_chemfiles_first(py: Python<'_>, path: &str) -> PyResult<PyConFrame> {
    use crate::chemfiles_import::con_frame_from_trajectory_path;
    let path_owned = path.to_owned();
    let frame = py
        .detach(|| con_frame_from_trajectory_path(Path::new(&path_owned)))
        .map_err(chemfiles_err_to_py)?;
    PyConFrame::from_owned(py, frame)
}

/// Read step ``index`` via chemfiles ``Trajectory.read_step``.
#[pyfunction]
fn read_chemfiles_nth(py: Python<'_>, path: &str, index: usize) -> PyResult<PyConFrame> {
    use crate::chemfiles_import::con_frame_from_trajectory_path_nth;
    let path_owned = path.to_owned();
    let frame = py
        .detach(|| con_frame_from_trajectory_path_nth(Path::new(&path_owned), index))
        .map_err(chemfiles_err_to_py)?;
    PyConFrame::from_owned(py, frame)
}

/// Number of steps in a chemfiles trajectory (``Trajectory.nsteps``).
#[pyfunction]
fn read_chemfiles_nsteps(py: Python<'_>, path: &str) -> PyResult<usize> {
    use crate::chemfiles_import::nsteps_from_trajectory_path;
    let path_owned = path.to_owned();
    py.detach(|| nsteps_from_trajectory_path(Path::new(&path_owned)))
        .map_err(chemfiles_err_to_py)
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
    let data_owned = data.to_owned();
    let format_owned = format.to_owned();
    let frames = py
        .detach(|| con_frames_from_memory_with(&data_owned, &format_owned, &opts))
        .map_err(chemfiles_err_to_py)?;
    frames
        .into_iter()
        .map(|frame| PyConFrame::from_owned(py, frame))
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
fn select_on_frame(
    py: Python<'_>,
    frame: &Bound<'_, PyConFrame>,
    selection: &str,
) -> PyResult<Py<PyAny>> {
    use crate::chemfiles_selection::evaluate_selection_on_con_frame;
    let rust_frame = shared(frame)?.to_con_frame(py)?;
    let selection_owned = selection.to_owned();
    let result = py
        .detach(|| evaluate_selection_on_con_frame(&selection_owned, &rust_frame))
        .map_err(chemfiles_err_to_py)?;
    selection_result_to_py(py, result)
}

/// Atom-context selection: sorted unique atom indices (e.g. ``name O``).
///
/// Prefer :meth:`ConFrame.select_atoms` for idiomatic method-call style.
#[pyfunction]
fn select_atom_indices(
    py: Python<'_>,
    frame: &Bound<'_, PyConFrame>,
    selection: &str,
) -> PyResult<Vec<usize>> {
    use crate::chemfiles_selection::select_atom_indices as rust_select;
    let rust_frame = shared(frame)?.to_con_frame(py)?;
    let selection_owned = selection.to_owned();
    py.detach(|| rust_select(&selection_owned, &rust_frame))
        .map_err(chemfiles_err_to_py)
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
    let seq = shared_frames(frames)?;
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
    let selection_owned = selection.to_owned();
    let multi = py
        .detach(|| rust_eval(&selection_owned, &rust_frames))
        .map_err(chemfiles_err_to_py)?;
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
    let selection_owned = selection.to_owned();
    let multi = py
        .detach(|| rust_sel(&selection_owned, &rust_frames))
        .map_err(chemfiles_err_to_py)?;
    multi_frame_selection_to_py(py, multi)
}

struct SymbolRun<'a> {
    symbol: &'a str,
    count: usize,
}

/// Species runs from the type table. One symbol per species, not per atom.
fn symbol_runs(frame: &ConFrame) -> Vec<SymbolRun<'_>> {
    let n = frame.atom_data.len();
    let declared: usize = frame.header.natms_per_type.iter().sum();
    if declared == n {
        let mut runs = Vec::with_capacity(frame.header.natms_per_type.len());
        let mut offset = 0usize;
        for &count in &frame.header.natms_per_type {
            if count == 0 || offset >= n {
                continue;
            }
            let take = count.min(n - offset);
            runs.push(SymbolRun {
                symbol: frame.atom_data[offset].symbol.as_ref(),
                count: take,
            });
            offset += take;
        }
        if offset == n {
            return runs;
        }
    }
    let mut runs = Vec::new();
    let mut index = 0usize;
    while index < n {
        let ptr = frame.atom_data[index].symbol.as_ptr();
        let symbol = frame.atom_data[index].symbol.as_ref();
        let start = index;
        index += 1;
        while index < n && std::ptr::eq(frame.atom_data[index].symbol.as_ptr(), ptr) {
            index += 1;
        }
        runs.push(SymbolRun {
            symbol,
            count: index - start,
        });
    }
    runs
}

fn push_frame_identity(
    frame: &ConFrame,
    atom_ids: &mut Vec<u64>,
    atomic_numbers: &mut Vec<u64>,
    symbol_runs_out: &mut Vec<(String, usize)>,
) {
    let n = frame.atom_data.len();
    match frame.atom_ids.as_slice() {
        Some(slice) if slice.len() == n => atom_ids.extend_from_slice(slice),
        _ => atom_ids.extend(frame.atom_data.iter().map(|atom| atom.atom_id)),
    }
    for run in symbol_runs(frame) {
        let atomic = crate::helpers::symbol_to_atomic_number(run.symbol);
        atomic_numbers.extend(std::iter::repeat_n(atomic, run.count));
        symbol_runs_out.push((run.symbol.to_owned(), run.count));
    }
}

/// Object array of species strings. Each run allocates one string.
///
/// The numeric columns do not store symbols, so this array is a copy
/// of pointers. `rows` stacks those pointers as `(frames, atoms)`.
fn symbols_array<'py>(
    py: Python<'py>,
    runs: &[(String, usize)],
    rows: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let total: usize = runs.iter().map(|(_, count)| *count).sum();
    let mut items: Vec<Py<PyAny>> = Vec::with_capacity(total);
    for (symbol, count) in runs {
        let text: Py<PyAny> = PyString::intern(py, symbol).into_any().unbind();
        for _ in 0..*count {
            items.push(text.clone_ref(py));
        }
    }
    let list = PyList::new(py, items)?;
    let numpy = py.import("numpy")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("dtype", numpy.getattr("object_")?)?;
    let array = numpy.call_method("array", (list,), Some(&kwargs))?;
    let Some(n_frames) = rows else {
        return Ok(array);
    };
    if n_frames == 0 {
        return array.call_method1("reshape", ((0, 0),));
    }
    if !total.is_multiple_of(n_frames) {
        return Err(PyValueError::new_err("symbol run length"));
    }
    array.call_method1("reshape", ((n_frames, total / n_frames),))
}

fn copy_f64_rows<'py>(
    py: Python<'py>,
    storage: &crate::storage_dtype::Array2Storage,
    what: &str,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let n = storage.nrows();
    let mut data = Vec::with_capacity(n.saturating_mul(3));
    for row in 0..n {
        data.extend_from_slice(&storage.as_f64_row(row));
    }
    let array = Array2::from_shape_vec((n, 3), data)
        .map_err(|err| PyValueError::new_err(format!("{what} shape error: {err}")))?;
    Ok(array.into_pyarray(py))
}

fn fixed_mask_bytes(flags: impl Iterator<Item = [bool; 3]>) -> Vec<u8> {
    let mut data = Vec::new();
    for flag in flags {
        data.push(u8::from(flag[0]));
        data.push(u8::from(flag[1]));
        data.push(u8::from(flag[2]));
    }
    data
}

fn fixed_mask_array_from<'py>(
    py: Python<'py>,
    data: Vec<u8>,
    n: usize,
) -> PyResult<Bound<'py, PyArray2<u8>>> {
    let array = Array2::from_shape_vec((n, 3), data)
        .map_err(|err| PyValueError::new_err(format!("fixed_mask_array shape error: {err}")))?;
    Ok(array.into_pyarray(py))
}

fn atomic_numbers_from_runs(runs: &[SymbolRun<'_>]) -> Vec<u64> {
    let n = runs.iter().map(|run| run.count).sum();
    let mut data = Vec::with_capacity(n);
    for run in runs {
        let atomic = crate::helpers::symbol_to_atomic_number(run.symbol);
        data.extend(std::iter::repeat_n(atomic, run.count));
    }
    data
}
