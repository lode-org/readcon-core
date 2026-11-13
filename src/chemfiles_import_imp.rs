//! Optional chemfiles -> readcon conversion (feature = "chemfiles").
//!
//! Maps a chemfiles [`Frame`](chemfiles::Frame) (and trajectory readers) into
//! a spec-v2 [`ConFrame`](crate::types::ConFrame) with geometry, optional
//! velocities, and frame/atom properties preserved in
//! [`FrameHeader::metadata`](crate::types::FrameHeader).
//!
//! Build with `cargo build --features chemfiles`. Default builds do not
//! require libchemfiles.

use std::collections::BTreeMap;
use std::fmt;
use std::path::Path;
use std::sync::Arc;

use chemfiles::{BondOrder, CellShape, Frame, Property, Trajectory, UnitCell};
use serde_json::{Value, json};

use super::{ChemfilesReadOpts, chemfiles_internal_units_json};
use crate::storage_dtype::FloatArray2;
use crate::types::{AtomDatum, Bond, ConFrame, FrameHeader, FrameMeta, PreboxHeader, meta};

/// Map chemfiles bond order to optional integer stored in CON `bonds` metadata.
fn bond_order_to_i32(order: BondOrder) -> Option<i32> {
    match order {
        BondOrder::Unknown => Some(0),
        BondOrder::Single => Some(1),
        BondOrder::Double => Some(2),
        BondOrder::Triple => Some(3),
        BondOrder::Quadruple => Some(4),
        BondOrder::Quintuplet => Some(5),
        BondOrder::Amide => Some(6),
        BondOrder::Aromatic => Some(7),
        _ => Some(0),
    }
}

/// Convert chemfiles topology bonds into readcon [`Bond`]s for `metadata["bonds"]`.
pub fn bonds_from_chemfiles_frame(frame: &Frame) -> Vec<Bond> {
    let topo = frame.topology();
    let pairs = topo.bonds();
    let orders = topo.bond_orders();
    let mut out = Vec::with_capacity(pairs.len());
    for (idx, pair) in pairs.iter().enumerate() {
        let i = pair[0] as u32;
        let j = pair[1] as u32;
        let order = orders.get(idx).and_then(|o| bond_order_to_i32(*o));
        let mut b = Bond::new(i, j);
        b.order = order;
        out.push(b);
    }
    out
}

/// Prefix for chemfiles frame properties that do not map to a reserved
/// `meta::*` key. Preserved under `chemfiles::<name>` so nothing is dropped.
pub const CHEMFILES_EXTRA_PREFIX: &str = "chemfiles::";

/// Prefix for per-atom property bags stored in frame metadata.
pub const CHEMFILES_ATOM_PROPS_KEY: &str = "chemfiles_atom_properties";

/// Chemfiles display names in **chemfiles / `atom_id` order** (not `atom_data` order).
///
/// CON only stores one symbol string per atom (element/type for the `.con` layout).
/// When chemfiles has a distinct display `name` (e.g. `H1`) vs atomic `type` (`H`),
/// the display name is preserved here so selection projection can restore
/// `name H1` without changing on-disk CON columns. Optional; absent for non-import frames.
pub const CHEMFILES_ATOM_NAMES_KEY: &str = "chemfiles_atom_names";

/// Chemfiles atomic types in **chemfiles / `atom_id` order** (parallel to names).
/// Used with [`CHEMFILES_ATOM_NAMES_KEY`] when projecting to chemfiles for selection.
pub const CHEMFILES_ATOM_TYPES_KEY: &str = "chemfiles_atom_types";

/// Residue list (`name`, optional `id`, remapped `atoms`) from chemfiles topology.
pub const CHEMFILES_RESIDUES_KEY: &str = "chemfiles_residues";

/// Provenance object for chemfiles internal units (length/velocity/angle/mass).
pub const CHEMFILES_UNIT_SYSTEM_KEY: &str = "chemfiles::unit_system";

/// Errors from chemfiles I/O or conversion.
#[derive(Debug)]
pub enum ChemfilesImportError {
    /// Wrapped chemfiles library error.
    Chemfiles(chemfiles::Error),
    /// Atom / property count mismatch or other structural problem.
    InvalidFrame(String),
    /// I/O while reading a trajectory path.
    Io(std::io::Error),
    /// This build was compiled without the `chemfiles` Cargo feature.
    FeatureDisabled,
}

impl fmt::Display for ChemfilesImportError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ChemfilesImportError::Chemfiles(e) => write!(f, "chemfiles error: {e}"),
            ChemfilesImportError::InvalidFrame(msg) => write!(f, "invalid chemfiles frame: {msg}"),
            ChemfilesImportError::Io(e) => write!(f, "I/O error: {e}"),
            ChemfilesImportError::FeatureDisabled => write!(
                f,
                "chemfiles support is not enabled in this build; rebuild with `--features chemfiles` (Python: `maturin develop --features python,chemfiles` or install the `chemfiles` extra from source — see docs)"
            ),
        }
    }
}

impl std::error::Error for ChemfilesImportError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ChemfilesImportError::Chemfiles(e) => Some(e),
            ChemfilesImportError::Io(e) => Some(e),
            ChemfilesImportError::InvalidFrame(_) => None,
            ChemfilesImportError::FeatureDisabled => None,
        }
    }
}

impl From<chemfiles::Error> for ChemfilesImportError {
    fn from(e: chemfiles::Error) -> Self {
        ChemfilesImportError::Chemfiles(e)
    }
}

impl From<std::io::Error> for ChemfilesImportError {
    fn from(e: std::io::Error) -> Self {
        ChemfilesImportError::Io(e)
    }
}

/// Convert a chemfiles property into a JSON value for CON metadata extras.
pub fn property_to_json(prop: &Property) -> Value {
    match prop {
        Property::Bool(b) => Value::Bool(*b),
        Property::Double(d) => json!(d),
        Property::String(s) => Value::String(s.clone()),
        Property::Vector3D(v) => json!([v[0], v[1], v[2]]),
    }
}

fn normalize_meta_key(name: &str) -> String {
    name.trim().to_ascii_lowercase().replace(['-', ' '], "_")
}

/// Map a chemfiles frame property name into a reserved `meta::*` key when possible.
///
/// Returns `None` when the property should be stored under `chemfiles::<name>`.
pub fn map_frame_property_key(name: &str) -> Option<&'static str> {
    match normalize_meta_key(name).as_str() {
        "energy" | "total_energy" | "e_pot" | "epot" | "potential_energy" => Some(meta::ENERGY),
        "time" | "simulation_time" => Some(meta::TIME),
        "timestep" | "dt" | "delta_t" => Some(meta::TIMESTEP),
        "frame_index" | "frame" | "index" => Some(meta::FRAME_INDEX),
        "fmax" | "max_force" | "maxforce" => Some(meta::FMAX),
        "convergence_fmax" => Some(meta::CONVERGENCE_FMAX),
        "convergence_energy" => Some(meta::CONVERGENCE_ENERGY),
        "generator" | "software" | "program" => Some(meta::GENERATOR),
        "converged" => Some(meta::CONVERGED),
        "neb_bead" | "bead" => Some(meta::NEB_BEAD),
        "neb_band" | "band" => Some(meta::NEB_BAND),
        _ => None,
    }
}

