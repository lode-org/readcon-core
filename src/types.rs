//=============================================================================
// Data Structures - The shape of our parsed data
//=============================================================================

pub use rustc_hash::FxHashMap;
use std::collections::BTreeMap;
use std::sync::Arc;

/// JSON metadata key names recognized by spec v2.
///
/// Each constant is the exact string that appears on the second header
/// line. The constants are centralized so the parser, writer, builder,
/// FFI, and Python layers all reference the same key spellings.
///
/// Reserved key schema, as enforced by [`crate::parser::validate_metadata_schema`]
/// when `validate=true`:
///
/// | Constant | JSON type | Required | Notes |
/// |----------|-----------|----------|-------|
/// | [`CON_SPEC_VERSION`] | unsigned integer | yes | The spec version this frame conforms to. The reader rejects values greater than [`crate::CON_SPEC_VERSION`]. |
/// | [`SECTIONS`] | array of strings | required when `validate=true` | Declares per-atom section blocks that follow the coordinates (e.g. `["velocities", "forces"]`). When absent, legacy blank-separator velocity detection applies. |
/// | [`VALIDATE`] | boolean | optional | When `true`, the reader runs the strict v2 schema and structural checks. |
/// | [`ENERGY`] | finite number | optional | Per-frame total energy in the units declared by [`UNITS`]. |
/// | [`TIME`] | finite number | optional | Simulation time. |
/// | [`TIMESTEP`] | finite number | optional | Integration timestep. |
/// | [`CONVERGENCE_FMAX`] | finite number | optional | Max-force convergence threshold. |
/// | [`CONVERGENCE_ENERGY`] | finite number | optional | Energy convergence threshold. |
/// | [`FMAX`] | finite number | optional | Per-frame max force magnitude. |
/// | [`FRAME_INDEX`] | non-negative integer | optional | Zero-based frame index in the trajectory. |
/// | [`NEB_BEAD`] | non-negative integer | optional | Bead index along an NEB band. |
/// | [`NEB_BAND`] | non-negative integer | optional | NEB band index. |
/// | [`GENERATOR`] | string | optional | Producing tool name (e.g. `"eOn 0.4.2"`). |
/// | [`UNITS`] | object | optional | Unit identifiers, typically with `length`, `energy`, `time` keys. |
/// | [`POTENTIAL`] | object | optional | Force-field descriptor; if a `type` field is present it must be a string. |
/// | [`PBC`] | length-3 array of booleans | optional | Periodic-boundary flags per cell axis. |
/// | [`LATTICE_VECTORS`] | 3x3 numeric array | optional | Full lattice basis when `boxl`/`angles` is insufficient. |
/// | [`CONVERGED`] | boolean | optional | Whether the producing tool considers this frame converged. |
/// | [`BONDS`] | array of pairs/objects | optional | Frame topology: 0-based `atom_data` index pairs (see spec). Enables chemfiles `bonds:` / `angles:` / `is_bonded` when projected. Not a per-atom `sections` block. |
///
/// Keys not listed above are accepted on read and round-tripped on
/// write but receive no schema check, even under `validate=true`.
pub mod meta {
    /// Required JSON key carrying the spec version (unsigned integer).
    pub const CON_SPEC_VERSION: &str = "con_spec_version";
    /// Array of declared section names (strings). Required when
    /// `validate=true`; absent triggers the legacy blank-separator
    /// velocity detection.
    pub const SECTIONS: &str = "sections";
    /// Boolean. When `true`, the reader applies strict v2 validation.
    pub const VALIDATE: &str = "validate";

    /// Per-frame total energy (finite number, units declared by
    /// [`UNITS`]).
    pub const ENERGY: &str = "energy";
    /// Simulation time (finite number).
    pub const TIME: &str = "time";
    /// Integration timestep (finite number).
    pub const TIMESTEP: &str = "timestep";
    /// Max-force convergence threshold (finite number).
    pub const CONVERGENCE_FMAX: &str = "convergence_fmax";
    /// Energy convergence threshold (finite number).
    pub const CONVERGENCE_ENERGY: &str = "convergence_energy";
    /// Per-frame max force magnitude (finite number).
    pub const FMAX: &str = "fmax";

    /// Zero-based frame index along a trajectory (non-negative integer).
    pub const FRAME_INDEX: &str = "frame_index";
    /// NEB bead index (non-negative integer).
    pub const NEB_BEAD: &str = "neb_bead";
    /// NEB band index (non-negative integer).
    pub const NEB_BAND: &str = "neb_band";

    /// Producing tool name (string).
    pub const GENERATOR: &str = "generator";
    /// Unit identifiers (object). Common subkeys: `length`, `energy`,
    /// `time`. **Required** for `con_spec_version` ≥ 3.
    pub const UNITS: &str = "units";
    /// In-memory SoA element types (object). Subkeys: `positions`,
    /// `velocities`, `forces`, `energies`, `masses` → `"float32"`|`"float64"`;
    /// `atom_ids` → `"uint64"`. On-disk CON text remains binary64; this key
    /// governs library storage and `as_dlpack` dtype. Optional on v3;
    /// absent means all-float64 / uint64.
    pub const STORAGE_DTYPES: &str = "storage_dtypes";
    /// Force-field descriptor (object). When a `type` field is
    /// present it must be a string.
    pub const POTENTIAL: &str = "potential";
    /// Periodic-boundary flags (length-3 boolean array, x/y/z order).
    pub const PBC: &str = "pbc";
    /// Full lattice basis (3x3 numeric array).
    pub const LATTICE_VECTORS: &str = "lattice_vectors";
    /// Convergence flag (boolean).
    pub const CONVERGED: &str = "converged";
    /// Optional frame-level bond list (JSON array). Each element is either
    /// `[i, j]` or `{"i": i, "j": j, "order"?: ...}` with 0-based indices into
    /// `atom_data` order (not `atom_id`). Absent means no topology (legacy).
    pub const BONDS: &str = "bonds";
}

/// One optional bond endpoint pair on a frame (indices into `atom_data`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Bond {
    /// First atom index (0-based into `ConFrame::atom_data`).
    pub i: u32,
    /// Second atom index (0-based into `ConFrame::atom_data`).
    pub j: u32,
    /// Optional chemfiles-style bond order (stored as integer when known).
    pub order: Option<i32>,
}

impl Bond {
    /// Creates an unordered pair with `i <= j` for stable storage (optional).
    pub fn new(i: u32, j: u32) -> Self {
        Self {
            i,
            j,
            order: None,
        }
    }

    pub fn with_order(mut self, order: i32) -> Self {
        self.order = Some(order);
        self
    }
}

/// Canonical section names used in the JSON `sections` array and label lines.
pub const SECTION_VELOCITIES: &str = "velocities";
pub const SECTION_FORCES: &str = "forces";
pub const SECTION_ENERGIES: &str = "energies";

/// The two-line block preceding the box dimensions.
///
/// Line 0 is free-form user text. Line 1 is reserved for machine-readable
/// JSON metadata; it is read by the parser and rebuilt by the writer from
/// `FrameHeader.spec_version + metadata + sections`. External callers
/// cannot set the metadata line directly -- they should mutate
/// `FrameHeader.metadata` instead and let the writer regenerate it.
#[derive(Debug, Clone, Default)]
pub struct PreboxHeader {
    /// User-supplied free-form text (e.g. "Generated by eOn").
    pub user: String,
    /// JSON metadata line as stored on disk; rebuilt on write.
    pub(crate) metadata_line: String,
}

impl PreboxHeader {
    /// Construct from the user-facing text only. The metadata line is
    /// initialized empty and will be filled in by the writer.
    pub fn new(user: impl Into<String>) -> Self {
        Self {
            user: user.into(),
            metadata_line: String::new(),
        }
    }

    /// Read-only access to the JSON metadata line as it was last parsed
    /// or written.
    pub fn metadata_line(&self) -> &str {
        &self.metadata_line
    }
}

impl PartialEq for PreboxHeader {
    /// Compare only the user line; the metadata line is regenerated on
    /// write and is not part of frame identity.
    fn eq(&self, other: &Self) -> bool {
        self.user == other.user
    }
}

/// Holds all metadata from the 9-line header of a simulation frame.
#[derive(Debug, Clone)]
pub struct FrameHeader {
    /// The two text lines preceding the box dimension data: a user line
    /// plus a managed JSON metadata line.
    pub prebox_header: PreboxHeader,
    /// The three box dimensions, typically Lx, Ly, and Lz.
    pub boxl: [f64; 3],
    /// The three box angles, typically alpha, beta, and gamma.
    pub angles: [f64; 3],
    /// The two text lines following the box angle data.
    pub postbox_header: [String; 2],
    /// The number of distinct atom types in the frame.
    pub natm_types: usize,
    /// A vector containing the count of atoms for each respective type.
    pub natms_per_type: Vec<usize>,
    /// A vector containing the mass for each respective atom type.
    pub masses_per_type: Vec<f64>,
    /// CON spec version parsed from the JSON metadata line.
    pub spec_version: u32,
    /// Additional key-value metadata from the JSON metadata line.
    /// Keys other than `con_spec_version` are preserved here for round-tripping.
    pub metadata: BTreeMap<String, serde_json::Value>,
    /// Declared data sections from JSON metadata or detected from data presence. (e.g. `["velocities", "forces"]`).
    /// Empty for legacy files (parser falls back to blank-separator velocity detection).
    pub sections: Vec<String>,
    /// Cached value of the `validate` JSON metadata key, captured at parse
    /// time so the per-frame strict-mode dispatch in parse_single_frame /
    /// parse_velocity_section / parse_force_section can avoid a BTreeMap
    /// lookup on every call.
    pub(crate) strict_validation: bool,
    /// Whether the parsed metadata explicitly listed a `sections` key.
    /// Distinguishes "declared as empty array" (no legacy fallback) from
    /// "key absent" (try blank-separator velocity detection). Cached at
    /// parse time so the section dispatch does not re-parse the JSON.
    pub(crate) sections_declared: bool,
}

impl PartialEq for FrameHeader {
    /// Frame identity excludes the cached `strict_validation` and
    /// `sections_declared` flags. Both are derived from the metadata at
    /// parse time and exist purely as a perf shortcut, so two frames
    /// that hold the same metadata + sections compare equal even when
    /// one came from a legacy blank-separator detection (cached=false)
    /// and the other from a re-read of an explicitly-declared v2 file
    /// (cached=true).
    fn eq(&self, other: &Self) -> bool {
        self.prebox_header == other.prebox_header
            && self.boxl == other.boxl
            && self.angles == other.angles
            && self.postbox_header == other.postbox_header
            && self.natm_types == other.natm_types
            && self.natms_per_type == other.natms_per_type
            && self.masses_per_type == other.masses_per_type
            && self.spec_version == other.spec_version
            && self.metadata == other.metadata
            && self.sections == other.sections
    }
}

/// Typed accessors for recommended JSON metadata keys.
///
/// All getters read from `self.metadata`; all setters write to it.
/// The underlying `BTreeMap` is the source of truth -- these helpers
/// provide ergonomic typed access without changing storage.
impl FrameHeader {
    /// Per-frame total energy (in the units declared by the `units` key).
    pub fn energy(&self) -> Option<f64> {
        self.metadata.get(meta::ENERGY).and_then(|v| v.as_f64())
    }

    /// Sets the per-frame total energy.
    pub fn set_energy(&mut self, e: f64) {
        self.metadata
            .insert(meta::ENERGY.into(), serde_json::Value::from(e));
    }

    /// Potential type string (e.g. "EMT", "LJ").
    pub fn potential_type(&self) -> Option<&str> {
        self.metadata
            .get(meta::POTENTIAL)
            .and_then(|v| v.as_object())
            .and_then(|obj| obj.get("type"))
            .and_then(|v| v.as_str())
    }

    /// Potential parameters as a JSON value.
    pub fn potential_params(&self) -> Option<&serde_json::Value> {
        self.metadata
            .get(meta::POTENTIAL)
            .and_then(|v| v.as_object())
            .and_then(|obj| obj.get("params"))
    }

    /// Sets the potential type and parameters.
    pub fn set_potential(&mut self, pot_type: &str, params: serde_json::Value) {
        let obj = serde_json::json!({
            "type": pot_type,
            "params": params,
        });
        self.metadata.insert(meta::POTENTIAL.into(), obj);
    }

    /// Zero-based frame index within a trajectory.
    pub fn frame_index(&self) -> Option<u64> {
        self.metadata
            .get(meta::FRAME_INDEX)
            .and_then(|v| v.as_u64())
    }

    /// Sets the frame index.
    pub fn set_frame_index(&mut self, idx: u64) {
        self.metadata
            .insert(meta::FRAME_INDEX.into(), serde_json::Value::from(idx));
    }

    /// Simulation time of this frame (in the declared time unit).
    pub fn time(&self) -> Option<f64> {
        self.metadata.get(meta::TIME).and_then(|v| v.as_f64())
    }

    /// Sets the simulation time.
    pub fn set_time(&mut self, t: f64) {
        self.metadata
            .insert(meta::TIME.into(), serde_json::Value::from(t));
    }

    /// Integration timestep (in the declared time unit).
    pub fn timestep(&self) -> Option<f64> {
        self.metadata.get(meta::TIMESTEP).and_then(|v| v.as_f64())
    }

    /// Sets the integration timestep.
    pub fn set_timestep(&mut self, dt: f64) {
        self.metadata
            .insert(meta::TIMESTEP.into(), serde_json::Value::from(dt));
    }

