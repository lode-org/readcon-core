use pyo3::prelude::*;
use pyo3::exceptions::PyIOError;
use pyo3::types::IntoPyDict;

use crate::iterators::ConFrameIterator;
use crate::types::{AtomDatum, ConFrame, ConFrameBuilder};
use crate::writer::ConFrameWriter;

/// Python-visible atom data.
#[pyclass(name = "Atom", from_py_object)]
#[derive(Clone)]
pub struct PyAtomDatum {
    #[pyo3(get)]
    pub symbol: String,
    #[pyo3(get)]
    pub x: f64,
    #[pyo3(get)]
    pub y: f64,
    #[pyo3(get)]
    pub z: f64,
    #[pyo3(get)]
    pub is_fixed: bool,
    #[pyo3(get)]
    pub atom_id: u64,
    #[pyo3(get)]
    pub mass: Option<f64>,
    #[pyo3(get)]
    pub vx: Option<f64>,
    #[pyo3(get)]
    pub vy: Option<f64>,
    #[pyo3(get)]
    pub vz: Option<f64>,
}

#[pymethods]
impl PyAtomDatum {
    #[new]
    #[pyo3(signature = (symbol, x, y, z, is_fixed=false, atom_id=0, mass=None, vx=None, vy=None, vz=None))]
    fn new(
        symbol: String,
        x: f64,
        y: f64,
        z: f64,
        is_fixed: bool,
        atom_id: u64,
        mass: Option<f64>,
        vx: Option<f64>,
        vy: Option<f64>,
        vz: Option<f64>,
    ) -> Self {
        PyAtomDatum {
            symbol,
            x,
            y,
            z,
            is_fixed,
            atom_id,
            mass,
            vx,
            vy,
            vz,
        }
    }

    #[getter]
    fn has_velocity(&self) -> bool {
        self.vx.is_some() && self.vy.is_some() && self.vz.is_some()
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
        PyAtomDatum {
            symbol: (*atom.symbol).clone(),
            x: atom.x,
            y: atom.y,
            z: atom.z,
            is_fixed: atom.is_fixed,
            atom_id: atom.atom_id,
            mass: Some(mass),
            vx: atom.vx,
            vy: atom.vy,
            vz: atom.vz,
        }
    }
}

/// Python-visible simulation frame.
#[pyclass(name = "ConFrame", from_py_object)]
#[derive(Clone)]
pub struct PyConFrame {
    #[pyo3(get)]
    pub cell: [f64; 3],
    #[pyo3(get)]
    pub angles: [f64; 3],
    #[pyo3(get)]
    pub prebox_header: Vec<String>,
    #[pyo3(get)]
    pub postbox_header: Vec<String>,
    atoms_inner: Vec<PyAtomDatum>,
    #[pyo3(get)]
    pub has_velocities: bool,
}

#[pymethods]
impl PyConFrame {
    #[new]
    #[pyo3(signature = (cell, angles, atoms, prebox_header=None, postbox_header=None))]
    fn new(
        cell: [f64; 3],
        angles: [f64; 3],
        atoms: Vec<PyAtomDatum>,
        prebox_header: Option<Vec<String>>,
        postbox_header: Option<Vec<String>>,
    ) -> Self {
        let has_velocities = atoms.first().is_some_and(|a| a.has_velocity());
        PyConFrame {
            cell,
            angles,
            prebox_header: prebox_header.unwrap_or_else(|| vec![String::new(), String::new()]),
            postbox_header: postbox_header.unwrap_or_else(|| vec![String::new(), String::new()]),
            atoms_inner: atoms,
            has_velocities,
        }
    }

    #[getter]
    fn atoms(&self) -> Vec<PyAtomDatum> {
        self.atoms_inner.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "ConFrame(cell={:?}, angles={:?}, natoms={}, has_velocities={})",
            self.cell,
            self.angles,
            self.atoms_inner.len(),
            self.has_velocities
        )
    }

    fn __len__(&self) -> usize {
        self.atoms_inner.len()
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
}