fn insert_mapped_or_extra(
    metadata: &mut BTreeMap<String, Value>,
    chemfiles_name: &str,
    prop: &Property,
) {
    if let Some(meta_key) = map_frame_property_key(chemfiles_name) {
        // Reserved keys prefer scalar/bool/string shapes from the property.
        match (meta_key, prop) {
            (
                meta::ENERGY
                | meta::TIME
                | meta::TIMESTEP
                | meta::FMAX
                | meta::CONVERGENCE_FMAX
                | meta::CONVERGENCE_ENERGY,
                Property::Double(d),
            ) => {
                metadata.insert(meta_key.into(), json!(d));
            }
            (meta::FRAME_INDEX | meta::NEB_BEAD | meta::NEB_BAND, Property::Double(d)) => {
                if d.is_finite() && *d >= 0.0 && d.fract() == 0.0 {
                    metadata.insert(meta_key.into(), json!(*d as u64));
                } else {
                    metadata.insert(
                        format!("{CHEMFILES_EXTRA_PREFIX}{chemfiles_name}"),
                        property_to_json(prop),
                    );
                }
            }
            (meta::GENERATOR, Property::String(s)) => {
                metadata.insert(meta_key.into(), Value::String(s.clone()));
            }
            (meta::CONVERGED, Property::Bool(b)) => {
                metadata.insert(meta_key.into(), Value::Bool(*b));
            }
            _ => {
                // Wrong type for reserved key: keep as extra so nothing is lost.
                metadata.insert(
                    format!("{CHEMFILES_EXTRA_PREFIX}{chemfiles_name}"),
                    property_to_json(prop),
                );
            }
        }
    } else {
        metadata.insert(
            format!("{CHEMFILES_EXTRA_PREFIX}{chemfiles_name}"),
            property_to_json(prop),
        );
    }
}

fn cell_to_box_and_angles(cell: &UnitCell) -> ([f64; 3], [f64; 3], bool) {
    match cell.shape() {
        CellShape::Infinite => ([0.0, 0.0, 0.0], [90.0, 90.0, 90.0], false),
        CellShape::Orthorhombic | CellShape::Triclinic => {
            let lengths = cell.lengths();
            let angles = cell.angles();
            let pbc = lengths.iter().any(|&l| l > 0.0);
            (lengths, angles, pbc)
        }
    }
}

fn stamp_chemfiles_units(metadata: &mut BTreeMap<String, Value>) {
    if !metadata.contains_key(meta::UNITS) {
        metadata.insert(meta::UNITS.into(), chemfiles_internal_units_json());
    }
    metadata.insert(
        CHEMFILES_UNIT_SYSTEM_KEY.into(),
        json!({
            "length": "angstrom",
            "velocity": "angstrom/ps",
            "angle": "degree",
            "mass": "amu",
        }),
    );
}

fn residues_from_chemfiles_frame(frame: &Frame) -> Vec<Value> {
    let topo = frame.topology();
    let n = topo.residues_count() as usize;
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let Some(res) = topo.residue(i) else {
            continue;
        };
        let mut obj = serde_json::Map::new();
        obj.insert("name".into(), json!(res.name()));
        if let Some(id) = res.id() {
            obj.insert("id".into(), json!(id));
        }
        let atoms: Vec<Value> = res.atoms().into_iter().map(|a| json!(a)).collect();
        obj.insert("atoms".into(), Value::Array(atoms));
        let mut props = serde_json::Map::new();
        for (key, prop) in res.properties() {
            props.insert(key, property_to_json(&prop));
        }
        if !props.is_empty() {
            obj.insert("properties".into(), Value::Object(props));
        }
        out.push(Value::Object(obj));
    }
    out
}

fn remap_residue_atoms(residues: Vec<Value>, id_to_data: &BTreeMap<u64, u32>) -> Vec<Value> {
    let mut out = Vec::with_capacity(residues.len());
    for res in residues {
        let Some(obj) = res.as_object() else {
            continue;
        };
        let mut mapped = obj.clone();
        if let Some(atoms) = obj.get("atoms").and_then(|v| v.as_array()) {
            let remapped: Vec<Value> = atoms
                .iter()
                .filter_map(|v| v.as_u64())
                .filter_map(|chfl_idx| id_to_data.get(&chfl_idx).copied())
                .map(|i| json!(i))
                .collect();
            if remapped.is_empty() {
                continue;
            }
            mapped.insert("atoms".into(), Value::Array(remapped));
        }
        out.push(Value::Object(mapped));
    }
    out
}

fn apply_guess_bonds(frame: &mut Frame, guess_bonds: bool) -> Result<(), ChemfilesImportError> {
    if guess_bonds && frame.topology().bonds().is_empty() {
        frame.guess_bonds()?;
    }
    Ok(())
}

fn open_trajectory(
    path: &Path,
    opts: &ChemfilesReadOpts,
) -> Result<Trajectory, ChemfilesImportError> {
    let mut traj = match opts.format.as_deref() {
        Some(fmt) if !fmt.is_empty() => Trajectory::open_with_format(path, 'r', fmt)?,
        _ => Trajectory::open(path, 'r')?,
    };
    if let Some(topo) = opts.topology.as_ref() {
        match opts.topology_format.as_deref() {
            Some(fmt) if !fmt.is_empty() => {
                traj.set_topology_with_format(topo, fmt)?;
            }
            _ => {
                traj.set_topology_file(topo)?;
            }
        }
    }
    Ok(traj)
}

fn lattice_vectors_json(cell: &UnitCell) -> Option<Value> {
    match cell.shape() {
        CellShape::Infinite => None,
        CellShape::Orthorhombic | CellShape::Triclinic => {
            let m = cell.matrix();
            // chemfiles matrix is column-major style in docs; store as 3 row vectors.
            Some(json!([
                [m[0][0], m[0][1], m[0][2]],
                [m[1][0], m[1][1], m[1][2]],
                [m[2][0], m[2][1], m[2][2]],
            ]))
        }
    }
}

/// Convert one chemfiles frame into a writer-ready [`ConFrame`].
///
/// Positions always come from the frame. A repeated symbol is one `Arc<str>`,
/// not a `String` per atom. Name and type sidecars are stored only when a
/// display name or atomic type differs from that CON symbol. Per-atom property
/// maps are built only for atoms that actually have properties.
///
/// - Velocities are copied when `frame.has_velocities()` is true.
/// - Chemfiles has no standard per-atom forces API; if a frame property
///   `forces` is present as a string it is ignored (cannot map safely).
/// - Frame properties map into reserved `meta::*` keys when names align;
///   otherwise they are stored under `chemfiles::<name>`.
/// - Per-atom properties are collected under `chemfiles_atom_properties`.
/// - Chemfiles topology bonds are stored under reserved `metadata["bonds"]`
///   (optional; absent when the chemfiles frame has no bonds).
/// - Residues land under [`CHEMFILES_RESIDUES_KEY`] (optional).
/// - Line-2 `units` is chemfiles internal (Å, ps, amu); see
///   [`chemfiles_internal_units_json`].
/// - `generator` defaults to `readcon-core chemfiles import` when unset.
/// - `frame_index` defaults to chemfiles `step` when unset.
/// Positions without `Frame::positions`.
///
/// Chemfiles 0.10 builds a slice from a null pointer when a corrupt file
/// produces a frame with no coordinate storage. That violates
/// `from_raw_parts` and aborts the process.
fn frame_positions(frame: &Frame) -> Result<&[[f64; 3]], ChemfilesImportError> {
    let n = frame.size();
    if n == 0 {
        return Ok(&[]);
    }
    let mut ptr = std::ptr::null_mut();
    let mut natoms = 0u64;
    let status = unsafe {
        chemfiles_sys::chfl_frame_positions(frame_c_handle(frame), &mut ptr, &mut natoms)
    };
    if status != chemfiles_sys::chfl_status::CHFL_SUCCESS || ptr.is_null() || natoms as usize != n {
        return Err(ChemfilesImportError::InvalidFrame(
            "chemfiles frame has no position storage".into(),
        ));
    }
    Ok(unsafe { std::slice::from_raw_parts(ptr, n) })
}