    /// Unit system as a JSON object (e.g. `{"length":"angstrom","energy":"eV"}`).
    pub fn units(&self) -> Option<&serde_json::Value> {
        self.metadata.get(meta::UNITS)
    }

    /// Unit string for a dimension key (`length`, `energy`, …) from `metadata["units"]`.
    pub fn unit_for(&self, dimension: &str) -> Option<&str> {
        self.units()
            .and_then(|u| u.as_object())
            .and_then(|o| o.get(dimension))
            .and_then(|v| v.as_str())
    }

    /// `length` unit string when present (v3 frames should always have it).
    pub fn length_unit(&self) -> Option<&str> {
        self.unit_for("length")
    }

    /// `energy` unit string when present.
    pub fn energy_unit(&self) -> Option<&str> {
        self.unit_for("energy")
    }

    /// Factor: `value_in_to = factor * value_in_frame_unit` for `dimension`.
    pub fn conversion_factor_to(
        &self,
        dimension: &str,
        to_unit: &str,
    ) -> Result<f64, crate::error::ParseError> {
        let from = self.unit_for(dimension).ok_or_else(|| {
            crate::error::ParseError::ValidationError(format!(
                "metadata units.{dimension} is missing"
            ))
        })?;
        crate::units::unit_conversion_factor(from, to_unit)
    }

    /// Sets the unit system.
    pub fn set_units(&mut self, units: serde_json::Value) {
        self.metadata.insert(meta::UNITS.into(), units);
    }

    /// Periodic boundary conditions as `[pbc_x, pbc_y, pbc_z]`.
    /// Returns `None` if not set (callers should default to `[true, true, true]`).
    pub fn pbc(&self) -> Option<[bool; 3]> {
        let arr = self.metadata.get(meta::PBC)?.as_array()?;
        if arr.len() != 3 {
            return None;
        }
        Some([arr[0].as_bool()?, arr[1].as_bool()?, arr[2].as_bool()?])
    }

    /// Sets the periodic boundary conditions.
    pub fn set_pbc(&mut self, pbc: [bool; 3]) {
        self.metadata
            .insert(meta::PBC.into(), serde_json::json!([pbc[0], pbc[1], pbc[2]]));
    }

    /// Exact 3x3 lattice vector matrix (row-major, angstroms).
    /// When present, takes precedence over the length/angle values on lines 3-4.
    pub fn lattice_vectors(&self) -> Option<[[f64; 3]; 3]> {
        let arr = self.metadata.get(meta::LATTICE_VECTORS)?.as_array()?;
        if arr.len() != 3 {
            return None;
        }
        let row = |i: usize| -> Option<[f64; 3]> {
            let r = arr[i].as_array()?;
            if r.len() != 3 {
                return None;
            }
            Some([r[0].as_f64()?, r[1].as_f64()?, r[2].as_f64()?])
        };
        Some([row(0)?, row(1)?, row(2)?])
    }

    /// Sets the exact lattice vector matrix.
    pub fn set_lattice_vectors(&mut self, vecs: [[f64; 3]; 3]) {
        self.metadata.insert(
            meta::LATTICE_VECTORS.into(),
            serde_json::json!([
                [vecs[0][0], vecs[0][1], vecs[0][2]],
                [vecs[1][0], vecs[1][1], vecs[1][2]],
                [vecs[2][0], vecs[2][1], vecs[2][2]],
            ]),
        );
    }

    /// NEB bead (image) index.
    pub fn neb_bead(&self) -> Option<u64> {
        self.metadata.get(meta::NEB_BEAD).and_then(|v| v.as_u64())
    }

    /// Sets the NEB bead index.
    pub fn set_neb_bead(&mut self, bead: u64) {
        self.metadata
            .insert(meta::NEB_BEAD.into(), serde_json::Value::from(bead));
    }

    /// NEB band index.
    pub fn neb_band(&self) -> Option<u64> {
        self.metadata.get(meta::NEB_BAND).and_then(|v| v.as_u64())
    }

    /// Sets the NEB band index.
    pub fn set_neb_band(&mut self, band: u64) {
        self.metadata
            .insert(meta::NEB_BAND.into(), serde_json::Value::from(band));
    }

    /// Optional frame-level bonds from the `bonds` metadata key (0-based
    /// `atom_data` indices). Returns an empty vec when the key is absent.
    pub fn bonds(&self) -> Vec<Bond> {
        parse_bonds_from_metadata(&self.metadata)
    }

    /// True when the `bonds` key is present and non-empty.
    pub fn has_bonds(&self) -> bool {
        !self.bonds().is_empty()
    }

    /// Replace frame topology in metadata. Pass an empty slice to remove the key.
    pub fn set_bonds(&mut self, bonds: &[Bond]) {
        if bonds.is_empty() {
            self.metadata.remove(meta::BONDS);
            return;
        }
        self.metadata
            .insert(meta::BONDS.into(), bonds_to_json_value(bonds));
    }

    /// Append one bond (does not de-duplicate).
    pub fn add_bond(&mut self, bond: Bond) {
        let mut bonds = self.bonds();
        bonds.push(bond);
        self.set_bonds(&bonds);
    }

    /// Clear topology (remove `bonds` key).
    pub fn clear_bonds(&mut self) {
        self.metadata.remove(meta::BONDS);
    }
}

/// Parse `bonds` from a metadata map. Invalid/missing entries yield empty
/// (parser validates shape at read time when the key is present).
pub fn parse_bonds_from_metadata(metadata: &BTreeMap<String, serde_json::Value>) -> Vec<Bond> {
    let Some(val) = metadata.get(meta::BONDS) else {
        return Vec::new();
    };
    let Some(arr) = val.as_array() else {
        return Vec::new();
    };
    let mut out = Vec::with_capacity(arr.len());
    for item in arr {
        if let Some(b) = bond_from_json_value(item) {
            out.push(b);
        }
    }
    out
}

/// Serialize bonds for the `bonds` metadata key.
pub fn bonds_to_json_value(bonds: &[Bond]) -> serde_json::Value {
    let items: Vec<serde_json::Value> = bonds
        .iter()
        .map(|b| {
            if let Some(order) = b.order {
                serde_json::json!({ "i": b.i, "j": b.j, "order": order })
            } else {
                serde_json::json!([b.i, b.j])
            }
        })
        .collect();
    serde_json::Value::Array(items)
}

fn bond_from_json_value(item: &serde_json::Value) -> Option<Bond> {
    if let Some(arr) = item.as_array() {
        if arr.len() != 2 {
            return None;
        }
        let i = arr[0].as_u64()? as u32;
        let j = arr[1].as_u64()? as u32;
        return Some(Bond::new(i, j));
    }
    if let Some(obj) = item.as_object() {
        let i = obj.get("i")?.as_u64()? as u32;
        let j = obj.get("j")?.as_u64()? as u32;
        let order = obj.get("order").and_then(|v| v.as_i64()).map(|v| v as i32);
        let mut b = Bond::new(i, j);
        b.order = order;
        return Some(b);
    }
    None
}

/// Represents the data for a single atom in a frame.
#[derive(Debug, Clone, PartialEq)]
pub struct AtomDatum {
    /// The chemical symbol of the atom (e.g., "C", "H", "O").
    /// Using Arc<str> to avoid expensive clones for each atom of the same type.
    pub symbol: Arc<str>,
    /// The Cartesian x-coordinate.
    pub x: f64,
    /// The Cartesian y-coordinate.
    pub y: f64,
    /// The Cartesian z-coordinate.
    pub z: f64,
    /// Per-direction constraint flags: [fixed_x, fixed_y, fixed_z].
    ///
    /// Encoded as a bitmask in column 4 of the file format:
    /// - 0 = free (all false)
    /// - 1 = all-fixed (legacy, treated as [true, true, true])
    /// - 2-6 = per-direction combinations (bit 0=y, bit 1=x+y, bit 2=z, ...)
    /// - 7 = all-fixed (canonical)
    pub fixed: [bool; 3],
    /// The original atom index (column 5 in .con format).
    ///
    /// The .con format groups atoms by element type, which reorders them
    /// relative to their original input ordering. This field preserves the
    /// pre-grouping index so the original sequence can be reconstructed
    /// after any number of read/write cycles.
    ///
    /// When column 5 is absent from the input, defaults to the sequential
    /// position within the frame (0, 1, 2, ...).
    pub atom_id: u64,
    /// Velocity vector `[vx, vy, vz]` (present only in `.convel` files).
    pub velocity: Option<[f64; 3]>,
    /// Force vector `[fx, fy, fz]` (present when `"forces"` section declared).
    pub force: Option<[f64; 3]>,
    /// Per-atom energy contribution (present when `"energies"` section declared).
    ///
    /// Useful for ML potentials that decompose total energy into per-atom
    /// contributions; the per-frame total still lives in
    /// `FrameHeader.metadata` under the `energy` key.
    pub energy: Option<f64>,
}

impl AtomDatum {
    /// Returns `true` if any direction is fixed.
    pub fn is_fixed(&self) -> bool {
        self.fixed[0] || self.fixed[1] || self.fixed[2]
    }

    /// Returns `true` if all three directions are fixed.
    pub fn is_fully_fixed(&self) -> bool {
        self.fixed[0] && self.fixed[1] && self.fixed[2]
    }

    /// Returns `true` if this atom has velocity data.
    pub fn has_velocity(&self) -> bool {
        self.velocity.is_some()
    }

    /// Returns `true` if this atom has force data.
    pub fn has_forces(&self) -> bool {
        self.force.is_some()
    }

    /// Returns `true` if this atom carries a per-atom energy contribution.
    pub fn has_energy(&self) -> bool {
        self.energy.is_some()
    }
}

/// Decode a column-4 bitmask value to per-direction fixed flags.
///
/// - 0 = free
/// - 1 = all-fixed (legacy, treated as [true, true, true])
/// - 2-7 = bitmask (bit 0 = x, bit 1 = y, bit 2 = z)
pub fn decode_fixed_bitmask(val: u8) -> [bool; 3] {
    match val {
        0 => [false, false, false],
        1 => [true, true, true], // legacy: treat as fully fixed
        v => [v & 1 != 0, v & 2 != 0, v & 4 != 0],
    }
}

/// Encode per-direction fixed flags to a column-4 bitmask value.
///
/// Always emits 7 for all-fixed (never legacy value 1).
pub fn encode_fixed_bitmask(fixed: [bool; 3]) -> u8 {
    let mut val: u8 = 0;
    if fixed[0] {
        val |= 1;
    }
    if fixed[1] {
        val |= 2;
    }
    if fixed[2] {
        val |= 4;
    }
    val
}

/// Represents a single, complete simulation frame, including header and all atomic data.
///
/// **Numeric layout (metatensor-shaped):** coordinates and optional sections live in
/// opaque [`crate::storage_dtype::FloatArray2`] / [`FloatArray1`] blocks. Callers treat
/// these as the source of truth for DLPack (`as_dlpack` exports **storage** dtype).
/// Project in-memory representation with [`Self::project_storage_dtypes`]. On-disk CON
/// text remains binary64. [`Self::atom_data`] is the AoS projection for the writer.
#[derive(Debug, Clone, PartialEq)]
pub struct ConFrame {
    /// The `FrameHeader` containing the frame's metadata.
    pub header: FrameHeader,
    /// AoS projection for CON serialization and symbol/fixed metadata.
    pub atom_data: Vec<AtomDatum>,
    /// Primary positions `(N, 3)`, type-grouped order (f32 or f64 storage).
    pub positions: crate::storage_dtype::FloatArray2,
    /// Velocities `(N, 3)` when present; else `(0, 3)`.
    pub velocities: crate::storage_dtype::FloatArray2,
    /// Forces `(N, 3)` when present; else `(0, 3)`.
    pub forces: crate::storage_dtype::FloatArray2,
    /// Per-atom energies `(N,)` when present; else `(0,)`.
    pub atom_energies: crate::storage_dtype::FloatArray1,
    /// Per-atom masses `(N,)`.
    pub masses: crate::storage_dtype::FloatArray1,
    /// Per-atom ids `(N,)` u64 (always).
    pub atom_ids: ndarray::ArcArray1<u64>,
}

impl ConFrame {
    /// Apply [`crate::storage_dtype::StorageDtypes`] from metadata (or argument) to SoA fields.
    pub fn project_storage_dtypes(&mut self, dtypes: &crate::storage_dtype::StorageDtypes) {
        self.positions.project_to(dtypes.positions);
        if self.velocities.nrows() > 0 {
            self.velocities.project_to(dtypes.velocities);
        }
        if self.forces.nrows() > 0 {
            self.forces.project_to(dtypes.forces);
        }
        if self.atom_energies.len() > 0 {
            self.atom_energies.project_to(dtypes.energies);
        }
        if self.masses.len() > 0 {
            self.masses.project_to(dtypes.masses);
        }
        dtypes.insert_into(&mut self.header.metadata);
        self.sync_atom_data_from_arrays();
    }