impl From<&ConFrame> for PyConFrame {
    fn from(frame: &ConFrame) -> Self {
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

        PyConFrame {
            cell: frame.header.boxl,
            angles: frame.header.angles,
            prebox_header: frame.header.prebox_header.to_vec(),
            postbox_header: frame.header.postbox_header.to_vec(),
            atoms_inner: atoms,
            has_velocities: frame.has_velocities(),
        }
    }
}

impl PyConFrame {
    fn to_con_frame(&self) -> ConFrame {
        let mut builder = ConFrameBuilder::new(self.cell, self.angles)
            .prebox_header([
                self.prebox_header.first().cloned().unwrap_or_default(),
                self.prebox_header.get(1).cloned().unwrap_or_default(),
            ])
            .postbox_header([
                self.postbox_header.first().cloned().unwrap_or_default(),
                self.postbox_header.get(1).cloned().unwrap_or_default(),
            ]);

        for py_atom in &self.atoms_inner {
            let mass = py_atom.mass.unwrap_or(0.0);
            if py_atom.has_velocity() {
                builder.add_atom_with_velocity(
                    &py_atom.symbol,
                    py_atom.x,
                    py_atom.y,
                    py_atom.z,
                    py_atom.is_fixed,
                    py_atom.atom_id,
                    mass,
                    py_atom.vx.unwrap_or(0.0),
                    py_atom.vy.unwrap_or(0.0),
                    py_atom.vz.unwrap_or(0.0),
                );
            } else {
                builder.add_atom(
                    &py_atom.symbol,
                    py_atom.x,
                    py_atom.y,
                    py_atom.z,
                    py_atom.is_fixed,
                    py_atom.atom_id,
                    mass,
                );
            }
        }

        builder.build()
    }
}

/// Read frames from a .con or .convel file path.
#[pyfunction]
fn read_con(path: &str) -> PyResult<Vec<PyConFrame>> {
    let contents = std::fs::read_to_string(path)
        .map_err(|e| PyIOError::new_err(format!("failed to read file: {e}")))?;
    read_con_string(&contents)
}

/// Read frames from a string containing .con or .convel data.
#[pyfunction]
fn read_con_string(contents: &str) -> PyResult<Vec<PyConFrame>> {
    let iter = ConFrameIterator::new(contents);
    let mut frames = Vec::new();
    for result in iter {
        let frame = result.map_err(|e| PyIOError::new_err(format!("parse error: {e}")))?;
        frames.push(PyConFrame::from(&frame));
    }
    Ok(frames)
}

/// Write frames to a .con or .convel file path.
#[pyfunction]
#[pyo3(signature = (path, frames, precision=6))]
fn write_con(path: &str, frames: Vec<PyConFrame>, precision: usize) -> PyResult<()> {
    let rust_frames: Vec<ConFrame> = frames.iter().map(|f| f.to_con_frame()).collect();
    let mut writer = ConFrameWriter::from_path_with_precision(path, precision)
        .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?;
    writer
        .extend(rust_frames.iter())
        .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    Ok(())
}

/// Write frames to a string in .con format.
#[pyfunction]
#[pyo3(signature = (frames, precision=6))]
fn write_con_string(frames: Vec<PyConFrame>, precision: usize) -> PyResult<String> {
    let rust_frames: Vec<ConFrame> = frames.iter().map(|f| f.to_con_frame()).collect();
    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::with_precision(&mut buffer, precision);
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
    let frames = read_con(path)?;
    frames
        .iter()
        .map(|f| ase_from_pyconframe(py, f))
        .collect()
}

// --- ASE conversion helpers (runtime import, no compile-time dep) ---