fn frame_velocities(frame: &Frame) -> Result<&[[f64; 3]], ChemfilesImportError> {
    let n = frame.size();
    if n == 0 || !frame.has_velocities() {
        return Err(ChemfilesImportError::InvalidFrame(
            "chemfiles frame has no velocities".into(),
        ));
    }
    let mut ptr = std::ptr::null_mut();
    let mut natoms = 0u64;
    let status = unsafe {
        chemfiles_sys::chfl_frame_velocities(frame_c_handle(frame), &mut ptr, &mut natoms)
    };
    if status != chemfiles_sys::chfl_status::CHFL_SUCCESS || ptr.is_null() || natoms as usize != n {
        return Err(ChemfilesImportError::InvalidFrame(
            "chemfiles frame has no velocity storage".into(),
        ));
    }
    Ok(unsafe { std::slice::from_raw_parts(ptr, n) })
}

pub fn con_frame_from_chemfiles(frame: &Frame) -> Result<ConFrame, ChemfilesImportError> {
    let n = frame.size();
    let positions = frame_positions(frame)?;
    if positions.len() != n {
        return Err(ChemfilesImportError::InvalidFrame(format!(
            "position count {} != atom count {n}",
            positions.len()
        )));
    }

    let cell_ref = frame.cell();
    let (boxl, angles, has_pbc) = cell_to_box_and_angles(&cell_ref);
    let velocities = if frame.has_velocities() {
        Some(frame_velocities(frame)?)
    } else {
        None
    };

    let geometry = import_geometry(frame, positions, velocities.as_deref())?;

    let mut metadata = BTreeMap::new();
    for (key, prop) in frame.properties() {
        insert_mapped_or_extra(&mut metadata, &key, &prop);
    }

    if !metadata.contains_key(meta::GENERATOR) {
        metadata.insert(
            meta::GENERATOR.into(),
            Value::String(format!(
                "readcon-core {} chemfiles {}",
                crate::VERSION,
                chemfiles::version()
            )),
        );
    }

    if !metadata.contains_key(meta::FRAME_INDEX) {
        metadata.insert(meta::FRAME_INDEX.into(), json!(frame.step() as u64));
    }

    if has_pbc {
        metadata.insert(meta::PBC.into(), json!([true, true, true]));
    } else {
        metadata.insert(meta::PBC.into(), json!([false, false, false]));
    }

    if let Some(lv) = lattice_vectors_json(&cell_ref) {
        metadata.insert(meta::LATTICE_VECTORS.into(), lv);
    }

    if let Some(props) = geometry.atom_props {
        metadata.insert(CHEMFILES_ATOM_PROPS_KEY.into(), Value::Array(props));
    }
    if let Some((names, types)) = geometry.sidecars {
        metadata.insert(CHEMFILES_ATOM_NAMES_KEY.into(), Value::Array(names));
        metadata.insert(CHEMFILES_ATOM_TYPES_KEY.into(), Value::Array(types));
    }

    metadata.insert(
        format!("{CHEMFILES_EXTRA_PREFIX}library_version"),
        Value::String(chemfiles::version()),
    );
    stamp_chemfiles_units(&mut metadata);

    let mut sections = Vec::new();
    if velocities.is_some() {
        sections.push(crate::types::SECTION_VELOCITIES.into());
    }
    let header = FrameHeader {
        prebox_header: PreboxHeader::new(format!(
            "imported via chemfiles {}",
            chemfiles::version()
        )),
        boxl,
        angles,
        postbox_header: [String::new(), String::new()],
        natm_types: geometry.kinds.len(),
        natms_per_type: geometry.counts,
        masses_per_type: geometry.masses,
        spec_version: crate::CON_SPEC_VERSION,
        metadata: FrameMeta::from_map(metadata),
        sections,
        strict_validation: false,
        sections_declared: velocities.is_some(),
    };
    let mut con = crate::types::con_frame_coords_only_with_ids(
        header,
        geometry.atoms,
        geometry.positions,
        geometry.ids,
    );

    let chfl_bonds = bonds_from_chemfiles_frame(frame);
    if !chfl_bonds.is_empty() {
        let mut id_to_data_idx: BTreeMap<u64, u32> = BTreeMap::new();
        for (data_idx, atom) in con.atom_data.iter().enumerate() {
            id_to_data_idx.insert(atom.atom_id, data_idx as u32);
        }
        let mut remapped = Vec::with_capacity(chfl_bonds.len());
        for b in chfl_bonds {
            let Some(&i) = id_to_data_idx.get(&(b.i as u64)) else {
                continue;
            };
            let Some(&j) = id_to_data_idx.get(&(b.j as u64)) else {
                continue;
            };
            let mut bond = Bond::new(i, j);
            bond.order = b.order;
            remapped.push(bond);
        }
        if !remapped.is_empty() {
            con.header.set_bonds(&remapped);
        }
    }

    let chfl_residues = residues_from_chemfiles_frame(frame);
    if !chfl_residues.is_empty() {
        let mut id_to_data_idx: BTreeMap<u64, u32> = BTreeMap::new();
        for (data_idx, atom) in con.atom_data.iter().enumerate() {
            id_to_data_idx.insert(atom.atom_id, data_idx as u32);
        }
        let remapped = remap_residue_atoms(chfl_residues, &id_to_data_idx);
        if !remapped.is_empty() {
            con.header
                .metadata
                .insert(CHEMFILES_RESIDUES_KEY.into(), Value::Array(remapped));
        }
    }

    Ok(con)
}

struct ImportedKind {
    symbol: Arc<str>,
    mass: f64,
    mass_set: bool,
    canonical: bool,
}

struct ImportedGeometry {
    kinds: Vec<ImportedKind>,
    counts: Vec<usize>,
    masses: Vec<f64>,
    atoms: Vec<AtomDatum>,
    positions: FloatArray2,
    ids: Vec<u64>,
    sidecars: Option<(Vec<Value>, Vec<Value>)>,
    atom_props: Option<Vec<Value>>,
}

/// `chemfiles::Frame` is one pointer to `CHFL_FRAME` in 0.10. The safe
/// `atom().name()` builds a fresh `String` on every call.
fn frame_c_handle(frame: &Frame) -> *mut chemfiles_sys::CHFL_FRAME {
    debug_assert_eq!(
        std::mem::size_of_val(frame),
        std::mem::size_of::<*mut chemfiles_sys::CHFL_FRAME>()
    );
    unsafe { std::mem::transmute_copy(frame) }
}

unsafe extern "C" {
    fn rc_chemfiles_scan(
        frame: *mut chemfiles_sys::CHFL_FRAME,
        sym_of: *mut u32,
        names: *mut [u8; 16],
        masses: *mut f64,
        max_kinds: u32,
        n_kinds: *mut u32,
        any_extra: *mut u32,
        any_props: *mut u32,
    ) -> i32;
    fn rc_chemfiles_matches(
        frame: *mut chemfiles_sys::CHFL_FRAME,
        begin: u64,
        end: u64,
        symbol: *const std::os::raw::c_char,
        mass: f64,
        bad: *mut u32,
    ) -> i32;
    fn rc_chemfiles_atom_view(
        frame: *mut chemfiles_sys::CHFL_FRAME,
        index: u64,
        name: *mut std::os::raw::c_char,
        name_cap: u64,
        type_name: *mut std::os::raw::c_char,
        type_cap: u64,
        mass: *mut f64,
        charge: *mut f64,
        nprops: *mut u64,
    ) -> i32;
}

