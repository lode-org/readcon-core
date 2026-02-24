use pyo3::prelude::*;
use pyo3::exceptions::PyIOError;

use crate::iterators::ConFrameIterator;
use crate::types::{AtomDatum, ConFrame, FrameHeader};
use crate::writer::ConFrameWriter;
use std::rc::Rc;

/// Python-visible atom data.
#[pyclass(name = "Atom")]
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
    pub vx: Option<f64>,
    #[pyo3(get)]
    pub vy: Option<f64>,
    #[pyo3(get)]
    pub vz: Option<f64>,
}

#[pymethods]
impl PyAtomDatum {
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

impl From<&AtomDatum> for PyAtomDatum {
    fn from(atom: &AtomDatum) -> Self {
        PyAtomDatum {
            symbol: (*atom.symbol).clone(),
            x: atom.x,
            y: atom.y,
            z: atom.z,
            is_fixed: atom.is_fixed,
            atom_id: atom.atom_id,
            vx: atom.vx,
            vy: atom.vy,
            vz: atom.vz,
        }
    }
}

/// Python-visible simulation frame.
#[pyclass(name = "ConFrame")]
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
}

impl From<&ConFrame> for PyConFrame {
    fn from(frame: &ConFrame) -> Self {
        let atoms: Vec<PyAtomDatum> = frame.atom_data.iter().map(PyAtomDatum::from).collect();
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
        let mut atom_data = Vec::with_capacity(self.atoms_inner.len());
        let mut natms_per_type: Vec<usize> = Vec::new();
        let mut masses_per_type: Vec<f64> = Vec::new();
        let mut current_symbol = String::new();
        let mut current_count: usize = 0;

        for py_atom in &self.atoms_inner {
            if py_atom.symbol != current_symbol {
                if current_count > 0 {
                    natms_per_type.push(current_count);
                }
                current_symbol = py_atom.symbol.clone();
                current_count = 0;
                masses_per_type.push(0.0);
            }
            current_count += 1;

            atom_data.push(AtomDatum {
                symbol: Rc::new(py_atom.symbol.clone()),
                x: py_atom.x,
                y: py_atom.y,
                z: py_atom.z,
                is_fixed: py_atom.is_fixed,
                atom_id: py_atom.atom_id,
                vx: py_atom.vx,
                vy: py_atom.vy,
                vz: py_atom.vz,
            });
        }
        if current_count > 0 {
            natms_per_type.push(current_count);
        }

        let header = FrameHeader {
            prebox_header: [
                self.prebox_header.first().cloned().unwrap_or_default(),
                self.prebox_header.get(1).cloned().unwrap_or_default(),
            ],
            boxl: self.cell,
            angles: self.angles,
            postbox_header: [
                self.postbox_header.first().cloned().unwrap_or_default(),
                self.postbox_header.get(1).cloned().unwrap_or_default(),
            ],
            natm_types: natms_per_type.len(),
            natms_per_type,
            masses_per_type,
        };

        ConFrame { header, atom_data }
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
fn write_con(path: &str, frames: Vec<PyConFrame>) -> PyResult<()> {
    let rust_frames: Vec<ConFrame> = frames.iter().map(|f| f.to_con_frame()).collect();
    let mut writer = ConFrameWriter::from_path(path)
        .map_err(|e| PyIOError::new_err(format!("failed to create writer: {e}")))?;
    writer
        .extend(rust_frames.iter())
        .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    Ok(())
}

/// Write frames to a string in .con format.
#[pyfunction]
fn write_con_string(frames: Vec<PyConFrame>) -> PyResult<String> {
    let rust_frames: Vec<ConFrame> = frames.iter().map(|f| f.to_con_frame()).collect();
    let mut buffer: Vec<u8> = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buffer);
        writer
            .extend(rust_frames.iter())
            .map_err(|e| PyIOError::new_err(format!("write error: {e}")))?;
    }
    String::from_utf8(buffer).map_err(|e| PyIOError::new_err(format!("utf8 error: {e}")))
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
    Ok(())
}