    /// Rebuild AoS [`atom_data`] coordinates (and optional sections) from SoA arrays.
    pub fn sync_atom_data_from_arrays(&mut self) {
        let n = self.positions.nrows();
        if self.atom_data.len() != n {
            return;
        }
        let has_vel = self.velocities.nrows() == n;
        let has_frc = self.forces.nrows() == n;
        let has_eng = self.atom_energies.len() == n;
        for i in 0..n {
            let a = &mut self.atom_data[i];
            let p = self.positions.as_f64_row(i);
            a.x = p[0];
            a.y = p[1];
            a.z = p[2];
            if has_vel {
                a.velocity = Some(self.velocities.as_f64_row(i));
            }
            if has_frc {
                a.force = Some(self.forces.as_f64_row(i));
            }
            if has_eng {
                a.energy = Some(self.atom_energies.get_f64(i));
            }
            if i < self.atom_ids.len() {
                a.atom_id = self.atom_ids[i];
            }
        }
    }

    /// After section parsers mutate AoS only, allocate/fill SoA **sections**
    /// (velocities/forces/energies) and atom_ids. Positions are **not** rewritten
    /// when `positions.nrows() == n` already (SoA-primary coordinate parse).
    /// Used on the shipped iterator path so section SoA nrows match AoS optionals
    /// without restoring a second O(N) position materialization.
    pub fn sync_arrays_from_atom_data(&mut self) {
        let n = self.atom_data.len();
        if n == 0 {
            return;
        }
        use crate::storage_dtype::{FloatArray1, FloatArray2, StorageDtypes};
        let dt = StorageDtypes::from_metadata(&self.header.metadata).unwrap_or_default();
        let has_vel = self.atom_data.iter().any(|a| a.has_velocity());
        let has_frc = self.atom_data.iter().any(|a| a.has_forces());
        let has_eng = self.atom_data.iter().any(|a| a.has_energy());
        // Only allocate positions if missing (should not happen on parse-primary path).
        let need_pos_fill = self.positions.nrows() != n;
        if need_pos_fill {
            self.positions = FloatArray2::zeros(dt.positions, n, 3);
        }
        if has_vel {
            if self.velocities.nrows() != n {
                self.velocities = FloatArray2::zeros(dt.velocities, n, 3);
            }
        } else if self.velocities.nrows() != 0 {
            self.velocities = FloatArray2::zeros(dt.velocities, 0, 3);
        }
        if has_frc {
            if self.forces.nrows() != n {
                self.forces = FloatArray2::zeros(dt.forces, n, 3);
            }
        } else if self.forces.nrows() != 0 {
            self.forces = FloatArray2::zeros(dt.forces, 0, 3);
        }
        if has_eng {
            if self.atom_energies.len() != n {
                self.atom_energies = FloatArray1::zeros(dt.energies, n);
            }
        } else if self.atom_energies.len() != 0 {
            self.atom_energies = FloatArray1::zeros(dt.energies, 0);
        }
        if self.atom_ids.len() != n {
            self.atom_ids = ndarray::ArcArray1::<u64>::zeros(n);
        }
        for (i, a) in self.atom_data.iter().enumerate() {
            if need_pos_fill {
                self.positions.set_f64_row(i, [a.x, a.y, a.z]);
            }
            self.atom_ids[i] = a.atom_id;
            if has_vel {
                if let Some(v) = a.velocity {
                    self.velocities.set_f64_row(i, v);
                }
            }
            if has_frc {
                if let Some(f) = a.force {
                    self.forces.set_f64_row(i, f);
                }
            }
            if has_eng {
                self.atom_energies
                    .set_f64(i, a.energy.unwrap_or(0.0));
            }
        }
    }

    /// Metatensor-style: export **stored** positions (f32 or f64) via DLPack.
    pub fn positions_as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<dlpk::DLPackTensor, crate::error::ParseError> {
        self.positions.as_dlpack(device)
    }

    pub fn velocities_as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<Option<dlpk::DLPackTensor>, crate::error::ParseError> {
        if self.velocities.nrows() == 0 {
            return Ok(None);
        }
        Ok(Some(self.velocities.as_dlpack(device)?))
    }

    pub fn forces_as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<Option<dlpk::DLPackTensor>, crate::error::ParseError> {
        if self.forces.nrows() == 0 {
            return Ok(None);
        }
        Ok(Some(self.forces.as_dlpack(device)?))
    }

    pub fn atom_energies_as_dlpack(
        &self,
        device: dlpk::sys::DLDevice,
    ) -> Result<Option<dlpk::DLPackTensor>, crate::error::ParseError> {
        if self.atom_energies.len() == 0 {
            return Ok(None);
        }
        Ok(Some(self.atom_energies.as_dlpack(device)?))
    }

    /// Returns `true` if any atom in this frame has velocity data.
    pub fn has_velocities(&self) -> bool {
        self.velocities.nrows() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_velocity())
    }

    /// Returns `true` if any atom in this frame has force data.
    pub fn has_forces(&self) -> bool {
        self.forces.nrows() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_forces())
    }

    /// Returns `true` if any atom in this frame carries a per-atom energy.
    pub fn has_energies(&self) -> bool {
        self.atom_energies.len() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_energy())
    }

    /// Builds an O(1) reverse index from `atom_id` to the position of
    /// the atom inside `atom_data`.
    ///
    /// Returns an [`FxHashMap`] (`rustc-hash`) so the small-integer
    /// hash workload stays fast. The index is built fresh on each
    /// call; callers that perform many lookups should cache the
    /// returned map.
    pub fn build_atom_id_index(&self) -> FxHashMap<u64, usize> {
        let mut idx = FxHashMap::with_capacity_and_hasher(
            self.atom_data.len(),
            Default::default(),
        );
        for (i, atom) in self.atom_data.iter().enumerate() {
            idx.insert(atom.atom_id, i);
        }
        idx
    }

    /// Linear-scan lookup of an atom by its `atom_id` column.
    ///
    /// O(N) per call. For repeated lookups on a stable frame, build a
    /// reverse index once with [`Self::build_atom_id_index`] and look
    /// up in the returned hash map directly.
    pub fn atom_index_by_id(&self, atom_id: u64) -> Option<usize> {
        self.atom_data.iter().position(|a| a.atom_id == atom_id)
    }

    /// Optional frame bonds (`metadata["bonds"]`, 0-based `atom_data` indices).
    pub fn bonds(&self) -> Vec<Bond> {
        self.header.bonds()
    }

    /// True when non-empty topology is present.
    pub fn has_bonds(&self) -> bool {
        self.header.has_bonds()
    }
}

/// A builder for constructing `ConFrame` objects from in-memory data.
///
/// Atoms are accumulated and grouped by symbol on `build()` to compute the
/// header fields (`natm_types`, `natms_per_type`, `masses_per_type`).
///
/// # Example
///
/// ```
/// use readcon_core::types::ConFrameBuilder;
///
/// let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
/// builder.add_atom("Cu", 0.0, 0.0, 0.0, [true, true, true], 0, 63.546);
/// builder.add_atom("H", 1.0, 2.0, 3.0, [false, false, false], 1, 1.008);
/// let frame = builder.build();
/// assert_eq!(frame.header.natm_types, 2);
/// assert_eq!(frame.atom_data.len(), 2);
/// ```
/// In-memory frame builder backed by struct-of-arrays storage so
/// downstream consumers (eOn's Matter, GROMACS-style integrators)
/// can map a `[N, 3] f64` view directly onto Rust-owned memory and
/// mutate positions / forces / energies via FFI raw pointer with no
/// copy-through-API overhead.
///
/// Storage contract:
///
/// Per-atom vector fields (`positions`, `velocities`, `forces`) are
/// stored as `ndarray::ArcArray2<f64>` with shape `(N, 3)`, row-major
/// (the default for newly-created `Array2` in standard layout). This
/// is the SOTA frame-builder layout adopted by metatensor v2 (which
/// uses `Arc<RwLock<ArrayD<T>>>` for the same reasons), and matches
/// what NumPy / Eigen RowMajor / PyTorch / JAX consumers expect via
/// DLPack `(N, 3) f64` views. Owning the data as an `ndarray::Array`
/// (rather than a `Vec<f64>` we'd have to re-wrap on every export)
/// is what makes dlpk's `TryFrom<&'a Array<T, D>> for
/// DLPackTensorRef<'a>` lifetime-clean: `&self.positions` carries
/// `&self`'s lifetime through to the returned tensor view, no
/// borrow-life-extension or unsafe-from-raw needed.
///
/// - `positions` shape `(N, 3) f64`, always populated, length-coherent
///   with `atom_count()`.
/// - `velocities`, `forces` shape `(N, 3) f64` when their respective
///   sections are declared, else `(0, 3)`. The `has_*` flag tracks
///   declaration so `build()` knows whether to emit the section block.
/// - `atom_energies` shape `(N,) f64` when populated, else `(0,)`.
/// - `masses` shape `(N,) f64`, always populated.
/// - `atom_ids` shape `(N,) u64`, always populated.
/// - `fixed` stays `Vec<[bool; 3]>` for now (DLPack `kDLBool` typing
///   is rarely worth round-tripping, and bool-tensor consumers are
///   uncommon); a future v0.12 may promote it to `Array2<bool>` once
///   we have a use case.
/// - `symbols` stays `Vec<String>` -- DLPack has no native variable-
///   length string dtype, so symbols are surfaced via a separate
///   `symbols()` getter (and emitted as Arrow string columns when the
///   `arrow` feature flag arrives in v0.12).
///
/// Pointer stability: once `atom_count()` is fixed (i.e. no further
/// `add_atom` calls), each ndarray's data pointer is stable until
/// `build()` consumes the builder. Callers that hold raw pointers
/// from a DLPack export across `add_atom` invocations MUST refresh
/// after the push (ndarray's `push` may reallocate the backing
/// buffer when capacity is exceeded).
/// Helper: `push_row` on a 2D ArcArray. ArcArray (OwnedArcRepr) does not
/// implement DataOwned (push_row requires DataOwned + DataMut), so the
/// implementation detours through the owned Array variant. When the
/// Arc is uniquely owned the detour is O(1) (just unwraps + rewraps the
/// Arc); when shared the detour is the copy-on-write the design wants.
fn arc_push_row(arr: &mut ndarray::ArcArray2<f64>, row: ndarray::ArrayView1<f64>) {
    let placeholder = ndarray::ArcArray2::<f64>::zeros((0, 3));
    let taken = std::mem::replace(arr, placeholder);
    let mut owned = taken.into_owned();
    owned
        .push_row(row)
        .expect("push_row failed (standard layout invariant)");
    *arr = owned.into_shared();
}

/// Helper: push a single u64 onto a 1D ArcArray.
fn arc_push_u64(arr: &mut ndarray::ArcArray1<u64>, value: u64) {
    let placeholder = ndarray::ArcArray1::<u64>::zeros(0);
    let taken = std::mem::replace(arr, placeholder);
    let mut owned = taken.into_owned();
    owned
        .push(ndarray::Axis(0), ndarray::aview0(&value))
        .expect("atom_ids push failed");
    *arr = owned.into_shared();
}

/// Helper: push a single f64 onto a 1D ArcArray.
fn arc_push_f64_1d(arr: &mut ndarray::ArcArray1<f64>, value: f64) {
    let placeholder = ndarray::ArcArray1::<f64>::zeros(0);
    let taken = std::mem::replace(arr, placeholder);
    let mut owned = taken.into_owned();
    owned
        .push(ndarray::Axis(0), ndarray::aview0(&value))
        .expect("push failed");
    *arr = owned.into_shared();
}

#[derive(Debug, Clone)]
pub struct ConFrameBuilder {
    prebox_user: String,
    cell: [f64; 3],
    angles: [f64; 3],
    postbox_header: [String; 2],

    // Per-atom heterogeneous fields kept as Vecs (no DLPack export).
    symbols: Vec<String>,
    fixed: Vec<[bool; 3]>,

    // Per-atom DLPack-exportable fields, owned ndarrays.
    /// Row-major `(N, 3) f64`, always populated.
    positions: ndarray::ArcArray2<f64>,
    /// Row-major `(N,) u64`, always populated.
    atom_ids: ndarray::ArcArray1<u64>,
    /// Row-major `(N,) f64`, always populated.
    masses: ndarray::ArcArray1<f64>,
    /// Row-major `(N, 3) f64` when has_velocities, else `(0, 3)`.
    velocities: ndarray::ArcArray2<f64>,
    has_velocities: bool,
    /// Row-major `(N, 3) f64` when has_forces, else `(0, 3)`.
    forces: ndarray::ArcArray2<f64>,
    has_forces: bool,
    /// `(N,) f64` when has_energies, else `(0,)`.
    atom_energies: ndarray::ArcArray1<f64>,
    has_energies: bool,

    metadata: BTreeMap<String, serde_json::Value>,
}

impl Default for ConFrameBuilder {
    fn default() -> Self {
        Self {
            prebox_user: String::new(),
            cell: [0.0; 3],
            angles: [0.0; 3],
            postbox_header: [String::new(), String::new()],
            symbols: Vec::new(),
            fixed: Vec::new(),
            positions: ndarray::ArcArray2::<f64>::zeros((0, 3)),
            atom_ids: ndarray::ArcArray1::<u64>::zeros(0),
            masses: ndarray::ArcArray1::<f64>::zeros(0),
            velocities: ndarray::ArcArray2::<f64>::zeros((0, 3)),
            has_velocities: false,
            forces: ndarray::ArcArray2::<f64>::zeros((0, 3)),
            has_forces: false,
            atom_energies: ndarray::ArcArray1::<f64>::zeros(0),
            has_energies: false,
            metadata: BTreeMap::new(),
        }
    }
}