fn c_view(
    frame: *mut chemfiles_sys::CHFL_FRAME,
    index: usize,
    name_buf: &mut Vec<u8>,
    type_buf: &mut Vec<u8>,
) -> Result<(usize, usize, f64, f64, u64), ChemfilesImportError> {
    loop {
        name_buf.fill(0);
        type_buf.fill(0);
        let mut mass = 0.0;
        let mut charge = 0.0;
        let mut nprops = 0u64;
        let status = unsafe {
            rc_chemfiles_atom_view(
                frame,
                index as u64,
                name_buf.as_mut_ptr().cast(),
                name_buf.len() as u64,
                type_buf.as_mut_ptr().cast(),
                type_buf.len() as u64,
                &mut mass,
                &mut charge,
                &mut nprops,
            )
        };
        if status != 0 {
            return Err(ChemfilesImportError::InvalidFrame(format!(
                "chemfiles atom {index} is missing"
            )));
        }
        let name_end = name_buf.iter().position(|&byte| byte == 0).unwrap_or(0);
        let type_end = type_buf.iter().position(|&byte| byte == 0).unwrap_or(0);
        let name_full = name_end + 1 < name_buf.len();
        let type_full = type_end + 1 < type_buf.len();
        if (name_full && type_full) || name_buf.len() >= 4096 {
            return Ok((name_end, type_end, mass, charge, nprops));
        }
        if !name_full {
            name_buf.resize(name_buf.len() * 2, 0);
        }
        if !type_full {
            type_buf.resize(type_buf.len() * 2, 0);
        }
    }
}

fn intern_symbol(kinds: &mut Vec<ImportedKind>, bytes: &[u8]) -> usize {
    for (index, kind) in kinds.iter().enumerate() {
        if kind.symbol.as_bytes() == bytes {
            return index;
        }
    }
    let text = std::str::from_utf8(bytes).unwrap_or("X");
    kinds.push(ImportedKind {
        symbol: Arc::from(text),
        mass: 1.0,
        mass_set: false,
        canonical: false,
    });
    kinds.len() - 1
}

fn parallel_uniform(
    handle: *mut chemfiles_sys::CHFL_FRAME,
    positions: &[[f64; 3]],
) -> Result<Option<ImportedGeometry>, ChemfilesImportError> {
    let n = positions.len();
    let mut name_buf = vec![0u8; 32];
    let mut type_buf = vec![0u8; 32];
    let (name_end, type_end, mass, charge, nprops) =
        c_view(handle, 0, &mut name_buf, &mut type_buf)?;
    if charge != 0.0 || nprops != 0 {
        return Ok(None);
    }
    let name = &name_buf[..name_end];
    let atomic_type = &type_buf[..type_end];
    if !atomic_type.is_empty() && name != atomic_type {
        return Ok(None);
    }
    let symbol_bytes = if !atomic_type.is_empty() {
        atomic_type
    } else if !name.is_empty() {
        name
    } else {
        b"X".as_slice()
    };
    if symbol_bytes.len() >= 15 {
        return Ok(None);
    }
    let stored_mass = if mass > 0.0 { mass } else { 1.0 };
    let mut symbol_c = vec![0u8; symbol_bytes.len() + 1];
    symbol_c[..symbol_bytes.len()].copy_from_slice(symbol_bytes);
    let threads = std::thread::available_parallelism()
        .map(|count| count.get())
        .unwrap_or(1)
        .clamp(1, 8);
    let mut flags = vec![0u32; threads];
    let chunk = n.div_ceil(threads);
    let handle_bits = handle as usize;
    let symbol_bits = symbol_c.as_ptr() as usize;
    std::thread::scope(|scope| {
        for (thread, flag) in flags.iter_mut().enumerate() {
            let begin = thread * chunk;
            let end = (begin + chunk).min(n);
            if begin >= end {
                continue;
            }
            scope.spawn(move || {
                let status = unsafe {
                    rc_chemfiles_matches(
                        handle_bits as *mut chemfiles_sys::CHFL_FRAME,
                        begin as u64,
                        end as u64,
                        symbol_bits as *const std::os::raw::c_char,
                        stored_mass,
                        flag,
                    )
                };
                if status != 0 {
                    *flag = 1;
                }
            });
        }
    });
    if flags.iter().any(|flag| *flag != 0) {
        return Ok(None);
    }
    let text = std::str::from_utf8(symbol_bytes).unwrap_or("X");
    let symbol: Arc<str> = Arc::from(text);
    let mut flat = Vec::with_capacity(n * 3);
    let src = unsafe { std::slice::from_raw_parts(positions.as_ptr().cast::<f64>(), n * 3) };
    flat.extend_from_slice(src);
    let xyz = flat.as_mut_ptr();
    crate::types::bump_arc_str(&symbol, n);
    let mut slots: Vec<std::mem::MaybeUninit<AtomDatum>> = Vec::with_capacity(n);
    // Every index is written before this buffer is read as `AtomDatum`.
    unsafe { slots.set_len(n) };
    let slot_bits = slots.as_mut_ptr() as usize;
    let xyz_bits = xyz as usize;
    let symbol_ref = &symbol;
    std::thread::scope(|scope| {
        for thread in 0..threads {
            let begin = thread * chunk;
            let end = (begin + chunk).min(n);
            if begin >= end {
                continue;
            }
            scope.spawn(move || {
                let slot_ptr = slot_bits as *mut std::mem::MaybeUninit<AtomDatum>;
                let xyz = xyz_bits as *mut f64;
                for index in begin..end {
                    let arc = crate::types::share_arc_str(symbol_ref);
                    let coord = unsafe { xyz.add(index * 3) };
                    unsafe {
                        (*slot_ptr.add(index)).write(AtomDatum::at_slot(
                            arc,
                            coord,
                            [false, false, false],
                            index as u64,
                        ));
                    }
                }
            });
        }
    });
    let slot_ptr = slot_bits as *mut std::mem::MaybeUninit<AtomDatum>;
    let capacity = slots.capacity();
    let atoms = unsafe { Vec::from_raw_parts(slot_ptr.cast::<AtomDatum>(), n, capacity) };
    std::mem::forget(slots);
    crate::types::mark_uniform_symbol_drop(&atoms);
    let ids: Vec<u64> = (0..n as u64).collect();
    Ok(Some(ImportedGeometry {
        kinds: vec![ImportedKind {
            symbol,
            mass: stored_mass,
            mass_set: true,
            canonical: true,
        }],
        counts: vec![n],
        masses: vec![stored_mass],
        atoms,
        positions: FloatArray2::from_f64_row_major(n, 3, flat),
        ids,
        sidecars: None,
        atom_props: None,
    }))
}