fn ase_from_pyconframe(py: Python<'_>, frame: &PyConFrame) -> PyResult<Py<PyAny>> {
    let ase = py.import("ase")?;
    let ase_atoms_cls = ase.getattr("Atoms")?;

    // Build symbols list and positions array
    let symbols: Vec<&str> = frame.atoms_inner.iter().map(|a| a.symbol.as_str()).collect();
    let positions: Vec<[f64; 3]> = frame
        .atoms_inner
        .iter()
        .map(|a| [a.x, a.y, a.z])
        .collect();

    // Build cell from lengths + angles using ASE's cellpar_to_cell
    let cellpar: Vec<f64> = frame
        .cell
        .iter()
        .chain(frame.angles.iter())
        .copied()
        .collect();

    let ase_cell_mod = py.import("ase.geometry.cell")?;
    let cell = ase_cell_mod
        .getattr("cellpar_to_cell")?
        .call1((cellpar,))?;

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

    // Set FixAtoms constraint for fixed atoms
    let fixed_indices: Vec<usize> = frame
        .atoms_inner
        .iter()
        .enumerate()
        .filter(|(_, a)| a.is_fixed)
        .map(|(i, _)| i)
        .collect();

    if !fixed_indices.is_empty() {
        let ase_constraints = py.import("ase.constraints")?;
        let fix_atoms = ase_constraints
            .getattr("FixAtoms")?
            .call(
                (),
                Some(
                    &[("indices", fixed_indices.into_pyobject(py)?.into_any())]
                        .into_py_dict(py)?,
                ),
            )?;
        atoms.call_method1("set_constraint", (vec![fix_atoms],))?;
    }

    Ok(atoms.unbind())
}

fn pyconframe_from_ase(_py: Python<'_>, ase_atoms: &Bound<'_, PyAny>) -> PyResult<PyConFrame> {
    // Extract symbols
    let symbols: Vec<String> = ase_atoms
        .call_method0("get_chemical_symbols")?
        .extract()?;

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
    let constraints = ase_atoms.getattr("constraints")?;
    let constraints_list: Vec<Bound<'_, PyAny>> = constraints.extract()?;
    let mut fixed_set = std::collections::HashSet::new();

    for constraint in &constraints_list {
        let type_name = constraint
            .getattr("__class__")?
            .getattr("__name__")?
            .extract::<String>()?;
        if type_name == "FixAtoms" {
            let indices: Vec<usize> = constraint
                .getattr("index")?
                .call_method0("tolist")?
                .extract()?;
            fixed_set.extend(indices);
        }
    }

    // Extract masses from ASE (optional, may not be set)
    let masses: Option<Vec<f64>> = ase_atoms
        .call_method0("get_masses")
        .ok()
        .and_then(|m| m.call_method0("tolist").ok())
        .and_then(|m| m.extract().ok());

    // Build PyAtomDatum list
    let atoms: Vec<PyAtomDatum> = symbols
        .iter()
        .zip(positions.iter())
        .enumerate()
        .map(|(i, (sym, pos))| PyAtomDatum {
            symbol: sym.clone(),
            x: pos[0],
            y: pos[1],
            z: pos[2],
            is_fixed: fixed_set.contains(&i),
            atom_id: i as u64,
            mass: masses.as_ref().map(|m| m[i]),
            vx: None,
            vy: None,
            vz: None,
        })
        .collect();

    let has_velocities = false;
    Ok(PyConFrame {
        cell,
        angles,
        prebox_header: vec![String::new(), String::new()],
        postbox_header: vec![String::new(), String::new()],
        atoms_inner: atoms,
        has_velocities,
    })
}

/// readcon Python module implemented in Rust.
#[pymodule]
fn readcon(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyAtomDatum>()?;
    m.add_class::<PyConFrame>()?;
    m.add_function(wrap_pyfunction!(read_con, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(write_con, m)?)?;
    m.add_function(wrap_pyfunction!(write_con_string, m)?)?;
    m.add_function(wrap_pyfunction!(read_con_as_ase, m)?)?;
    Ok(())
}
