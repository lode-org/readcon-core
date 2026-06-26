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

use chemfiles::{BondOrder, CellShape, Frame, Property, Trajectory, UnitCell};
use serde_json::{json, Value};

use crate::types::{meta, Bond, ConFrame, ConFrameBuilder};

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
    name.trim().to_ascii_lowercase().replace('-', "_").replace(' ', "_")
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
            (meta::ENERGY | meta::TIME | meta::TIMESTEP | meta::FMAX
             | meta::CONVERGENCE_FMAX | meta::CONVERGENCE_ENERGY, Property::Double(d)) => {
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
/// - Positions always come from the frame.
/// - Velocities are copied when `frame.has_velocities()` is true.
/// - Chemfiles has no standard per-atom forces API; if a frame property
///   `forces` is present as a string it is ignored (cannot map safely).
/// - Frame properties map into reserved `meta::*` keys when names align;
///   otherwise they are stored under `chemfiles::<name>`.
/// - Per-atom properties are collected under `chemfiles_atom_properties`.
/// - Chemfiles topology bonds are stored under reserved `metadata["bonds"]`
///   (optional; absent when the chemfiles frame has no bonds).
/// - `generator` defaults to `readcon-core chemfiles import` when unset.
/// - `frame_index` defaults to chemfiles `step` when unset.
pub fn con_frame_from_chemfiles(frame: &Frame) -> Result<ConFrame, ChemfilesImportError> {
    let n = frame.size();
    let positions = frame.positions();
    if positions.len() != n {
        return Err(ChemfilesImportError::InvalidFrame(format!(
            "position count {} != atom count {n}",
            positions.len()
        )));
    }

    let cell_ref = frame.cell();
    let (boxl, angles, has_pbc) = cell_to_box_and_angles(&cell_ref);
    let mut builder = ConFrameBuilder::new(boxl, angles);
    builder.prebox_header(format!(
        "imported via chemfiles {}",
        chemfiles::version()
    ));

    let velocities = if frame.has_velocities() {
        frame.velocities()
    } else {
        None
    };

    let mut atom_props_all: Vec<BTreeMap<String, Value>> = Vec::with_capacity(n);
    // Parallel arrays in chemfiles index order (= atom_id); survive type-grouped build.
    let mut chfl_names: Vec<String> = Vec::with_capacity(n);
    let mut chfl_types: Vec<String> = Vec::with_capacity(n);
    let mut any_name_type_extra = false;

    for i in 0..n {
        let atom = frame.atom(i);
        let chfl_name = atom.name();
        let chfl_type = atom.atomic_type();
        let symbol = {
            if !chfl_type.is_empty() {
                chfl_type.clone()
            } else if !chfl_name.is_empty() {
                chfl_name.clone()
            } else {
                "X".to_string()
            }
        };
        let display_name = if !chfl_name.is_empty() {
            chfl_name.clone()
        } else {
            symbol.clone()
        };
        let atomic_type_str = if !chfl_type.is_empty() {
            chfl_type.clone()
        } else {
            symbol.clone()
        };
        if display_name != symbol || atomic_type_str != symbol {
            any_name_type_extra = true;
        }
        chfl_names.push(display_name);
        chfl_types.push(atomic_type_str);

        let mass = atom.mass();
        let mass = if mass > 0.0 { mass } else { 1.0 };
        let pos = positions[i];
        // chemfiles has no fix/constraint flags; default all mobile.
        let fixed = [false, false, false];
        builder.add_atom(&symbol, pos[0], pos[1], pos[2], fixed, i as u64, mass);
        if let Some(vels) = velocities {
            if let Some(v) = vels.get(i) {
                builder.with_velocity(*v);
            }
        }

        let mut atom_props = BTreeMap::new();
        for (key, prop) in atom.properties() {
            atom_props.insert(key, property_to_json(&prop));
        }
        if atom.charge() != 0.0 {
            atom_props
                .entry("charge".into())
                .or_insert_with(|| json!(atom.charge()));
        }
        atom_props_all.push(atom_props);
    }

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

    let any_atom_props = atom_props_all.iter().any(|m| !m.is_empty());
    if any_atom_props {
        let arr: Vec<Value> = atom_props_all
            .into_iter()
            .map(|m| Value::Object(m.into_iter().collect()))
            .collect();
        metadata.insert(CHEMFILES_ATOM_PROPS_KEY.into(), Value::Array(arr));
    }

    // Always store name/type sidecars on chemfiles import so selection can restore
    // display names (H1) distinct from CON symbol/type (H) without CON v3.
    if any_name_type_extra || n > 0 {
        let names_json: Vec<Value> = chfl_names.into_iter().map(Value::String).collect();
        let types_json: Vec<Value> = chfl_types.into_iter().map(Value::String).collect();
        metadata.insert(CHEMFILES_ATOM_NAMES_KEY.into(), Value::Array(names_json));
        metadata.insert(CHEMFILES_ATOM_TYPES_KEY.into(), Value::Array(types_json));
    }

    // Record chemfiles library version as an extra for provenance.
    metadata.insert(
        format!("{CHEMFILES_EXTRA_PREFIX}library_version"),
        Value::String(chemfiles::version()),
    );

    builder.metadata(metadata);
    let mut con = builder.build();

    // Optional topology: chemfiles bonds -> CON metadata["bonds"].
    // Chemfiles indices are 0..n in trajectory order. `ConFrameBuilder::build`
    // groups atoms by symbol for CON layout, so bond endpoints must be remapped
    // via `atom_id` (set to the chemfiles index above) into `atom_data` order.
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

    Ok(con)
}

/// Open a trajectory with chemfiles and convert every step to [`ConFrame`].
pub fn con_frames_from_trajectory_path<P: AsRef<Path>>(
    path: P,
) -> Result<Vec<ConFrame>, ChemfilesImportError> {
    let path = path.as_ref();
    let mut traj = Trajectory::open(path, 'r')?;
    let nsteps = traj.nsteps();
    let mut frames = Vec::with_capacity(nsteps);
    let mut chfl_frame = Frame::new();
    for _ in 0..nsteps {
        traj.read(&mut chfl_frame)?;
        frames.push(con_frame_from_chemfiles(&chfl_frame)?);
    }
    Ok(frames)
}

/// Read the first frame from a trajectory path.
pub fn con_frame_from_trajectory_path<P: AsRef<Path>>(
    path: P,
) -> Result<ConFrame, ChemfilesImportError> {
    let path = path.as_ref();
    let mut traj = Trajectory::open(path, 'r')?;
    let mut chfl_frame = Frame::new();
    traj.read(&mut chfl_frame)?;
    con_frame_from_chemfiles(&chfl_frame)
}

/// Read a trajectory from an in-memory buffer (chemfiles memory reader).
///
/// `format` is a chemfiles format string such as `"XYZ"` or `"PDB"`.
pub fn con_frames_from_memory(
    data: &str,
    format: &str,
) -> Result<Vec<ConFrame>, ChemfilesImportError> {
    use chemfiles::MemoryTrajectoryReader;
    let mut reader = MemoryTrajectoryReader::new(data.as_bytes(), format)?;
    let nsteps = reader.nsteps();
    let mut frames = Vec::with_capacity(nsteps);
    let mut chfl_frame = Frame::new();
    for _ in 0..nsteps {
        reader.read(&mut chfl_frame)?;
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
    fn converts_geometry_and_mapped_metadata() {
        let frame = make_water_frame();
        let con = con_frame_from_chemfiles(&frame).expect("convert");
        assert_eq!(con.atom_data.len(), 3);
        assert_eq!(con.header.boxl, [10.0, 10.0, 10.0]);
        assert_eq!(con.header.angles, [90.0, 90.0, 90.0]);
        assert_eq!(con.header.natm_types, 2); // O and H grouped

        let symbols: Vec<&str> = con
            .atom_data
            .iter()
            .map(|a| a.symbol.as_ref())
            .collect();
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
        assert!(
            generator.contains("readcon-core"),
            "generator={generator}"
        );
        assert!(generator.contains("chemfiles"), "generator={generator}");

        let extra = con
            .header
            .metadata
            .get(&format!("{CHEMFILES_EXTRA_PREFIX}custom_note"))
            .and_then(|v| v.as_str());
        assert_eq!(extra, Some("hello"));

        assert!(con.header.metadata.contains_key(meta::PBC));
        assert!(con.header.metadata.contains_key(meta::LATTICE_VECTORS));
        assert!(con
            .header
            .metadata
            .contains_key(&format!("{CHEMFILES_EXTRA_PREFIX}library_version")));
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
        let v = atom.velocity.expect("velocity on atom");
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
        let symbols: Vec<&str> = con
            .atom_data
            .iter()
            .map(|a| a.symbol.as_ref())
            .collect();
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
            a.symbol.as_ref() == "O" && a.x.abs() < 1e-6 && a.y.abs() < 1e-6 && a.z.abs() < 1e-6
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
}