fn scan_uniform(
    handle: *mut chemfiles_sys::CHFL_FRAME,
    positions: &[[f64; 3]],
    velocities: Option<&[[f64; 3]]>,
) -> Result<Option<ImportedGeometry>, ChemfilesImportError> {
    let n = positions.len();
    if n == 0 {
        return Ok(None);
    }
    // The allocation bound is measured on a few thousand atoms, on one thread.
    // A million-atom frame is checked in disjoint ranges.
    if velocities.is_none() && n >= 65_536 {
        if let Some(geometry) = parallel_uniform(handle, positions)? {
            return Ok(Some(geometry));
        }
    }
    const MAX_KINDS: usize = 64;
    let mut sym_of = vec![0u32; n];
    let mut names = [[0u8; 16]; MAX_KINDS];
    let mut mass_of = [0.0f64; MAX_KINDS];
    let mut n_kinds = 0u32;
    let mut any_extra = 0u32;
    let mut any_props = 0u32;
    let status = unsafe {
        rc_chemfiles_scan(
            handle,
            sym_of.as_mut_ptr(),
            names.as_mut_ptr(),
            mass_of.as_mut_ptr(),
            MAX_KINDS as u32,
            &mut n_kinds,
            &mut any_extra,
            &mut any_props,
        )
    };
    if status == 3 || any_extra != 0 || any_props != 0 {
        return Ok(None);
    }
    if status != 0 {
        return Err(ChemfilesImportError::InvalidFrame(
            "chemfiles frame scan failed".into(),
        ));
    }
    let n_kinds = n_kinds as usize;
    let mut kinds = Vec::with_capacity(n_kinds);
    for index in 0..n_kinds {
        let end = names[index].iter().position(|&byte| byte == 0).unwrap_or(0);
        let text = std::str::from_utf8(&names[index][..end]).unwrap_or("X");
        kinds.push(ImportedKind {
            symbol: Arc::from(text),
            mass: mass_of[index],
            mass_set: true,
            canonical: true,
        });
    }
    if n_kinds == 1 && velocities.is_none() {
        let symbol = Arc::clone(&kinds[0].symbol);
        let mut flat = Vec::with_capacity(n * 3);
        let src = unsafe { std::slice::from_raw_parts(positions.as_ptr().cast::<f64>(), n * 3) };
        flat.extend_from_slice(src);
        let mut atoms = Vec::with_capacity(n);
        let mut ids = Vec::with_capacity(n);
        let ptr = flat.as_mut_ptr();
        crate::types::bump_arc_str(&symbol, n);
        for grouped in 0..n {
            let slot = unsafe { ptr.add(grouped * 3) };
            atoms.push(AtomDatum::at_slot(
                crate::types::share_arc_str(&symbol),
                slot,
                [false, false, false],
                grouped as u64,
            ));
            ids.push(grouped as u64);
        }
        crate::types::mark_uniform_symbol_drop(&atoms);
        let positions_soa = FloatArray2::from_f64_row_major(n, 3, flat);
        let masses = vec![kinds[0].mass];
        return Ok(Some(ImportedGeometry {
            kinds,
            counts: vec![n],
            masses,
            atoms,
            positions: positions_soa,
            ids,
            sidecars: None,
            atom_props: None,
        }));
    }
    let mut counts = vec![0usize; n_kinds];
    for &kind in &sym_of {
        counts[kind as usize] += 1;
    }
    let mut cursor = Vec::with_capacity(n_kinds);
    let mut start = 0usize;
    for &count in &counts {
        cursor.push(start);
        start += count;
    }
    let mut chem_at = vec![0usize; n];
    let mut next = cursor;
    for (index, &kind) in sym_of.iter().enumerate() {
        let slot = next[kind as usize];
        next[kind as usize] = slot + 1;
        chem_at[slot] = index;
    }
    let mut flat = vec![0.0f64; n * 3];
    for grouped in 0..n {
        let chem = chem_at[grouped];
        let row = positions[chem];
        flat[grouped * 3..grouped * 3 + 3].copy_from_slice(&row);
    }
    let mut atoms = Vec::with_capacity(n);
    let mut ids = Vec::with_capacity(n);
    let ptr = flat.as_mut_ptr();
    for grouped in 0..n {
        let chem = chem_at[grouped];
        let kind = sym_of[chem] as usize;
        let symbol = Arc::clone(&kinds[kind].symbol);
        let atom_id = chem as u64;
        if let Some(vels) = velocities {
            let row = positions[chem];
            atoms.push(AtomDatum::with_sections(
                symbol,
                row[0],
                row[1],
                row[2],
                [false, false, false],
                atom_id,
                Some(vels[chem]),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ));
        } else {
            let slot = unsafe { ptr.add(grouped * 3) };
            atoms.push(AtomDatum::at_slot(
                symbol,
                slot,
                [false, false, false],
                atom_id,
            ));
        }
        ids.push(atom_id);
    }
    let positions_soa = FloatArray2::from_f64_row_major(n, 3, flat);
    let masses = kinds.iter().map(|kind| kind.mass).collect();
    Ok(Some(ImportedGeometry {
        kinds,
        counts,
        masses,
        atoms,
        positions: positions_soa,
        ids,
        sidecars: None,
        atom_props: None,
    }))
}

fn import_geometry(
    frame: &Frame,
    positions: &[[f64; 3]],
    velocities: Option<&[[f64; 3]]>,
) -> Result<ImportedGeometry, ChemfilesImportError> {
    let n = positions.len();
    let handle = frame_c_handle(frame);
    if let Some(geometry) = scan_uniform(handle, positions, velocities)? {
        return Ok(geometry);
    }
    let mut kinds: Vec<ImportedKind> = Vec::new();
    let mut sym_of = Vec::with_capacity(n);
    let mut name_buf = vec![0u8; 32];
    let mut type_buf = vec![0u8; 32];
    let mut extras: Vec<(usize, String, String)> = Vec::new();
    let mut props: Vec<BTreeMap<String, Value>> = Vec::new();
    let mut any_props = false;

    for index in 0..n {
        let (name_end, type_end, mass, charge, prop_count) =
            c_view(handle, index, &mut name_buf, &mut type_buf)?;
        let name = &name_buf[..name_end];
        let atomic_type = &type_buf[..type_end];
        let symbol = if !atomic_type.is_empty() {
            atomic_type
        } else if !name.is_empty() {
            name
        } else {
            b"X".as_slice()
        };
        let kind = intern_symbol(&mut kinds, symbol);
        let canonical = name == atomic_type;
        if mass > 0.0 {
            let slot = &mut kinds[kind];
            let replace = !slot.mass_set || (canonical && !slot.canonical);
            if replace {
                slot.mass = mass;
                slot.mass_set = true;
                slot.canonical = canonical;
            }
        }
        let display_differs = !name.is_empty() && name != symbol;
        let type_differs = !atomic_type.is_empty() && atomic_type != symbol;
        if display_differs || type_differs {
            let display = if name.is_empty() {
                std::str::from_utf8(symbol).unwrap_or("X").to_string()
            } else {
                std::str::from_utf8(name).unwrap_or("X").to_string()
            };
            let type_text = if atomic_type.is_empty() {
                std::str::from_utf8(symbol).unwrap_or("X").to_string()
            } else {
                std::str::from_utf8(atomic_type).unwrap_or("X").to_string()
            };
            extras.push((index, display, type_text));
        }
        if prop_count > 0 || charge != 0.0 {
            if !any_props {
                props.resize_with(index, BTreeMap::new);
                any_props = true;
            }
            let mut bag = BTreeMap::new();
            for (key, prop) in frame.atom(index).properties() {
                bag.insert(key, property_to_json(&prop));
            }
            if charge != 0.0 {
                bag.entry("charge".into()).or_insert_with(|| json!(charge));
            }
            props.push(bag);
        } else if any_props {
            props.push(BTreeMap::new());
        }
        sym_of.push(kind as u32);
    }

    let n_kinds = kinds.len();
    let mut counts = vec![0usize; n_kinds];
    for &kind in &sym_of {
        counts[kind as usize] += 1;
    }
    let mut cursor = Vec::with_capacity(n_kinds);
    let mut start = 0usize;
    for &count in &counts {
        cursor.push(start);
        start += count;
    }
    let mut place = vec![0usize; n];
    let mut chem_at = vec![0usize; n];
    let mut next = cursor;
    for (index, &kind) in sym_of.iter().enumerate() {
        let slot = next[kind as usize];
        next[kind as usize] = slot + 1;
        place[index] = slot;
        chem_at[slot] = index;
    }

    let mut flat = vec![0.0f64; n.saturating_mul(3)];
    for (index, row) in positions.iter().enumerate() {
        let slot = place[index] * 3;
        flat[slot..slot + 3].copy_from_slice(row);
    }
    let mut atoms = Vec::with_capacity(n);
    let mut ids = Vec::with_capacity(n);
    let ptr = flat.as_mut_ptr();
    for grouped in 0..n {
        let chem = chem_at[grouped];
        let kind = sym_of[chem] as usize;
        let symbol = Arc::clone(&kinds[kind].symbol);
        let atom_id = chem as u64;
        if let Some(vels) = velocities {
            let row = positions[chem];
            atoms.push(AtomDatum::with_sections(
                symbol,
                row[0],
                row[1],
                row[2],
                [false, false, false],
                atom_id,
                Some(vels[chem]),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ));
        } else {
            let slot = unsafe { ptr.add(grouped * 3) };
            atoms.push(AtomDatum::at_slot(
                symbol,
                slot,
                [false, false, false],
                atom_id,
            ));
        }
        ids.push(atom_id);
    }
    let positions_soa = FloatArray2::from_f64_row_major(n, 3, flat);
    // `from_f64_row_major` keeps the `Vec` allocation. Slots already point at it.

    let sidecars = if extras.is_empty() {
        None
    } else {
        let mut names = Vec::with_capacity(n);
        let mut types = Vec::with_capacity(n);
        let mut extra_at = vec![None; n];
        for (index, display, atomic_type) in extras {
            extra_at[index] = Some((display, atomic_type));
        }
        for index in 0..n {
            let kind = &kinds[sym_of[index] as usize];
            let symbol = kind.symbol.as_ref().to_string();
            if let Some((display, atomic_type)) = extra_at[index].take() {
                names.push(Value::String(display));
                types.push(Value::String(atomic_type));
            } else {
                names.push(Value::String(symbol.clone()));
                types.push(Value::String(symbol));
            }
        }
        Some((names, types))
    };
    let atom_props = if any_props {
        Some(
            props
                .into_iter()
                .map(|bag| Value::Object(bag.into_iter().collect()))
                .collect(),
        )
    } else {
        None
    };
    let masses = kinds.iter().map(|kind| kind.mass).collect();
    Ok(ImportedGeometry {
        kinds,
        counts,
        masses,
        atoms,
        positions: positions_soa,
        ids,
        sidecars,
        atom_props,
    })
}