impl ConFrameBuilder {
    /// Creates a new builder with the given cell dimensions and angles.
    ///
    /// In-memory SoA on [`Self::build`] defaults to float64 unless
    /// [`Self::storage_dtypes`] / metadata `storage_dtypes` requests otherwise.
    pub fn new(cell: [f64; 3], angles: [f64; 3]) -> Self {
        Self {
            cell,
            angles,
            ..Self::default()
        }
    }

    /// Sets the user-facing pre-box header line. The JSON metadata line is
    /// regenerated by the writer from `metadata`/`sections`.
    pub fn prebox_header(&mut self, line: impl Into<String>) -> &mut Self {
        self.prebox_user = line.into();
        self
    }

    /// Sets the two post-box header lines.
    pub fn postbox_header(&mut self, h: [String; 2]) -> &mut Self {
        self.postbox_header = h;
        self
    }

    /// Set in-memory SoA element types (written to `metadata["storage_dtypes"]`).
    ///
    /// [`Self::build`] **allocates** positions/velocities/forces/energies/masses
    /// in these types (float32 or float64), then fills from builder f64 scratch
    /// buffers. On-disk CON text remains binary64.
    pub fn storage_dtypes(
        &mut self,
        dtypes: crate::storage_dtype::StorageDtypes,
    ) -> &mut Self {
        dtypes.insert_into(&mut self.metadata);
        self
    }

    /// Convenience: allocate positions (and other float fields if still default)
    /// as float32 in memory on the next [`Self::build`].
    pub fn storage_float32_positions(&mut self) -> &mut Self {
        let mut d = crate::storage_dtype::StorageDtypes::from_metadata(&self.metadata)
            .unwrap_or_default();
        d.positions = crate::storage_dtype::FloatStorageKind::Float32;
        self.storage_dtypes(d)
    }

    /// Adds extra key-value pairs to the JSON metadata line.
    /// The `con_spec_version` key is always set automatically.
    pub fn metadata(&mut self, m: BTreeMap<String, serde_json::Value>) -> &mut Self {
        self.metadata = m;
        self
    }

    /// Parses and sets JSON metadata for the frame header.
    ///
    /// The input must be a JSON object. The `con_spec_version` and
    /// `sections` keys are ignored because they are managed by the
    /// builder/writer. The schema is validated up front (matching what
    /// the parser checks on read), so authoring with bad metadata fails
    /// fast.
    pub fn set_metadata_json(
        &mut self,
        metadata_json: &str,
    ) -> Result<(), crate::error::ParseError> {
        let object: serde_json::Map<String, serde_json::Value> =
            serde_json::from_str(metadata_json)?;
        crate::parser::validate_metadata_schema(&object)?;
        self.metadata.clear();
        for (key, value) in object {
            if key == meta::CON_SPEC_VERSION || key == meta::SECTIONS {
                continue;
            }
            self.metadata.insert(key, value);
        }
        Ok(())
    }

    /// Sets a numeric metadata key.
    pub fn set_scalar_metadata(&mut self, key: &str, value: f64) -> &mut Self {
        self.metadata
            .insert(key.to_string(), serde_json::Value::from(value));
        self
    }

    /// Sets a string metadata key.
    pub fn set_string_metadata(&mut self, key: &str, value: &str) -> &mut Self {
        self.metadata
            .insert(key.to_string(), serde_json::Value::from(value));
        self
    }

    /// Sets the per-frame total energy metadata.
    pub fn set_energy(&mut self, energy: f64) -> &mut Self {
        self.set_scalar_metadata(meta::ENERGY, energy)
    }

    /// Sets the zero-based frame index metadata.
    pub fn set_frame_index(&mut self, idx: u64) -> &mut Self {
        self.metadata
            .insert(meta::FRAME_INDEX.into(), serde_json::Value::from(idx));
        self
    }

    /// Sets the simulation time metadata.
    pub fn set_time(&mut self, time: f64) -> &mut Self {
        self.set_scalar_metadata(meta::TIME, time)
    }

    /// Sets the timestep metadata.
    pub fn set_timestep(&mut self, dt: f64) -> &mut Self {
        self.set_scalar_metadata(meta::TIMESTEP, dt)
    }

    /// Sets the NEB bead index metadata.
    pub fn set_neb_bead(&mut self, bead: u64) -> &mut Self {
        self.metadata
            .insert(meta::NEB_BEAD.into(), serde_json::Value::from(bead));
        self
    }

    /// Sets the NEB band index metadata.
    pub fn set_neb_band(&mut self, band: u64) -> &mut Self {
        self.metadata
            .insert(meta::NEB_BAND.into(), serde_json::Value::from(band));
        self
    }

    /// Replace optional frame topology (synced to `metadata["bonds"]`).
    pub fn set_bonds(&mut self, bonds: &[Bond]) -> &mut Self {
        if bonds.is_empty() {
            self.metadata.remove(meta::BONDS);
        } else {
            self.metadata
                .insert(meta::BONDS.into(), bonds_to_json_value(bonds));
        }
        self
    }

    /// Append one bond.
    pub fn add_bond(&mut self, bond: Bond) -> &mut Self {
        let mut bonds = parse_bonds_from_metadata(&self.metadata);
        bonds.push(bond);
        self.set_bonds(&bonds)
    }

    /// Adds an atom with no velocity or force data and returns `&mut self`
    /// for chaining `with_velocity` / `with_force` on the just-added atom.
    ///
    /// # Example
    /// ```
    /// use readcon_core::types::ConFrameBuilder;
    /// let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
    /// b.add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 0, 63.546)
    ///  .with_velocity([0.1, 0.2, 0.3])
    ///  .with_force([1.0, 0.0, 0.0]);
    /// ```
    #[allow(clippy::too_many_arguments)]
    pub fn add_atom(
        &mut self,
        symbol: &str,
        x: f64,
        y: f64,
        z: f64,
        fixed: [bool; 3],
        atom_id: u64,
        mass: f64,
    ) -> &mut Self {
        use ndarray::array;
        self.symbols.push(symbol.to_string());
        self.fixed.push(fixed);
        // Push a row to each owned ndarray. push_row is defined on
        // owned Array (OwnedRepr) but not on ArcArray (OwnedArcRepr),
        // so route the ArcArray storage through into_owned() then
        // back through into_shared(). When the Arc is uniquely owned
        // (the building phase before any clone) both calls are O(1)
        // atomic ops; once shared the into_owned() copy is the
        // copy-on-write the design wants.
        arc_push_row(&mut self.positions, array![x, y, z].view());
        arc_push_u64(&mut self.atom_ids, atom_id);
        arc_push_f64_1d(&mut self.masses, mass);
        if self.has_velocities {
            arc_push_row(&mut self.velocities, array![0.0, 0.0, 0.0].view());
        }
        if self.has_forces {
            arc_push_row(&mut self.forces, array![0.0, 0.0, 0.0].view());
        }
        if self.has_energies {
            arc_push_f64_1d(&mut self.atom_energies, 0.0);
        }
        self
    }

    /// Attaches velocity data to the most recently added atom.
    /// No-op (silently) if no atom has been added yet.
    pub fn with_velocity(&mut self, velocity: [f64; 3]) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_velocities {
            // First velocity declaration: backfill all earlier atoms with
            // zero so the section is length-coherent when declared on build().
            self.velocities = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_velocities = true;
        }
        let mut row = self.velocities.row_mut(n - 1);
        row[0] = velocity[0];
        row[1] = velocity[1];
        row[2] = velocity[2];
        self
    }

    /// Attaches force data to the most recently added atom.
    /// No-op (silently) if no atom has been added yet.
    pub fn with_force(&mut self, force: [f64; 3]) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_forces {
            self.forces = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_forces = true;
        }
        let mut row = self.forces.row_mut(n - 1);
        row[0] = force[0];
        row[1] = force[1];
        row[2] = force[2];
        self
    }

    /// Attaches a per-atom energy contribution to the most recently added
    /// atom. No-op (silently) if no atom has been added yet.
    pub fn with_energy(&mut self, energy: f64) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_energies {
            self.atom_energies = ndarray::ArcArray1::<f64>::zeros(n);
            self.has_energies = true;
        }
        self.atom_energies[n - 1] = energy;
        self
    }

    // ----- In-place mutation API (added in v0.11.0) -------------------------
    //
    // Hot-loop consumers (eOn's Matter, dynamics integrators in GROMACS-style
    // engines) update positions / forces / energies many thousands of times
    // per simulation step. The append-only `add_atom` + `with_*` API forces a
    // full rebuild each step, which is O(n*types) on `build()` and a pile of
    // allocations besides. The methods below let callers treat the builder as
    // a mutable in-memory frame: bulk-load once via `add_atom`, then update
    // positions / velocities / forces / energies in place across many steps,
    // and call `build()` only when serialising to disk.
    //
    // Index validation is fail-loud: every method returns
    // `Result<&mut Self, ParseError>` and surfaces an
    // `IndexOutOfBounds { index, len }` ParseError when `i >= atom_count()`.
    // The C ABI maps that to RKR_STATUS_INDEX_OUT_OF_BOUNDS.

    /// Number of atoms currently held in the builder.
    pub fn atom_count(&self) -> usize {
        self.symbols.len()
    }

    /// Updates the Cartesian position of an existing atom (zero-based index).
    pub fn set_atom_position(
        &mut self,
        i: usize,
        x: f64,
        y: f64,
        z: f64,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        let mut row = self.positions.row_mut(i);
        row[0] = x;
        row[1] = y;
        row[2] = z;
        Ok(self)
    }

    /// Sets the velocity vector of an existing atom. The frame auto-declares
    /// a `"velocities"` section on `build()` when any atom carries velocity.
    pub fn set_atom_velocity(
        &mut self,
        i: usize,
        velocity: [f64; 3],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_velocities {
            self.velocities = ndarray::ArcArray2::<f64>::zeros((len, 3));
            self.has_velocities = true;
        }
        let mut row = self.velocities.row_mut(i);
        row[0] = velocity[0];
        row[1] = velocity[1];
        row[2] = velocity[2];
        Ok(self)
    }

    /// Sets the force vector of an existing atom. The frame auto-declares a
    /// `"forces"` section on `build()` if any atom carries force.
    pub fn set_atom_force(
        &mut self,
        i: usize,
        force: [f64; 3],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_forces {
            self.forces = ndarray::ArcArray2::<f64>::zeros((len, 3));
            self.has_forces = true;
        }
        let mut row = self.forces.row_mut(i);
        row[0] = force[0];
        row[1] = force[1];
        row[2] = force[2];
        Ok(self)
    }

    /// Sets the per-atom energy contribution of an existing atom. The frame
    /// auto-declares an `"energies"` section on `build()` when any atom
    /// carries per-atom energy.
    pub fn set_atom_energy(
        &mut self,
        i: usize,
        energy: f64,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_energies {
            self.atom_energies = ndarray::ArcArray1::<f64>::zeros(len);
            self.has_energies = true;
        }
        self.atom_energies[i] = energy;
        Ok(self)
    }

    /// Updates per-direction fixed flags `[fixed_x, fixed_y, fixed_z]`.
    pub fn set_atom_fixed(
        &mut self,
        i: usize,
        fixed: [bool; 3],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        self.fixed[i] = fixed;
        Ok(self)
    }

    /// Updates the mass of an existing atom. Note: changing the mass of the
    /// only atom of a given type recomputes that type's `masses_per_type`
    /// entry on `build()`; mixing different masses for the same symbol is
    /// not supported by the .con format and the last value wins.
    pub fn set_atom_mass(
        &mut self,
        i: usize,
        mass: f64,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        self.masses[i] = mass;
        Ok(self)
    }

    /// Updates the atom_id (the pre-grouping index from .con column 5)
    /// of an existing atom. The atom_id is the only per-atom field that
    /// `add_atom` set once and offered no post-add mutator for, which
    /// forced downstream consumers (eOn's `ConFileIO::con2matter`) to
    /// rebuild the builder from scratch whenever they wanted to install
    /// non-sequential ids. This setter lets callers mutate one slot in
    /// place; the underlying `Array1<u64>` buffer pointer stays stable.
    pub fn set_atom_id(
        &mut self,
        i: usize,
        atom_id: u64,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        self.atom_ids[i] = atom_id;
        Ok(self)
    }

    /// Removes velocity data from an existing atom by zeroing the slot.
    /// If every atom subsequently lacks a meaningful velocity (the section
    /// can be cleared via `clear_velocities_section`) the next `build()`
    /// will not declare a `"velocities"` section.
    pub fn clear_atom_velocity(
        &mut self,
        i: usize,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if self.has_velocities {
            let mut row = self.velocities.row_mut(i);
            row[0] = 0.0;
            row[1] = 0.0;
            row[2] = 0.0;
        }
        Ok(self)
    }

    /// Removes force data from an existing atom by zeroing the slot.
    pub fn clear_atom_force(
        &mut self,
        i: usize,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if self.has_forces {
            let mut row = self.forces.row_mut(i);
            row[0] = 0.0;
            row[1] = 0.0;
            row[2] = 0.0;
        }
        Ok(self)
    }

    /// Removes per-atom energy data from an existing atom by zeroing the slot.
    pub fn clear_atom_energy(
        &mut self,
        i: usize,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if self.has_energies {
            self.atom_energies[i] = 0.0;
        }
        Ok(self)
    }

    /// Drops the velocities section entirely. The next `build()` will not
    /// declare `"velocities"`. Storage is reclaimed.
    pub fn clear_velocities_section(&mut self) -> &mut Self {
        self.velocities = ndarray::ArcArray2::<f64>::zeros((0, 3));
        self.has_velocities = false;
        self
    }

    /// Drops the forces section entirely.
    pub fn clear_forces_section(&mut self) -> &mut Self {
        self.forces = ndarray::ArcArray2::<f64>::zeros((0, 3));
        self.has_forces = false;
        self
    }

    /// Drops the per-atom energies section entirely.
    pub fn clear_energies_section(&mut self) -> &mut Self {
        self.atom_energies = ndarray::ArcArray1::<f64>::zeros(0);
        self.has_energies = false;
        self
    }

    /// Bulk-update positions for every atom from a flat buffer of length
    /// `3 * atom_count()`. Layout is row-major `[x0, y0, z0, x1, y1, z1, ...]`
    /// matching what NumPy / Eigen / Fortran-on-rows callers already use.
    /// Returns `InvalidVectorLength` if the buffer length disagrees.
    pub fn set_positions_from_flat(
        &mut self,
        positions: &[f64],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let n = self.symbols.len();
        if positions.len() != 3 * n {
            return Err(crate::error::ParseError::InvalidVectorLength {
                expected: 3 * n,
                found: positions.len(),
            });
        }
        // Standard-layout Array2 is row-major contiguous; safe to use
        // as_slice_memory_order_mut for a one-shot bulk copy.
        let dst = self
            .positions
            .as_slice_memory_order_mut()
            .expect("positions standard layout invariant violated");
        dst.copy_from_slice(positions);
        Ok(self)
    }

    /// Bulk-update forces for every atom from a flat buffer of length
    /// `3 * atom_count()`. Auto-declares a `"forces"` section on `build()`.
    pub fn set_forces_from_flat(
        &mut self,
        forces: &[f64],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let n = self.symbols.len();
        if forces.len() != 3 * n {
            return Err(crate::error::ParseError::InvalidVectorLength {
                expected: 3 * n,
                found: forces.len(),
            });
        }
        if !self.has_forces {
            self.forces = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_forces = true;
        }
        let dst = self
            .forces
            .as_slice_memory_order_mut()
            .expect("forces standard layout invariant violated");
        dst.copy_from_slice(forces);
        Ok(self)
    }

    /// Bulk-update per-atom energies for every atom from a buffer of length
    /// `atom_count()`. Auto-declares an `"energies"` section on `build()`.
    pub fn set_atom_energies_from_flat(
        &mut self,
        energies: &[f64],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let n = self.symbols.len();
        if energies.len() != n {
            return Err(crate::error::ParseError::InvalidVectorLength {
                expected: n,
                found: energies.len(),
            });
        }
        if !self.has_energies {
            self.atom_energies = ndarray::ArcArray1::<f64>::zeros(n);
            self.has_energies = true;
        }
        let dst = self
            .atom_energies
            .as_slice_memory_order_mut()
            .expect("atom_energies standard layout invariant violated");
        dst.copy_from_slice(energies);
        Ok(self)
    }

    /// Read-only accessor: position of atom `i` as `(x, y, z)`.
    pub fn get_atom_position(
        &self,
        i: usize,
    ) -> Result<(f64, f64, f64), crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        let row = self.positions.row(i);
        Ok((row[0], row[1], row[2]))
    }

    /// Read-only accessor: velocity of atom `i`, if any.
    pub fn get_atom_velocity(
        &self,
        i: usize,
    ) -> Result<Option<[f64; 3]>, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_velocities {
            return Ok(None);
        }
        let row = self.velocities.row(i);
        Ok(Some([row[0], row[1], row[2]]))
    }

    /// Read-only accessor: force on atom `i`, if any.
    pub fn get_atom_force(
        &self,
        i: usize,
    ) -> Result<Option<[f64; 3]>, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_forces {
            return Ok(None);
        }
        let row = self.forces.row(i);
        Ok(Some([row[0], row[1], row[2]]))
    }

    /// Read-only accessor: per-atom energy of atom `i`, if any.
    pub fn get_atom_energy(
        &self,
        i: usize,
    ) -> Result<Option<f64>, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_energies {
            return Ok(None);
        }
        Ok(Some(self.atom_energies[i]))
    }

    /// Read-only accessor: mass of atom `i`.
    pub fn get_atom_mass(&self, i: usize) -> Result<f64, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        Ok(self.masses[i])
    }

    // ----- Zero-copy SoA slice access (v0.11.0) -----------------------------
    //
    // Hot-loop consumers (eOn's Matter, MD integrators, NEB image updaters)
    // hold a `ConFrameBuilder` for the lifetime of a simulation and update
    // positions / forces / energies thousands of times per second. The
    // get/set wrappers above all charge a copy through Rust on every call,
    // which dominates the integration cost. The accessors below expose the
    // underlying SoA ndarray storage as `&[f64]` (row-major flat) /
    // `ArrayView2<f64>` (typed 2D) so callers can map a contiguous view --
    // `Eigen::Map<MatrixXd>(positions_data(), N, 3)` in C++,
    // `numpy.from_dlpack(...)` in Python, `unsafe_wrap(Array, ptr, ...)`
    // in Julia -- onto the builder's memory and write through it directly.
    //
    // The DLPack export tier (positions_dlpack(), etc.) is the cross-
    // language zero-copy hot path; the &[f64] slice tier below is the
    // pure-Rust shortcut.
    //
    // Pointer stability: the data pointer is stable as long as no
    // `add_atom` call grows the ndarray. Callers that hold raw pointers
    // across `add_atom` must refresh after the push.

    /// Row-major flat positions slice `[x0,y0,z0, x1,y1,z1, ...]`,
    /// length `3 * atom_count()`. Panics if the ndarray loses its
    /// standard-layout invariant (which our internal API never does).
    pub fn positions(&self) -> &[f64] {
        self.positions
            .as_slice_memory_order()
            .expect("positions standard layout invariant violated")
    }

    /// Mutable row-major positions slice; FFI exposes the same pointer
    /// for zero-copy in-place updates from C / C++ / Python / Julia.
    pub fn positions_mut(&mut self) -> &mut [f64] {
        self.positions
            .as_slice_memory_order_mut()
            .expect("positions standard layout invariant violated")
    }

    /// Typed 2D `(N, 3) f64` view onto positions. Preferred over the
    /// flat slice when the caller already speaks ndarray.
    pub fn positions_view(&self) -> ndarray::ArrayView2<'_, f64> {
        self.positions.view()
    }

    /// Mutable typed 2D `(N, 3) f64` view onto positions.
    pub fn positions_view_mut(&mut self) -> ndarray::ArrayViewMut2<'_, f64> {
        self.positions.view_mut()
    }

    /// Row-major velocities slice if the velocities section is populated,
    /// else an empty slice.
    pub fn velocities(&self) -> &[f64] {
        if self.has_velocities {
            self.velocities
                .as_slice_memory_order()
                .expect("velocities standard layout invariant violated")
        } else {
            &[]
        }
    }

    /// Mutable velocities slice. Auto-allocates the section if it was
    /// not already populated; subsequent `build()` will declare
    /// `"velocities"`.
    pub fn velocities_mut(&mut self) -> &mut [f64] {
        if !self.has_velocities {
            let n = self.symbols.len();
            self.velocities = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_velocities = true;
        }
        self.velocities
            .as_slice_memory_order_mut()
            .expect("velocities standard layout invariant violated")
    }

    /// Typed 2D `(N, 3) f64` view onto velocities (empty `(0, 3)` when
    /// the section is absent).
    pub fn velocities_view(&self) -> ndarray::ArrayView2<'_, f64> {
        self.velocities.view()
    }

    /// Row-major forces slice if the forces section is populated, else
    /// an empty slice.
    pub fn forces(&self) -> &[f64] {
        if self.has_forces {
            self.forces
                .as_slice_memory_order()
                .expect("forces standard layout invariant violated")
        } else {
            &[]
        }
    }

    /// Mutable forces slice. Auto-allocates the section if needed.
    pub fn forces_mut(&mut self) -> &mut [f64] {
        if !self.has_forces {
            let n = self.symbols.len();
            self.forces = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_forces = true;
        }
        self.forces
            .as_slice_memory_order_mut()
            .expect("forces standard layout invariant violated")
    }

    /// Typed 2D `(N, 3) f64` view onto forces.
    pub fn forces_view(&self) -> ndarray::ArrayView2<'_, f64> {
        self.forces.view()
    }

    /// Per-atom energies slice if the energies section is populated.
    pub fn atom_energies(&self) -> &[f64] {
        if self.has_energies {
            self.atom_energies
                .as_slice_memory_order()
                .expect("atom_energies standard layout invariant violated")
        } else {
            &[]
        }
    }

    /// Mutable per-atom energies slice. Auto-allocates the section if needed.
    pub fn atom_energies_mut(&mut self) -> &mut [f64] {
        if !self.has_energies {
            let n = self.symbols.len();
            self.atom_energies = ndarray::ArcArray1::<f64>::zeros(n);
            self.has_energies = true;
        }
        self.atom_energies
            .as_slice_memory_order_mut()
            .expect("atom_energies standard layout invariant violated")
    }

    /// Per-atom masses slice (length `atom_count()`).
    pub fn masses(&self) -> &[f64] {
        self.masses
            .as_slice_memory_order()
            .expect("masses standard layout invariant violated")
    }

    /// Mutable per-atom masses slice.
    pub fn masses_mut(&mut self) -> &mut [f64] {
        self.masses
            .as_slice_memory_order_mut()
            .expect("masses standard layout invariant violated")
    }

    /// Per-atom atom_id slice (length `atom_count()`).
    pub fn atom_ids(&self) -> &[u64] {
        self.atom_ids
            .as_slice_memory_order()
            .expect("atom_ids standard layout invariant violated")
    }

    // ----- Crate-internal ndarray refs --------------------------------------
    //
    // FFI / cross-crate consumers (src/ffi.rs) need `&Array<T, D>` to
    // construct DLPack tensors via dlpk's `TryFrom<&'a Array<T, D>>`.
    // These accessors are pub-but-deliberately-low-level: callers should
    // prefer `positions_dlpack()` / `positions_view()` for typed access.
    /// Crate-internal `&Array2<f64>` for the FFI DLPack exporter.
    pub fn positions_2d_ref(&self) -> &ndarray::ArcArray2<f64> {
        &self.positions
    }
    /// Crate-internal `&Array2<f64>` velocities ref (caller checks the
    /// section flag first).
    pub fn velocities_2d_ref(&self) -> &ndarray::ArcArray2<f64> {
        &self.velocities
    }
    /// Crate-internal `&Array2<f64>` forces ref.
    pub fn forces_2d_ref(&self) -> &ndarray::ArcArray2<f64> {
        &self.forces
    }
    /// Crate-internal `&Array1<f64>` atom_energies ref.
    pub fn atom_energies_1d_ref(&self) -> &ndarray::ArcArray1<f64> {
        &self.atom_energies
    }
    /// Crate-internal `&Array1<f64>` masses ref.
    pub fn masses_1d_ref(&self) -> &ndarray::ArcArray1<f64> {
        &self.masses
    }
    /// Crate-internal `&Array1<u64>` atom_ids ref.
    pub fn atom_ids_1d_ref(&self) -> &ndarray::ArcArray1<u64> {
        &self.atom_ids
    }

    // ----- DLPack zero-copy export (v0.11.0) --------------------------------
    //
    // Cross-language consumers (C++ Eigen, Python numpy / PyTorch / JAX,
    // Julia DLPack.jl, R reticulate, ...) speak DLPack as the canonical
    // tensor-exchange ABI. The methods below return a
    // `dlpk::DLPackTensorRef<'_>` (borrowed view, lifetime tied to
    // `&self`) for each per-atom field. The view carries shape, strides,
    // dtype, device, and data pointer; the consumer reinterprets it as
    // their native tensor type with zero copies.
    //
    // The lifetime contract is enforced by Rust: a DLPackTensorRef borrowed
    // from `&self.positions` cannot outlive the builder. C / FFI consumers
    // that need an owning tensor (longer lifetime than the builder) go
    // through the C ABI's `DLManagedTensorVersioned` export which clones the
    // backing storage; see `src/ffi.rs`.

    /// DLPack view onto positions, shape `(N, 3) f64`, lifetime tied to
    /// `&self`. The returned `DLPackTensorRef` reads through to the
    /// builder's `Array2<f64>` storage zero-copy.
    pub fn positions_dlpack(&self) -> Result<dlpk::DLPackTensorRef<'_>, crate::error::ParseError> {
        dlpk::DLPackTensorRef::try_from(&self.positions).map_err(|e| {
            crate::error::ParseError::ValidationError(format!(
                "DLPack export for positions failed: {e}"
            ))
        })
    }

    /// DLPack view onto velocities, shape `(N, 3) f64`. Returns `None`
    /// if the velocities section is absent.
    pub fn velocities_dlpack(
        &self,
    ) -> Result<Option<dlpk::DLPackTensorRef<'_>>, crate::error::ParseError> {
        if !self.has_velocities {
            return Ok(None);
        }
        let view = dlpk::DLPackTensorRef::try_from(&self.velocities).map_err(|e| {
            crate::error::ParseError::ValidationError(format!(
                "DLPack export for velocities failed: {e}"
            ))
        })?;
        Ok(Some(view))
    }

    /// DLPack view onto forces, shape `(N, 3) f64`. Returns `None` if
    /// the forces section is absent.
    pub fn forces_dlpack(
        &self,
    ) -> Result<Option<dlpk::DLPackTensorRef<'_>>, crate::error::ParseError> {
        if !self.has_forces {
            return Ok(None);
        }
        let view = dlpk::DLPackTensorRef::try_from(&self.forces).map_err(|e| {
            crate::error::ParseError::ValidationError(format!(
                "DLPack export for forces failed: {e}"
            ))
        })?;
        Ok(Some(view))
    }

    /// DLPack view onto per-atom energies, shape `(N,) f64`. Returns
    /// `None` if the energies section is absent.
    pub fn atom_energies_dlpack(
        &self,
    ) -> Result<Option<dlpk::DLPackTensorRef<'_>>, crate::error::ParseError> {
        if !self.has_energies {
            return Ok(None);
        }
        let view = dlpk::DLPackTensorRef::try_from(&self.atom_energies).map_err(|e| {
            crate::error::ParseError::ValidationError(format!(
                "DLPack export for atom_energies failed: {e}"
            ))
        })?;
        Ok(Some(view))
    }

    /// DLPack view onto per-atom masses, shape `(N,) f64`.
    pub fn masses_dlpack(&self) -> Result<dlpk::DLPackTensorRef<'_>, crate::error::ParseError> {
        dlpk::DLPackTensorRef::try_from(&self.masses).map_err(|e| {
            crate::error::ParseError::ValidationError(format!(
                "DLPack export for masses failed: {e}"
            ))
        })
    }

    /// DLPack view onto per-atom atom_ids, shape `(N,) u64`.
    pub fn atom_ids_dlpack(&self) -> Result<dlpk::DLPackTensorRef<'_>, crate::error::ParseError> {
        dlpk::DLPackTensorRef::try_from(&self.atom_ids).map_err(|e| {
            crate::error::ParseError::ValidationError(format!(
                "DLPack export for atom_ids failed: {e}"
            ))
        })
    }

    /// Whether the builder currently has a velocities section populated.
    pub fn has_velocities_section(&self) -> bool {
        self.has_velocities
    }

    /// Whether the builder currently has a forces section populated.
    pub fn has_forces_section(&self) -> bool {
        self.has_forces
    }

    /// Whether the builder currently has a per-atom energies section populated.
    pub fn has_energies_section(&self) -> bool {
        self.has_energies
    }

    // ----- end in-place mutation API ----------------------------------------

    /// Consumes the builder and produces a `ConFrame`.
    ///
    /// Atoms are grouped by symbol (in encounter order) to compute
    /// `natm_types`, `natms_per_type`, and `masses_per_type`.
    pub fn build(self) -> ConFrame {
        // Single-pass grouping: assign each atom a type index in encounter
        // order and bucket its position. The buckets preserve per-symbol
        // input order so the final flatten yields atoms grouped by type.
        let n = self.symbols.len();
        let mut type_order: Vec<String> = Vec::new();
        let mut type_counts: Vec<usize> = Vec::new();
        let mut type_masses: Vec<f64> = Vec::new();
        let mut buckets: Vec<Vec<usize>> = Vec::new();

        for i in 0..n {
            let symbol = &self.symbols[i];
            let mass = self.masses[i];
            let idx = match type_order.iter().position(|s| s == symbol) {
                Some(idx) => {
                    type_counts[idx] += 1;
                    idx
                }
                None => {
                    type_order.push(symbol.clone());
                    type_counts.push(1);
                    type_masses.push(mass);
                    buckets.push(Vec::new());
                    type_order.len() - 1
                }
            };
            buckets[idx].push(i);
        }

        // One Arc<str> per type so all atoms of the same symbol share storage.
        let type_symbols: Vec<Arc<str>> =
            type_order.iter().map(|s| Arc::from(s.as_str())).collect();

        let has_vel = self.has_velocities;
        let has_frc = self.has_forces;
        let has_eng = self.has_energies;

        let mut atom_data: Vec<AtomDatum> = Vec::with_capacity(n);
        for (type_idx, indices) in buckets.iter().enumerate() {
            let symbol = &type_symbols[type_idx];
            for &i in indices {
                let pos = self.positions.row(i);
                let velocity = if has_vel {
                    let r = self.velocities.row(i);
                    Some([r[0], r[1], r[2]])
                } else {
                    None
                };
                let force = if has_frc {
                    let r = self.forces.row(i);
                    Some([r[0], r[1], r[2]])
                } else {
                    None
                };
                let energy = if has_eng {
                    Some(self.atom_energies[i])
                } else {
                    None
                };
                atom_data.push(AtomDatum {
                    symbol: Arc::clone(symbol),
                    x: pos[0],
                    y: pos[1],
                    z: pos[2],
                    fixed: self.fixed[i],
                    atom_id: self.atom_ids[i],
                    velocity,
                    force,
                    energy,
                });
            }
        }

        let mut sections = Vec::new();
        if has_vel {
            sections.push(SECTION_VELOCITIES.into());
        }
        if has_frc {
            sections.push(SECTION_FORCES.into());
        }
        if has_eng {
            sections.push(SECTION_ENERGIES.into());
        }

        let strict_validation = matches!(
            self.metadata.get(meta::VALIDATE),
            Some(serde_json::Value::Bool(true))
        );
        let sections_declared = !sections.is_empty();
        let mut metadata = self.metadata;
        // v3 writers always emit units (defaults if the caller omitted them).
        if crate::CON_SPEC_VERSION >= 3 && !metadata.contains_key(meta::UNITS) {
            metadata.insert(meta::UNITS.into(), crate::units::default_v3_units_json());
        }
        use crate::storage_dtype::{FloatArray1, FloatArray2, StorageDtypes};
        let dt = StorageDtypes::from_metadata(&metadata).unwrap_or_default();
        // Allocate SoA in the requested storage dtypes (not f64-then-cast).
        let mut pos = FloatArray2::zeros(dt.positions, n, 3);
        let mut vel = FloatArray2::zeros(dt.velocities, if has_vel { n } else { 0 }, 3);
        let mut frc = FloatArray2::zeros(dt.forces, if has_frc { n } else { 0 }, 3);
        let mut eng = FloatArray1::zeros(dt.energies, if has_eng { n } else { 0 });
        let mut masses_arr = FloatArray1::zeros(dt.masses, n);
        let mut ids_arr = ndarray::ArcArray1::<u64>::zeros(n);
        if dt != StorageDtypes::all_f64() {
            dt.insert_into(&mut metadata);
        }
        for (i, a) in atom_data.iter().enumerate() {
            pos.set_f64_row(i, [a.x, a.y, a.z]);
            ids_arr[i] = a.atom_id;
            if has_vel {
                if let Some(v) = a.velocity {
                    vel.set_f64_row(i, v);
                }
            }
            if has_frc {
                if let Some(f) = a.force {
                    frc.set_f64_row(i, f);
                }
            }
            if has_eng {
                eng.set_f64(i, a.energy.unwrap_or(0.0));
            }
        }
        let mut off = 0usize;
        for (ti, &count) in type_counts.iter().enumerate() {
            let m = type_masses.get(ti).copied().unwrap_or(0.0);
            for _ in 0..count {
                if off < n {
                    masses_arr.set_f64(off, m);
                    off += 1;
                }
            }
        }

        let header = FrameHeader {
            prebox_header: PreboxHeader::new(self.prebox_user),
            boxl: self.cell,
            angles: self.angles,
            postbox_header: self.postbox_header,
            natm_types: type_order.len(),
            natms_per_type: type_counts,
            masses_per_type: type_masses,
            spec_version: crate::CON_SPEC_VERSION,
            metadata,
            sections,
            strict_validation,
            sections_declared,
        };

        ConFrame {
            header,
            atom_data,
            positions: pos,
            velocities: vel,
            forces: frc,
            atom_energies: eng,
            masses: masses_arr,
            atom_ids: ids_arr,
        }
    }
}