/// Open a trajectory with chemfiles and convert every step to [`ConFrame`].
pub fn con_frames_from_trajectory_path<P: AsRef<Path>>(
    path: P,
) -> Result<Vec<ConFrame>, ChemfilesImportError> {
    con_frames_from_trajectory_path_with(path, &ChemfilesReadOpts::default())
}

/// Open a trajectory with skip / stride / topology / `guess_bonds`.
///
/// Uses sequential [`Trajectory::read`] for the dense `start=0, step=1, stop=None`
/// path. Any other window uses [`Trajectory::read_step`].
pub fn con_frames_from_trajectory_path_with<P: AsRef<Path>>(
    path: P,
    opts: &ChemfilesReadOpts,
) -> Result<Vec<ConFrame>, ChemfilesImportError> {
    let path = path.as_ref();
    let stride = opts.stride().map_err(ChemfilesImportError::InvalidFrame)?;
    let mut traj = open_trajectory(path, opts)?;
    let nsteps = traj.nsteps();
    let start = opts.start;
    let end = opts.stop.unwrap_or(nsteps).min(nsteps);
    if start > end {
        return Err(ChemfilesImportError::InvalidFrame(format!(
            "chemfiles start {start} is past stop {end} ({nsteps} steps)"
        )));
    }
    let mut frames = Vec::new();
    let mut chfl_frame = Frame::new();
    let dense = start == 0 && stride == 1 && opts.stop.is_none();
    if dense {
        for _ in 0..nsteps {
            traj.read(&mut chfl_frame)?;
            apply_guess_bonds(&mut chfl_frame, opts.guess_bonds)?;
            frames.push(con_frame_from_chemfiles(&chfl_frame)?);
        }
    } else {
        let mut i = start;
        while i < end {
            traj.read_step(i, &mut chfl_frame)?;
            apply_guess_bonds(&mut chfl_frame, opts.guess_bonds)?;
            frames.push(con_frame_from_chemfiles(&chfl_frame)?);
            i = i.saturating_add(stride);
        }
    }
    Ok(frames)
}

/// Read the first frame from a trajectory path.
pub fn con_frame_from_trajectory_path<P: AsRef<Path>>(
    path: P,
) -> Result<ConFrame, ChemfilesImportError> {
    con_frame_from_trajectory_path_nth(path, 0)
}

/// Read step `index` via chemfiles [`Trajectory::read_step`].
pub fn con_frame_from_trajectory_path_nth<P: AsRef<Path>>(
    path: P,
    index: usize,
) -> Result<ConFrame, ChemfilesImportError> {
    let path = path.as_ref();
    let mut traj = Trajectory::open(path, 'r')?;
    let nsteps = traj.nsteps();
    if index >= nsteps {
        return Err(ChemfilesImportError::InvalidFrame(format!(
            "frame {index} out of range ({nsteps} steps)"
        )));
    }
    let mut chfl_frame = Frame::new();
    traj.read_step(index, &mut chfl_frame)?;
    con_frame_from_chemfiles(&chfl_frame)
}

/// Number of steps in a chemfiles trajectory ([`Trajectory::nsteps`]).
pub fn nsteps_from_trajectory_path<P: AsRef<Path>>(path: P) -> Result<usize, ChemfilesImportError> {
    let mut traj = Trajectory::open(path.as_ref(), 'r')?;
    Ok(traj.nsteps())
}

/// Read a trajectory from an in-memory buffer (chemfiles memory reader).
///
/// `format` is a chemfiles format string such as `"XYZ"` or `"PDB"`.
pub fn con_frames_from_memory(
    data: &str,
    format: &str,
) -> Result<Vec<ConFrame>, ChemfilesImportError> {
    con_frames_from_memory_with(data, format, &ChemfilesReadOpts::default())
}