/// Build a [`ConFrame`] from header + AoS atoms, filling SoA numeric arrays.
/// Prefer [`con_frame_from_atom_data_with_positions`] on the CON parse hot path
/// when positions were already written into SoA during coordinate parsing.
pub fn con_frame_from_atom_data(header: FrameHeader, atom_data: Vec<AtomDatum>) -> ConFrame {
    let n = atom_data.len();
    use crate::storage_dtype::{FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let mut pos = FloatArray2::zeros(dt.positions, n, 3);
    for (i, a) in atom_data.iter().enumerate() {
        pos.set_f64_row(i, [a.x, a.y, a.z]);
    }
    con_frame_from_atom_data_with_positions(header, atom_data, pos)
}

/// Like [`con_frame_from_atom_data`], but **reuses** prefilled `positions` SoA
/// (no second O(N) position write). Velocities/forces/energies still filled from AoS.
pub fn con_frame_from_atom_data_with_positions(
    header: FrameHeader,
    atom_data: Vec<AtomDatum>,
    positions: crate::storage_dtype::FloatArray2,
) -> ConFrame {
    let n = atom_data.len();
    debug_assert_eq!(positions.nrows(), n);
    let has_vel = atom_data.first().is_some_and(|a| a.has_velocity());
    let has_frc = atom_data.first().is_some_and(|a| a.has_forces());
    let has_eng = atom_data.first().is_some_and(|a| a.has_energy());
    use crate::storage_dtype::{FloatArray1, FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let pos = positions;
    let mut vel = FloatArray2::zeros(dt.velocities, if has_vel { n } else { 0 }, 3);
    let mut frc = FloatArray2::zeros(dt.forces, if has_frc { n } else { 0 }, 3);
    let mut eng = FloatArray1::zeros(dt.energies, if has_eng { n } else { 0 });
    let mut masses_arr = FloatArray1::zeros(dt.masses, n);
    let mut ids_arr = ndarray::ArcArray1::<u64>::zeros(n);
    let mut off = 0usize;
    for (ti, &count) in header.natms_per_type.iter().enumerate() {
        let m = header.masses_per_type.get(ti).copied().unwrap_or(0.0);
        for _ in 0..count {
            if off < n {
                masses_arr.set_f64(off, m);
                off += 1;
            }
        }
    }
    for (i, a) in atom_data.iter().enumerate() {
        // Positions already in SoA; only ids + optional sections.
        ids_arr[i] = a.atom_id;
        if has_vel {
            if let Some(v) = a.velocity {
                vel.set_f64_row(i, v);
            }
        }
        if has_frc {
            if let Some(f) = a.force {
                frc.set_f64_row(i, f);
            }
        }
        if has_eng {
            eng.set_f64(i, a.energy.unwrap_or(0.0));
        }
    }
    let mut header = header;
    // Only persist storage_dtypes when non-default (avoid metadata churn on hot parse).
    if dt != crate::storage_dtype::StorageDtypes::all_f64() {
        dt.insert_into(&mut header.metadata);
    }
    // AoS and SoA agree on positions (written during parse); sections mirrored above.
    ConFrame {
        header,
        atom_data,
        positions: pos,
        velocities: vel,
        forces: frc,
        atom_energies: eng,
        masses: masses_arr,
        atom_ids: ids_arr,
    }
}

// }

impl ConFrame {
    /// Creates a new builder for constructing a `ConFrame`.
    pub fn builder(cell: [f64; 3], angles: [f64; 3]) -> ConFrameBuilder {
        ConFrameBuilder::new(cell, angles)
    }

    /// Delegate: `length` unit from header metadata.
    pub fn length_unit(&self) -> Option<&str> {
        self.header.length_unit()
    }

    /// Delegate: `energy` unit from header metadata.
    pub fn energy_unit(&self) -> Option<&str> {
        self.header.energy_unit()
    }

    /// Delegate: conversion factor from this frame's unit for `dimension` to `to_unit`.
    pub fn conversion_factor_to(
        &self,
        dimension: &str,
        to_unit: &str,
    ) -> Result<f64, crate::error::ParseError> {
        self.header.conversion_factor_to(dimension, to_unit)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_atom_id_index_handles_non_sequential_ids() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 100, 63.546);
        builder.add_atom("Cu", 1.0, 0.0, 0.0, [false, false, false], 42, 63.546);
        builder.add_atom("H", 2.0, 0.0, 0.0, [false, false, false], 7, 1.008);
        let frame = builder.build();
        let idx = frame.build_atom_id_index();
        assert_eq!(idx.get(&100).copied(), Some(0));
        assert_eq!(idx.get(&42).copied(), Some(1));
        assert_eq!(idx.get(&7).copied(), Some(2));
        assert_eq!(idx.get(&999), None);
        assert_eq!(frame.atom_index_by_id(42), Some(1));
        assert_eq!(frame.atom_index_by_id(999), None);
    }

    #[test]
    fn test_builder_basic() {
        let mut builder = ConFrameBuilder::new([10.0, 20.0, 30.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [true, true, true], 0, 63.546);
        builder.add_atom("Cu", 1.0, 0.0, 0.0, [true, true, true], 1, 63.546);
        builder.add_atom("H", 2.0, 3.0, 4.0, [false, false, false], 2, 1.008);
        let frame = builder.build();

        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![2, 1]);
        assert_eq!(frame.header.masses_per_type, vec![63.546, 1.008]);
        assert_eq!(frame.atom_data.len(), 3);
        assert_eq!(&*frame.atom_data[0].symbol, "Cu");
        assert_eq!(&*frame.atom_data[2].symbol, "H");
    }

    #[test]
    fn test_builder_with_velocities() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .add_atom("Cu", 0.0, 0.0, 0.0, [true, true, true], 0, 63.546)
            .with_velocity([0.1, 0.2, 0.3]);
        let frame = builder.build();

        assert!(frame.has_velocities());
        assert_eq!(frame.atom_data[0].velocity, Some([0.1, 0.2, 0.3]));
    }

    #[test]
    fn test_builder_with_headers() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .prebox_header("line1")
            .postbox_header(["line3".to_string(), "line4".to_string()]);
        let frame = builder.build();

        assert_eq!(frame.header.prebox_header.user, "line1");
        assert_eq!(frame.header.postbox_header, ["line3", "line4"]);
    }

    #[test]
    fn test_builder_groups_atoms_by_symbol() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        // Add interleaved symbols
        builder.add_atom("H", 0.0, 0.0, 0.0, [false, false, false], 0, 1.008);
        builder.add_atom("Cu", 1.0, 0.0, 0.0, [true, true, true], 1, 63.546);
        builder.add_atom("H", 2.0, 0.0, 0.0, [false, false, false], 2, 1.008);
        let frame = builder.build();

        // H appears first, so it should be first type
        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![2, 1]);
        // Atoms should be grouped: H, H, Cu
        assert_eq!(&*frame.atom_data[0].symbol, "H");
        assert_eq!(&*frame.atom_data[1].symbol, "H");
        assert_eq!(&*frame.atom_data[2].symbol, "Cu");
    }

    #[test]
    fn test_metadata_helpers_energy() {
        let mut header = FrameHeader {
            prebox_header: PreboxHeader::default(),
            boxl: [10.0, 10.0, 10.0],
            angles: [90.0, 90.0, 90.0],
            postbox_header: [String::new(), String::new()],
            natm_types: 0,
            natms_per_type: vec![],
            masses_per_type: vec![],
            spec_version: 2,
            metadata: BTreeMap::new(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        assert_eq!(header.energy(), None);
        header.set_energy(-42.5);
        assert_eq!(header.energy(), Some(-42.5));
    }

    #[test]
    fn test_metadata_helpers_potential() {
        let mut header = FrameHeader {
            prebox_header: PreboxHeader::default(),
            boxl: [10.0, 10.0, 10.0],
            angles: [90.0, 90.0, 90.0],
            postbox_header: [String::new(), String::new()],
            natm_types: 0,
            natms_per_type: vec![],
            masses_per_type: vec![],
            spec_version: 2,
            metadata: BTreeMap::new(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        assert_eq!(header.potential_type(), None);
        header.set_potential("EMT", serde_json::json!({"cutoff": 6.0}));
        assert_eq!(header.potential_type(), Some("EMT"));
        assert_eq!(
            header.potential_params(),
            Some(&serde_json::json!({"cutoff": 6.0}))
        );
    }

    #[test]
    fn test_metadata_helpers_trajectory() {
        let mut header = FrameHeader {
            prebox_header: PreboxHeader::default(),
            boxl: [10.0, 10.0, 10.0],
            angles: [90.0, 90.0, 90.0],
            postbox_header: [String::new(), String::new()],
            natm_types: 0,
            natms_per_type: vec![],
            masses_per_type: vec![],
            spec_version: 2,
            metadata: BTreeMap::new(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        header.set_frame_index(5);
        header.set_time(2.5);
        header.set_timestep(0.5);
        header.set_neb_bead(3);
        header.set_neb_band(1);
        assert_eq!(header.frame_index(), Some(5));
        assert_eq!(header.time(), Some(2.5));
        assert_eq!(header.timestep(), Some(0.5));
        assert_eq!(header.neb_bead(), Some(3));
        assert_eq!(header.neb_band(), Some(1));
    }

    #[test]
    fn project_positions_to_float32_storage_and_as_dlpack() {
        use crate::storage_dtype::FloatStorageKind;
        // Allocate SoA as float32 on build (not f64 then project).
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.storage_float32_positions();
        b.add_atom("H", 1.0, 2.0, 3.0, [false; 3], 0, 1.0);
        let frame = b.build();
        assert_eq!(frame.positions.kind(), FloatStorageKind::Float32);
        let t = frame
            .positions_as_dlpack(dlpk::sys::DLDevice::cpu())
            .unwrap();
        assert_eq!(t.shape(), &[1, 3]);
        assert!(frame.header.metadata.get(meta::STORAGE_DTYPES).is_some());
        let row = frame.positions.as_f64_row(0);
        assert!((row[0] - 1.0).abs() < 1e-5);
    }

    #[test]
    fn allocate_all_float_fields_as_f32() {
        use crate::storage_dtype::{FloatStorageKind, StorageDtypes};
        let mut dt = StorageDtypes::all_f64();
        dt.positions = FloatStorageKind::Float32;
        dt.velocities = FloatStorageKind::Float32;
        dt.forces = FloatStorageKind::Float32;
        dt.energies = FloatStorageKind::Float32;
        dt.masses = FloatStorageKind::Float32;
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.storage_dtypes(dt);
        b.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0)
            .with_velocity([1.0, 0.0, 0.0])
            .with_force([0.0, 1.0, 0.0])
            .with_energy(-1.0);
        let frame = b.build();
        assert_eq!(frame.positions.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.velocities.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.forces.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.atom_energies.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.masses.kind(), FloatStorageKind::Float32);
        assert!(frame.velocities_as_dlpack(dlpk::sys::DLDevice::cpu())
            .unwrap()
            .is_some());
    }

    #[test]
    fn typed_units_and_conversion_on_built_frame() {
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 1.0, 2.0, 3.0, [false; 3], 0, 1.0);
        let frame = b.build();
        assert_eq!(frame.header.spec_version, crate::CON_SPEC_VERSION);
        // Builder injects default v3 units
        assert_eq!(frame.length_unit(), Some("angstrom"));
        assert_eq!(frame.energy_unit(), Some("eV"));
        let to_nm = frame.conversion_factor_to("length", "nm").unwrap();
        assert!((to_nm - 0.1).abs() < 1e-12);
        let x_nm = frame.atom_data[0].x * to_nm;
        assert!((x_nm - 0.1).abs() < 1e-12);
    }

    #[test]
    fn test_metadata_helpers_units() {
        let mut header = FrameHeader {
            prebox_header: PreboxHeader::default(),
            boxl: [10.0, 10.0, 10.0],
            angles: [90.0, 90.0, 90.0],
            postbox_header: [String::new(), String::new()],
            natm_types: 0,
            natms_per_type: vec![],
            masses_per_type: vec![],
            spec_version: 2,
            metadata: BTreeMap::new(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        assert_eq!(header.units(), None);
        header.set_units(serde_json::json!({"length": "angstrom", "energy": "eV"}));
        let units = header.units().unwrap();
        assert_eq!(units["length"], "angstrom");
        assert_eq!(units["energy"], "eV");
    }

    #[test]
    fn test_metadata_helpers_pbc() {
        let mut header = FrameHeader {
            prebox_header: PreboxHeader::default(),
            boxl: [10.0, 10.0, 20.0],
            angles: [90.0, 90.0, 90.0],
            postbox_header: [String::new(), String::new()],
            natm_types: 0,
            natms_per_type: vec![],
            masses_per_type: vec![],
            spec_version: 2,
            metadata: BTreeMap::new(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        assert_eq!(header.pbc(), None);
        header.set_pbc([true, true, false]);
        assert_eq!(header.pbc(), Some([true, true, false]));
    }

    #[test]
    fn test_metadata_helpers_lattice_vectors() {
        let mut header = FrameHeader {
            prebox_header: PreboxHeader::default(),
            boxl: [10.0, 10.0, 10.0],
            angles: [90.0, 90.0, 90.0],
            postbox_header: [String::new(), String::new()],
            natm_types: 0,
            natms_per_type: vec![],
            masses_per_type: vec![],
            spec_version: 2,
            metadata: BTreeMap::new(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        assert_eq!(header.lattice_vectors(), None);
        let vecs = [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 20.0]];
        header.set_lattice_vectors(vecs);
        assert_eq!(header.lattice_vectors(), Some(vecs));
    }

    #[test]
    fn test_builder_set_metadata_json_rejects_bad_pbc() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        let err = builder
            .set_metadata_json(r#"{"pbc":[1, 2, 3]}"#)
            .expect_err("non-bool pbc must be rejected");
        assert!(err.to_string().contains("pbc"));
    }

    #[test]
    fn test_builder_set_metadata_json_rejects_bad_lattice() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        let err = builder
            .set_metadata_json(r#"{"lattice_vectors":[[1,2,3],[4,5,6]]}"#)
            .expect_err("3x2 lattice_vectors must be rejected");
        assert!(err.to_string().contains("lattice_vectors"));
    }

    #[test]
    fn test_builder_set_metadata_json() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .set_metadata_json(
                r#"{"con_spec_version":2,"frame_index":5,"energy":-42.5,"sections":["forces"],"generator":"test"}"#,
            )
            .unwrap();
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 0, 63.546);

        let frame = builder.build();
        assert_eq!(frame.header.spec_version, crate::CON_SPEC_VERSION);
        assert_eq!(frame.header.frame_index(), Some(5));
        assert_eq!(frame.header.energy(), Some(-42.5));
        assert_eq!(
            frame.header.metadata.get("generator"),
            Some(&serde_json::Value::String("test".to_string()))
        );
        assert!(frame.header.sections.is_empty());
    }

    #[test]
    fn test_builder_typed_metadata_setters() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.set_frame_index(7);
        builder.set_energy(-1.25);
        builder.set_time(3.5);
        builder.set_timestep(0.2);
        builder.set_neb_bead(4);
        builder.set_neb_band(2);
        builder.set_scalar_metadata("convergence", 1.0e-3);
        builder.set_string_metadata("generator", "eon");
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 0, 63.546);

        let frame = builder.build();
        assert_eq!(frame.header.frame_index(), Some(7));
        assert_eq!(frame.header.energy(), Some(-1.25));
        assert_eq!(frame.header.time(), Some(3.5));
        assert_eq!(frame.header.timestep(), Some(0.2));
        assert_eq!(frame.header.neb_bead(), Some(4));
        assert_eq!(frame.header.neb_band(), Some(2));
        assert_eq!(
            frame.header.metadata.get("convergence"),
            Some(&serde_json::Value::from(1.0e-3))
        );
        assert_eq!(
            frame.header.metadata.get("generator"),
            Some(&serde_json::Value::from("eon"))
        );
    }

    // ----- in-place mutation API tests (v0.11.0) --------------------------

    fn three_atom_builder() -> ConFrameBuilder {
        let mut b = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        b.add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 0, 63.546);
        b.add_atom("Cu", 1.0, 1.0, 1.0, [false; 3], 1, 63.546);
        b.add_atom("H", 2.0, 0.0, 0.0, [false; 3], 2, 1.008);
        b
    }

    #[test]
    fn builder_atom_count_tracks_pushes() {
        let mut b = ConFrameBuilder::new([1.0; 3], [90.0; 3]);
        assert_eq!(b.atom_count(), 0);
        b.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
        assert_eq!(b.atom_count(), 1);
        b.add_atom("H", 1.0, 1.0, 1.0, [false; 3], 1, 1.0);
        assert_eq!(b.atom_count(), 2);
    }

    #[test]
    fn builder_set_atom_position_in_place() {
        let mut b = three_atom_builder();
        b.set_atom_position(1, 5.0, 6.0, 7.0).unwrap();
        let (x, y, z) = b.get_atom_position(1).unwrap();
        assert_eq!((x, y, z), (5.0, 6.0, 7.0));
        // unaffected siblings
        let (x0, y0, z0) = b.get_atom_position(0).unwrap();
        assert_eq!((x0, y0, z0), (0.0, 0.0, 0.0));
        let (x2, y2, z2) = b.get_atom_position(2).unwrap();
        assert_eq!((x2, y2, z2), (2.0, 0.0, 0.0));
    }

    #[test]
    fn builder_set_atom_velocity_force_energy() {
        let mut b = three_atom_builder();
        b.set_atom_velocity(0, [0.1, 0.2, 0.3]).unwrap();
        b.set_atom_force(1, [10.0, 0.0, 0.0]).unwrap();
        b.set_atom_energy(2, -1.5).unwrap();
        assert_eq!(b.get_atom_velocity(0).unwrap(), Some([0.1, 0.2, 0.3]));
        assert_eq!(b.get_atom_force(1).unwrap(), Some([10.0, 0.0, 0.0]));
        assert_eq!(b.get_atom_energy(2).unwrap(), Some(-1.5));
        // Frame should auto-declare all three sections on build.
        let frame = b.build();
        let names: Vec<&str> = frame.header.sections.iter().map(|s| s.as_str()).collect();
        assert!(names.contains(&"velocities"));
        assert!(names.contains(&"forces"));
        assert!(names.contains(&"energies"));
    }

    #[test]
    fn builder_clear_atom_velocity_zeros_slot_keeps_section() {
        // v0.11 SoA contract: clearing one atom's velocity zeros the
        // slot but keeps the velocities section declared so the
        // contiguous Vec<f64> stays length-coherent (3*N). The slice
        // / DLPack view contract requires the buffer to exist whenever
        // the section flag is set. Use clear_velocities_section() to
        // drop the section entirely.
        let mut b = three_atom_builder();
        b.with_velocity([1.0, 2.0, 3.0]);
        b.clear_atom_velocity(2).unwrap();
        // Section still declared; slot zeroed.
        assert!(b.has_velocities_section());
        assert_eq!(b.get_atom_velocity(2).unwrap(), Some([0.0, 0.0, 0.0]));
        // Section-level drop returns to "no velocities at all".
        b.clear_velocities_section();
        assert!(!b.has_velocities_section());
        assert_eq!(b.get_atom_velocity(2).unwrap(), None);
    }

    #[test]
    fn builder_set_atom_fixed_and_mass() {
        let mut b = three_atom_builder();
        b.set_atom_fixed(0, [true, false, true]).unwrap();
        b.set_atom_mass(0, 100.0).unwrap();
        let frame = b.build();
        assert_eq!(frame.atom_data[0].fixed, [true, false, true]);
        // type-grouped: index 0 in atom_data is the first "Cu" entry which
        // started life at builder index 0; mass survives via masses_per_type.
        assert_eq!(frame.header.masses_per_type[0], 100.0);
    }

    #[test]
    fn builder_set_atom_id_overrides_sequential_default() {
        let mut b = three_atom_builder();
        // three_atom_builder seeds atom_ids 0..3 via add_atom; override
        // them with non-sequential values (simulating .con column-5
        // load) and verify the build round-trips them.
        b.set_atom_id(0, 42).unwrap();
        b.set_atom_id(1, 7).unwrap();
        b.set_atom_id(2, 99).unwrap();
        // Buffer pointer stability: mutation should not reallocate.
        let ptr_before = b.atom_ids().as_ptr();
        b.set_atom_id(0, 1234).unwrap();
        let ptr_after = b.atom_ids().as_ptr();
        assert_eq!(ptr_before, ptr_after);
        // Restore the test fixture's id 42 so the build round-trip
        // check below still asserts the documented value.
        b.set_atom_id(0, 42).unwrap();
        let frame = b.build();
        // Type-grouping reorders atom_data; locate ids via the symbol.
        let cu_ids: Vec<u64> = frame
            .atom_data
            .iter()
            .filter(|a| a.symbol.as_ref() == "Cu")
            .map(|a| a.atom_id)
            .collect();
        let h_ids: Vec<u64> = frame
            .atom_data
            .iter()
            .filter(|a| a.symbol.as_ref() == "H")
            .map(|a| a.atom_id)
            .collect();
        assert_eq!(cu_ids, vec![42, 7]);
        assert_eq!(h_ids, vec![99]);
    }

    #[test]
    fn builder_set_atom_id_out_of_bounds_is_loud() {
        let mut b = three_atom_builder();
        let err = b.set_atom_id(99, 0).unwrap_err();
        assert!(matches!(
            err,
            crate::error::ParseError::IndexOutOfBounds { index: 99, len: 3 }
        ));
    }

    #[test]
    fn builder_index_out_of_bounds_is_loud() {
        let mut b = three_atom_builder();
        let err = b.set_atom_position(99, 0.0, 0.0, 0.0).unwrap_err();
        match err {
            crate::error::ParseError::IndexOutOfBounds { index, len } => {
                assert_eq!(index, 99);
                assert_eq!(len, 3);
            }
            other => panic!("expected IndexOutOfBounds, got {other:?}"),
        }
    }

    #[test]
    fn builder_bulk_set_positions_from_flat() {
        let mut b = three_atom_builder();
        let new_pos = [
            10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0,
        ];
        b.set_positions_from_flat(&new_pos).unwrap();
        assert_eq!(b.get_atom_position(0).unwrap(), (10.0, 20.0, 30.0));
        assert_eq!(b.get_atom_position(1).unwrap(), (40.0, 50.0, 60.0));
        assert_eq!(b.get_atom_position(2).unwrap(), (70.0, 80.0, 90.0));
    }

    #[test]
    fn builder_bulk_set_positions_wrong_length_errors() {
        let mut b = three_atom_builder();
        let bad = [1.0, 2.0, 3.0, 4.0]; // 4 != 3*3
        let err = b.set_positions_from_flat(&bad).unwrap_err();
        match err {
            crate::error::ParseError::InvalidVectorLength { expected, found } => {
                assert_eq!(expected, 9);
                assert_eq!(found, 4);
            }
            other => panic!("expected InvalidVectorLength, got {other:?}"),
        }
    }

    #[test]
    fn builder_bulk_set_forces_and_energies_from_flat() {
        let mut b = three_atom_builder();
        let f = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0];
        let e = [-0.1, -0.2, -0.3];
        b.set_forces_from_flat(&f).unwrap();
        b.set_atom_energies_from_flat(&e).unwrap();
        assert_eq!(b.get_atom_force(0).unwrap(), Some([1.0, 0.0, 0.0]));
        assert_eq!(b.get_atom_force(2).unwrap(), Some([0.0, 0.0, 1.0]));
        assert_eq!(b.get_atom_energy(0).unwrap(), Some(-0.1));
        assert_eq!(b.get_atom_energy(2).unwrap(), Some(-0.3));
    }

    #[test]
    fn builder_round_trip_after_bulk_mutation() {
        let mut b = three_atom_builder();
        b.set_positions_from_flat(&[5.0; 9]).unwrap();
        b.set_forces_from_flat(&[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])
            .unwrap();
        b.set_atom_energies_from_flat(&[-1.0, -2.0, -3.0]).unwrap();
        let frame = b.build();
        assert_eq!(frame.atom_data.len(), 3);
        assert!(frame.has_forces());
        assert!(frame.has_energies());
        // group order: Cu, Cu, H
        assert_eq!(frame.atom_data[0].force, Some([1.0, 0.0, 0.0]));
        assert_eq!(frame.atom_data[2].force, Some([0.0, 0.0, 1.0]));
    }

    // ----- DLPack export tier tests -----------------------------------------
    //
    // These tests pin the cross-language zero-copy contract: every per-atom
    // field surfaces as a DLPackTensorRef with the right shape, dtype, and
    // device, and a mutable view writes back to the builder's storage with
    // no intermediate copy.

    #[test]
    fn dlpack_positions_shape_dtype_device() {
        let b = three_atom_builder();
        let t = b.positions_dlpack().expect("positions_dlpack");
        // (N, 3) f64 on CPU is the spec contract for v0.11.
        assert_eq!(t.shape(), &[3, 3]);
        let dt = t.dtype();
        assert_eq!(dt.code, dlpk::sys::DLDataTypeCode::kDLFloat);
        assert_eq!(dt.bits, 64);
        assert_eq!(dt.lanes, 1);
        assert_eq!(t.device(), dlpk::sys::DLDevice::cpu());
    }

    #[test]
    fn dlpack_velocities_absent_returns_none() {
        let b = three_atom_builder();
        assert!(b.velocities_dlpack().expect("velocities_dlpack").is_none());
        assert!(b.forces_dlpack().expect("forces_dlpack").is_none());
        assert!(
            b.atom_energies_dlpack()
                .expect("atom_energies_dlpack")
                .is_none()
        );
    }

    #[test]
    fn dlpack_velocities_present_after_declaration() {
        let mut b = three_atom_builder();
        b.set_atom_velocity(1, [1.5, 2.5, 3.5]).unwrap();
        let t = b
            .velocities_dlpack()
            .expect("velocities_dlpack ok")
            .expect("section present");
        assert_eq!(t.shape(), &[3, 3]);
        let dt = t.dtype();
        assert_eq!(dt.code, dlpk::sys::DLDataTypeCode::kDLFloat);
        assert_eq!(dt.bits, 64);
    }

    #[test]
    fn dlpack_atom_ids_dtype_is_uint64() {
        let b = three_atom_builder();
        let t = b.atom_ids_dlpack().expect("atom_ids_dlpack");
        assert_eq!(t.shape(), &[3]);
        let dt = t.dtype();
        assert_eq!(dt.code, dlpk::sys::DLDataTypeCode::kDLUInt);
        assert_eq!(dt.bits, 64);
    }

    #[test]
    fn dlpack_masses_shape_and_values() {
        let b = three_atom_builder();
        let t = b.masses_dlpack().expect("masses_dlpack");
        assert_eq!(t.shape(), &[3]);
        let dt = t.dtype();
        assert_eq!(dt.code, dlpk::sys::DLDataTypeCode::kDLFloat);
        assert_eq!(dt.bits, 64);
    }

    /// Omitted `bonds` key vs empty pair list: both mean "no topology" for
    /// `has_bonds()` / selection; writers drop an empty list so files do not
    /// accumulate a useless key.
    #[test]
    fn writer_emits_units_for_v3_frame_without_units_key() {
        use crate::writer::ConFrameWriter;
        use std::io::Cursor;
        let mut frame = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        frame.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
        let mut fr = frame.build();
        // Strip units to simulate hand-built non-compliant header still claiming v3
        fr.header.metadata.remove(meta::UNITS);
        fr.header.spec_version = 3;
        let mut buf = Cursor::new(Vec::new());
        {
            let mut w = ConFrameWriter::new(&mut buf);
            w.write_frame(&fr).unwrap();
        }
        let s = String::from_utf8(buf.into_inner()).unwrap();
        assert!(s.contains("\"units\""), "writer must emit units for v3: {s}");
        assert!(s.contains("angstrom") || s.contains("length"), "{s}");
        // Round-trip parse must succeed as v3
        let parsed = crate::iterators::ConFrameIterator::new(&s)
            .next()
            .unwrap()
            .unwrap();
        assert_eq!(parsed.header.spec_version, 3);
        assert_eq!(parsed.length_unit(), Some("angstrom"));
    }


    #[test]
    fn bonds_absent_vs_empty_array_are_both_no_topology() {
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0);
        b.add_atom("H", 1.0, 0.0, 0.0, [false; 3], 1, 1.0);
        let mut frame = b.build();
        assert!(!frame.has_bonds());
        assert!(frame.bonds().is_empty());
        assert!(!frame.header.metadata.contains_key(meta::BONDS));

        frame.header.set_bonds(&[]);
        assert!(!frame.has_bonds());
        assert!(
            !frame.header.metadata.contains_key(meta::BONDS),
            "empty bonds must not leave a key on the header"
        );

        frame.header.set_bonds(&[Bond {
            i: 0,
            j: 1,
            order: None,
        }]);
        assert!(frame.has_bonds());
        assert!(frame.header.metadata.contains_key(meta::BONDS));

        frame.header.clear_bonds();
        assert!(!frame.has_bonds());
        assert!(!frame.header.metadata.contains_key(meta::BONDS));

        frame
            .header
            .metadata
            .insert(meta::BONDS.into(), serde_json::json!([]));
        assert!(parse_bonds_from_metadata(&frame.header.metadata).is_empty());
        assert!(
            !frame.has_bonds(),
            "empty bonds JSON array must not count as has_bonds"
        );
    }

    #[test]
    fn clone_shares_storage_until_cow() {
        // ArcArray's clone is a shallow Arc bump, so two builders born
        // from a single template point to the same per-atom buffers
        // until one of them mutates. This is the v0.12.0 NEB-image
        // sharing primitive: build the template once, clone N+2 times,
        // and only pay the (N, 3) f64 copy when an image is actually
        // perturbed.
        let template = three_atom_builder();
        let cloned = template.clone();
        // Same backing pointer for positions / masses / atom_ids
        // through the crate-internal _ref helpers.
        assert_eq!(
            template.positions_2d_ref().as_ptr(),
            cloned.positions_2d_ref().as_ptr()
        );
        assert_eq!(
            template.masses_1d_ref().as_ptr(),
            cloned.masses_1d_ref().as_ptr()
        );
        assert_eq!(
            template.atom_ids_1d_ref().as_ptr(),
            cloned.atom_ids_1d_ref().as_ptr()
        );

        // Mutate the clone; the template's pointer must stay put,
        // the clone's pointer must diverge.
        let template_ptr = template.positions_2d_ref().as_ptr();
        let mut cloned_mut = cloned;
        cloned_mut.set_atom_position(0, 9.0, 9.0, 9.0).unwrap();
        assert_eq!(template.positions_2d_ref().as_ptr(), template_ptr);
        assert_ne!(
            cloned_mut.positions_2d_ref().as_ptr(),
            template.positions_2d_ref().as_ptr()
        );
        // Template's atom 0 stays at its original value.
        assert_eq!(template.get_atom_position(0).unwrap(), (0.0, 0.0, 0.0));
        // Clone reflects the new write.
        assert_eq!(cloned_mut.get_atom_position(0).unwrap(), (9.0, 9.0, 9.0));
    }

    #[test]
    fn positions_view_mut_writes_back_with_arc_cow() {
        // Mutating through the typed view triggers ArcArray copy-on-write
        // when storage is shared, and writes through to the builder's
        // (now-unique) buffer. This is the property eOn's Matter, MD
        // integrators, and ML potentials rely on. The DLPack mutable
        // borrow path was retired in v0.12.0 because dlpk's
        // `TryFrom<&'a mut ArcArray<T, D>> for DLPackTensorRefMut<'a>`
        // is not yet implemented upstream; cross-language consumers go
        // through the C ABI's raw pointer path (also CoW-aware) or
        // through the owned DLPack export.
        let mut b = three_atom_builder();
        {
            let mut view = b.positions_view_mut();
            view[[1, 0]] = 42.0;
            view[[1, 1]] = 43.0;
            view[[1, 2]] = 44.0;
        }
        assert_eq!(b.get_atom_position(1).unwrap(), (42.0, 43.0, 44.0));
        let v = b.positions_view();
        assert_eq!(v[[1, 0]], 42.0);
        assert_eq!(v[[1, 1]], 43.0);
        assert_eq!(v[[1, 2]], 44.0);
    }
}