/// In-memory read with skip / stride / `guess_bonds`.
pub fn con_frames_from_memory_with(
    data: &str,
    format: &str,
    opts: &ChemfilesReadOpts,
) -> Result<Vec<ConFrame>, ChemfilesImportError> {
    use chemfiles::MemoryTrajectoryReader;
    let stride = opts.stride().map_err(ChemfilesImportError::InvalidFrame)?;
    let mut reader = MemoryTrajectoryReader::new(data.as_bytes(), format)?;
    let nsteps = reader.nsteps();
    let start = opts.start;
    let end = opts.stop.unwrap_or(nsteps).min(nsteps);
    let mut frames = Vec::new();
    let mut chfl_frame = Frame::new();
    for i in 0..nsteps {
        reader.read(&mut chfl_frame)?;
        if i < start || i >= end || !(i - start).is_multiple_of(stride) {
            continue;
        }
        apply_guess_bonds(&mut chfl_frame, opts.guess_bonds)?;
        frames.push(con_frame_from_chemfiles(&chfl_frame)?);
    }
    Ok(frames)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chemfiles::{Atom, Frame, Property, UnitCell};
    use std::io::Write;

    fn make_water_frame() -> Frame {
        let mut frame = Frame::new();
        frame.add_atom(&Atom::new("O"), [0.0, 0.0, 0.0], None);
        frame.add_atom(&Atom::new("H"), [0.96, 0.0, 0.0], None);
        frame.add_atom(&Atom::new("H"), [-0.24, 0.93, 0.0], None);
        frame.set_cell(&UnitCell::new([10.0, 10.0, 10.0]));
        frame.set_step(7);
        frame.set("energy", Property::Double(-12.5));
        frame.set("custom_note", Property::String("hello".into()));
        frame.set("time", Property::Double(1.25));
        frame
    }

    #[test]
    fn name_type_split_uses_one_mass_per_con_symbol() {
        let mut frame = Frame::new();
        let mut h1 = Atom::new("H1");
        h1.set_atomic_type("H");
        frame.add_atom(&h1, [0.0, 1.0, 2.0], None);
        frame.add_atom(&Atom::new("O"), [1.0, 2.0, 3.0], None);
        frame.add_atom(&Atom::new("O"), [2.0, 3.0, 4.0], None);
        frame.add_atom(&Atom::new("H"), [3.0, 4.0, 5.0], None);
        frame.set_cell(&UnitCell::new([10.0, 10.0, 10.0]));
        let con = con_frame_from_chemfiles(&frame).expect("H1 and H share CON type H");
        assert_eq!(con.header.natm_types, 2);
        assert_eq!(
            con.atom_data
                .iter()
                .filter(|a| a.symbol.as_ref() == "H")
                .count(),
            2
        );
        assert!(
            con.header
                .masses_per_type
                .iter()
                .any(|m| *m > 1.0 && *m < 2.0),
            "expected a hydrogen mass, got {:?}",
            con.header.masses_per_type
        );
    }

    #[test]
    fn converts_geometry_and_mapped_metadata() {
        let frame = make_water_frame();
        let con = con_frame_from_chemfiles(&frame).expect("convert");
        assert_eq!(con.atom_data.len(), 3);
        assert_eq!(con.header.boxl, [10.0, 10.0, 10.0]);
        assert_eq!(con.header.angles, [90.0, 90.0, 90.0]);
        assert_eq!(con.header.natm_types, 2); // O and H grouped

        let symbols: Vec<&str> = con.atom_data.iter().map(|a| a.symbol.as_ref()).collect();
        assert!(symbols.contains(&"O"));
        assert!(symbols.contains(&"H"));

        assert_eq!(con.header.energy(), Some(-12.5));
        assert_eq!(con.header.time(), Some(1.25));
        assert_eq!(con.header.frame_index(), Some(7));

        let generator = con
            .header
            .metadata
            .get(meta::GENERATOR)
            .and_then(|v| v.as_str())
            .unwrap_or("");
        assert!(generator.contains("readcon-core"), "generator={generator}");
        assert!(generator.contains("chemfiles"), "generator={generator}");

        let extra = con
            .header
            .metadata
            .get(&format!("{CHEMFILES_EXTRA_PREFIX}custom_note"))
            .and_then(|v| v.as_str());
        assert_eq!(extra, Some("hello"));

        assert!(con.header.metadata.contains_key(meta::PBC));
        assert!(con.header.metadata.contains_key(meta::LATTICE_VECTORS));
        assert!(
            con.header
                .metadata
                .contains_key(&format!("{CHEMFILES_EXTRA_PREFIX}library_version"))
        );
    }

    #[test]
    fn a_star_count_line_does_not_abort() {
        let result = std::panic::catch_unwind(|| con_frames_from_memory("*\n\n", "XYZ"));
        let err = result
            .expect("chemfiles import panicked")
            .expect_err("not a frame");
        let message = err.to_string();
        assert!(
            message.contains("position")
                || message.contains("atoms")
                || message.contains("XYZ")
                || message.contains("chemfiles"),
            "{message}"
        );
    }

    #[test]
    fn copies_velocities_when_present() {
        let mut frame = Frame::new();
        frame.add_atom(&Atom::new("Cu"), [1.0, 2.0, 3.0], Some([0.1, 0.2, 0.3]));
        frame.add_velocities();
        {
            let vels = frame.velocities_mut().expect("vel buffer");
            vels[0] = [0.1, 0.2, 0.3];
        }
        frame.set_cell(&UnitCell::new([5.0, 5.0, 5.0]));

        let con = con_frame_from_chemfiles(&frame).expect("convert");
        assert!(con.has_velocities());
        let atom = &con.atom_data[0];
        let v = atom.velocity().expect("velocity on atom");
        assert!((v[0] - 0.1).abs() < 1e-12);
        assert!((v[1] - 0.2).abs() < 1e-12);
        assert!((v[2] - 0.3).abs() < 1e-12);
    }

    #[test]
    fn infinite_cell_sets_non_pbc_metadata() {
        let mut frame = Frame::new();
        frame.add_atom(&Atom::new("Ar"), [0.0, 0.0, 0.0], None);
        frame.set_cell(&UnitCell::infinite());
        let con = con_frame_from_chemfiles(&frame).expect("convert");
        let pbc = con.header.pbc().expect("pbc");
        assert_eq!(pbc, [false, false, false]);
        assert!(!con.header.metadata.contains_key(meta::LATTICE_VECTORS));
    }

    #[test]
    fn property_key_mapping_covers_aliases() {
        assert_eq!(map_frame_property_key("energy"), Some(meta::ENERGY));
        assert_eq!(map_frame_property_key("E_pot"), Some(meta::ENERGY));
        assert_eq!(map_frame_property_key("timestep"), Some(meta::TIMESTEP));
        assert_eq!(map_frame_property_key("dt"), Some(meta::TIMESTEP));
        assert_eq!(map_frame_property_key("weird_prop"), None);
    }

    #[test]
    fn imports_xyz_from_memory_via_chemfiles() {
        let xyz = "\
2
chemfiles xyz fixture
Cu 0.0 0.0 0.0
H  1.0 0.0 0.0
";
        let frames = con_frames_from_memory(xyz, "XYZ").expect("memory xyz");
        assert_eq!(frames.len(), 1);
        let con = &frames[0];
        assert_eq!(con.atom_data.len(), 2);
        let symbols: Vec<&str> = con.atom_data.iter().map(|a| a.symbol.as_ref()).collect();
        assert!(symbols.contains(&"Cu"));
        assert!(symbols.contains(&"H"));
        // XYZ via chemfiles typically has infinite/default cell
        assert!(con.header.metadata.contains_key(meta::GENERATOR));
    }

    #[test]
    fn imports_xyz_from_temp_file_via_chemfiles_io() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("water_fixture.xyz");
        {
            let mut f = std::fs::File::create(&path).expect("create xyz");
            write!(
                f,
                "\
3
water-like
O  0.000  0.000  0.000
H  0.957  0.000  0.000
H -0.240  0.927  0.000
"
            )
            .expect("write xyz");
        }

        let con = con_frame_from_trajectory_path(&path).expect("read xyz path");
        assert_eq!(con.atom_data.len(), 3);
        assert_eq!(con.header.natm_types, 2);
        let positions_ok = con.atom_data.iter().any(|a| {
            a.symbol.as_ref() == "O"
                && a.x().abs() < 1e-6
                && a.y().abs() < 1e-6
                && a.z().abs() < 1e-6
        });
        assert!(positions_ok, "expected O at origin in converted frame");
    }

    #[test]
    fn atom_properties_land_in_metadata_bag() {
        let mut frame = Frame::new();
        let mut atom = Atom::new("C");
        atom.set("partial_charge", Property::Double(-0.5));
        frame.add_atom(&atom, [0.0, 0.0, 0.0], None);
        frame.set_cell(&UnitCell::new([1.0, 1.0, 1.0]));

        let con = con_frame_from_chemfiles(&frame).expect("convert");
        let bag = con
            .header
            .metadata
            .get(CHEMFILES_ATOM_PROPS_KEY)
            .and_then(|v| v.as_array())
            .expect("atom props array");
        assert_eq!(bag.len(), 1);
        let q = bag[0]
            .get("partial_charge")
            .and_then(|v| v.as_f64())
            .expect("partial_charge");
        assert!((q - (-0.5)).abs() < 1e-12);
    }

    #[test]
    fn stamps_chemfiles_internal_units_not_con_default_fs() {
        let frame = make_water_frame();
        let con = con_frame_from_chemfiles(&frame).expect("convert");
        assert_eq!(con.header.length_unit(), Some("angstrom"));
        assert_eq!(con.header.unit_for("time"), Some("ps"));
        assert_eq!(con.header.unit_for("mass"), Some("amu"));
        assert_eq!(con.header.energy_unit(), Some("eV"));
        let sys = con
            .header
            .metadata
            .get(CHEMFILES_UNIT_SYSTEM_KEY)
            .and_then(|v| v.as_object())
            .expect("unit_system");
        assert_eq!(
            sys.get("velocity").and_then(|v| v.as_str()),
            Some("angstrom/ps")
        );
        assert_eq!(sys.get("angle").and_then(|v| v.as_str()), Some("degree"));
    }

    #[test]
    fn gro_nm_converts_to_angstrom_via_chemfiles() {
        // GROMACS .gro is nm; chemfiles converts lengths to Å.
        let gro = "\
water
    2
    1WATER  OW     1   0.000   0.000   0.000
    1WATER  HW     2   0.100   0.000   0.000
   1.00000   1.00000   1.00000
";
        let frames = con_frames_from_memory(gro, "GRO").expect("gro");
        assert_eq!(frames.len(), 1);
        let con = &frames[0];
        assert_eq!(con.header.length_unit(), Some("angstrom"));
        assert!(
            (con.header.boxl[0] - 10.0).abs() < 1e-6,
            "box={:?}",
            con.header.boxl
        );
        let hw = con
            .atom_data
            .iter()
            .find(|a| a.symbol.as_ref() == "H" || a.symbol.as_ref() == "HW")
            .expect("H");
        // 0.100 nm → 1.00 Å
        assert!(
            (hw.x() - 1.0).abs() < 1e-6,
            "H.x()={} (expected 1 Å)",
            hw.x()
        );
        let residues = con
            .header
            .metadata
            .get(CHEMFILES_RESIDUES_KEY)
            .and_then(|v| v.as_array())
            .expect("residues");
        assert!(!residues.is_empty());
        assert_eq!(
            residues[0].get("name").and_then(|v| v.as_str()),
            Some("WATER")
        );
    }

    #[test]
    fn read_step_nth_and_stride() {
        let xyz = "\
2
frame0
Cu 0.0 0.0 0.0
H  1.0 0.0 0.0
2
frame1
Cu 2.0 0.0 0.0
H  3.0 0.0 0.0
2
frame2
Cu 4.0 0.0 0.0
H  5.0 0.0 0.0
";
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("three.xyz");
        std::fs::write(&path, xyz).expect("write");

        assert_eq!(nsteps_from_trajectory_path(&path).expect("nsteps"), 3);
        let mid = con_frame_from_trajectory_path_nth(&path, 1).expect("nth 1");
        let cu = mid
            .atom_data
            .iter()
            .find(|a| a.symbol.as_ref() == "Cu")
            .expect("Cu");
        assert!((cu.x() - 2.0).abs() < 1e-12);

        let opts = ChemfilesReadOpts {
            start: 0,
            step: 2,
            stop: None,
            ..ChemfilesReadOpts::default()
        };
        let strided = con_frames_from_trajectory_path_with(&path, &opts).expect("stride");
        assert_eq!(strided.len(), 2); // frames 0 and 2
        let cu0 = strided[0]
            .atom_data
            .iter()
            .find(|a| a.symbol.as_ref() == "Cu")
            .unwrap();
        let cu2 = strided[1]
            .atom_data
            .iter()
            .find(|a| a.symbol.as_ref() == "Cu")
            .unwrap();
        assert!((cu0.x() - 0.0).abs() < 1e-12);
        assert!((cu2.x() - 4.0).abs() < 1e-12);

        let err = con_frame_from_trajectory_path_nth(&path, 99).unwrap_err();
        assert!(err.to_string().contains("out of range"), "{err}");
    }

    #[test]
    fn guess_bonds_adds_water_topology() {
        let xyz = "\
3
water
O  0.000  0.000  0.000
H  0.957  0.000  0.000
H -0.240  0.927  0.000
";
        let plain = con_frames_from_memory(xyz, "XYZ").expect("plain");
        assert!(
            !plain[0].header.has_bonds(),
            "XYZ has no bonds unless guessed"
        );
        let opts = ChemfilesReadOpts {
            guess_bonds: true,
            ..ChemfilesReadOpts::default()
        };
        let guessed = con_frames_from_memory_with(xyz, "XYZ", &opts).expect("guess");
        let bonds = guessed[0].header.bonds();
        assert_eq!(bonds.len(), 2, "water should guess 2 O-H bonds");
    }

    #[test]
    fn residues_from_constructed_frame() {
        use chemfiles::Residue;
        let mut frame = Frame::new();
        frame.add_atom(&Atom::new("N"), [0.0, 0.0, 0.0], None);
        frame.add_atom(&Atom::new("CA"), [1.0, 0.0, 0.0], None);
        frame.add_atom(&Atom::new("C"), [2.0, 0.0, 0.0], None);
        let mut res = Residue::with_id("ALA", 7);
        res.add_atom(0);
        res.add_atom(1);
        res.add_atom(2);
        frame.add_residue(&res).expect("add residue");
        frame.set_cell(&UnitCell::new([10.0, 10.0, 10.0]));
        let con = con_frame_from_chemfiles(&frame).expect("convert");
        let residues = con
            .header
            .metadata
            .get(CHEMFILES_RESIDUES_KEY)
            .and_then(|v| v.as_array())
            .expect("residues");
        assert_eq!(residues.len(), 1);
        assert_eq!(
            residues[0].get("name").and_then(|v| v.as_str()),
            Some("ALA")
        );
        assert_eq!(residues[0].get("id").and_then(|v| v.as_i64()), Some(7));
        assert_eq!(
            residues[0]
                .get("atoms")
                .and_then(|v| v.as_array())
                .map(|a| a.len()),
            Some(3)
        );
    }

    #[test]
    fn extended_xyz_lattice_becomes_box_lengths() {
        let xyz = "\
1
Properties=species:S:1:pos:R:3 Lattice=\"2 0 0 0 2.5 0 0 0 3\"
Cu 0.00000000 0.00000000 0.00000000
";
        let frames = con_frames_from_memory(xyz, "XYZ").expect("xyz");
        let boxl = frames[0].header.boxl;
        assert!((boxl[0] - 2.0).abs() < 1e-6, "{boxl:?}");
        assert!((boxl[1] - 2.5).abs() < 1e-6, "{boxl:?}");
        assert!((boxl[2] - 3.0).abs() < 1e-6, "{boxl:?}");
        for angle in frames[0].header.angles {
            assert!((angle - 90.0).abs() < 1e-6, "{angle}");
        }
    }

    /// Identical atoms must share one symbol and must not allocate a heap
    /// block per atom. The old import cloned a name, a type, and a JSON
    /// sidecar for every atom, which was several allocations each.
    #[test]
    fn uniform_import_allocates_less_than_once_per_atom() {
        let n = 2048usize;
        let mut frame = Frame::new();
        frame.resize(n);
        {
            let pos = frame.positions_mut();
            for (index, row) in pos.iter_mut().enumerate() {
                *row = [index as f64, 0.0, 1.0];
            }
        }
        for index in 0..n {
            frame.atom_mut(index).set_name("Cu");
            frame.atom_mut(index).set_atomic_type("Cu");
        }
        let before = mimalloc_mallocs();
        let con = con_frame_from_chemfiles(&frame).expect("import");
        let after = mimalloc_mallocs();
        let delta = after.saturating_sub(before);
        let shared = Arc::clone(&con.atom_data[0].symbol);
        assert!(
            con.atom_data
                .iter()
                .all(|atom| Arc::ptr_eq(&atom.symbol, &shared)),
            "identical symbols were not one allocation"
        );
        assert!(
            !con.header.metadata.contains_key(CHEMFILES_ATOM_NAMES_KEY),
            "a uniform frame stored a name string per atom"
        );
        assert_eq!(con.atom_data[3].x(), 3.0);
        assert!(
            delta < n as u64,
            "bridge allocated {delta} times for {n} identical atoms (limit {n})"
        );
    }
}

fn mimalloc_mallocs() -> u64 {
    let stats = mimalloc::MiMalloc::stats_json().expect("mimalloc stats");
    let text = stats.to_str().expect("stats utf-8");
    // Count every `"count":N` under the process stats. The snapshot itself
    // allocates, so callers subtract two snapshots.
    let mut total = 0u64;
    for chunk in text.split("\"count\":") {
        let digits: String = chunk
            .chars()
            .skip_while(|c| c.is_whitespace())
            .take_while(|c| c.is_ascii_digit())
            .collect();
        if let Ok(value) = digits.parse::<u64>() {
            total += value;
        }
    }
    total
}
