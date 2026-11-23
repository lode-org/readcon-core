//=============================================================================
// Data Structures - The shape of our parsed data
//=============================================================================

use crate::error::ParseError;
pub use rustc_hash::FxHashMap;
use std::collections::BTreeMap;
use std::sync::Arc;

/// Indices of `ids` in pre-grouping order (CON-id.5, D9).
///
/// Unique ids sort by ascending id. Any repeated id keeps file order.
/// Callers that return atoms in file order leave `atom_data` unchanged
/// and still expose the column-5 ids (CON-id.6, CON-id.8).
pub fn pre_grouping_indices(ids: &[u64]) -> Vec<usize> {
    let mut order: Vec<usize> = (0..ids.len()).collect();
    let mut seen = std::collections::HashSet::with_capacity(ids.len());
    if ids.iter().copied().all(|id| seen.insert(id)) {
        order.sort_by(|&i, &j| ids[i].cmp(&ids[j]).then(i.cmp(&j)));
    }
    order
}

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
/// | [`UNITS`] | object | optional (required v3) | Line-2 unit system. v3 needs `length` and `energy`. Writers store canonical names (`angstrom`, `eV`, `fs`), not aliases (`A`, `ev`). |
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
    /// Minor of a known major. Absent or 0 means minor 0 (CON-line2.10).
    pub const CON_SPEC_MINOR: &str = "con_spec_minor";
    /// Value-field counts for sections this reader may skip (CON-section.12).
    /// The flag and the optional id are not part of the count.
    pub const SECTION_ARITY: &str = "section_arity";
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
        Self { i, j, order: None }
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
/// Per-atom charge (scalar); same block shape as [`SECTION_ENERGIES`].
pub const SECTION_CHARGES: &str = "charges";
/// Per-atom spin (scalar); same block shape as [`SECTION_ENERGIES`].
pub const SECTION_SPINS: &str = "spins";
/// Per-atom magnetic moment (3-vector); same block shape as [`SECTION_VELOCITIES`].
pub const SECTION_MAGMOMS: &str = "magmoms";
/// Per-atom displacement vector `[dx, dy, dz]` in Angstrom (e.g. a normal
/// mode); same block shape as [`SECTION_VELOCITIES`].
pub const SECTION_DISPLACEMENTS: &str = "displacements";
/// Per-atom root-mean-square spread `[sx, sy, sz]` in Angstrom about the
/// written coordinates (a standard deviation per axis, each non-negative; 0
/// is a classical point); same block shape as [`SECTION_VELOCITIES`].
pub const SECTION_SPREADS: &str = "spreads";

/// Value-field count of a section that minor 1 reserves (CON-section.13).
///
/// Vector rows are 3 and scalar rows are 1. `None` means the name is
/// not reserved, so a later minor lists it in `section_arity` (CON-section.16).
pub fn reserved_section_value_arity(name: &str) -> Option<u64> {
    match name {
        SECTION_VELOCITIES
        | SECTION_FORCES
        | SECTION_MAGMOMS
        | SECTION_DISPLACEMENTS
        | SECTION_SPREADS => Some(3),
        SECTION_ENERGIES | SECTION_CHARGES | SECTION_SPINS => Some(1),
        _ => None,
    }
}

/// A spread row is a standard deviation per axis: finite and non-negative.
/// Zero is a classical point.
pub(crate) fn spread_row_ok(spread: [f64; 3]) -> bool {
    spread.iter().all(|v| v.is_finite() && *v >= 0.0)
}

pub(crate) fn invalid_spread(atom_index: usize) -> crate::error::ParseError {
    crate::error::ParseError::ValidationError(format!(
        "spreads: atom {atom_index} has a negative or non-finite spread"
    ))
}

/// The two-line block preceding the box dimensions.
///
/// Line 0 is free-form user text. Line 1 is reserved for machine-readable
/// JSON metadata; it is read by the parser and rebuilt by the writer from
/// `FrameHeader.spec_version + metadata + sections`. External callers
/// cannot set the metadata line directly -- they should mutate
/// `FrameHeader.metadata` instead and let the writer regenerate it.
#[derive(Debug, Clone)]
pub struct PreboxHeader {
    /// User-supplied free-form text (e.g. "Generated by eOn").
    pub user: String,
    /// JSON metadata line as stored on disk; rebuilt on write.
    ///
    /// Shared with [`FrameMeta`] so a read does not keep a second copy.
    pub(crate) metadata_line: std::sync::Arc<str>,
}

impl Default for PreboxHeader {
    fn default() -> Self {
        Self {
            user: String::new(),
            metadata_line: std::sync::Arc::from(""),
        }
    }
}

impl PreboxHeader {
    /// Construct from the user-facing text only. The metadata line is
    /// initialized empty and will be filled in by the writer.
    pub fn new(user: impl Into<String>) -> Self {
        Self {
            user: user.into(),
            metadata_line: std::sync::Arc::from(""),
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

/// JSON metadata kept as the source line until a caller looks a key up.
///
/// The read builds one line per frame. The map is the same object the
/// parser used to store, and it is built on the first keyed lookup or
/// edit rather than for every frame.
///
/// Generic `serde::Serialize` emits the exact unquoted integer for
/// `con_spec_minor` values up to `u128::MAX` and returns a serialization error
/// when `con_spec_minor > u128::MAX` (because `serde_json` is built without
/// `arbitrary_precision`/`raw_value`); the native [`crate::writer::ConFrameWriter`]
/// preserves arbitrary-length minors.
#[derive(Debug, Clone)]
pub struct FrameMeta {
    raw: std::sync::Arc<str>,
    /// `con_spec_minor`, or 0 when the line does not set it.
    ///
    /// Kept beside the line so a frame read does not build the map just to
    /// answer the minor. Values above `u64::MAX` saturate to
    /// [`SATURATED_SPEC_MINOR`].
    minor: u64,
    /// Exact decimal digits of `con_spec_minor` when it exceeds `u64::MAX`.
    minor_raw: Option<Box<str>>,
    map: std::sync::OnceLock<BTreeMap<String, serde_json::Value>>,
}

impl PartialEq for FrameMeta {
    fn eq(&self, other: &Self) -> bool {
        if self.minor_raw != other.minor_raw {
            return false;
        }
        if self.raw == other.raw && self.map.get().is_none() && other.map.get().is_none() {
            return true;
        }
        self.to_map() == other.to_map()
    }
}

impl serde::Serialize for FrameMeta {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        if let Some(digits) = self.minor_raw.as_deref() {
            use serde::ser::SerializeMap;
            let minor_u128 = digits.parse::<u128>().map_err(|_| {
                serde::ser::Error::custom(format!(
                    "con_spec_minor {digits} exceeds u128::MAX for generic serde::Serialize"
                ))
            })?;
            return self.with_map(|map| {
                let has_minor_key = map.contains_key(meta::CON_SPEC_MINOR);
                let len = map.len() + usize::from(!has_minor_key);
                let mut ser = serializer.serialize_map(Some(len))?;
                for (k, v) in map {
                    if k == meta::CON_SPEC_MINOR {
                        ser.serialize_entry(k, &minor_u128)?;
                    } else {
                        ser.serialize_entry(k, v)?;
                    }
                }
                if !has_minor_key {
                    ser.serialize_entry(meta::CON_SPEC_MINOR, &minor_u128)?;
                }
                ser.end()
            });
        }
        self.with_map(|map| serde::Serialize::serialize(map, serializer))
    }
}

impl FrameMeta {
    pub fn from_line(raw: impl Into<std::sync::Arc<str>>) -> Self {
        let raw = raw.into();
        let (minor, minor_raw) = minor_from_line(&raw);
        Self {
            raw,
            minor,
            minor_raw,
            map: std::sync::OnceLock::new(),
        }
    }

    pub fn from_shared(raw: std::sync::Arc<str>) -> Self {
        Self::from_line(raw)
    }

    pub fn from_map(map: BTreeMap<String, serde_json::Value>) -> Self {
        Self::from_map_with_minor_raw(map, None)
    }

    pub(crate) fn from_map_with_minor_raw(
        mut map: BTreeMap<String, serde_json::Value>,
        minor_raw: Option<&str>,
    ) -> Self {
        let (minor, stored_raw) = if let Some(digits) = minor_raw {
            match digits.parse::<u64>() {
                Ok(v) => {
                    map.insert(meta::CON_SPEC_MINOR.into(), serde_json::Value::from(v));
                    (v, None)
                }
                Err(_) => {
                    map.insert(
                        meta::CON_SPEC_MINOR.into(),
                        serde_json::Value::from(SATURATED_SPEC_MINOR),
                    );
                    (SATURATED_SPEC_MINOR, Some(Box::from(digits)))
                }
            }
        } else if let Some(val) = map.get(meta::CON_SPEC_MINOR) {
            let (minor, raw) = extract_minor_from_value(val);
            if raw.is_some() {
                map.insert(
                    meta::CON_SPEC_MINOR.into(),
                    serde_json::Value::from(SATURATED_SPEC_MINOR),
                );
            }
            (minor, raw)
        } else {
            (0, None)
        };
        let lock = std::sync::OnceLock::new();
        let _ = lock.set(map);
        Self {
            raw: std::sync::Arc::from(""),
            minor,
            minor_raw: stored_raw,
            map: lock,
        }
    }

    /// Saturating `con_spec_minor` (`0` when absent; [`SATURATED_SPEC_MINOR`]
    /// when the file's value exceeds `u64::MAX`).
    pub fn spec_minor(&self) -> u64 {
        self.minor
    }

    /// Exact decimal string for `con_spec_minor` (`"0"` when absent).
    pub fn spec_minor_str(&self) -> std::borrow::Cow<'_, str> {
        if let Some(raw) = self.minor_raw.as_deref() {
            std::borrow::Cow::Borrowed(raw)
        } else if self.minor == 0 {
            std::borrow::Cow::Borrowed("0")
        } else {
            std::borrow::Cow::Owned(self.minor.to_string())
        }
    }

    /// Sets `con_spec_minor` from a decimal integer string (including values > `u64::MAX`
    /// accepted by `serde_json`).
    pub fn set_con_spec_minor_str(&mut self, digits: &str) -> Result<(), ParseError> {
        if !crate::parser::is_nonneg_decimal_int(digits) {
            return Err(ParseError::InvalidMetadataJson(
                "con_spec_minor must be a JSON integer >= 0".into(),
            ));
        }
        match digits.parse::<u64>() {
            Ok(v) => {
                self.minor = v;
                self.minor_raw = None;
                self.cached_mut()
                    .insert(meta::CON_SPEC_MINOR.into(), serde_json::Value::from(v));
            }
            Err(_) => {
                if let Err(e) = serde_json::from_str::<serde_json::Number>(digits) {
                    return Err(ParseError::InvalidMetadataJson(e.to_string()));
                }
                self.minor = SATURATED_SPEC_MINOR;
                self.minor_raw = Some(Box::from(digits));
                self.cached_mut().insert(
                    meta::CON_SPEC_MINOR.into(),
                    serde_json::Value::from(SATURATED_SPEC_MINOR),
                );
            }
        }
        Ok(())
    }

    /// Exact decimal digits of `con_spec_minor` only when it exceeds `u64::MAX`.
    pub(crate) fn huge_minor_raw(&self) -> Option<&str> {
        self.minor_raw.as_deref()
    }

    pub fn empty() -> Self {
        Self::from_line(String::new())
    }

    fn ensure(&self) -> &BTreeMap<String, serde_json::Value> {
        self.map.get_or_init(|| metadata_map_from_line(&self.raw))
    }

    fn cached_mut(&mut self) -> &mut BTreeMap<String, serde_json::Value> {
        if self.map.get().is_none() {
            let parsed = metadata_map_from_line(&self.raw);
            let _ = self.map.set(parsed);
        }
        self.map.get_mut().expect("metadata map")
    }

    /// Owned map. Does not keep the map on this value when it was still a line.
    pub fn to_map(&self) -> BTreeMap<String, serde_json::Value> {
        if let Some(map) = self.map.get() {
            map.clone()
        } else {
            metadata_map_from_line(&self.raw)
        }
    }

    /// The parsed map is kept only after a lookup that expects to reuse it.
    /// A streaming write must not be one of those lookups: one map per frame
    /// is about a kilobyte, and a long trajectory holds every frame.
    #[cfg(test)]
    pub(crate) fn has_cached_map(&self) -> bool {
        self.map.get().is_some()
    }

    fn with_map<R>(&self, f: impl FnOnce(&BTreeMap<String, serde_json::Value>) -> R) -> R {
        if let Some(map) = self.map.get() {
            return f(map);
        }
        // A write looks up lattice vectors once per frame. Storing the map on
        // the frame kept about a kilobyte for every frame the caller still
        // held. The line is usually the same across a trajectory, so a few
        // shared parses answer the repeat lookups.
        META_LINE_CACHE.with(|cell| {
            let mut cache = cell.borrow_mut();
            if let Some(index) = cache.iter().position(|entry| {
                std::sync::Arc::ptr_eq(&entry.raw, &self.raw) || *entry.raw == *self.raw
            }) {
                if index != 0 {
                    let entry = cache.remove(index);
                    cache.insert(0, entry);
                }
                return f(&cache[0].map);
            }
            let parsed = metadata_map_from_line(&self.raw);
            if cache.len() == META_LINE_CACHE_CAP {
                cache.pop();
            }
            cache.insert(
                0,
                ParsedMetaLine {
                    raw: std::sync::Arc::clone(&self.raw),
                    map: parsed,
                },
            );
            f(&cache[0].map)
        })
    }

    pub fn get(&self, key: &str) -> Option<&serde_json::Value> {
        self.ensure().get(key)
    }
}

impl std::ops::Index<&str> for FrameMeta {
    type Output = serde_json::Value;

    fn index(&self, key: &str) -> &serde_json::Value {
        &self.ensure()[key]
    }
}

impl FrameMeta {
    pub fn insert(
        &mut self,
        key: String,
        mut value: serde_json::Value,
    ) -> Option<serde_json::Value> {
        if key == meta::CON_SPEC_MINOR {
            let (minor, minor_raw) = extract_minor_from_value(&value);
            self.minor = minor;
            self.minor_raw = minor_raw;
            if self.minor_raw.is_some() {
                value = serde_json::Value::from(SATURATED_SPEC_MINOR);
            }
        }
        self.cached_mut().insert(key, value)
    }

    pub fn remove(&mut self, key: &str) -> Option<serde_json::Value> {
        if key == meta::CON_SPEC_MINOR {
            self.minor = 0;
            self.minor_raw = None;
        }
        self.cached_mut().remove(key)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        if let Some(map) = self.map.get() {
            map.contains_key(key)
        } else {
            metadata_map_from_line(&self.raw).contains_key(key)
        }
    }

    pub fn is_empty(&self) -> bool {
        if let Some(map) = self.map.get() {
            map.is_empty()
        } else {
            metadata_map_from_line(&self.raw).is_empty()
        }
    }

    pub fn len(&self) -> usize {
        if let Some(map) = self.map.get() {
            map.len()
        } else {
            metadata_map_from_line(&self.raw).len()
        }
    }

    pub fn iter(&self) -> std::collections::btree_map::Iter<'_, String, serde_json::Value> {
        self.ensure().iter()
    }

    /// The parsed line, when the map has not been edited.
    ///
    /// A keyed edit materialises the map and the line is no longer the
    /// source of the metadata JSON.
    pub(crate) fn unedited_line(&self) -> Option<&std::sync::Arc<str>> {
        if self.map.get().is_some() {
            None
        } else {
            Some(&self.raw)
        }
    }

    /// In-memory dtypes. A line with no `storage_dtypes` key does not parse.
    pub(crate) fn dtypes(&self) -> crate::storage_dtype::StorageDtypes {
        if let Some(map) = self.map.get() {
            return crate::storage_dtype::StorageDtypes::from_metadata(map).unwrap_or_default();
        }
        if !self.raw.contains("storage_dtypes") {
            return crate::storage_dtype::StorageDtypes::default();
        }
        let map = metadata_map_from_line(&self.raw);
        crate::storage_dtype::StorageDtypes::from_metadata(&map).unwrap_or_default()
    }
}

impl<'a> IntoIterator for &'a FrameMeta {
    type Item = (&'a String, &'a serde_json::Value);
    type IntoIter = std::collections::btree_map::Iter<'a, String, serde_json::Value>;

    fn into_iter(self) -> Self::IntoIter {
        self.ensure().iter()
    }
}

/// Saturated minor returned when `con_spec_minor` exceeds `u64::MAX`.
///
/// Strictly greater than [`crate::CON_SPEC_MINOR`], while [`FrameMeta::spec_minor_str`]
/// preserves the exact decimal digits for values above `u64::MAX`.
pub const SATURATED_SPEC_MINOR: u64 = u64::MAX;

fn extract_minor_from_value(value: &serde_json::Value) -> (u64, Option<Box<str>>) {
    if let Some(v) = value.as_u64() {
        (v, None)
    } else {
        (0, None)
    }
}

/// In-range top-level `con_spec_minor`, the first one when it is repeated.
///
/// CON-line2.10 says a missing minor is 0. A nested object, an array
/// element, or a dotted name is not that field, so the minor stays
/// missing. The bytes skipped around the key are ASCII whitespace, the
/// set the fast path skips. `1.5` yields 1, and a token that does not
/// fit in `u64` yields 0. [`minor_from_line`] handles a last huge token
/// before this runs.
fn base_minor_from_line(line: &str) -> u64 {
    let trimmed = line.trim();
    let Some(at) = crate::parser::top_level_first_minor_key_end(trimmed) else {
        return 0;
    };
    let rest = trimmed[at..].trim_start();
    let rest = rest.strip_prefix(':').unwrap_or(rest).trim_start();
    let end = rest
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(rest.len());
    rest[..end].parse().unwrap_or(0)
}

/// Map stored for a metadata line.
///
/// `con_spec_version` and `sections` stay on the header, as they do when
/// the parser walks the object. Any other key is kept. A line that is not
/// a JSON object is an empty map.
fn minor_from_line(line: &str) -> (u64, Option<Box<str>>) {
    let trimmed = line.trim();
    if trimmed.starts_with('{')
        && let Some(token) = crate::parser::top_level_last_raw_token(trimmed, meta::CON_SPEC_MINOR)
        && crate::parser::is_substitutable_huge_minor(token)
    {
        return (SATURATED_SPEC_MINOR, Some(Box::from(token)));
    }
    (base_minor_from_line(line), None)
}

struct ParsedMetaLine {
    raw: std::sync::Arc<str>,
    map: BTreeMap<String, serde_json::Value>,
}

const META_LINE_CACHE_CAP: usize = 4;

std::thread_local! {
    // Native builds keep the bounded cache alive until process exit.
    // Free-threaded CPython can tear worker TLS down while libc is still
    // running other TLS destructors; dropping the cached Arcs there produces
    // a TSan-visible libc TLS-dtor race. At most four parsed lines remain
    // per exited thread. Miri does not run those destructors concurrently,
    // and it reports the retained lines as leaks, so under Miri the cache
    // is an ordinary thread-local and drops with the thread.
    #[cfg(not(miri))]
    static META_LINE_CACHE: std::mem::ManuallyDrop<std::cell::RefCell<Vec<ParsedMetaLine>>> =
        const { std::mem::ManuallyDrop::new(std::cell::RefCell::new(Vec::new())) };
    #[cfg(miri)]
    static META_LINE_CACHE: std::cell::RefCell<Vec<ParsedMetaLine>> =
        const { std::cell::RefCell::new(Vec::new()) };
}

pub(crate) fn metadata_map_from_line(line: &str) -> BTreeMap<String, serde_json::Value> {
    let trimmed = line.trim();
    if trimmed == "{\"con_spec_version\":2}" || !trimmed.starts_with('{') {
        return BTreeMap::new();
    }
    let spans = crate::parser::top_level_minor_spans(trimmed);
    let (sanitized, huge_minor) = crate::parser::sanitize_huge_con_spec_minor(trimmed, &spans);
    let Ok(value) = serde_json::from_str::<serde_json::Value>(sanitized.as_ref()) else {
        return BTreeMap::new();
    };
    let Some(obj) = value.as_object() else {
        return BTreeMap::new();
    };
    let mut metadata = BTreeMap::new();
    for (k, v) in obj {
        match k.as_str() {
            meta::CON_SPEC_VERSION | meta::SECTIONS => {}
            meta::CON_SPEC_MINOR if huge_minor.is_some() => {
                metadata.insert(k.clone(), serde_json::Value::from(SATURATED_SPEC_MINOR));
            }
            _ => {
                metadata.insert(k.clone(), v.clone());
            }
        }
    }
    metadata
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
    pub metadata: FrameMeta,
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
    /// Saturating `con_spec_minor` (`0` when absent; [`SATURATED_SPEC_MINOR`]
    /// when the frame's minor exceeds `u64::MAX`).
    pub fn con_spec_minor_saturating(&self) -> u64 {
        self.metadata.spec_minor()
    }

    /// Exact decimal string for `con_spec_minor` (`"0"` when absent).
    pub fn con_spec_minor_str(&self) -> std::borrow::Cow<'_, str> {
        self.metadata.spec_minor_str()
    }

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

    /// Unit of line 3 and the coordinate columns.
    /// Absent `units`, or an absent `length` key, means angstrom (CON-header.3).
    pub fn coordinate_length_unit(&self) -> &str {
        self.length_unit().unwrap_or("angstrom")
    }

    /// Unit of the masses on line 9.
    /// Absent `units`, or an absent `mass` key, means amu (CON-header.3).
    pub fn mass_unit(&self) -> &str {
        self.unit_for("mass").unwrap_or("amu")
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

    /// Sets the unit system. Aliases are rewritten to preferred names
    /// (`A` → `angstrom`) so line 2 carries the contract spelling.
    pub fn set_units(&mut self, units: serde_json::Value) {
        let stored = crate::units::canonicalize_units_object(&units).unwrap_or(units);
        self.metadata.insert(meta::UNITS.into(), stored);
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
        self.metadata.insert(
            meta::PBC.into(),
            serde_json::json!([pbc[0], pbc[1], pbc[2]]),
        );
    }

    /// Exact 3x3 lattice vector matrix (row-major, angstroms).
    /// When present, takes precedence over the length/angle values on lines 3-4.
    pub fn lattice_vectors(&self) -> Option<[[f64; 3]; 3]> {
        // Shared across frames. A per-frame map stays reachable for as long
        // as the caller holds the trajectory, which a streaming write must
        // not do.
        self.metadata.with_map(|map| {
            let arr = map.get(meta::LATTICE_VECTORS)?.as_array()?;
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
        })
    }

    /// Cell matrix. A present `lattice_vectors` wins over lines 3-4 (CON-cell.1).
    /// Otherwise the matrix is built from those lines (CON-cell.6).
    pub fn cell_matrix(&self) -> [[f64; 3]; 3] {
        self.lattice_vectors()
            .unwrap_or_else(|| cell_vectors(self.boxl, self.angles))
    }

    /// Periodic boundary conditions. A missing `pbc` key is fully periodic
    /// (CON-cell.3, D12).
    pub fn pbc_effective(&self) -> [bool; 3] {
        self.pbc().unwrap_or([true, true, true])
    }

    /// Sets the exact lattice vector matrix and keeps lines 3-4 consistent
    /// with that matrix (CON-cell.2, D12).
    ///
    /// # Errors
    ///
    /// [`ParseError::NonFiniteValue`] naming `lattice_vectors[row][column]`
    /// when a component is NaN or infinite. The header is not changed: JSON
    /// has no spelling for such a number, so the matrix would be stored as
    /// `null` and read back as no lattice at all.
    pub fn set_lattice_vectors(&mut self, vecs: [[f64; 3]; 3]) -> Result<(), ParseError> {
        check_lattice_finite(&vecs)?;
        self.metadata.insert(
            meta::LATTICE_VECTORS.into(),
            serde_json::json!([
                [vecs[0][0], vecs[0][1], vecs[0][2]],
                [vecs[1][0], vecs[1][1], vecs[1][2]],
                [vecs[2][0], vecs[2][1], vecs[2][2]],
            ]),
        );
        let (boxl, angles) = lengths_and_angles(vecs);
        if boxl.iter().all(|v| v.is_finite()) && angles.iter().all(|v| v.is_finite()) {
            self.boxl = boxl;
            self.angles = angles;
        }
        Ok(())
    }

    /// Checks that the three lengths and three angles of lines 3-4 are
    /// finite.
    ///
    /// The fields are named `boxl[i]` and `angles[i]`. The lattice vectors
    /// in the metadata are not read: JSON cannot hold a NaN or an infinity.
    /// One test of six numbers per frame, not per atom.
    ///
    /// # Errors
    ///
    /// [`ParseError::NonFiniteValue`], with [`ParseError::in_frame`] left to
    /// the caller that knows the frame.
    #[inline]
    pub fn check_cell_finite(&self) -> Result<(), ParseError> {
        check_cell_finite(&self.boxl, "boxl", &self.angles, "angles")
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
        bonds_from_metadata_value(self.metadata.get(meta::BONDS))
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
    bonds_from_metadata_value(metadata.get(meta::BONDS))
}

fn bonds_from_metadata_value(val: Option<&serde_json::Value>) -> Vec<Bond> {
    let Some(val) = val else {
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

/// Where a parsed section lives.
///
/// Coordinate-only atoms stay empty, which is a null pointer, so the atom
/// record does not reserve room for a velocity. A velocity-only atom, the
/// `.convel` case, boxes the three components. Any other section boxes the
/// full tail behind that same pointer.
#[derive(Debug, Clone, PartialEq)]
enum AtomSections {
    Empty,
    Present(Box<HeapTail>),
}

#[doc(hidden)]
#[derive(Debug, Clone)]
#[repr(align(32))]
pub enum HeapTail {
    Velocity([f64; 3]),
    Full(Box<AtomTail>),
    /// Pointers into the frame's velocity and force columns. The columns
    /// own the floats. This tail lives in the frame's arena, not a per-atom box.
    Column {
        vel: *mut f64,
        force: *mut f64,
    },
}

// The column pointers address the frame that owns the arena. Moving the
// frame moves both, the same way an atom's coordinate slot does.
unsafe impl Send for HeapTail {}
unsafe impl Sync for HeapTail {}

impl PartialEq for HeapTail {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Velocity(left), Self::Velocity(right)) => left == right,
            (Self::Full(left), Self::Full(right)) => left == right,
            (
                Self::Column {
                    vel: left_vel,
                    force: left_force,
                },
                Self::Column {
                    vel: right_vel,
                    force: right_force,
                },
            ) => {
                column_values_eq(*left_vel, *right_vel)
                    && column_values_eq(*left_force, *right_force)
            }
            _ => false,
        }
    }
}

fn column_values_eq(left: *mut f64, right: *mut f64) -> bool {
    if left.is_null() || right.is_null() {
        return left.is_null() && right.is_null();
    }
    unsafe { [*left, *left.add(1), *left.add(2)] == [*right, *right.add(1), *right.add(2)] }
}

impl AtomSections {
    fn velocity(v: [f64; 3]) -> Self {
        Self::Present(Box::new(HeapTail::Velocity(v)))
    }

    fn from_full(tail: AtomTail) -> Self {
        Self::Present(Box::new(HeapTail::Full(Box::new(tail))))
    }
}

/// Optional per-atom sections. Absent on the coordinate-only path so a frame
/// does not pay a fat tail on every atom.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct AtomTail {
    velocity: Option<[f64; 3]>,
    force: Option<[f64; 3]>,
    energy: Option<f64>,
    charge: Option<f64>,
    spin: Option<f64>,
    magmom: Option<[f64; 3]>,
    displacement: Option<[f64; 3]>,
    spread: Option<[f64; 3]>,
}

impl AtomTail {
    fn is_empty(&self) -> bool {
        self.velocity.is_none()
            && self.force.is_none()
            && self.energy.is_none()
            && self.charge.is_none()
            && self.spin.is_none()
            && self.magmom.is_none()
            && self.displacement.is_none()
            && self.spread.is_none()
    }
}

/// Represents the data for a single atom in a frame.
///
/// The symbol, the fixed mask, and the id sit inline. Optional sections live
/// in one heap tail, allocated only when a section value is set, so a
/// coordinates-only trajectory does not store eight empty `Option`s per atom.
///
/// Coordinates are not stored here and this atom holds no pointer. They live
/// in [`ConFrame::positions`]. [`ConFrame::xyz_at`] reads that column at this
/// atom's index in [`ConFrame::atom_data`]. [`ConFrame::set_x_at`] writes the
/// same row, so a column store and an accessor see one value.
#[derive(Debug)]
pub struct AtomDatum {
    /// The chemical symbol of the atom (e.g., "C", "H", "O").
    /// Using Arc<str> to avoid expensive clones for each atom of the same type.
    pub symbol: Arc<str>,
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
    /// Bits 0-2 are fixed flags. Bit 4 marks a tail that lives in the frame
    /// arena, not a `Box`. The rest is a `HeapTail` pointer or null.
    /// `HeapTail` is 32-byte aligned.
    tail: usize,
}

const TAIL_EXTERNAL: usize = 0b1_0000;
/// Low bits that are not part of the tail pointer. Bits 0-2 are fixed
/// flags. Bit 3 is unused. Bit 4 marks an arena tail. `HeapTail` is
/// 32-byte aligned, so these bits are free.
const TAIL_MASK: usize = 0b1_1111;

impl AtomDatum {
    fn tail_ptr(&self) -> *mut HeapTail {
        (self.tail & !TAIL_MASK) as *mut HeapTail
    }

    fn flags_bits(fixed: [bool; 3]) -> usize {
        usize::from(fixed[0]) | (usize::from(fixed[1]) << 1) | (usize::from(fixed[2]) << 2)
    }

    /// Per-direction constraint flags: `[fixed_x, fixed_y, fixed_z]`.
    ///
    /// Encoded as a bitmask in column 4 of the file format:
    /// bit 0 = x, bit 1 = y, bit 2 = z.
    /// Spec 1 (no JSON line 2) treats value 1 as all-fixed.
    /// Spec 2 treats 1 as x-only. All-fixed is 7.
    #[inline]
    pub fn fixed(&self) -> [bool; 3] {
        let bits = self.tail & 0b111;
        [bits & 1 != 0, bits & 2 != 0, bits & 4 != 0]
    }

    #[inline]
    pub fn set_fixed(&mut self, fixed: [bool; 3]) {
        self.tail = (self.tail & !0b111) | Self::flags_bits(fixed);
    }

    fn set_tail_ptr(&mut self, ptr: *mut HeapTail) {
        debug_assert!(ptr as usize & TAIL_MASK == 0);
        self.tail = (ptr as usize) | (self.tail & TAIL_MASK);
    }
}

impl PartialEq for AtomDatum {
    fn eq(&self, other: &Self) -> bool {
        self.symbol == other.symbol
            && self.fixed() == other.fixed()
            && self.atom_id == other.atom_id
            && self.velocity() == other.velocity()
            && self.force() == other.force()
            && self.energy().map(f64::to_bits) == other.energy().map(f64::to_bits)
            && self.charge().map(f64::to_bits) == other.charge().map(f64::to_bits)
            && self.spin().map(f64::to_bits) == other.spin().map(f64::to_bits)
            && self.magmom() == other.magmom()
            && self.displacement() == other.displacement()
            && self.spread() == other.spread()
    }
}

// The tail word may address a heap section owned by this atom or by the
// frame's column arena. The frame and the atom move together. Coordinates
// live in the frame column, so cloning an atom copies no coordinate memory.
unsafe impl Send for AtomDatum {}
unsafe impl Sync for AtomDatum {}

impl Clone for AtomDatum {
    fn clone(&self) -> Self {
        let mut cloned = Self {
            symbol: self.symbol.clone(),
            atom_id: self.atom_id,
            tail: self.tail & 0b111,
        };
        let external = self.tail & TAIL_EXTERNAL != 0;
        let ptr = self.tail_ptr();
        if !external && !ptr.is_null() {
            let tail = unsafe { (*ptr).clone() };
            cloned.set_tail_ptr(Box::into_raw(Box::new(tail)));
        }
        // An arena tail belongs to the source frame. The clone owns a copy.
        if external {
            if let Some(value) = self.velocity() {
                cloned.set_velocity(Some(value));
            }
            if let Some(value) = self.force() {
                cloned.set_force(Some(value));
            }
        }
        cloned
    }
}

impl Drop for AtomDatum {
    fn drop(&mut self) {
        let ptr = self.tail_ptr();
        if self.tail & TAIL_EXTERNAL == 0 && !ptr.is_null() {
            unsafe { drop(Box::from_raw(ptr)) };
        }
    }
}

/// Drop `atoms` when every shell shares one symbol and owns no heap tail.
///
/// A million atoms otherwise run a million decrements against the same
/// symbol counter. One `fetch_sub` matches that count.
#[derive(Clone, Copy)]
struct SymbolDropHint {
    atoms: usize,
    symbol: *const u8,
    n: usize,
}

thread_local! {
    static SYMBOL_DROP_HINT: std::cell::Cell<SymbolDropHint> = const {
        std::cell::Cell::new(SymbolDropHint {
            atoms: 0,
            symbol: std::ptr::null(),
            n: 0,
        })
    };
}

/// The next drop of this atom buffer releases its symbol counts in one step.
///
/// The buffer must be one shared symbol and no heap tail. Coordinates live
/// on the frame and are not freed per atom.
#[cfg(any(feature = "parallel", feature = "chemfiles", test))]
pub(crate) fn mark_uniform_symbol_drop(atoms: &[AtomDatum]) {
    if atoms.is_empty() {
        return;
    }
    let symbol = std::sync::Arc::as_ptr(&atoms[0].symbol) as *const u8;
    SYMBOL_DROP_HINT.with(|hint| {
        hint.set(SymbolDropHint {
            atoms: atoms.as_ptr() as usize,
            symbol,
            n: atoms.len(),
        });
    });
}

/// Drop this atom buffer atom by atom. Call before an atom takes a box.
fn clear_uniform_symbol_drop(atoms: &[AtomDatum]) {
    SYMBOL_DROP_HINT.with(|hint| {
        if hint.get().atoms == atoms.as_ptr() as usize {
            hint.set(SymbolDropHint {
                atoms: 0,
                symbol: std::ptr::null(),
                n: 0,
            });
        }
    });
}

fn bulk_drop_uniform_symbols(atoms: &mut Vec<AtomDatum>) {
    let n = atoms.len();
    if n < 1024 {
        return;
    }
    let hint = SYMBOL_DROP_HINT.with(|hint| hint.get());
    if hint.n != n || hint.atoms != atoms.as_ptr() as usize {
        return;
    }
    SYMBOL_DROP_HINT.with(|hint| {
        hint.set(SymbolDropHint {
            atoms: 0,
            symbol: std::ptr::null(),
            n: 0,
        });
    });
    if !atoms.iter().all(|atom| {
        std::ptr::eq(
            std::sync::Arc::as_ptr(&atom.symbol) as *const u8,
            hint.symbol,
        )
    }) {
        return;
    }
    release_arc_str_count(&atoms[0].symbol, n);
    let mut taken = std::mem::take(atoms);
    let cap = taken.capacity();
    let ptr = taken.as_mut_ptr();
    std::mem::forget(taken);
    let recycled =
        unsafe { Vec::from_raw_parts(ptr as *mut std::mem::MaybeUninit<AtomDatum>, 0, cap) };
    stash_atom_spare(recycled);
}

thread_local! {
    static ATOM_SPARE: std::cell::RefCell<Vec<std::mem::MaybeUninit<AtomDatum>>> =
        const { std::cell::RefCell::new(Vec::new()) };
    static SNAPSHOT_ATOM_SPARES:
        std::cell::RefCell<Vec<Vec<std::mem::MaybeUninit<AtomDatum>>>> =
        const { std::cell::RefCell::new(Vec::new()) };
}

#[cfg(feature = "parallel")]
pub(crate) fn take_atom_spare(n: usize) -> Vec<std::mem::MaybeUninit<AtomDatum>> {
    ATOM_SPARE.with(|cell| {
        let spare = cell.replace(Vec::new());
        if spare.capacity() < n {
            Vec::with_capacity(n)
        } else {
            spare
        }
    })
}

fn stash_atom_spare(buf: Vec<std::mem::MaybeUninit<AtomDatum>>) {
    ATOM_SPARE.with(|cell| {
        let mut slot = cell.borrow_mut();
        if buf.capacity() > slot.capacity() {
            *slot = buf;
        }
    });
}

#[cfg(feature = "python")]
fn take_snapshot_atom_spare(n: usize) -> Vec<std::mem::MaybeUninit<AtomDatum>> {
    SNAPSHOT_ATOM_SPARES.with(|cell| {
        let mut pool = cell.borrow_mut();
        if let Some(index) = pool.iter().position(|buf| buf.capacity() >= n) {
            pool.swap_remove(index)
        } else {
            Vec::with_capacity(n)
        }
    })
}

#[cfg(feature = "python")]
fn stash_snapshot_atom_spare(buf: Vec<std::mem::MaybeUninit<AtomDatum>>) {
    const CAP_BYTES: usize = 64 * 1024 * 1024;
    SNAPSHOT_ATOM_SPARES.with(|cell| {
        let mut pool = cell.borrow_mut();
        let used = pool
            .iter()
            .map(|entry| entry.capacity() * std::mem::size_of::<AtomDatum>())
            .sum::<usize>();
        let bytes = buf.capacity() * std::mem::size_of::<AtomDatum>();
        if used.saturating_add(bytes) <= CAP_BYTES {
            pool.push(buf);
        }
    });
}

fn arc_str_strong<T: ?Sized>(symbol: &std::sync::Arc<T>) -> *const std::sync::atomic::AtomicUsize {
    let header = 2 * std::mem::size_of::<usize>();
    let align = std::mem::align_of_val(symbol.as_ref());
    let rem = header % align;
    let offset = if rem == 0 {
        header
    } else {
        header + (align - rem)
    };
    let bytes = std::sync::Arc::as_ptr(symbol) as *const u8;
    unsafe { bytes.sub(offset) as *const std::sync::atomic::AtomicUsize }
}

fn release_arc_str_count<T: ?Sized>(symbol: &std::sync::Arc<T>, n: usize) {
    if n == 0 {
        return;
    }
    unsafe {
        (*arc_str_strong(symbol)).fetch_sub(n - 1, std::sync::atomic::Ordering::Release);
    }
    // The atoms can hold the last references. The final count is an `Arc`
    // drop, so the string is freed when no other owner remains.
    drop(share_arc_str(symbol));
}

/// Add `extra` strong references to `symbol` in one atomic add.
///
/// Pair each added count with [`share_arc_str`]. The source `Arc` must stay
/// alive until those shares exist, or the allocation can be freed early.
#[cfg(any(feature = "chemfiles", test))]
pub(crate) fn bump_arc_str<T: ?Sized>(symbol: &std::sync::Arc<T>, extra: usize) {
    if extra == 0 {
        return;
    }
    unsafe {
        (*arc_str_strong(symbol)).fetch_add(extra, std::sync::atomic::Ordering::Relaxed);
    }
}

/// One strong reference already counted by [`bump_arc_str`].
pub(crate) fn share_arc_str<T: ?Sized>(symbol: &std::sync::Arc<T>) -> std::sync::Arc<T> {
    unsafe { std::sync::Arc::from_raw(std::sync::Arc::as_ptr(symbol)) }
}

impl Drop for ConFrame {
    fn drop(&mut self) {
        crate::writer::invalidate_packed_lengths_if(self as *const Self as usize);
        bulk_drop_uniform_symbols(&mut self.atom_data);
    }
}

#[cfg(feature = "python")]
impl ConFrame {
    /// This frame with a private copy of atom `i`'s coordinates.
    ///
    /// When `fill` is set, those values are also written at `base + 3 i`.
    /// Otherwise `base` already holds them and the copy is taken from there.
    /// The atom vector and the metadata map cell are new. Every other field
    /// is shared with `self`, so the same rules as a bitwise copy apply.
    /// Another reader may fill the source map cell meanwhile, so that cell
    /// is never copied bit for bit; the view starts with the map the source
    /// already had, if any. The flag says whether it did.
    ///
    /// The view keeps a private positions column of the coordinates observed
    /// at this call. Its atoms store none. Its velocity and force columns
    /// are counted handles on the source's blocks.
    unsafe fn view_onto(&self, base: *mut f64, fill: bool, from: *const f64) -> (ConFrame, bool) {
        use std::ptr::read;
        let n_atoms = self.atom_data.len();
        let mut raw = take_snapshot_atom_spare(n_atoms);
        unsafe {
            std::ptr::copy_nonoverlapping(
                self.atom_data.as_ptr(),
                raw.as_mut_ptr().cast::<AtomDatum>(),
                n_atoms,
            );
            raw.set_len(n_atoms);
        }
        let atom_data = unsafe {
            Vec::from_raw_parts(
                raw.as_mut_ptr().cast::<AtomDatum>(),
                raw.len(),
                raw.capacity(),
            )
        };
        std::mem::forget(raw);
        let atom_data = SnapshotAtomGuard(atom_data);
        let base_address = base as usize;
        let mut copied = Vec::with_capacity(n_atoms.saturating_mul(3));
        for index in 0..n_atoms {
            let slot = unsafe { (base_address as *mut f64).add(index * 3) };
            let values = if !fill {
                unsafe { [*slot, *slot.add(1), *slot.add(2)] }
            } else if from.is_null() {
                self.load_coords(index)
            } else {
                unsafe {
                    [
                        atomic_load_f64(from.add(index * 3)),
                        atomic_load_f64(from.add(index * 3 + 1)),
                        atomic_load_f64(from.add(index * 3 + 2)),
                    ]
                }
            };
            if fill {
                unsafe { std::ptr::copy_nonoverlapping(values.as_ptr(), slot, 3) };
            }
            copied.extend_from_slice(&values);
        }
        let mut atom_data = atom_data;
        let source = &self.header;
        let map = std::sync::OnceLock::new();
        let shared_map = match source.metadata.map.get() {
            Some(parsed) => {
                let _ = map.set(unsafe { read(parsed) });
                true
            }
            None => false,
        };
        let header = unsafe {
            FrameHeader {
                prebox_header: read(&source.prebox_header),
                boxl: source.boxl,
                angles: source.angles,
                postbox_header: read(&source.postbox_header),
                natm_types: source.natm_types,
                natms_per_type: read(&source.natms_per_type),
                masses_per_type: read(&source.masses_per_type),
                spec_version: source.spec_version,
                metadata: FrameMeta {
                    raw: read(&source.metadata.raw),
                    minor: source.metadata.minor,
                    minor_raw: read(&source.metadata.minor_raw),
                    map,
                },
                sections: read(&source.sections),
                strict_validation: source.strict_validation,
                sections_declared: source.sections_declared,
            }
        };
        let mut view = unsafe {
            ConFrame {
                header,
                atom_data: std::mem::take(&mut atom_data.0),
                column_tails: read(&self.column_tails),
                positions: read(&self.positions),
                velocities: self.velocities.clone(),
                forces: self.forces.clone(),
                atom_energies: read(&self.atom_energies),
                charges: read(&self.charges),
                spins: read(&self.spins),
                magmoms: read(&self.magmoms),
                displacements: read(&self.displacements),
                spreads: read(&self.spreads),
                masses: read(&self.masses),
                atom_ids: read(&self.atom_ids),
                sequential_plain: self.sequential_plain,
            }
        };
        // The bitwise positions alias the source. The view keeps a private
        // column of the coordinates copied above, and the shared handle is
        // not dropped. The velocity and force handles are counted clones:
        // the source's atoms address those blocks, and a source that saw a
        // count of one would treat its block as its own while the view
        // still reads it.
        let owned = crate::storage_dtype::FloatArray2::from_f64_row_major(n_atoms, 3, copied);
        let shared = std::mem::replace(&mut view.positions, owned);
        std::mem::forget(shared);
        (view, shared_map)
    }
}

#[cfg(feature = "python")]
fn recycle_snapshot_atoms(atoms: &mut Vec<AtomDatum>) {
    let mut atoms = std::mem::take(atoms);
    let capacity = atoms.capacity();
    if capacity == 0 {
        return;
    }
    let pointer = atoms.as_mut_ptr();
    std::mem::forget(atoms);
    let spare = unsafe {
        Vec::from_raw_parts(
            pointer.cast::<std::mem::MaybeUninit<AtomDatum>>(),
            0,
            capacity,
        )
    };
    stash_snapshot_atom_spare(spare);
}

#[cfg(feature = "python")]
struct SnapshotAtomGuard(Vec<AtomDatum>);

#[cfg(feature = "python")]
impl Drop for SnapshotAtomGuard {
    fn drop(&mut self) {
        // The shells were copied bit-for-bit from a live source. On unwind,
        // free only their vector allocation, never their borrowed fields.
        recycle_snapshot_atoms(&mut self.0);
    }
}

/// Views of frames whose coordinates live in a buffer only this value
/// holds.
///
/// A source frame can read its coordinates from memory another thread may
/// store into, such as a NumPy array handed to Python. The writer prices
/// each frame's text length before it spells it, so a store between the
/// two would overrun the priced range. These views read the values once,
/// when the snapshot is taken, and share everything else with the source
/// frames, which the borrow keeps alive and unchanged.
#[cfg(feature = "python")]
pub(crate) struct CoordSnapshot<'a> {
    frames: Vec<Option<ConFrame>>,
    /// Per view: its metadata map belongs to the source frame.
    shared_maps: Vec<bool>,
    /// The writer may keep this buffer past the snapshot to check a later
    /// one against it, so it is shared and never written after the copy.
    coords: Arc<Vec<f64>>,
    /// First and last source frame.
    ends: Option<(usize, usize)>,
    /// Identity of every source frame in order.
    identities: Arc<[usize]>,
    _sources: std::marker::PhantomData<&'a ConFrame>,
}

#[cfg(feature = "python")]
struct SnapshotViewGuard {
    frames: Vec<Option<ConFrame>>,
    shared_maps: Vec<bool>,
}

#[cfg(feature = "python")]
impl SnapshotViewGuard {
    fn dismantle(&mut self) {
        for (slot, shared) in self.frames.iter_mut().zip(&self.shared_maps) {
            let Some(frame) = slot else { continue };
            // The view owns its positions column. Drop it before the rest
            // of the frame is forgotten with the source.
            let positions = unsafe { std::ptr::read(&frame.positions) };
            unsafe {
                std::ptr::write(&mut frame.positions, std::mem::zeroed());
            }
            drop(positions);
            // Counted clones of the source columns, released here.
            drop(std::mem::take(&mut frame.velocities));
            drop(std::mem::take(&mut frame.forces));
            recycle_snapshot_atoms(&mut frame.atom_data);
            // A map parsed into the view is owned by it. A copied map is
            // still owned by the source and must not be dropped here.
            let map = frame.header.metadata.map.take();
            if *shared {
                std::mem::forget(map);
            }
        }
        // Every other field in each raw view belongs to its source.
        unsafe { self.frames.set_len(0) };
        self.shared_maps.clear();
    }
}

#[cfg(feature = "python")]
impl Drop for SnapshotViewGuard {
    fn drop(&mut self) {
        // `copy_of` can unwind after earlier views were built. Dismantling
        // those views prevents their pointer-read fields from double-freeing
        // the live source frames.
        self.dismantle();
    }
}

#[cfg(feature = "python")]
impl<'a> CoordSnapshot<'a> {
    pub(crate) fn copy_of(frames: &[Option<&'a ConFrame>]) -> Self {
        Self::copy_reading(frames, std::ptr::null())
    }

    /// `source` is a contiguous `[frame][atom][xyz]` slab Python can store
    /// into. A null source reads each frame's positions column.
    pub(crate) fn copy_reading(frames: &[Option<&'a ConFrame>], source: *const f64) -> Self {
        Self::copy_reading_gap(frames, source, 0)
    }

    /// `gap_doubles` is the slab width of one missing frame.
    ///
    /// A `None` slot consumes that many doubles of a non-null source and
    /// writes no view. Skipping the slot without that advance shifts every
    /// later frame. A null source ignores the gap and reads each present
    /// column.
    pub(crate) fn copy_reading_gap(
        frames: &[Option<&'a ConFrame>],
        source: *const f64,
        gap_doubles: usize,
    ) -> Self {
        if !source.is_null() {
            assert_atomic_f64_alignment(source);
        }
        let total: usize = frames
            .iter()
            .flatten()
            .map(|frame| frame.atom_data.len())
            .sum();
        let mut sources = frames.iter().flatten();
        let ends = sources.next().map(|first| {
            let last = sources.last().unwrap_or(first);
            (
                *first as *const ConFrame as usize,
                *last as *const ConFrame as usize,
            )
        });
        let identities: Arc<[usize]> = frames
            .iter()
            .map(|slot| {
                slot.map(|frame| frame as *const ConFrame as usize)
                    .unwrap_or(0)
            })
            .collect();
        // Coordinates the writer last priced for these frames serve again
        // while every bit still matches; nothing writes that buffer. The
        // first frame that differs moves the views to a fresh copy.
        let priced = ends
            .and_then(|_| crate::writer::priced_coords(&identities))
            .filter(|priced| priced.len() == total * 3);
        let mut fill = priced.is_none();
        let mut fresh: Vec<f64> = Vec::new();
        let mut base = match &priced {
            Some(priced) => priced.as_ptr().cast_mut(),
            None => {
                fresh.reserve_exact(total * 3);
                fresh.as_mut_ptr()
            }
        };
        let mut src_at = 0usize;
        let mut dst_at = 0usize;
        let mut views = SnapshotViewGuard {
            frames: Vec::with_capacity(frames.len()),
            shared_maps: Vec::with_capacity(frames.len()),
        };
        for slot in frames {
            let Some(frame) = slot else {
                views.frames.push(None);
                views.shared_maps.push(false);
                if !source.is_null() {
                    src_at += gap_doubles;
                }
                continue;
            };
            let at = unsafe { base.add(dst_at) };
            let from = if source.is_null() {
                std::ptr::null()
            } else {
                unsafe { source.add(src_at) }
            };
            if !fill && !coords_match(frame, at, from) {
                fresh.reserve_exact(total * 3);
                let to = fresh.as_mut_ptr();
                unsafe {
                    std::ptr::copy_nonoverlapping(base, to, dst_at);
                }
                base = to;
                fill = true;
            }
            let (view, shared) = unsafe { frame.view_onto(base.add(dst_at), fill, from) };
            let width = frame.atom_data.len() * 3;
            src_at += width;
            dst_at += width;
            views.frames.push(Some(view));
            views.shared_maps.push(shared);
        }
        let frames = std::mem::take(&mut views.frames);
        let shared_maps = std::mem::take(&mut views.shared_maps);
        let coords = match priced {
            Some(priced) if !fill => priced,
            _ => {
                // Every slot was written above. The Arc keeps those bytes for
                // the price key. The views' atoms already hold the same values.
                unsafe { fresh.set_len(total * 3) };
                Arc::new(fresh)
            }
        };
        CoordSnapshot {
            frames,
            shared_maps,
            coords,
            ends,
            identities,
            _sources: std::marker::PhantomData,
        }
    }

    pub(crate) fn slots(&self) -> &[Option<ConFrame>] {
        &self.frames
    }

    /// Lets the writer reuse lengths priced for the same source frames
    /// while the coordinates are bit-for-bit the same.
    pub(crate) fn price_key(&self) -> Option<crate::writer::PriceKey> {
        self.ends?;
        let view_identities: Arc<[usize]> = self
            .frames
            .iter()
            .flatten()
            .map(|frame| frame as *const ConFrame as usize)
            .collect();
        if view_identities.is_empty() {
            return None;
        }
        Some(crate::writer::PriceKey {
            identities: self.identities.clone(),
            view_identities,
            coords: self.coords.clone(),
        })
    }
}

/// Whether the doubles at `priced` hold the coordinates of `frame` bit
/// for bit.
#[cfg(feature = "python")]
fn coords_match(frame: &ConFrame, priced: *const f64, from: *const f64) -> bool {
    let n = frame.atom_data.len() * 3;
    if n == 0 {
        return true;
    }
    let priced = unsafe { std::slice::from_raw_parts(priced, n) };
    if from.is_null() {
        return frame.atom_data.iter().enumerate().all(|(index, _)| {
            let xyz = frame.load_coords(index);
            let base = index * 3;
            (xyz[0].to_bits() ^ priced[base].to_bits())
                | (xyz[1].to_bits() ^ priced[base + 1].to_bits())
                | (xyz[2].to_bits() ^ priced[base + 2].to_bits())
                == 0
        });
    }
    (0..n).all(|index| {
        let value = unsafe { atomic_load_f64(from.add(index)) };
        value.to_bits() == priced[index].to_bits()
    })
}

#[cfg(any(feature = "python", test))]
pub(crate) fn assert_atomic_f64_alignment(ptr: *const f64) {
    assert!(
        ptr.cast::<std::sync::atomic::AtomicU64>().is_aligned(),
        "shared f64 storage is not aligned for AtomicU64"
    );
}

/// Load one potentially shared `f64` without creating an `f64` reference.
///
/// A concurrent writer may change adjacent elements, so a snapshot has no
/// cross-element atomicity. Each returned element is nevertheless one complete
/// value observed by a relaxed 64-bit atomic load. Callers must keep the
/// allocation alive and check [`assert_atomic_f64_alignment`] first.
#[cfg(any(feature = "python", test))]
#[inline(always)]
pub(crate) unsafe fn atomic_load_f64(ptr: *const f64) -> f64 {
    f64::from_bits(unsafe { atomic_load_bits(ptr) })
}

/// Store one potentially shared `f64` without creating an `f64` reference.
#[cfg(feature = "python")]
#[inline(always)]
pub(crate) unsafe fn atomic_store_f64(ptr: *mut f64, value: f64) {
    use std::sync::atomic::{AtomicU64, Ordering};
    let atomic = unsafe { AtomicU64::from_ptr(ptr.cast::<u64>()) };
    atomic.store(value.to_bits(), Ordering::Relaxed);
}

#[cfg(any(feature = "python", test))]
#[inline(always)]
unsafe fn atomic_load_bits(ptr: *const f64) -> u64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    // `from_ptr` borrows the cell as an atomic. Callers must not also hold
    // an `f64` reference to that cell.
    let atomic = unsafe { AtomicU64::from_ptr(ptr.cast_mut().cast::<u64>()) };
    atomic.load(Ordering::Relaxed)
}

/// Copy potentially shared doubles to private storage with relaxed loads.
///
/// The loop is explicitly unrolled so release builds issue independent plain
/// loads on x86-64 and AArch64. The destination must not overlap the source.
#[cfg(feature = "python")]
#[inline]
pub(crate) unsafe fn atomic_copy_f64(src: *const f64, dst: *mut f64, len: usize) {
    unsafe { atomic_copy_f64_serial(src, dst, len) };
}

#[cfg(feature = "python")]
#[inline(always)]
unsafe fn atomic_copy_f64_serial(src: *const f64, dst: *mut f64, len: usize) {
    let mut index = 0;
    while index + 8 <= len {
        unsafe {
            dst.add(index).write(atomic_load_f64(src.add(index)));
            dst.add(index + 1)
                .write(atomic_load_f64(src.add(index + 1)));
            dst.add(index + 2)
                .write(atomic_load_f64(src.add(index + 2)));
            dst.add(index + 3)
                .write(atomic_load_f64(src.add(index + 3)));
            dst.add(index + 4)
                .write(atomic_load_f64(src.add(index + 4)));
            dst.add(index + 5)
                .write(atomic_load_f64(src.add(index + 5)));
            dst.add(index + 6)
                .write(atomic_load_f64(src.add(index + 6)));
            dst.add(index + 7)
                .write(atomic_load_f64(src.add(index + 7)));
        }
        index += 8;
    }
    while index < len {
        unsafe {
            dst.add(index).write(atomic_load_f64(src.add(index)));
        }
        index += 1;
    }
}

#[cfg(feature = "python")]
impl Drop for CoordSnapshot<'_> {
    fn drop(&mut self) {
        crate::writer::invalidate_packed_lengths_if_any(
            self.frames
                .iter()
                .flatten()
                .map(|frame| frame as *const ConFrame as usize),
        );
        let mut views = SnapshotViewGuard {
            frames: std::mem::take(&mut self.frames),
            shared_maps: std::mem::take(&mut self.shared_maps),
        };
        views.dismantle();
    }
}

impl AtomDatum {
    /// Coordinate-only atom. Section accessors return `None` until one is set.
    pub fn coords(
        symbol: impl Into<Arc<str>>,
        x: f64,
        y: f64,
        z: f64,
        fixed: [bool; 3],
        atom_id: u64,
    ) -> Self {
        // Coordinates belong in the frame column. Callers that still pass
        // them here also write that column; the atom does not keep a copy.
        let _ = (x, y, z);
        let mut atom = Self {
            symbol: symbol.into(),
            atom_id,
            tail: 0,
        };
        atom.set_fixed(fixed);
        atom
    }

    fn install(&mut self, section: AtomSections) {
        let old = self.tail_ptr();
        if self.tail & TAIL_EXTERNAL == 0 && !old.is_null() {
            unsafe { drop(Box::from_raw(old)) };
        }
        self.tail &= !TAIL_EXTERNAL;
        let ptr = match section {
            AtomSections::Empty => std::ptr::null_mut(),
            AtomSections::Present(boxed) => Box::into_raw(boxed),
        };
        self.set_tail_ptr(ptr);
    }

    /// `slot` is an arena element. The frame owns it. This atom does not free it.
    pub(crate) fn bind_external_tail(&mut self, slot: *mut HeapTail) {
        if self.tail & TAIL_EXTERNAL == 0 {
            let old = self.tail_ptr();
            if !old.is_null() {
                unsafe { drop(Box::from_raw(old)) };
            }
        }
        debug_assert!(slot as usize & TAIL_MASK == 0);
        self.tail = (slot as usize) | (self.tail & 0b1111) | TAIL_EXTERNAL;
    }

    fn detach_external_tail(&mut self) {
        if self.tail & TAIL_EXTERNAL != 0 {
            self.tail &= 0b1111;
        }
    }

    fn is_external(&self) -> bool {
        self.tail & TAIL_EXTERNAL != 0
    }

    /// No section other than velocity and force, so a column slot can
    /// stand in for this atom's own tail without losing a value.
    fn holds_only_motion(&self) -> bool {
        match self.heap() {
            None | Some(HeapTail::Velocity(_)) | Some(HeapTail::Column { .. }) => true,
            Some(HeapTail::Full(full)) => {
                full.energy.is_none()
                    && full.charge.is_none()
                    && full.spin.is_none()
                    && full.magmom.is_none()
                    && full.displacement.is_none()
                    && full.spread.is_none()
            }
        }
    }

    fn heap(&self) -> Option<&HeapTail> {
        let ptr = self.tail_ptr();
        if ptr.is_null() {
            None
        } else {
            Some(unsafe { &*ptr })
        }
    }

    fn heap_mut(&mut self) -> Option<&mut HeapTail> {
        let ptr = self.tail_ptr();
        if ptr.is_null() {
            None
        } else {
            Some(unsafe { &mut *ptr })
        }
    }

    /// Full atom, boxing the section tail only when at least one section is set.
    #[allow(clippy::too_many_arguments)]
    pub fn with_sections(
        symbol: impl Into<Arc<str>>,
        x: f64,
        y: f64,
        z: f64,
        fixed: [bool; 3],
        atom_id: u64,
        velocity: Option<[f64; 3]>,
        force: Option<[f64; 3]>,
        energy: Option<f64>,
        charge: Option<f64>,
        spin: Option<f64>,
        magmom: Option<[f64; 3]>,
        displacement: Option<[f64; 3]>,
        spread: Option<[f64; 3]>,
    ) -> Self {
        let mut atom = Self::coords(symbol, x, y, z, fixed, atom_id);
        if velocity.is_some()
            || force.is_some()
            || energy.is_some()
            || charge.is_some()
            || spin.is_some()
            || magmom.is_some()
            || displacement.is_some()
            || spread.is_some()
        {
            let only_velocity = velocity.is_some()
                && force.is_none()
                && energy.is_none()
                && charge.is_none()
                && spin.is_none()
                && magmom.is_none()
                && displacement.is_none()
                && spread.is_none();
            atom.install(if only_velocity {
                AtomSections::velocity(velocity.unwrap())
            } else {
                AtomSections::from_full(AtomTail {
                    velocity,
                    force,
                    energy,
                    charge,
                    spin,
                    magmom,
                    displacement,
                    spread,
                })
            });
        }
        atom
    }

    fn read3(ptr: *const f64) -> [f64; 3] {
        unsafe { [*ptr, *ptr.add(1), *ptr.add(2)] }
    }

    fn write3(ptr: *mut f64, value: [f64; 3]) {
        unsafe {
            *ptr = value[0];
            *ptr.add(1) = value[1];
            *ptr.add(2) = value[2];
        }
    }

    pub(crate) fn velocity_slot(&self) -> *const f64 {
        match self.heap() {
            Some(HeapTail::Column { vel, .. }) => *vel,
            _ => std::ptr::null(),
        }
    }

    pub(crate) fn force_slot(&self) -> *const f64 {
        match self.heap() {
            Some(HeapTail::Column { force, .. }) => *force,
            _ => std::ptr::null(),
        }
    }

    fn column_pair(&self) -> (Option<[f64; 3]>, Option<[f64; 3]>) {
        match self.heap() {
            Some(HeapTail::Column { vel, force }) => (
                if vel.is_null() {
                    None
                } else {
                    Some(Self::read3(*vel))
                },
                if force.is_null() {
                    None
                } else {
                    Some(Self::read3(*force))
                },
            ),
            _ => (None, None),
        }
    }

    fn ensure_tail(&mut self) -> &mut AtomTail {
        let (slotted_vel, slotted_force) = self.column_pair();
        self.detach_external_tail();
        let needs_full = !matches!(self.heap(), Some(HeapTail::Full(_)));
        if needs_full {
            let velocity = slotted_vel.or(match self.heap() {
                Some(HeapTail::Velocity(v)) => Some(*v),
                _ => None,
            });
            self.install(AtomSections::from_full(AtomTail {
                velocity,
                force: slotted_force,
                ..AtomTail::default()
            }));
        } else if let Some(HeapTail::Full(full)) = self.heap_mut() {
            if slotted_vel.is_some() {
                full.velocity = slotted_vel;
            }
            if slotted_force.is_some() {
                full.force = slotted_force;
            }
        }
        match self.heap_mut() {
            Some(HeapTail::Full(full)) => full,
            _ => unreachable!(),
        }
    }

    fn shrink_tail(&mut self) {
        let next = match self.heap() {
            Some(HeapTail::Full(full)) if full.is_empty() => Some(AtomSections::Empty),
            Some(HeapTail::Full(full))
                if full.force.is_none()
                    && full.energy.is_none()
                    && full.charge.is_none()
                    && full.spin.is_none()
                    && full.magmom.is_none()
                    && full.displacement.is_none()
                    && full.spread.is_none()
                    && full.velocity.is_some() =>
            {
                Some(AtomSections::velocity(full.velocity.unwrap()))
            }
            _ => None,
        };
        if let Some(next) = next {
            self.install(next);
        }
    }

    /// Velocity vector `[vx, vy, vz]` (present only in `.convel` files).
    #[inline]
    pub fn velocity(&self) -> Option<[f64; 3]> {
        match self.heap() {
            Some(HeapTail::Column { vel, .. }) if !vel.is_null() => Some(Self::read3(*vel)),
            Some(HeapTail::Velocity(v)) => Some(*v),
            Some(HeapTail::Full(full)) => full.velocity,
            _ => None,
        }
    }
    /// Force vector `[fx, fy, fz]`.
    #[inline]
    pub fn force(&self) -> Option<[f64; 3]> {
        match self.heap() {
            Some(HeapTail::Column { force, .. }) if !force.is_null() => Some(Self::read3(*force)),
            Some(HeapTail::Full(full)) => full.force,
            _ => None,
        }
    }
    /// Per-atom energy contribution.
    #[inline]
    pub fn energy(&self) -> Option<f64> {
        match self.heap() {
            Some(HeapTail::Full(full)) => full.energy,
            _ => None,
        }
    }
    /// Partial charge.
    #[inline]
    pub fn charge(&self) -> Option<f64> {
        match self.heap() {
            Some(HeapTail::Full(full)) => full.charge,
            _ => None,
        }
    }
    /// Spin scalar.
    #[inline]
    pub fn spin(&self) -> Option<f64> {
        match self.heap() {
            Some(HeapTail::Full(full)) => full.spin,
            _ => None,
        }
    }
    /// Magnetic moment `[mx, my, mz]`.
    #[inline]
    pub fn magmom(&self) -> Option<[f64; 3]> {
        match self.heap() {
            Some(HeapTail::Full(full)) => full.magmom,
            _ => None,
        }
    }
    /// Displacement `[dx, dy, dz]`.
    #[inline]
    pub fn displacement(&self) -> Option<[f64; 3]> {
        match self.heap() {
            Some(HeapTail::Full(full)) => full.displacement,
            _ => None,
        }
    }
    /// RMS spread `[sx, sy, sz]`.
    #[inline]
    pub fn spread(&self) -> Option<[f64; 3]> {
        match self.heap() {
            Some(HeapTail::Full(full)) => full.spread,
            _ => None,
        }
    }

    /// Set or clear the velocity.
    ///
    /// On an atom of a parsed frame this stores into the frame's velocity
    /// column. Another handle on that block, such as a DLPack export, sees
    /// the store; [`ConFrame::unshare_slot_columns`] gives the frame its
    /// own block first.
    pub fn set_velocity(&mut self, value: Option<[f64; 3]>) {
        let slot = match self.heap() {
            Some(HeapTail::Column { vel, .. }) if !vel.is_null() => Some(*vel),
            _ => None,
        };
        if let Some(slot) = slot {
            if let Some(v) = value {
                Self::write3(slot, v);
                return;
            }
            if let Some(HeapTail::Column { vel, .. }) = self.heap_mut() {
                *vel = std::ptr::null_mut();
            }
            return;
        }
        if let Some(HeapTail::Column { force, .. }) = self.heap() {
            if !force.is_null() {
                if value.is_some() {
                    self.ensure_tail().velocity = value;
                    self.shrink_tail();
                }
                return;
            }
        }
        if matches!(self.heap(), Some(HeapTail::Full(_))) {
            self.ensure_tail().velocity = value;
            self.shrink_tail();
            return;
        }
        self.install(match value {
            Some(v) => AtomSections::velocity(v),
            None => AtomSections::Empty,
        });
    }
    /// Set or clear the force. A parsed frame's atom stores into the force
    /// column, as [`Self::set_velocity`] does into the velocity column.
    pub fn set_force(&mut self, value: Option<[f64; 3]>) {
        let slot = match self.heap() {
            Some(HeapTail::Column { force, .. }) if !force.is_null() => Some(*force),
            _ => None,
        };
        if let Some(slot) = slot {
            if let Some(v) = value {
                Self::write3(slot, v);
                return;
            }
            if let Some(HeapTail::Column { force, .. }) = self.heap_mut() {
                *force = std::ptr::null_mut();
            }
            return;
        }
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().force = value;
        self.shrink_tail();
    }
    pub fn set_energy(&mut self, value: Option<f64>) {
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().energy = value;
        self.shrink_tail();
    }
    pub fn set_charge(&mut self, value: Option<f64>) {
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().charge = value;
        self.shrink_tail();
    }
    pub fn set_spin(&mut self, value: Option<f64>) {
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().spin = value;
        self.shrink_tail();
    }
    pub fn set_magmom(&mut self, value: Option<[f64; 3]>) {
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().magmom = value;
        self.shrink_tail();
    }
    pub fn set_displacement(&mut self, value: Option<[f64; 3]>) {
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().displacement = value;
        self.shrink_tail();
    }
    pub fn set_spread(&mut self, value: Option<[f64; 3]>) {
        if value.is_none() && self.tail_ptr().is_null() {
            return;
        }
        self.ensure_tail().spread = value;
        self.shrink_tail();
    }

    /// Returns `true` if any direction is fixed.
    pub fn is_fixed(&self) -> bool {
        let fixed = self.fixed();
        fixed[0] || fixed[1] || fixed[2]
    }

    /// Returns `true` if all three directions are fixed.
    pub fn is_fully_fixed(&self) -> bool {
        let fixed = self.fixed();
        fixed[0] && fixed[1] && fixed[2]
    }

    /// Returns `true` if this atom has velocity data.
    pub fn has_velocity(&self) -> bool {
        self.velocity().is_some()
    }

    /// Returns `true` if this atom has force data.
    pub fn has_forces(&self) -> bool {
        self.force().is_some()
    }

    /// Returns `true` if this atom carries a per-atom energy contribution.
    pub fn has_energy(&self) -> bool {
        self.energy().is_some()
    }

    pub fn has_charge(&self) -> bool {
        self.charge().is_some()
    }

    pub fn has_spin(&self) -> bool {
        self.spin().is_some()
    }

    pub fn has_magmom(&self) -> bool {
        self.magmom().is_some()
    }

    pub fn has_displacement(&self) -> bool {
        self.displacement().is_some()
    }

    pub fn has_spread(&self) -> bool {
        self.spread().is_some()
    }
}

/// Lengths `|a| |b| |c|` and angles `alpha beta gamma` in degrees.
/// `alpha` is the angle between b and c, `beta` between a and c,
/// `gamma` between a and b (CON-cell, D12).
pub fn lengths_and_angles(vecs: [[f64; 3]; 3]) -> ([f64; 3], [f64; 3]) {
    fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
        a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    }
    fn len(v: [f64; 3]) -> f64 {
        dot(v, v).sqrt()
    }
    fn angle_deg(a: [f64; 3], b: [f64; 3]) -> f64 {
        let la = len(a);
        let lb = len(b);
        if la == 0.0 || lb == 0.0 {
            return f64::NAN;
        }
        let cosine = (dot(a, b) / (la * lb)).clamp(-1.0, 1.0);
        cosine.acos().to_degrees()
    }
    let a = vecs[0];
    let b = vecs[1];
    let c = vecs[2];
    (
        [len(a), len(b), len(c)],
        [angle_deg(b, c), angle_deg(a, c), angle_deg(a, b)],
    )
}

/// The first of `values` that is NaN or infinite, as a cell field error.
#[cold]
#[inline(never)]
fn non_finite_cell_value(values: &[(&[f64], &str)]) -> ParseError {
    for (group, name) in values {
        if let Some((index, value)) = group.iter().enumerate().find(|(_, v)| !v.is_finite()) {
            return ParseError::non_finite_cell(&format!("{name}[{index}]"), value);
        }
    }
    ParseError::ValidationError("cell check found no non-finite value".into())
}

/// Checks that three cell lengths and three cell angles are finite.
///
/// `lengths_name` and `angles_name` are the names of the two arrays in the
/// caller's API (`boxl` and `angles` in a header, `cell` and `angles` in a
/// builder). An element is reported as `name[i]`.
///
/// # Errors
///
/// [`ParseError::NonFiniteValue`] naming the first non-finite field. The
/// check is six comparisons and allocates only when it fails.
#[inline]
pub fn check_cell_finite(
    lengths: &[f64; 3],
    lengths_name: &str,
    angles: &[f64; 3],
    angles_name: &str,
) -> Result<(), ParseError> {
    if lengths.iter().all(|v| v.is_finite()) && angles.iter().all(|v| v.is_finite()) {
        Ok(())
    } else {
        Err(non_finite_cell_value(&[
            (lengths, lengths_name),
            (angles, angles_name),
        ]))
    }
}

/// Checks a row of cell parameters: `a b c alpha beta gamma`.
///
/// This is the layout of a `cell` array with one row per frame (CON-bin,
/// extended XYZ, the column writers, Python `cell`). An element is reported
/// as `cell[i]`, `i` counted from the start of the row.
///
/// # Errors
///
/// [`ParseError::NonFiniteValue`] naming the first non-finite field.
#[inline]
pub fn check_cellpar_finite(cellpar: &[f64]) -> Result<(), ParseError> {
    if cellpar.iter().all(|v| v.is_finite()) {
        Ok(())
    } else {
        Err(non_finite_cell_value(&[(cellpar, "cell")]))
    }
}

/// Checks every row of a `(frames, 6)` cell array, rows of `a b c alpha beta
/// gamma`, laid out flat.
///
/// # Errors
///
/// [`ParseError::NonFiniteValue`] naming the first non-finite field as
/// `cell[i]` of the frame, the row, that holds it. A trailing partial row is
/// checked like a whole one.
pub fn check_cell_rows(cells: &[f64]) -> Result<(), ParseError> {
    if cells.iter().all(|v| v.is_finite()) {
        return Ok(());
    }
    for (frame, row) in cells.chunks(6).enumerate() {
        check_cellpar_finite(row).map_err(|error| error.in_frame(frame as u64))?;
    }
    Ok(())
}

/// Same as [`check_cell_rows`] for a binary32 array.
///
/// # Errors
///
/// [`ParseError::NonFiniteValue`], as [`check_cell_rows`].
pub fn check_cell_rows_f32(cells: &[f32]) -> Result<(), ParseError> {
    if cells.iter().all(|v| v.is_finite()) {
        return Ok(());
    }
    for (frame, row) in cells.chunks(6).enumerate() {
        if let Some((index, value)) = row.iter().enumerate().find(|(_, v)| !v.is_finite()) {
            return Err(
                ParseError::non_finite_cell(&format!("cell[{index}]"), value)
                    .in_frame(frame as u64),
            );
        }
    }
    Ok(())
}

/// Checks that the nine components of a lattice matrix are finite.
///
/// A component is reported as `lattice_vectors[row][column]`.
///
/// # Errors
///
/// [`ParseError::NonFiniteValue`] naming the first non-finite component.
pub fn check_lattice_finite(vecs: &[[f64; 3]; 3]) -> Result<(), ParseError> {
    for (row, vector) in vecs.iter().enumerate() {
        if let Some((column, value)) = vector.iter().enumerate().find(|(_, v)| !v.is_finite()) {
            return Err(ParseError::non_finite_cell(
                &format!("lattice_vectors[{row}][{column}]"),
                value,
            ));
        }
    }
    Ok(())
}

/// Lattice vectors from lengths `|a| |b| |c|` and angles `alpha beta gamma`
/// in degrees (CON-cell.6).
///
/// `a = (|a|, 0, 0)`,
/// `b = (|b| cos gamma, |b| sin gamma, 0)`,
/// `c = (|c| cos beta, |c| (cos alpha - cos beta cos gamma) / sin gamma,
/// |c| sqrt(1 - cos^2 beta - cy^2))` where `cy` is that middle term.
pub fn cell_vectors(lengths: [f64; 3], angles_deg: [f64; 3]) -> [[f64; 3]; 3] {
    let [a_len, b_len, c_len] = lengths;
    let alpha = angles_deg[0].to_radians();
    let beta = angles_deg[1].to_radians();
    let gamma = angles_deg[2].to_radians();
    let cos_alpha = alpha.cos();
    let cos_beta = beta.cos();
    let cos_gamma = gamma.cos();
    let sin_gamma = gamma.sin();
    let cy = (cos_alpha - cos_beta * cos_gamma) / sin_gamma;
    let cz_sq = 1.0 - cos_beta * cos_beta - cy * cy;
    // Orthogonal angles leave a rounding crumb below zero.
    let cz = if cz_sq < 0.0 && cz_sq > -1e-12 {
        0.0
    } else {
        cz_sq.sqrt()
    };
    [
        [a_len, 0.0, 0.0],
        [b_len * cos_gamma, b_len * sin_gamma, 0.0],
        [c_len * cos_beta, c_len * cy, c_len * cz],
    ]
}

/// Decode a column-4 bitmask as a spec-2 value.
///
/// Spec-2 files use a pure bitmask (bit 0 = x, bit 1 = y, bit 2 = z),
/// so 1 is x-only. Spec-1 files that wrote 1 meaning fully fixed must
/// call [`decode_fixed_bitmask_for_spec`] with `spec_version = 1`.
pub fn decode_fixed_bitmask(val: u8) -> [bool; 3] {
    decode_fixed_bitmask_for_spec(val, crate::CON_SPEC_VERSION)
}

/// Decode a column-4 value under a specific CON spec version.
///
/// Spec 1 (legacy, no JSON on line 2) treats 1 as all-fixed. Spec 2
/// and later treat 1 as x-only, which is what
/// [`encode_fixed_bitmask`] writes for `[true, false, false]`.
pub(crate) fn decode_fixed_bitmask_for_spec(val: u8, spec_version: u32) -> [bool; 3] {
    match val {
        0 => [false, false, false],
        1 if spec_version < 2 => [true, true, true],
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
#[derive(Debug)]
pub struct ConFrame {
    /// The `FrameHeader` containing the frame's metadata.
    pub header: FrameHeader,
    /// AoS records for CON serialization and symbol/fixed metadata.
    ///
    /// An atom stores no coordinates. [`Self::positions`] is the column
    /// [`Self::xyz_at`] reads, at the atom's index in this list.
    pub atom_data: Vec<AtomDatum>,
    /// Arena for velocity and force column tails. Empty on a coordinate-only
    /// frame, so those atoms stay the same size as a file with no sections.
    #[doc(hidden)]
    pub column_tails: Vec<HeapTail>,
    /// Primary positions `(N, 3)`, type-grouped order (f32 or f64 storage).
    pub positions: crate::storage_dtype::FloatArray2,
    /// Velocities `(N, 3)` when present; else `(0, 3)`.
    ///
    /// On a parsed frame each atom's [`AtomDatum::velocity`] reads its row
    /// of this block. A row write through this field is seen by the atoms
    /// while the frame holds the only handle; [`Self::clone`] gives the
    /// clone its own block. After handing out another handle, such as a
    /// clone of this field or a DLPack export, call
    /// [`Self::unshare_slot_columns`] before writing. Assign a new
    /// column inside [`Self::with_section_columns`].
    pub velocities: crate::storage_dtype::Optional2,
    /// Forces `(N, 3)` when present; else `(0, 3)`.
    ///
    /// The atoms address this block the way they address
    /// [`Self::velocities`], and the same rules apply.
    pub forces: crate::storage_dtype::Optional2,
    /// Per-atom energies `(N,)` when present; else `(0,)`.
    pub atom_energies: crate::storage_dtype::Optional1,
    /// Per-atom charges `(N,)` when present; else `(0,)`.
    pub charges: crate::storage_dtype::Optional1,
    /// Per-atom spins `(N,)` when present; else `(0,)`.
    pub spins: crate::storage_dtype::Optional1,
    /// Magnetic moments `(N, 3)` when present; else `(0, 3)`.
    pub magmoms: crate::storage_dtype::Optional2,
    /// Displacements `(N, 3)` in Angstrom when present; else `(0, 3)`.
    pub displacements: crate::storage_dtype::Optional2,
    /// Spreads `(N, 3)` in Angstrom when present; else `(0, 3)`.
    pub spreads: crate::storage_dtype::Optional2,
    /// Per-atom masses `(N,)`.
    pub masses: crate::storage_dtype::FloatArray1,
    /// Per-atom ids `(N,)` u64 (always).
    pub atom_ids: ndarray::ArcArray1<u64>,
    /// Coordinates only, ids are `0..n`, and no atom is fixed.
    ///
    /// Set while the frame is parsed. The eOn atom fill trusts it and does
    /// not walk the atoms again.
    pub(crate) sequential_plain: bool,
}

impl Clone for ConFrame {
    /// Cloned atoms own their section tails (`AtomDatum::clone` clears
    /// `TAIL_EXTERNAL`). The clone therefore owns its velocity and force
    /// columns when atoms address their rows, and its atoms are rebound to
    /// the clone's copy.
    ///
    /// A block shared between the two frames would be copied by the first
    /// write through either frame's field, which leaves that frame's atoms
    /// on the other frame's block, and a write through an atom would show
    /// in both frames.
    fn clone(&self) -> Self {
        let bound = self.section_slot_mask();
        let column = |column: &crate::storage_dtype::Optional2| {
            if bound.is_empty() {
                return column.clone();
            }
            match &**column {
                crate::storage_dtype::Array2Storage::F64(array) if column.is_present() => {
                    crate::storage_dtype::Array2Storage::F64(array.to_owned().into_shared()).into()
                }
                _ => column.clone(),
            }
        };
        let mut out = Self {
            header: self.header.clone(),
            atom_data: self.atom_data.clone(),
            column_tails: Vec::new(),
            positions: self.positions.clone(),
            velocities: column(&self.velocities),
            forces: column(&self.forces),
            atom_energies: self.atom_energies.clone(),
            charges: self.charges.clone(),
            spins: self.spins.clone(),
            magmoms: self.magmoms.clone(),
            displacements: self.displacements.clone(),
            spreads: self.spreads.clone(),
            masses: self.masses.clone(),
            atom_ids: self.atom_ids.clone(),
            sequential_plain: self.sequential_plain,
        };
        out.bind_section_slots(&bound);
        out
    }
}

impl PartialEq for ConFrame {
    /// The column-tail arena is how a parsed frame addresses its velocity
    /// and force columns. A built frame keeps those values in the section
    /// arrays and in each atom. Both shapes are the same frame.
    fn eq(&self, other: &Self) -> bool {
        self.header == other.header
            && self.atom_data == other.atom_data
            && self.positions == other.positions
            && self.velocities == other.velocities
            && self.forces == other.forces
            && self.atom_energies == other.atom_energies
            && self.charges == other.charges
            && self.spins == other.spins
            && self.magmoms == other.magmoms
            && self.displacements == other.displacements
            && self.spreads == other.spreads
            && self.masses == other.masses
            && self.atom_ids == other.atom_ids
    }
}

impl ConFrame {
    /// Coordinates of the atom at `index`, copied from [`Self::positions`].
    #[inline]
    pub fn xyz_at(&self, index: usize) -> [f64; 3] {
        self.positions.as_f64_row(index)
    }

    /// `x` of the atom at `index`.
    #[inline]
    pub fn x_at(&self, index: usize) -> f64 {
        self.xyz_at(index)[0]
    }

    /// `y` of the atom at `index`.
    #[inline]
    pub fn y_at(&self, index: usize) -> f64 {
        self.xyz_at(index)[1]
    }

    /// `z` of the atom at `index`.
    #[inline]
    pub fn z_at(&self, index: usize) -> f64 {
        self.xyz_at(index)[2]
    }

    /// Write one coordinate row. Accessors read this row back.
    #[inline]
    pub fn set_xyz_at(&mut self, index: usize, xyz: [f64; 3]) {
        self.positions.set_f64_row(index, xyz);
        crate::writer::invalidate_packed_lengths();
    }

    /// Write `x` of the atom at `index` into the positions column.
    ///
    /// A shared column is copied first, so a clone or a DLPack export of
    /// the old allocation keeps the previous value.
    #[inline]
    pub fn set_x_at(&mut self, index: usize, value: f64) {
        let mut xyz = self.xyz_at(index);
        xyz[0] = value;
        self.set_xyz_at(index, xyz);
    }

    /// Write `y` of the atom at `index` into the positions column.
    #[inline]
    pub fn set_y_at(&mut self, index: usize, value: f64) {
        let mut xyz = self.xyz_at(index);
        xyz[1] = value;
        self.set_xyz_at(index, xyz);
    }

    /// Write `z` of the atom at `index` into the positions column.
    #[inline]
    pub fn set_z_at(&mut self, index: usize, value: f64) {
        let mut xyz = self.xyz_at(index);
        xyz[2] = value;
        self.set_xyz_at(index, xyz);
    }

    /// Coordinates of atom `index`. Same row as [`Self::xyz_at`].
    #[cfg_attr(not(feature = "python"), allow(dead_code))]
    #[inline]
    pub(crate) fn load_coords(&self, index: usize) -> [f64; 3] {
        self.xyz_at(index)
    }

    /// Apply [`crate::storage_dtype::StorageDtypes`] from metadata (or argument) to SoA fields.
    pub fn project_storage_dtypes(&mut self, dtypes: &crate::storage_dtype::StorageDtypes) {
        // Projection replaces the column allocation. Section slots that
        // address the old velocity or force column are copied into owned
        // tails first, and address the projected column after, when it is
        // still float64. Coordinates are that column.
        clear_uniform_symbol_drop(&self.atom_data);
        let bound = self.materialise_section_slots();
        self.positions.project_to(dtypes.positions);
        if self.velocities.nrows() > 0 {
            self.velocities.project_to(dtypes.velocities);
        }
        if self.forces.nrows() > 0 {
            self.forces.project_to(dtypes.forces);
        }
        if !self.atom_energies.is_empty() {
            self.atom_energies.project_to(dtypes.energies);
        }
        if !self.charges.is_empty() {
            self.charges.project_to(dtypes.energies);
        }
        if !self.spins.is_empty() {
            self.spins.project_to(dtypes.energies);
        }
        if self.magmoms.nrows() > 0 {
            self.magmoms.project_to(dtypes.forces);
        }
        if self.displacements.nrows() > 0 {
            self.displacements.project_to(dtypes.forces);
        }
        if self.spreads.nrows() > 0 {
            self.spreads.project_to(dtypes.forces);
        }
        if !self.masses.is_empty() {
            self.masses.project_to(dtypes.masses);
        }
        let mut map = self.header.metadata.to_map();
        let minor_raw = self.header.metadata.huge_minor_raw().map(str::to_owned);
        dtypes.insert_into(&mut map);
        self.header.metadata = FrameMeta::from_map_with_minor_raw(map, minor_raw.as_deref());
        self.sync_atom_data_from_arrays();
        self.bind_section_slots(&bound);
    }

    /// Rebuild AoS [`atom_data`] coordinates (and optional sections) from SoA arrays.
    pub fn sync_atom_data_from_arrays(&mut self) {
        let n = self.positions.nrows();
        if self.atom_data.len() != n {
            return;
        }
        self.materialise_section_slots();
        let has_vel = self.velocities.nrows() == n;
        let has_frc = self.forces.nrows() == n;
        let has_eng = self.atom_energies.len() == n;
        let has_chg = self.charges.len() == n;
        let has_spn = self.spins.len() == n;
        let has_mm = self.magmoms.nrows() == n;
        let has_dsp = self.displacements.nrows() == n;
        let has_spr = self.spreads.nrows() == n;
        for i in 0..n {
            let a = &mut self.atom_data[i];
            if has_vel {
                a.set_velocity(Some(self.velocities.as_f64_row(i)));
            }
            if has_frc {
                a.set_force(Some(self.forces.as_f64_row(i)));
            }
            if has_eng {
                a.set_energy(Some(self.atom_energies.get_f64(i)));
            }
            if has_chg {
                a.set_charge(Some(self.charges.get_f64(i)));
            }
            if has_spn {
                a.set_spin(Some(self.spins.get_f64(i)));
            }
            if has_mm {
                a.set_magmom(Some(self.magmoms.as_f64_row(i)));
            }
            if has_dsp {
                a.set_displacement(Some(self.displacements.as_f64_row(i)));
            }
            if has_spr {
                a.set_spread(Some(self.spreads.as_f64_row(i)));
            }
            if i < self.atom_ids.len() {
                a.atom_id = self.atom_ids[i];
            }
        }
    }

    /// Take ownership of a flat `(n, 3)` velocity buffer and point each atom at its row.
    pub(crate) fn adopt_velocity_column(&mut self, data: Vec<f64>) {
        let n = self.atom_data.len();
        let kind = self.header.metadata.dtypes().velocities;
        if kind != crate::storage_dtype::ElementKind::Float64 {
            self.materialise_section_slots();
        }
        self.velocities = store_rows(kind, n, data).into();
        self.bind_velocity_slots();
    }

    /// Take ownership of a flat `(n, 3)` force buffer and point each atom at its row.
    pub(crate) fn adopt_force_column(&mut self, data: Vec<f64>) {
        let n = self.atom_data.len();
        let kind = self.header.metadata.dtypes().forces;
        if kind != crate::storage_dtype::ElementKind::Float64 {
            self.materialise_section_slots();
        }
        self.forces = store_rows(kind, n, data).into();
        self.bind_force_slots();
    }

    fn bind_velocity_slots(&mut self) {
        let n = self.atom_data.len();
        if self.velocities.nrows() != n || n == 0 {
            return;
        }
        let Some(ptr) = self.velocities.f64_allocation_ptr() else {
            for i in 0..n {
                let row = self.velocities.as_f64_row(i);
                self.atom_data[i].set_velocity(Some(row));
            }
            return;
        };
        self.point_column(
            |tail, slot| {
                if let HeapTail::Column { vel, .. } = tail {
                    *vel = slot;
                }
            },
            ptr,
        );
    }

    fn bind_force_slots(&mut self) {
        let n = self.atom_data.len();
        if self.forces.nrows() != n || n == 0 {
            return;
        }
        let Some(ptr) = self.forces.f64_allocation_ptr() else {
            for i in 0..n {
                let row = self.forces.as_f64_row(i);
                self.atom_data[i].set_force(Some(row));
            }
            return;
        };
        self.point_column(
            |tail, slot| {
                if let HeapTail::Column { force, .. } = tail {
                    *force = slot;
                }
            },
            ptr,
        );
    }

    fn point_column(&mut self, set: impl Fn(&mut HeapTail, *mut f64), base: *mut f64) {
        let n = self.atom_data.len();
        if self.column_tails.len() != n {
            self.column_tails.clear();
            self.column_tails.resize(
                n,
                HeapTail::Column {
                    vel: std::ptr::null_mut(),
                    force: std::ptr::null_mut(),
                },
            );
            let tails = self.column_tails.as_mut_ptr();
            for (i, atom) in self.atom_data.iter_mut().enumerate() {
                atom.bind_external_tail(unsafe { tails.add(i) });
            }
        }
        for (i, tail) in self.column_tails.iter_mut().enumerate() {
            set(tail, unsafe { base.add(i * 3) });
        }
    }

    /// Which atoms address a row of the velocity or force column.
    ///
    /// Empty when no atom does.
    fn section_slot_mask(&self) -> Vec<bool> {
        if self.column_tails.is_empty() {
            return Vec::new();
        }
        self.atom_data.iter().map(AtomDatum::is_external).collect()
    }

    /// Whether any atom slot addresses the force column, or the velocity
    /// column when `force` is false.
    fn slots_address(&self, force: bool) -> bool {
        self.column_tails.iter().any(|tail| match tail {
            HeapTail::Column { vel, force: frc } => !(if force { *frc } else { *vel }).is_null(),
            _ => false,
        })
    }

    /// Run `op` with every atom holding its own velocity and force.
    ///
    /// `op` may replace, reshape, reorder, or copy the velocity and force
    /// columns. Atoms that addressed a column row before `op` address the
    /// same row of the column `op` leaves, which is then the value they
    /// read. An atom stays on its own tail when that column is no longer a
    /// float64 `(n, 3)` row-major block or the atom gained another section.
    pub fn with_section_columns<R>(&mut self, op: impl FnOnce(&mut Self) -> R) -> R {
        let bound = self.materialise_section_slots();
        let out = op(self);
        self.bind_section_slots(&bound);
        out
    }

    /// Give this frame its own copy of a shared velocity or force column.
    ///
    /// Atoms of a parsed frame address rows of those columns. A write
    /// through [`AtomDatum::set_velocity`] lands in the column, so a block
    /// another handle shares, such as a DLPack export or a clone of the
    /// `velocities` field, would see it, and a write through the field would
    /// copy the block and leave the atoms on the old one. After this call
    /// the frame holds the only handle and the atoms address it.
    pub fn unshare_slot_columns(&mut self) {
        let n = self.atom_data.len();
        if n == 0 || self.column_tails.len() != n {
            return;
        }
        for force in [false, true] {
            if !self.slots_address(force) {
                continue;
            }
            let column = if force {
                &mut self.forces
            } else {
                &mut self.velocities
            };
            if !column.is_present() {
                continue;
            }
            let crate::storage_dtype::Array2Storage::F64(array) = &mut **column else {
                continue;
            };
            if array.is_unique() || array.dim() != (n, 3) || !array.is_standard_layout() {
                continue;
            }
            // Copies the block. The old one stays alive until this returns,
            // because the other handle still holds it.
            let base = array.as_mut_ptr();
            for (i, tail) in self.column_tails.iter_mut().enumerate() {
                if let HeapTail::Column { vel, force: frc } = tail {
                    let slot = if force { frc } else { vel };
                    if !slot.is_null() {
                        *slot = unsafe { base.add(i * 3) };
                    }
                }
            }
        }
    }

    /// Point the atoms marked in `bound` at their rows of the velocity and
    /// force columns. Call after [`Self::materialise_section_slots`].
    ///
    /// An atom keeps its own tail when it holds another section, or a
    /// velocity or force whose column is not a float64 `(n, 3)` row-major
    /// block. Binding makes the column unique first, so the slots address
    /// a block no other handle writes.
    pub(crate) fn bind_section_slots(&mut self, bound: &[bool]) {
        let n = self.atom_data.len();
        if n == 0 || bound.len() != n || !bound.contains(&true) {
            return;
        }
        debug_assert!(self.column_tails.is_empty());
        if !self.column_tails.is_empty() {
            return;
        }
        fn row_base(column: &mut crate::storage_dtype::Optional2, n: usize) -> Option<*mut f64> {
            if column.nrows() != n || column.ncols() != 3 {
                return None;
            }
            column.f64_allocation_ptr()
        }
        let vel = row_base(&mut self.velocities, n);
        let force = row_base(&mut self.forces, n);
        if vel.is_none() && force.is_none() {
            return;
        }
        clear_uniform_symbol_drop(&self.atom_data);
        self.column_tails = vec![
            HeapTail::Column {
                vel: std::ptr::null_mut(),
                force: std::ptr::null_mut(),
            };
            n
        ];
        let tails = self.column_tails.as_mut_ptr();
        for (i, atom) in self.atom_data.iter_mut().enumerate() {
            if !bound[i] || !atom.holds_only_motion() {
                continue;
            }
            let has_vel = atom.has_velocity();
            let has_force = atom.has_forces();
            if (!has_vel && !has_force)
                || (has_vel && vel.is_none())
                || (has_force && force.is_none())
            {
                continue;
            }
            let at = |base: Option<*mut f64>, present: bool| match base {
                Some(base) if present => unsafe { base.add(i * 3) },
                _ => std::ptr::null_mut(),
            };
            let slot = unsafe { tails.add(i) };
            unsafe {
                *slot = HeapTail::Column {
                    vel: at(vel, has_vel),
                    force: at(force, has_force),
                };
            }
            atom.bind_external_tail(slot);
        }
    }

    /// Copy every atom's velocity and force into its own tail and drop the
    /// slot arena. Returns which atoms held a slot, for
    /// [`Self::bind_section_slots`].
    pub(crate) fn materialise_section_slots(&mut self) -> Vec<bool> {
        let bound = self.section_slot_mask();
        if bound.is_empty() {
            return bound;
        }
        clear_uniform_symbol_drop(&self.atom_data);
        let n = self.atom_data.len();
        for i in 0..n {
            let velocity = self.atom_data[i].velocity();
            let force = self.atom_data[i].force();
            self.atom_data[i].detach_external_tail();
            if velocity.is_some() {
                self.atom_data[i].set_velocity(velocity);
            }
            if force.is_some() {
                self.atom_data[i].set_force(force);
            }
        }
        self.column_tails.clear();
        bound
    }

    fn velocity_column_live(&self) -> bool {
        let n = self.atom_data.len();
        n > 0
            && self.velocities.nrows() == n
            && self
                .velocities
                .f64_slice()
                .is_some_and(|slice| self.atom_data[0].velocity_slot() == slice.as_ptr())
    }

    fn force_column_live(&self) -> bool {
        let n = self.atom_data.len();
        n > 0
            && self.forces.nrows() == n
            && self
                .forces
                .f64_slice()
                .is_some_and(|slice| self.atom_data[0].force_slot() == slice.as_ptr())
    }

    /// Fill SoA blocks for sections named on the header.
    ///
    /// The iterator calls this after a section parse. Each present section is
    /// copied once into a plain buffer and wrapped, instead of scanning atoms
    /// for sections that are absent and storing each row through `ArcArray`.
    pub(crate) fn install_declared_section_soa(&mut self) {
        let n = self.atom_data.len();
        if n == 0 || self.header.sections.is_empty() {
            return;
        }
        let dt = self.header.metadata.dtypes();
        let sections = self.header.sections.clone();
        let declared = |name: &str| sections.iter().any(|section| section == name);
        let pack_velocities = declared(SECTION_VELOCITIES) && !self.velocity_column_live();
        let pack_forces = declared(SECTION_FORCES) && !self.force_column_live();
        // A column that is packed again replaces the block other atoms'
        // slots may still address.
        let bound = if (pack_velocities && self.slots_address(false))
            || (pack_forces && self.slots_address(true))
        {
            self.materialise_section_slots()
        } else {
            Vec::new()
        };
        for name in &sections {
            match name.as_str() {
                SECTION_VELOCITIES => {
                    if !pack_velocities {
                        continue;
                    }
                    let data = pack_rows(n, |i| self.atom_data[i].velocity().unwrap_or([0.0; 3]));
                    self.velocities = store_rows(dt.velocities, n, data).into();
                }
                SECTION_FORCES => {
                    if !pack_forces {
                        continue;
                    }
                    let data = pack_rows(n, |i| self.atom_data[i].force().unwrap_or([0.0; 3]));
                    self.forces = store_rows(dt.forces, n, data).into();
                }
                SECTION_ENERGIES => {
                    let data = pack_col(n, |i| self.atom_data[i].energy().unwrap_or(0.0));
                    self.atom_energies = store_col(dt.energies, n, data).into();
                }
                SECTION_CHARGES => {
                    let data = pack_col(n, |i| self.atom_data[i].charge().unwrap_or(0.0));
                    self.charges = store_col(dt.energies, n, data).into();
                }
                SECTION_SPINS => {
                    let data = pack_col(n, |i| self.atom_data[i].spin().unwrap_or(0.0));
                    self.spins = store_col(dt.energies, n, data).into();
                }
                SECTION_MAGMOMS => {
                    let data = pack_rows(n, |i| self.atom_data[i].magmom().unwrap_or([0.0; 3]));
                    self.magmoms = store_rows(dt.forces, n, data).into();
                }
                SECTION_DISPLACEMENTS => {
                    let data =
                        pack_rows(n, |i| self.atom_data[i].displacement().unwrap_or([0.0; 3]));
                    self.displacements = store_rows(dt.forces, n, data).into();
                }
                SECTION_SPREADS => {
                    let data = pack_rows(n, |i| self.atom_data[i].spread().unwrap_or([0.0; 3]));
                    self.spreads = store_rows(dt.forces, n, data).into();
                }
                _ => {}
            }
        }
        self.bind_section_slots(&bound);
    }

    /// After section parsers mutate AoS only, allocate/fill SoA **sections**
    /// (velocities/forces/energies) and atom_ids. Positions are **not** rewritten
    /// when `positions.nrows() == n` already (SoA-primary coordinate parse).
    /// Call this after editing atoms in place. The frame iterator fills parsed
    /// sections from one flat buffer per present section instead.
    pub fn sync_arrays_from_atom_data(&mut self) {
        let n = self.atom_data.len();
        if n == 0 {
            return;
        }
        // Replacing a column drops the allocation the slots address, and a
        // row store into a shared column copies it first.
        let bound = self.materialise_section_slots();
        use crate::storage_dtype::{FloatArray1, FloatArray2};
        let dt = self.header.metadata.dtypes();
        let has_vel = self.atom_data.iter().any(|a| a.has_velocity());
        let has_frc = self.atom_data.iter().any(|a| a.has_forces());
        let has_eng = self.atom_data.iter().any(|a| a.has_energy());
        let has_chg = self.atom_data.iter().any(|a| a.has_charge());
        let has_spn = self.atom_data.iter().any(|a| a.has_spin());
        let has_mm = self.atom_data.iter().any(|a| a.has_magmom());
        let has_dsp = self.atom_data.iter().any(|a| a.has_displacement());
        let has_spr = self.atom_data.iter().any(|a| a.has_spread());
        // The column is the coordinate store. A length change keeps the
        // rows that still have an atom and leaves a new row at zero.
        if self.positions.nrows() != n {
            let mut next = FloatArray2::zeros(dt.positions, n, 3);
            let keep = self.positions.nrows().min(n);
            for i in 0..keep {
                next.set_f64_row(i, self.positions.as_f64_row(i));
            }
            self.positions = next;
        }
        if has_vel {
            if self.velocities.nrows() != n {
                self.velocities = FloatArray2::zeros(dt.velocities, n, 3).into();
            }
        } else if self.velocities.nrows() != 0 {
            self.velocities = FloatArray2::zeros(dt.velocities, 0, 3).into();
        }
        if has_frc {
            if self.forces.nrows() != n {
                self.forces = FloatArray2::zeros(dt.forces, n, 3).into();
            }
        } else if self.forces.nrows() != 0 {
            self.forces = FloatArray2::zeros(dt.forces, 0, 3).into();
        }
        if has_eng {
            if self.atom_energies.len() != n {
                self.atom_energies = FloatArray1::zeros(dt.energies, n).into();
            }
        } else if !self.atom_energies.is_empty() {
            self.atom_energies = FloatArray1::zeros(dt.energies, 0).into();
        }
        if has_chg {
            if self.charges.len() != n {
                self.charges = FloatArray1::zeros(dt.energies, n).into();
            }
        } else if !self.charges.is_empty() {
            self.charges = FloatArray1::zeros(dt.energies, 0).into();
        }
        if has_spn {
            if self.spins.len() != n {
                self.spins = FloatArray1::zeros(dt.energies, n).into();
            }
        } else if !self.spins.is_empty() {
            self.spins = FloatArray1::zeros(dt.energies, 0).into();
        }
        if has_mm {
            if self.magmoms.nrows() != n {
                self.magmoms = FloatArray2::zeros(dt.forces, n, 3).into();
            }
        } else if self.magmoms.nrows() != 0 {
            self.magmoms = FloatArray2::zeros(dt.forces, 0, 3).into();
        }
        if has_dsp {
            if self.displacements.nrows() != n {
                self.displacements = FloatArray2::zeros(dt.forces, n, 3).into();
            }
        } else if self.displacements.nrows() != 0 {
            self.displacements = FloatArray2::zeros(dt.forces, 0, 3).into();
        }
        if has_spr {
            if self.spreads.nrows() != n {
                self.spreads = FloatArray2::zeros(dt.forces, n, 3).into();
            }
        } else if self.spreads.nrows() != 0 {
            self.spreads = FloatArray2::zeros(dt.forces, 0, 3).into();
        }
        if self.atom_ids.len() != n {
            self.atom_ids = ndarray::ArcArray1::<u64>::zeros(n);
        }
        for (i, a) in self.atom_data.iter().enumerate() {
            self.atom_ids[i] = a.atom_id;
            if has_vel && let Some(v) = a.velocity() {
                self.velocities.set_f64_row(i, v);
            }
            if has_frc && let Some(f) = a.force() {
                self.forces.set_f64_row(i, f);
            }
            if has_eng {
                self.atom_energies.set_f64(i, a.energy().unwrap_or(0.0));
            }
            if has_chg {
                self.charges.set_f64(i, a.charge().unwrap_or(0.0));
            }
            if has_spn {
                self.spins.set_f64(i, a.spin().unwrap_or(0.0));
            }
            if has_mm && let Some(m) = a.magmom() {
                self.magmoms.set_f64_row(i, m);
            }
            if has_dsp && let Some(d) = a.displacement() {
                self.displacements.set_f64_row(i, d);
            }
            if has_spr && let Some(d) = a.spread() {
                self.spreads.set_f64_row(i, d);
            }
        }
        self.bind_section_slots(&bound);
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
        if self.atom_energies.is_empty() {
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
    pub fn has_charges(&self) -> bool {
        self.charges.len() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_charge())
    }

    pub fn has_spins(&self) -> bool {
        self.spins.len() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_spin())
    }

    pub fn has_magmoms(&self) -> bool {
        self.magmoms.nrows() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_magmom())
    }

    pub fn has_displacements(&self) -> bool {
        self.displacements.nrows() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_displacement())
    }

    pub fn has_spreads(&self) -> bool {
        self.spreads.nrows() == self.positions.nrows() && self.positions.nrows() > 0
            || self.atom_data.first().is_some_and(|a| a.has_spread())
    }

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
        let mut idx = FxHashMap::with_capacity_and_hasher(self.atom_data.len(), Default::default());
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
/// Atoms are accumulated and grouped by symbol on [`ConFrameBuilder::build`]
/// to compute the header fields (`natm_types`, `natms_per_type`,
/// `masses_per_type`). CON cannot represent an interleaved type layout, so
/// insertion order is not preserved; [`AtomDatum::atom_id`] is the recovery
/// path, and [`ConFrameBuilder::build_with_permutation`] returns the
/// insertion-to-grouped map.
///
/// # Example
///
/// ```
/// use readcon_core::types::ConFrameBuilder;
///
/// let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
/// builder.add_atom("Cu", 0.0, 0.0, 0.0, [true, true, true], 0, 63.546);
/// builder.add_atom("H", 1.0, 2.0, 3.0, [false, false, false], 1, 1.008);
/// let frame = builder.build().unwrap();
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
    /// `(N,) f64` when has_charges, else `(0,)`.
    charges: ndarray::ArcArray1<f64>,
    has_charges: bool,
    /// `(N,) f64` when has_spins, else `(0,)`.
    spins: ndarray::ArcArray1<f64>,
    has_spins: bool,
    /// `(N, 3) f64` when has_magmoms, else `(0, 3)`.
    magmoms: ndarray::ArcArray2<f64>,
    has_magmoms: bool,
    /// `(N, 3) f64` when has_displacements, else `(0, 3)`.
    displacements: ndarray::ArcArray2<f64>,
    has_displacements: bool,
    /// `(N, 3) f64` when has_spreads, else `(0, 3)`.
    spreads: ndarray::ArcArray2<f64>,
    has_spreads: bool,

    metadata: BTreeMap<String, serde_json::Value>,
    minor_raw: Option<String>,
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
            charges: ndarray::ArcArray1::<f64>::zeros(0),
            has_charges: false,
            spins: ndarray::ArcArray1::<f64>::zeros(0),
            has_spins: false,
            magmoms: ndarray::ArcArray2::<f64>::zeros((0, 3)),
            has_magmoms: false,
            displacements: ndarray::ArcArray2::<f64>::zeros((0, 3)),
            has_displacements: false,
            spreads: ndarray::ArcArray2::<f64>::zeros((0, 3)),
            has_spreads: false,
            metadata: BTreeMap::new(),
            minor_raw: None,
        }
    }
}

impl ConFrameBuilder {
    /// Absolute mass difference allowed between atoms of the same CON type.
    ///
    /// CON line 9 stores one mass per type. [`Self::build_with_permutation`]
    /// rejects a later atom of an already-seen symbol whose mass differs
    /// from the first of that type by more than this value.
    pub const TYPE_MASS_ABS_TOL: f64 = 1e-8;

    /// Creates a new builder with the given cell dimensions and angles.
    ///
    /// In-memory SoA on [`Self::build`] defaults to float64 unless
    /// [`Self::storage_dtypes`] / metadata `storage_dtypes` requests otherwise.
    ///
    /// A NaN or infinite cell is not refused here, because this constructor
    /// cannot fail. [`Self::build`] and [`Self::build_with_permutation`]
    /// refuse it. Use [`Self::try_new`] to find out at construction.
    pub fn new(cell: [f64; 3], angles: [f64; 3]) -> Self {
        Self {
            cell,
            angles,
            ..Self::default()
        }
    }

    /// [`Self::new`] that refuses a cell with a NaN or infinite component.
    ///
    /// # Errors
    ///
    /// [`ParseError::NonFiniteValue`] naming the field, `cell[i]` or
    /// `angles[i]`.
    pub fn try_new(cell: [f64; 3], angles: [f64; 3]) -> Result<Self, ParseError> {
        check_cell_finite(&cell, "cell", &angles, "angles")?;
        Ok(Self::new(cell, angles))
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
    pub fn storage_dtypes(&mut self, dtypes: crate::storage_dtype::StorageDtypes) -> &mut Self {
        dtypes.insert_into(&mut self.metadata);
        self
    }

    /// Convenience: allocate positions (and other float fields if still default)
    /// as float32 in memory on the next [`Self::build`].
    pub fn storage_float32_positions(&mut self) -> &mut Self {
        let mut d =
            crate::storage_dtype::StorageDtypes::from_metadata(&self.metadata).unwrap_or_default();
        d.positions = crate::storage_dtype::FloatStorageKind::Float32;
        self.storage_dtypes(d)
    }

    /// Adds extra key-value pairs to the JSON metadata line.
    /// The `con_spec_version` key is always set automatically.
    pub fn metadata(&mut self, m: BTreeMap<String, serde_json::Value>) -> &mut Self {
        self.metadata = m;
        self.minor_raw = None;
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
        let (object, minor_raw) = crate::parser::parse_metadata_object_with_raw(metadata_json)?;
        self.metadata.clear();
        for (key, value) in object {
            if key == meta::CON_SPEC_VERSION || key == meta::SECTIONS {
                continue;
            }
            self.metadata.insert(key, value);
        }
        self.minor_raw = minor_raw;
        Ok(())
    }

    /// Sets `metadata["units"]` from a JSON object.
    ///
    /// Aliases are rewritten to preferred names. The natural time spelling
    /// `(amu*angstrom^2/eV)^0.5` is kept byte for byte (CON-units.5, D10).
    /// This is the builder entry that C and C++ call. [`FrameHeader::set_units`]
    /// is the same contract on a frame that already exists.
    pub fn set_units(&mut self, units: serde_json::Value) -> Result<(), crate::error::ParseError> {
        let stored = crate::units::canonicalize_units_object(&units)
            .map_err(|err| crate::error::ParseError::InvalidUnits(err.to_string()))?;
        self.metadata.insert(meta::UNITS.into(), stored);
        Ok(())
    }

    /// Sets `con_spec_minor` for the frame this builder will write.
    ///
    /// [`Self::build`] stamps [`crate::CON_SPEC_MINOR`] (1) when this has
    /// not been called and the key is absent. The writer does not invent
    /// or replace the minor (D15).
    pub fn set_con_spec_minor(&mut self, minor: u32) -> &mut Self {
        self.metadata
            .insert(meta::CON_SPEC_MINOR.into(), serde_json::Value::from(minor));
        self.minor_raw = None;
        self
    }

    /// Sets `con_spec_minor` from a decimal integer string (including values > `u64::MAX`
    /// accepted by `serde_json`).
    pub fn set_con_spec_minor_str(&mut self, digits: &str) -> Result<&mut Self, ParseError> {
        if !crate::parser::is_nonneg_decimal_int(digits) {
            return Err(ParseError::InvalidMetadataJson(
                "con_spec_minor must be a JSON integer >= 0".into(),
            ));
        }
        match digits.parse::<u64>() {
            Ok(v) => {
                self.metadata
                    .insert(meta::CON_SPEC_MINOR.into(), serde_json::Value::from(v));
                self.minor_raw = None;
            }
            Err(_) => {
                if let Err(e) = serde_json::from_str::<serde_json::Number>(digits) {
                    return Err(ParseError::InvalidMetadataJson(e.to_string()));
                }
                self.metadata.insert(
                    meta::CON_SPEC_MINOR.into(),
                    serde_json::Value::from(SATURATED_SPEC_MINOR),
                );
                self.minor_raw = Some(digits.to_string());
            }
        }
        Ok(self)
    }

    /// Sets a numeric metadata key.
    pub fn set_scalar_metadata(&mut self, key: &str, value: f64) -> &mut Self {
        if key == meta::CON_SPEC_MINOR {
            self.minor_raw = None;
        }
        self.metadata
            .insert(key.to_string(), serde_json::Value::from(value));
        self
    }

    /// Sets a string metadata key.
    pub fn set_string_metadata(&mut self, key: &str, value: &str) -> &mut Self {
        if key == meta::CON_SPEC_MINOR {
            self.minor_raw = None;
        }
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
        let mut bonds = bonds_from_metadata_value(self.metadata.get(meta::BONDS));
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
        if self.has_charges {
            arc_push_f64_1d(&mut self.charges, 0.0);
        }
        if self.has_spins {
            arc_push_f64_1d(&mut self.spins, 0.0);
        }
        if self.has_magmoms {
            arc_push_row(&mut self.magmoms, array![0.0, 0.0, 0.0].view());
        }
        if self.has_displacements {
            arc_push_row(&mut self.displacements, array![0.0, 0.0, 0.0].view());
        }
        if self.has_spreads {
            arc_push_row(&mut self.spreads, array![0.0, 0.0, 0.0].view());
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

    /// Attaches a per-atom charge to the most recently added atom.
    pub fn with_charge(&mut self, charge: f64) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_charges {
            self.charges = ndarray::ArcArray1::<f64>::zeros(n);
            self.has_charges = true;
        }
        self.charges[n - 1] = charge;
        self
    }

    /// Attaches a per-atom spin to the most recently added atom.
    pub fn with_spin(&mut self, spin: f64) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_spins {
            self.spins = ndarray::ArcArray1::<f64>::zeros(n);
            self.has_spins = true;
        }
        self.spins[n - 1] = spin;
        self
    }

    /// Attaches a per-atom magnetic moment to the most recently added atom.
    pub fn with_magmom(&mut self, magmom: [f64; 3]) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_magmoms {
            self.magmoms = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_magmoms = true;
        }
        let mut row = self.magmoms.row_mut(n - 1);
        row[0] = magmom[0];
        row[1] = magmom[1];
        row[2] = magmom[2];
        self
    }

    /// Attaches a per-atom displacement vector (Angstrom) to the most
    /// recently added atom.
    pub fn with_displacement(&mut self, displacement: [f64; 3]) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_displacements {
            self.displacements = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_displacements = true;
        }
        let mut row = self.displacements.row_mut(n - 1);
        row[0] = displacement[0];
        row[1] = displacement[1];
        row[2] = displacement[2];
        self
    }

    /// Attaches a per-atom root-mean-square spread (Angstrom) to the most
    /// recently added atom.
    pub fn with_spread(&mut self, spread: [f64; 3]) -> &mut Self {
        let n = self.symbols.len();
        if n == 0 {
            return self;
        }
        if !self.has_spreads {
            self.spreads = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_spreads = true;
        }
        let mut row = self.spreads.row_mut(n - 1);
        row[0] = spread[0];
        row[1] = spread[1];
        row[2] = spread[2];
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

    /// Sets the displacement vector (Angstrom) of an existing atom. The
    /// frame auto-declares a `"displacements"` section on `build()` if any
    /// atom carries a displacement.
    pub fn set_atom_displacement(
        &mut self,
        i: usize,
        displacement: [f64; 3],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_displacements {
            self.displacements = ndarray::ArcArray2::<f64>::zeros((len, 3));
            self.has_displacements = true;
        }
        let mut row = self.displacements.row_mut(i);
        row[0] = displacement[0];
        row[1] = displacement[1];
        row[2] = displacement[2];
        Ok(self)
    }

    /// Sets the spread vector (Angstrom) of an existing atom. The
    /// frame auto-declares a `"spreads"` section on `build()` if any
    /// atom carries a spread.
    pub fn set_atom_spread(
        &mut self,
        i: usize,
        spread: [f64; 3],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !spread_row_ok(spread) {
            return Err(invalid_spread(i));
        }
        if !self.has_spreads {
            self.spreads = ndarray::ArcArray2::<f64>::zeros((len, 3));
            self.has_spreads = true;
        }
        let mut row = self.spreads.row_mut(i);
        row[0] = spread[0];
        row[1] = spread[1];
        row[2] = spread[2];
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

    /// Updates the mass of an existing atom. CON line 9 stores one mass
    /// per type. [`Self::build`] keeps the first-encountered mass for a
    /// symbol and returns [`crate::error::ParseError::MassMismatch`] if
    /// later atoms of that symbol disagree.
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
    pub fn clear_atom_velocity(&mut self, i: usize) -> Result<&mut Self, crate::error::ParseError> {
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
    pub fn clear_atom_force(&mut self, i: usize) -> Result<&mut Self, crate::error::ParseError> {
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

    /// Removes displacement data from an existing atom by zeroing the slot.
    pub fn clear_atom_displacement(
        &mut self,
        i: usize,
    ) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if self.has_displacements {
            let mut row = self.displacements.row_mut(i);
            row[0] = 0.0;
            row[1] = 0.0;
            row[2] = 0.0;
        }
        Ok(self)
    }

    /// Removes spread data from an existing atom by zeroing the slot.
    pub fn clear_atom_spread(&mut self, i: usize) -> Result<&mut Self, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if self.has_spreads {
            let mut row = self.spreads.row_mut(i);
            row[0] = 0.0;
            row[1] = 0.0;
            row[2] = 0.0;
        }
        Ok(self)
    }

    /// Removes per-atom energy data from an existing atom by zeroing the slot.
    pub fn clear_atom_energy(&mut self, i: usize) -> Result<&mut Self, crate::error::ParseError> {
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

    /// Drops the displacements section entirely.
    pub fn clear_displacements_section(&mut self) -> &mut Self {
        self.displacements = ndarray::ArcArray2::<f64>::zeros((0, 3));
        self.has_displacements = false;
        self
    }

    /// Drops the spreads section entirely.
    pub fn clear_spreads_section(&mut self) -> &mut Self {
        self.spreads = ndarray::ArcArray2::<f64>::zeros((0, 3));
        self.has_spreads = false;
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

    /// Bulk-update displacements (Angstrom) for every atom from a flat
    /// buffer of length `3 * atom_count()`. Auto-declares a
    /// `"displacements"` section on `build()`.
    pub fn set_displacements_from_flat(
        &mut self,
        displacements: &[f64],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let n = self.symbols.len();
        if displacements.len() != 3 * n {
            return Err(crate::error::ParseError::InvalidVectorLength {
                expected: 3 * n,
                found: displacements.len(),
            });
        }
        if !self.has_displacements {
            self.displacements = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_displacements = true;
        }
        let dst = self
            .displacements
            .as_slice_memory_order_mut()
            .expect("displacements standard layout invariant violated");
        dst.copy_from_slice(displacements);
        Ok(self)
    }

    /// Bulk-update spreads (Angstrom) for every atom from a flat
    /// buffer of length `3 * atom_count()`. Auto-declares a
    /// `"spreads"` section on `build()`.
    pub fn set_spreads_from_flat(
        &mut self,
        spreads: &[f64],
    ) -> Result<&mut Self, crate::error::ParseError> {
        let n = self.symbols.len();
        if spreads.len() != 3 * n {
            return Err(crate::error::ParseError::InvalidVectorLength {
                expected: 3 * n,
                found: spreads.len(),
            });
        }
        for (i, chunk) in spreads.as_chunks::<3>().0.iter().enumerate() {
            let row = [chunk[0], chunk[1], chunk[2]];
            if !spread_row_ok(row) {
                return Err(invalid_spread(i));
            }
        }
        if !self.has_spreads {
            self.spreads = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_spreads = true;
        }
        let dst = self
            .spreads
            .as_slice_memory_order_mut()
            .expect("spreads standard layout invariant violated");
        dst.copy_from_slice(spreads);
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
    pub fn get_atom_position(&self, i: usize) -> Result<(f64, f64, f64), crate::error::ParseError> {
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
    pub fn get_atom_force(&self, i: usize) -> Result<Option<[f64; 3]>, crate::error::ParseError> {
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

    /// Read-only accessor: displacement of atom `i`, if any.
    pub fn get_atom_displacement(
        &self,
        i: usize,
    ) -> Result<Option<[f64; 3]>, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_displacements {
            return Ok(None);
        }
        let row = self.displacements.row(i);
        Ok(Some([row[0], row[1], row[2]]))
    }

    /// Read-only accessor: spread of atom `i`, if any.
    pub fn get_atom_spread(&self, i: usize) -> Result<Option<[f64; 3]>, crate::error::ParseError> {
        let len = self.symbols.len();
        if i >= len {
            return Err(crate::error::ParseError::IndexOutOfBounds { index: i, len });
        }
        if !self.has_spreads {
            return Ok(None);
        }
        let row = self.spreads.row(i);
        Ok(Some([row[0], row[1], row[2]]))
    }

    /// Read-only accessor: per-atom energy of atom `i`, if any.
    pub fn get_atom_energy(&self, i: usize) -> Result<Option<f64>, crate::error::ParseError> {
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

    /// Row-major displacements slice if the section is populated, else
    /// an empty slice.
    pub fn displacements(&self) -> &[f64] {
        if self.has_displacements {
            self.displacements
                .as_slice_memory_order()
                .expect("displacements standard layout invariant violated")
        } else {
            &[]
        }
    }

    /// Mutable displacements slice. Auto-allocates the section if needed.
    pub fn displacements_mut(&mut self) -> &mut [f64] {
        if !self.has_displacements {
            let n = self.symbols.len();
            self.displacements = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_displacements = true;
        }
        self.displacements
            .as_slice_memory_order_mut()
            .expect("displacements standard layout invariant violated")
    }

    /// Typed 2D `(N, 3) f64` view onto displacements.
    pub fn displacements_view(&self) -> ndarray::ArrayView2<'_, f64> {
        self.displacements.view()
    }

    /// Row-major spreads slice if the section is populated, else
    /// an empty slice.
    pub fn spreads(&self) -> &[f64] {
        if self.has_spreads {
            self.spreads
                .as_slice_memory_order()
                .expect("spreads standard layout invariant violated")
        } else {
            &[]
        }
    }

    /// Mutable spreads slice. Auto-allocates the section if needed.
    pub fn spreads_mut(&mut self) -> &mut [f64] {
        if !self.has_spreads {
            let n = self.symbols.len();
            self.spreads = ndarray::ArcArray2::<f64>::zeros((n, 3));
            self.has_spreads = true;
        }
        self.spreads
            .as_slice_memory_order_mut()
            .expect("spreads standard layout invariant violated")
    }

    /// Typed 2D `(N, 3) f64` view onto spreads.
    pub fn spreads_view(&self) -> ndarray::ArrayView2<'_, f64> {
        self.spreads.view()
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
    /// Crate-internal `&Array2<f64>` displacements ref.
    pub fn displacements_2d_ref(&self) -> &ndarray::ArcArray2<f64> {
        &self.displacements
    }
    /// Crate-internal `&Array2<f64>` spreads ref.
    pub fn spreads_2d_ref(&self) -> &ndarray::ArcArray2<f64> {
        &self.spreads
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

    /// Whether the builder currently has a displacements section populated.
    pub fn has_displacements_section(&self) -> bool {
        self.has_displacements
    }

    /// Whether the builder currently has a spreads section populated.
    pub fn has_spreads_section(&self) -> bool {
        self.has_spreads
    }

    /// Whether the builder currently has a per-atom energies section populated.
    pub fn has_energies_section(&self) -> bool {
        self.has_energies
    }

    // ----- end in-place mutation API ----------------------------------------

    /// Consumes the builder and produces a `ConFrame`.
    ///
    /// CON groups atoms by type (symbol, first-encounter order) so the
    /// returned frame's `atom_data` order is not the insertion order.
    /// `atom_id` (column 5) is the recovery path for the original index.
    /// Use [`Self::build_with_permutation`] when a parallel array must
    /// be remapped with the insertion-to-grouped index map.
    ///
    /// Atoms of the same symbol must share one mass (CON line 9). A
    /// mismatch beyond [`Self::TYPE_MASS_ABS_TOL`] returns
    /// [`crate::error::ParseError::MassMismatch`].
    ///
    /// # Errors
    ///
    /// Returns [`crate::error::ParseError::MassMismatch`] when two atoms
    /// share a symbol and their masses differ by more than
    /// [`Self::TYPE_MASS_ABS_TOL`].
    pub fn build(self) -> Result<ConFrame, crate::error::ParseError> {
        self.build_with_permutation().map(|(frame, _perm)| frame)
    }

    /// Consumes the builder and produces a `ConFrame` plus the
    /// insertion-to-grouped index map.
    ///
    /// CON groups atoms by type (symbol, first-encounter order). The
    /// returned `Vec<usize>` has length `N` (insertion count) and
    /// `perm[i]` is the index of insertion-`i` in the built
    /// `frame.atom_data`. Insertion order is not preserved; `atom_id`
    /// is the on-disk recovery path for the same mapping.
    ///
    /// # Errors
    ///
    /// Returns [`crate::error::ParseError::MassMismatch`] when two atoms
    /// share a symbol and their masses differ by more than
    /// [`Self::TYPE_MASS_ABS_TOL`]. CON line 9 stores one mass per type.
    ///
    /// Returns [`crate::error::ParseError::NonFiniteValue`] when a cell
    /// length or angle is NaN or infinite. The message names the field
    /// (`cell[i]` or `angles[i]`), and the frame when the builder has a
    /// `frame_index`.
    pub fn build_with_permutation(
        self,
    ) -> Result<(ConFrame, Vec<usize>), crate::error::ParseError> {
        if let Err(err) = check_cell_finite(&self.cell, "cell", &self.angles, "angles") {
            let frame = self
                .metadata
                .get(meta::FRAME_INDEX)
                .and_then(serde_json::Value::as_u64);
            return Err(match frame {
                Some(frame) => err.in_frame(frame),
                None => err,
            });
        }
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
                    let first = type_masses[idx];
                    if (mass - first).abs() > Self::TYPE_MASS_ABS_TOL {
                        return Err(crate::error::ParseError::MassMismatch {
                            symbol: symbol.clone(),
                            first_mass: first,
                            found_mass: mass,
                            atom_index: i,
                        });
                    }
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
        let has_chg = self.has_charges;
        let has_spn = self.has_spins;
        let has_mag = self.has_magmoms;
        let has_dsp = self.has_displacements;
        let has_spr = self.has_spreads;

        let mut atom_data: Vec<AtomDatum> = Vec::with_capacity(n);
        let mut insertion_to_grouped = vec![0usize; n];
        for (type_idx, indices) in buckets.iter().enumerate() {
            let symbol = &type_symbols[type_idx];
            for &i in indices {
                insertion_to_grouped[i] = atom_data.len();
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
                let charge = if has_chg { Some(self.charges[i]) } else { None };
                let spin = if has_spn { Some(self.spins[i]) } else { None };
                let magmom = if has_mag {
                    let r = self.magmoms.row(i);
                    Some([r[0], r[1], r[2]])
                } else {
                    None
                };
                let displacement = if has_dsp {
                    let r = self.displacements.row(i);
                    Some([r[0], r[1], r[2]])
                } else {
                    None
                };
                let spread = if has_spr {
                    let r = self.spreads.row(i);
                    let row = [r[0], r[1], r[2]];
                    if !spread_row_ok(row) {
                        return Err(invalid_spread(i));
                    }
                    Some(row)
                } else {
                    None
                };
                atom_data.push(AtomDatum::with_sections(
                    Arc::clone(symbol),
                    pos[0],
                    pos[1],
                    pos[2],
                    self.fixed[i],
                    self.atom_ids[i],
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
        if has_chg {
            sections.push(SECTION_CHARGES.into());
        }
        if has_spn {
            sections.push(SECTION_SPINS.into());
        }
        if has_mag {
            sections.push(SECTION_MAGMOMS.into());
        }
        if has_dsp {
            sections.push(SECTION_DISPLACEMENTS.into());
        }
        if has_spr {
            sections.push(SECTION_SPREADS.into());
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
        // The builder, not the writer, stamps minor 1 on a v3 frame when
        // the caller did not call set_con_spec_minor (D15).
        if crate::CON_SPEC_VERSION >= 3 && !metadata.contains_key(meta::CON_SPEC_MINOR) {
            metadata.insert(
                meta::CON_SPEC_MINOR.into(),
                serde_json::Value::from(crate::CON_SPEC_MINOR),
            );
        }
        use crate::storage_dtype::{FloatArray1, FloatArray2, StorageDtypes};
        let dt = StorageDtypes::from_metadata(&metadata).unwrap_or_default();
        // Allocate SoA in the requested storage dtypes (not f64-then-cast).
        let mut pos = FloatArray2::zeros(dt.positions, n, 3);
        let mut vel = FloatArray2::zeros(dt.velocities, if has_vel { n } else { 0 }, 3);
        let mut frc = FloatArray2::zeros(dt.forces, if has_frc { n } else { 0 }, 3);
        let mut eng = FloatArray1::zeros(dt.energies, if has_eng { n } else { 0 });
        let mut chg = FloatArray1::zeros(dt.energies, if has_chg { n } else { 0 });
        let mut spn = FloatArray1::zeros(dt.energies, if has_spn { n } else { 0 });
        let mut mag = FloatArray2::zeros(dt.forces, if has_mag { n } else { 0 }, 3);
        let mut dsp = FloatArray2::zeros(dt.forces, if has_dsp { n } else { 0 }, 3);
        let mut spr = FloatArray2::zeros(dt.forces, if has_spr { n } else { 0 }, 3);
        let mut masses_arr = FloatArray1::zeros(dt.masses, n);
        let mut ids_arr = ndarray::ArcArray1::<u64>::zeros(n);
        if dt != StorageDtypes::all_f64() {
            dt.insert_into(&mut metadata);
        }
        // `atom_data` is grouped. `self.positions` is still insertion
        // order, so copy the row that landed in each grouped slot.
        let mut from_insertion = vec![0usize; n];
        for (insertion, &grouped) in insertion_to_grouped.iter().enumerate() {
            from_insertion[grouped] = insertion;
        }
        for (i, a) in atom_data.iter().enumerate() {
            let row = self.positions.row(from_insertion[i]);
            pos.set_f64_row(i, [row[0], row[1], row[2]]);
            ids_arr[i] = a.atom_id;
            if has_vel && let Some(v) = a.velocity() {
                vel.set_f64_row(i, v);
            }
            if has_frc && let Some(f) = a.force() {
                frc.set_f64_row(i, f);
            }
            if has_eng {
                eng.set_f64(i, a.energy().unwrap_or(0.0));
            }
            if has_chg {
                chg.set_f64(i, a.charge().unwrap_or(0.0));
            }
            if has_spn {
                spn.set_f64(i, a.spin().unwrap_or(0.0));
            }
            if has_mag && let Some(m) = a.magmom() {
                mag.set_f64_row(i, m);
            }
            if has_dsp && let Some(d) = a.displacement() {
                dsp.set_f64_row(i, d);
            }
            if has_spr && let Some(d) = a.spread() {
                spr.set_f64_row(i, d);
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
            metadata: FrameMeta::from_map_with_minor_raw(metadata, self.minor_raw.as_deref()),
            sections,
            strict_validation,
            sections_declared,
        };

        Ok((
            ConFrame {
                header,
                atom_data,
                column_tails: Vec::new(),
                sequential_plain: false,
                positions: pos,
                velocities: vel.into(),
                forces: frc.into(),
                atom_energies: eng.into(),
                charges: chg.into(),
                spins: spn.into(),
                magmoms: mag.into(),
                displacements: dsp.into(),
                spreads: spr.into(),
                masses: masses_arr,
                atom_ids: ids_arr,
            },
            insertion_to_grouped,
        ))
    }
}

fn pack_rows(n: usize, mut one: impl FnMut(usize) -> [f64; 3]) -> Vec<f64> {
    let mut data = Vec::with_capacity(n.saturating_mul(3));
    for i in 0..n {
        let row = one(i);
        data.extend_from_slice(&row);
    }
    data
}

fn pack_col(n: usize, mut one: impl FnMut(usize) -> f64) -> Vec<f64> {
    let mut data = Vec::with_capacity(n);
    for i in 0..n {
        data.push(one(i));
    }
    data
}

fn store_rows(
    kind: crate::storage_dtype::ElementKind,
    n: usize,
    data: Vec<f64>,
) -> crate::storage_dtype::FloatArray2 {
    use crate::storage_dtype::{ElementKind, FloatArray2};
    if kind == ElementKind::Float64 {
        return FloatArray2::from_f64_row_major(n, 3, data);
    }
    let mut arr = FloatArray2::zeros(kind, n, 3);
    for i in 0..n {
        let o = i * 3;
        arr.set_f64_row(i, [data[o], data[o + 1], data[o + 2]]);
    }
    arr
}

fn store_col(
    kind: crate::storage_dtype::ElementKind,
    n: usize,
    data: Vec<f64>,
) -> crate::storage_dtype::FloatArray1 {
    use crate::storage_dtype::{ElementKind, FloatArray1};
    if kind == ElementKind::Float64 {
        return FloatArray1::from_f64_vec(data);
    }
    let mut arr = FloatArray1::zeros(kind, n);
    for (i, value) in data.iter().copied().enumerate() {
        arr.set_f64(i, value);
    }
    arr
}

/// Build a [`ConFrame`] from header + AoS atoms, filling SoA numeric arrays.
/// Prefer [`con_frame_from_atom_data_with_positions`] on the CON parse hot path
/// when positions were already written into SoA during coordinate parsing.
pub fn con_frame_from_atom_data(
    header: FrameHeader,
    atom_data: Vec<AtomDatum>,
    coords: &[[f64; 3]],
) -> ConFrame {
    let n = atom_data.len();
    use crate::storage_dtype::FloatArray2;
    let dt = header.metadata.dtypes();
    let mut pos = FloatArray2::zeros(dt.positions, n, 3);
    for (i, row) in coords.iter().enumerate().take(n) {
        pos.set_f64_row(i, *row);
    }
    con_frame_from_atom_data_with_positions(header, atom_data, pos)
}

/// Coords-only frame assembly (the common `.con` path after coordinate parse,
/// before optional velocity/force sections).
///
/// Design (profile-driven): positions are already filled; **do not** O(N)-scan
/// for optional sections; expand per-type masses with a run-length `fill` into a
/// flat buffer (one Arc wrap); copy `atom_id` into a plain `Vec` then share once.
/// Section SoA is left empty — callers that attach velocities/forces must run
/// [`ConFrame::sync_arrays_from_atom_data`] afterward.
pub fn con_frame_coords_only(
    header: FrameHeader,
    atom_data: Vec<AtomDatum>,
    positions: crate::storage_dtype::FloatArray2,
) -> ConFrame {
    let n = atom_data.len();
    let mut ids = Vec::with_capacity(n);
    for a in &atom_data {
        ids.push(a.atom_id);
    }
    con_frame_coords_only_with_ids(header, atom_data, positions, ids)
}

/// [`con_frame_coords_only`] with ids already collected during the coordinate scan.
pub(crate) fn con_frame_coords_only_with_ids(
    header: FrameHeader,
    atom_data: Vec<AtomDatum>,
    positions: crate::storage_dtype::FloatArray2,
    ids: Vec<u64>,
) -> ConFrame {
    let n = atom_data.len();
    debug_assert_eq!(positions.nrows(), n);
    debug_assert_eq!(ids.len(), n);
    use crate::storage_dtype::{FloatArray1, FloatArray2, StorageDtypes};
    let dt = header.metadata.dtypes();

    let mass_flat = if header.natms_per_type.len() == 1 && header.natms_per_type[0] == n {
        let mass = header.masses_per_type.first().copied().unwrap_or(0.0);
        vec![mass; n]
    } else {
        let mut mass_flat = Vec::with_capacity(n);
        for (ti, &count) in header.natms_per_type.iter().enumerate() {
            let m = header.masses_per_type.get(ti).copied().unwrap_or(0.0);
            let take = count.min(n.saturating_sub(mass_flat.len()));
            mass_flat.extend(std::iter::repeat_n(m, take));
        }
        if mass_flat.len() < n {
            mass_flat.resize(n, 0.0);
        }
        mass_flat
    };
    let masses_arr = if dt.masses == crate::storage_dtype::ElementKind::Float64 {
        FloatArray1::from_f64_vec(mass_flat)
    } else {
        let mut m = FloatArray1::zeros(dt.masses, n);
        for (i, &v) in mass_flat.iter().enumerate() {
            m.set_f64(i, v);
        }
        m
    };

    let ids_arr = ndarray::Array1::from(ids).into_shared();

    let mut header = header;
    if dt != StorageDtypes::all_f64() {
        let mut map = header.metadata.to_map();
        let minor_raw = header.metadata.huge_minor_raw().map(str::to_owned);
        dt.insert_into(&mut map);
        header.metadata = FrameMeta::from_map_with_minor_raw(map, minor_raw.as_deref());
    }
    ConFrame {
        header,
        atom_data,
        column_tails: Vec::new(),
        sequential_plain: crate::parser::take_sequential_plain(),
        positions,
        velocities: FloatArray2::zeros(dt.velocities, 0, 3).into(),
        forces: FloatArray2::zeros(dt.forces, 0, 3).into(),
        atom_energies: FloatArray1::zeros(dt.energies, 0).into(),
        charges: FloatArray1::zeros(dt.energies, 0).into(),
        spins: FloatArray1::zeros(dt.energies, 0).into(),
        magmoms: FloatArray2::zeros(dt.forces, 0, 3).into(),
        displacements: FloatArray2::zeros(dt.forces, 0, 3).into(),
        spreads: FloatArray2::zeros(dt.forces, 0, 3).into(),
        masses: masses_arr,
        atom_ids: ids_arr,
    }
}

/// Like [`con_frame_from_atom_data`], but **reuses** prefilled `positions` SoA
/// (no second O(N) position write). Optional sections still filled from AoS
/// when present; the common coords-only case delegates to [`con_frame_coords_only`].
pub fn con_frame_from_atom_data_with_positions(
    header: FrameHeader,
    atom_data: Vec<AtomDatum>,
    positions: crate::storage_dtype::FloatArray2,
) -> ConFrame {
    let has_vel = atom_data.first().is_some_and(|a| a.has_velocity());
    let has_frc = atom_data.first().is_some_and(|a| a.has_forces());
    let has_eng = atom_data.first().is_some_and(|a| a.has_energy());
    let has_chg = atom_data.first().is_some_and(|a| a.has_charge());
    let has_spn = atom_data.first().is_some_and(|a| a.has_spin());
    let has_mm = atom_data.first().is_some_and(|a| a.has_magmom());
    let has_dsp = atom_data.first().is_some_and(|a| a.has_displacement());
    let has_spr = atom_data.first().is_some_and(|a| a.has_spread());
    if !has_vel && !has_frc && !has_eng && !has_chg && !has_spn && !has_mm && !has_dsp && !has_spr {
        return con_frame_coords_only(header, atom_data, positions);
    }
    let n = atom_data.len();
    debug_assert_eq!(positions.nrows(), n);
    use crate::storage_dtype::{FloatArray1, FloatArray2};
    let dt = header.metadata.dtypes();
    let pos = positions;
    let mut vel = FloatArray2::zeros(dt.velocities, if has_vel { n } else { 0 }, 3);
    let mut frc = FloatArray2::zeros(dt.forces, if has_frc { n } else { 0 }, 3);
    let mut eng = FloatArray1::zeros(dt.energies, if has_eng { n } else { 0 });
    let mut chg = FloatArray1::zeros(dt.energies, if has_chg { n } else { 0 });
    let mut spn = FloatArray1::zeros(dt.energies, if has_spn { n } else { 0 });
    let mut mm = FloatArray2::zeros(dt.forces, if has_mm { n } else { 0 }, 3);
    let mut dsp = FloatArray2::zeros(dt.forces, if has_dsp { n } else { 0 }, 3);
    let mut spr = FloatArray2::zeros(dt.forces, if has_spr { n } else { 0 }, 3);
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
        ids_arr[i] = a.atom_id;
        if has_vel && let Some(v) = a.velocity() {
            vel.set_f64_row(i, v);
        }
        if has_frc && let Some(f) = a.force() {
            frc.set_f64_row(i, f);
        }
        if has_eng {
            eng.set_f64(i, a.energy().unwrap_or(0.0));
        }
        if has_chg {
            chg.set_f64(i, a.charge().unwrap_or(0.0));
        }
        if has_spn {
            spn.set_f64(i, a.spin().unwrap_or(0.0));
        }
        if has_mm && let Some(m) = a.magmom() {
            mm.set_f64_row(i, m);
        }
        if has_dsp && let Some(d) = a.displacement() {
            dsp.set_f64_row(i, d);
        }
        if has_spr && let Some(d) = a.spread() {
            spr.set_f64_row(i, d);
        }
    }
    let mut header = header;
    if dt != crate::storage_dtype::StorageDtypes::all_f64() {
        let mut map = header.metadata.to_map();
        let minor_raw = header.metadata.huge_minor_raw().map(str::to_owned);
        dt.insert_into(&mut map);
        header.metadata = FrameMeta::from_map_with_minor_raw(map, minor_raw.as_deref());
    }
    ConFrame {
        header,
        atom_data,
        column_tails: Vec::new(),
        sequential_plain: false,
        positions: pos,
        velocities: vel.into(),
        forces: frc.into(),
        atom_energies: eng.into(),
        charges: chg.into(),
        spins: spn.into(),
        magmoms: mm.into(),
        displacements: dsp.into(),
        spreads: spr.into(),
        masses: masses_arr,
        atom_ids: ids_arr,
    }
}

// }

impl ConFrame {
    /// Creates a new builder for constructing a `ConFrame`.
    ///
    /// A NaN or infinite cell is refused by the builder's `build`. See
    /// [`Self::try_builder`] to refuse it at once.
    pub fn builder(cell: [f64; 3], angles: [f64; 3]) -> ConFrameBuilder {
        ConFrameBuilder::new(cell, angles)
    }

    /// [`Self::builder`] that refuses a cell with a NaN or infinite component.
    ///
    /// # Errors
    ///
    /// [`ParseError::NonFiniteValue`] naming the field, `cell[i]` or
    /// `angles[i]`.
    pub fn try_builder(cell: [f64; 3], angles: [f64; 3]) -> Result<ConFrameBuilder, ParseError> {
        ConFrameBuilder::try_new(cell, angles)
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

    /// One copper component of `n` atoms, each with its own coordinates.
    fn uniform_frame_text(n: usize) -> String {
        let mut text = String::from(
            "Random Number Seed\n{\"con_spec_version\":2}\n15.0 15.0 15.0\n\
             90.0 90.0 90.0\n0 0\n218 0 1\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            let x = 0.1234567 + i as f64 * 0.01;
            text.push_str(&format!("{x} {} {} 0 {i}\n", x + 1.0, x + 2.0));
        }
        text
    }

    fn bulk_drop_is_marked(atoms: &[AtomDatum]) -> bool {
        SYMBOL_DROP_HINT.with(|hint| {
            let hint = hint.get();
            hint.atoms == atoms.as_ptr() as usize && hint.n == atoms.len()
        })
    }

    /// A successful write fills the per-thread metadata line cache. The
    /// cache must not be reported as a leak when the thread ends.
    #[test]
    fn a_written_frame_releases_the_metadata_line_cache() {
        let frame = crate::iterators::ConFrameIterator::new(&uniform_frame_text(1))
            .next()
            .expect("frame")
            .expect("parse");
        let bytes =
            crate::writer::write_frames_to_vec(std::slice::from_ref(&frame)).expect("write");
        assert!(!bytes.is_empty());
    }

    #[cfg(feature = "python")]
    #[test]
    fn coordinate_snapshot_unwind_does_not_drop_source_fields() {
        let mut first = crate::iterators::ConFrameIterator::new(&uniform_frame_text(1))
            .next()
            .expect("first frame")
            .expect("parse first");
        let mut second = crate::iterators::ConFrameIterator::new(&uniform_frame_text(1))
            .next()
            .expect("second frame")
            .expect("parse second");

        // The second frame's column has no row, so reading it panics after
        // the first view has copied its source fields.
        second.positions = crate::storage_dtype::FloatArray2::zeros_f64(0, 3);

        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = CoordSnapshot::copy_of(&[Some(&first), Some(&second)]);
        }));
        assert!(result.is_err(), "an empty coordinate column should panic");

        // The first source must still own and use all of its fields; without
        // the unwind guard the partial view drops them.
        assert_eq!(first.x_at(0), 0.1234567);
        first.header.prebox_header.user.push_str("still owned");
        drop(first);
        drop(second);
    }

    #[test]
    fn projected_positions_leave_no_atom_in_the_freed_column() {
        // The bulk symbol drop needs 1024 atoms, so a smaller frame never
        // has the hint the projection must clear.
        let text = uniform_frame_text(1100);
        let mut frame = crate::iterators::ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        assert_eq!(frame.atom_data.len(), 1100);
        let symbol = Arc::as_ptr(&frame.atom_data[0].symbol);
        assert!(
            frame
                .atom_data
                .iter()
                .all(|atom| std::ptr::eq(Arc::as_ptr(&atom.symbol), symbol)),
            "the frame should share one symbol"
        );
        for i in 0..frame.atom_data.len() {
            assert_eq!(
                frame.xyz_at(i),
                frame.positions.as_f64_row(i),
                "parsed atom {i} should match its positions row"
            );
        }
        // The piped reader and the chemfiles import mark a buffer like this.
        mark_uniform_symbol_drop(&frame.atom_data);
        assert!(bulk_drop_is_marked(&frame.atom_data));
        let expect: Vec<[f64; 3]> = (0..frame.atom_data.len())
            .map(|i| frame.xyz_at(i).map(|v| v as f32 as f64))
            .collect();
        let dtypes = crate::storage_dtype::StorageDtypes {
            positions: crate::storage_dtype::ElementKind::Float32,
            ..Default::default()
        };
        frame.project_storage_dtypes(&dtypes);
        // Projection may install owned section tails, so the bulk drop is
        // disarmed before the column is replaced.
        assert!(
            !bulk_drop_is_marked(&frame.atom_data),
            "the projection left the bulk drop armed"
        );
        for (i, row) in expect.iter().enumerate() {
            assert_eq!(frame.xyz_at(i), *row, "atom {i}");
            assert_eq!(frame.positions.as_f64_row(i), *row, "row {i}");
        }
    }

    #[test]
    fn resized_atoms_leave_no_atom_in_the_replaced_column() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let mut frame = crate::iterators::ConFrameIterator::new(text)
            .next()
            .expect("frame")
            .expect("parse");
        let coords = |frame: &ConFrame| -> Vec<[f64; 3]> {
            (0..frame.atom_data.len())
                .map(|i| frame.xyz_at(i))
                .collect()
        };
        let mut expect = coords(&frame);
        // Shrinking and growing the atoms both make the sync replace the
        // positions column. A clone carries no coordinates, so the new row
        // is zero until a column write.
        frame.atom_data.pop();
        expect.pop();
        frame.sync_arrays_from_atom_data();
        assert_eq!(coords(&frame), expect);
        let kept = expect[0];
        let extra = frame.atom_data[0].clone();
        frame.atom_data.push(extra);
        expect.push([0.0; 3]);
        frame.sync_arrays_from_atom_data();
        assert_eq!(coords(&frame), expect);
        let last = frame.atom_data.len() - 1;
        frame.set_xyz_at(last, kept);
        expect[last] = kept;
        for (i, row) in expect.iter().enumerate() {
            assert_eq!(frame.positions.as_f64_row(i), *row, "row {i}");
        }
    }

    #[test]
    fn releasing_the_last_counts_drops_the_value() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        struct Counted(Arc<AtomicUsize>);
        impl Drop for Counted {
            fn drop(&mut self) {
                self.0.fetch_add(1, Ordering::SeqCst);
            }
        }
        let n = 2048;
        let drops = Arc::new(AtomicUsize::new(0));
        let value = Arc::new(Counted(Arc::clone(&drops)));
        let weak = Arc::downgrade(&value);
        bump_arc_str(&value, n);
        // The shares stand in for the atoms. The bulk drop gives their counts
        // back in one call instead of dropping each one.
        let mut shares: Vec<Arc<Counted>> = (0..n).map(|_| share_arc_str(&value)).collect();
        drop(value);
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        release_arc_str_count(&shares[0], n);
        unsafe { shares.set_len(0) };
        assert_eq!(drops.load(Ordering::SeqCst), 1, "the value was not dropped");
        assert!(weak.upgrade().is_none());
    }

    #[test]
    fn bulk_symbol_drop_frees_a_symbol_the_atoms_held_last() {
        let n = 2048;
        let symbol: Arc<str> = Arc::from("O");
        let weak = Arc::downgrade(&symbol);
        bump_arc_str(&symbol, n);
        let mut atoms: Vec<AtomDatum> = (0..n)
            .map(|i| AtomDatum::coords(share_arc_str(&symbol), 0.0, 0.0, 0.0, [false; 3], i as u64))
            .collect();
        mark_uniform_symbol_drop(&atoms);
        drop(symbol);
        bulk_drop_uniform_symbols(&mut atoms);
        assert!(atoms.is_empty(), "the bulk path did not run");
        // `releasing_the_last_counts_drops_the_value` shows the release runs
        // the drop.
        assert!(weak.upgrade().is_none());
    }

    #[test]
    fn bulk_symbol_drop_rejects_a_mutated_nonfirst_symbol() {
        let text = uniform_frame_text(2048);
        let mut frame = crate::iterators::ConFrameIterator::new(&text)
            .next()
            .expect("frame")
            .expect("parse");
        mark_uniform_symbol_drop(&frame.atom_data);
        frame.atom_data[2047].symbol = Arc::from("H");

        bulk_drop_uniform_symbols(&mut frame.atom_data);

        assert_eq!(
            frame.atom_data.len(),
            2048,
            "a non-uniform buffer took the bulk drop path"
        );
        assert_eq!(&*frame.atom_data[0].symbol, "Cu");
        assert_eq!(&*frame.atom_data[2047].symbol, "H");
    }

    #[test]
    fn test_x_only_is_one_under_spec_2() {
        assert_eq!(encode_fixed_bitmask([true, false, false]), 1);
        assert_eq!(decode_fixed_bitmask_for_spec(1, 2), [true, false, false]);
        assert_eq!(decode_fixed_bitmask(1), [true, false, false]);
        assert_eq!(decode_fixed_bitmask_for_spec(1, 1), [true, true, true]);
        assert_eq!(decode_fixed_bitmask_for_spec(7, 1), [true, true, true]);
        assert_eq!(encode_fixed_bitmask([true, true, true]), 7);
    }

    #[test]
    fn test_atom_id_index_handles_non_sequential_ids() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 100, 63.546);
        builder.add_atom("Cu", 1.0, 0.0, 0.0, [false, false, false], 42, 63.546);
        builder.add_atom("H", 2.0, 0.0, 0.0, [false, false, false], 7, 1.008);
        let frame = builder.build().unwrap();
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
        let frame = builder.build().unwrap();

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
        let frame = builder.build().unwrap();

        assert!(frame.has_velocities());
        assert_eq!(frame.atom_data[0].velocity(), Some([0.1, 0.2, 0.3]));
    }

    #[test]
    fn test_builder_with_headers() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .prebox_header("line1")
            .postbox_header(["line3".to_string(), "line4".to_string()]);
        let frame = builder.build().unwrap();

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
        let frame = builder.build().unwrap();

        // H appears first, so it should be first type
        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![2, 1]);
        // Atoms should be grouped: H, H, Cu
        assert_eq!(&*frame.atom_data[0].symbol, "H");
        assert_eq!(&*frame.atom_data[1].symbol, "H");
        assert_eq!(&*frame.atom_data[2].symbol, "Cu");
        // Coordinates follow the symbols, not the insertion slots.
        assert_eq!(frame.xyz_at(0), [0.0, 0.0, 0.0]);
        assert_eq!(frame.xyz_at(1), [2.0, 0.0, 0.0]);
        assert_eq!(frame.xyz_at(2), [1.0, 0.0, 0.0]);
    }

    #[test]
    fn test_build_with_permutation_mixed_cu_h() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        // Insertion: Cu, H, Cu, H. Grouped encounter order: Cu, Cu, H, H.
        builder.add_atom("Cu", 0.0, 0.0, 0.0, [false; 3], 10, 63.546);
        builder.add_atom("H", 1.0, 0.0, 0.0, [false; 3], 20, 1.008);
        builder.add_atom("Cu", 2.0, 0.0, 0.0, [false; 3], 30, 63.546);
        builder.add_atom("H", 3.0, 0.0, 0.0, [false; 3], 40, 1.008);
        let (frame, perm) = builder.build_with_permutation().unwrap();

        assert_eq!(perm, vec![0, 2, 1, 3]);
        assert_eq!(
            frame
                .atom_data
                .iter()
                .map(|a| &*a.symbol)
                .collect::<Vec<_>>(),
            vec!["Cu", "Cu", "H", "H"]
        );
        assert_eq!(
            frame
                .atom_data
                .iter()
                .map(|a| a.atom_id)
                .collect::<Vec<_>>(),
            vec![10, 30, 20, 40]
        );
        assert_eq!(
            (0..4).map(|i| frame.xyz_at(i)).collect::<Vec<_>>(),
            vec![
                [0.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [3.0, 0.0, 0.0],
            ]
        );
        for (insertion, &grouped) in perm.iter().enumerate() {
            let expected_id = [10, 20, 30, 40][insertion];
            assert_eq!(frame.atom_data[grouped].atom_id, expected_id);
        }
    }

    #[test]
    fn test_build_mass_mismatch_h_vs_d_same_symbol() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.008);
        builder.add_atom("H", 1.0, 0.0, 0.0, [false; 3], 1, 2.014);
        let err = builder.build_with_permutation().unwrap_err();
        match err {
            crate::error::ParseError::MassMismatch {
                symbol,
                first_mass,
                found_mass,
                atom_index,
            } => {
                assert_eq!(symbol, "H");
                assert!((first_mass - 1.008).abs() < 1e-12);
                assert!((found_mass - 2.014).abs() < 1e-12);
                assert_eq!(atom_index, 1);
            }
            other => panic!("expected MassMismatch, got {other:?}"),
        }
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.008);
        builder.add_atom("H", 1.0, 0.0, 0.0, [false; 3], 1, 2.014);
        assert!(matches!(
            builder.build(),
            Err(crate::error::ParseError::MassMismatch { .. })
        ));
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
            metadata: FrameMeta::empty(),
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
            metadata: FrameMeta::empty(),
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
            metadata: FrameMeta::empty(),
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
        let frame = b.build().unwrap();
        assert_eq!(frame.positions.kind(), FloatStorageKind::Float32);
        let t = frame
            .positions_as_dlpack(dlpk::sys::DLDevice::cpu())
            .unwrap();
        assert_eq!(t.shape(), &[1, 3]);
        assert!(frame.header.metadata.contains_key(meta::STORAGE_DTYPES));
        let row = frame.positions.as_f64_row(0);
        assert!((row[0] - 1.0).abs() < 1e-5);
    }

    /// With `--features cuda`, requesting CUDA on frame positions H2D-exports
    /// real device memory (not host pointers labeled as CUDA).
    #[cfg(feature = "cuda")]
    #[test]
    fn frame_positions_as_dlpack_cuda_h2d() {
        if crate::cuda_array::cuda_device_count().is_err() {
            return;
        }
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 1.0, 2.0, 3.0, [false; 3], 0, 1.0);
        b.add_atom("O", 4.0, 5.0, 6.0, [false; 3], 0, 16.0);
        let frame = b.build().unwrap();
        let t = frame
            .positions_as_dlpack(dlpk::sys::DLDevice::cuda(0))
            .expect("CUDA H2D export");
        assert_eq!(t.device().device_type, dlpk::sys::DLDeviceType::kDLCUDA);
        assert_eq!(t.shape(), &[2, 3]);
        let p = t.data_ptr::<f64>().expect("device data_ptr");
        assert!(!p.is_null());
        // CPU still works
        let cpu = frame
            .positions_as_dlpack(dlpk::sys::DLDevice::cpu())
            .unwrap();
        assert_eq!(cpu.device(), dlpk::sys::DLDevice::cpu());
    }

    #[cfg(not(feature = "cuda"))]
    #[test]
    fn frame_positions_as_dlpack_cuda_rejected_without_feature() {
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 1.0, 2.0, 3.0, [false; 3], 0, 1.0);
        let frame = b.build().unwrap();
        let err = frame
            .positions_as_dlpack(dlpk::sys::DLDevice::cuda(0))
            .unwrap_err();
        assert!(
            format!("{err:?}").contains("non-CPU") || format!("{err:?}").contains("cuda"),
            "{err:?}"
        );
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
        let frame = b.build().unwrap();
        assert_eq!(frame.positions.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.velocities.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.forces.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.atom_energies.kind(), FloatStorageKind::Float32);
        assert_eq!(frame.masses.kind(), FloatStorageKind::Float32);
        assert!(
            frame
                .velocities_as_dlpack(dlpk::sys::DLDevice::cpu())
                .unwrap()
                .is_some()
        );
    }

    #[test]
    fn typed_units_and_conversion_on_built_frame() {
        let mut b = ConFrameBuilder::new([10.0; 3], [90.0; 3]);
        b.add_atom("H", 1.0, 2.0, 3.0, [false; 3], 0, 1.0);
        let frame = b.build().unwrap();
        assert_eq!(frame.header.spec_version, crate::CON_SPEC_VERSION);
        // Builder injects default v3 units
        assert_eq!(frame.length_unit(), Some("angstrom"));
        assert_eq!(frame.energy_unit(), Some("eV"));
        let to_nm = frame.conversion_factor_to("length", "nm").unwrap();
        assert!((to_nm - 0.1).abs() < 1e-12);
        let x_nm = frame.x_at(0) * to_nm;
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
            metadata: FrameMeta::empty(),
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
            metadata: FrameMeta::empty(),
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
            metadata: FrameMeta::empty(),
            sections: Vec::new(),
            strict_validation: false,
            sections_declared: false,
        };
        assert_eq!(header.lattice_vectors(), None);
        let vecs = [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 20.0]];
        header.set_lattice_vectors(vecs).unwrap();
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

        let frame = builder.build().unwrap();
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
    fn test_builder_set_metadata_json_accepts_validate_without_sections() {
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        builder
            .set_metadata_json(r#"{"con_spec_version":2,"validate":true}"#)
            .unwrap();
        builder
            .add_atom("Cu", 0.0, 0.0, 0.0, [false, false, false], 0, 63.546)
            .with_charge(0.5);
        let frame = builder.build().unwrap();
        let mut buf = Vec::new();
        crate::writer::ConFrameWriter::new(&mut buf)
            .write_frame(&frame)
            .unwrap();
        let text = String::from_utf8(buf).unwrap();
        assert!(text.contains(r#""sections":["charges"]"#), "{text}");
        assert!(text.contains(r#""validate":true"#), "{text}");
        let reread: Vec<_> = crate::iterators::ConFrameIterator::new(&text)
            .collect::<Result<_, _>>()
            .unwrap();
        assert_eq!(reread[0].atom_data[0].charge(), Some(0.5));

        let mut bad = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        assert!(bad.set_metadata_json(r#"{"validate":1}"#).is_err());
        assert!(
            bad.set_metadata_json(r#"{"validate":true,"sections":"charges"}"#)
                .is_err()
        );
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

        let frame = builder.build().unwrap();
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
        let frame = b.build().unwrap();
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
        b.set_atom_mass(1, 100.0).unwrap();
        let frame = b.build().unwrap();
        assert_eq!(frame.atom_data[0].fixed(), [true, false, true]);
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
        let frame = b.build().unwrap();
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
        let new_pos = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0];
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
        let frame = b.build().unwrap();
        assert_eq!(frame.atom_data.len(), 3);
        assert!(frame.has_forces());
        assert!(frame.has_energies());
        // group order: Cu, Cu, H
        assert_eq!(frame.atom_data[0].force(), Some([1.0, 0.0, 0.0]));
        assert_eq!(frame.atom_data[2].force(), Some([0.0, 0.0, 1.0]));
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
        let mut fr = frame.clone().build().unwrap();
        // Strip units to simulate hand-built non-compliant header still claiming v3
        fr.header.metadata.remove(meta::UNITS);
        fr.header.spec_version = 3;
        let mut buf = Cursor::new(Vec::new());
        {
            let mut w = ConFrameWriter::new(&mut buf);
            let err = w.write_frame(&fr).unwrap_err();
            assert!(
                matches!(
                    err,
                    crate::writer::WriteError::Format(crate::error::ParseError::InvalidUnits(_))
                ),
                "D11: writer must not replace missing v3 units, got {err}"
            );
        }
        // A frame that still carries the builder units does write them.
        let fr_ok = frame.build().unwrap();
        let mut buf = Cursor::new(Vec::new());
        {
            let mut w = ConFrameWriter::new(&mut buf);
            w.write_frame(&fr_ok).unwrap();
        }
        let s = String::from_utf8(buf.into_inner()).unwrap();
        assert!(s.contains("\"units\""), "builder frames carry units: {s}");
        assert!(s.contains("angstrom") || s.contains("length"), "{s}");
        assert!(!s.contains("\"time\""), "builder must not inject time: {s}");
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
        let mut frame = b.build().unwrap();
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
        assert!(parse_bonds_from_metadata(&frame.header.metadata.to_map()).is_empty());
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

    #[test]
    fn cloned_and_permuted_frame_clears_column_tails_and_unshares_safely() {
        let text = std::fs::read_to_string("resources/test/tiny_cuh2_vel_forces.con").unwrap();
        let frame = crate::iterators::ConFrameIterator::new(&text)
            .next()
            .unwrap()
            .unwrap();
        assert!(!frame.column_tails.is_empty());

        let cloned = frame.clone();
        assert!(!cloned.column_tails.is_empty());
        assert_slots_on_columns(&cloned);

        let mut reordered = crate::correspondence::reorder_like(
            &frame,
            &frame,
            crate::correspondence::IdentityCheck::Strict,
        )
        .unwrap();
        assert!(!reordered.column_tails.is_empty());
        assert_slots_on_columns(&reordered);
        drop(frame);

        let _shared_vel = reordered.velocities.clone();
        reordered.unshare_slot_columns();
        assert!(reordered.atom_data[0].velocity().is_some());
    }

    #[test]
    fn set_velocity_on_forces_only_parsed_frame_preserves_force() {
        let text = std::fs::read_to_string("resources/test/tiny_cuh2_forces.con").unwrap();
        let mut frame = crate::iterators::ConFrameIterator::new(&text)
            .next()
            .unwrap()
            .unwrap();
        let force0 = frame.atom_data[0].force().expect("parsed force");
        let force1 = frame.atom_data[1].force().expect("parsed force");

        frame.atom_data[0].set_velocity(None);
        assert_eq!(frame.atom_data[0].force(), Some(force0));
        assert_eq!(frame.atom_data[0].velocity(), None);

        frame.atom_data[1].set_velocity(Some([1.5, -2.5, 3.5]));
        assert_eq!(frame.atom_data[1].force(), Some(force1));
        assert_eq!(frame.atom_data[1].velocity(), Some([1.5, -2.5, 3.5]));
    }

    #[test]
    fn sync_atom_data_from_arrays_does_not_mutate_shared_column_view() {
        let text = std::fs::read_to_string("resources/test/tiny_cuh2_vel_forces.con").unwrap();
        let mut frame = crate::iterators::ConFrameIterator::new(&text)
            .next()
            .unwrap()
            .unwrap();
        let shared_vel = frame.velocities.clone();
        let before = shared_vel.as_f64_row(0);

        frame.velocities.set_f64_row(0, [11.0, 22.0, 33.0]);
        frame.sync_atom_data_from_arrays();

        assert_eq!(shared_vel.as_f64_row(0), before);
        drop(shared_vel);
        assert_eq!(frame.atom_data[0].velocity(), Some([11.0, 22.0, 33.0]));
    }

    #[test]
    fn unshare_moves_live_slots_off_a_shared_velocity_column() {
        let text = std::fs::read_to_string("resources/test/tiny_cuh2_vel_forces.con").unwrap();
        let mut frame = crate::iterators::ConFrameIterator::new(&text)
            .next()
            .unwrap()
            .unwrap();
        let shared = frame.velocities.clone();
        let before = shared.as_f64_row(0);
        frame.unshare_slot_columns();
        frame.atom_data[0].set_velocity(Some([123.0, 0.0, 0.0]));
        assert_eq!(shared.as_f64_row(0), before);
        assert_eq!(frame.atom_data[0].velocity(), Some([123.0, 0.0, 0.0]));
        assert_eq!(frame.velocities.as_f64_row(0), [123.0, 0.0, 0.0]);
        let slot = frame.atom_data[0].velocity_slot() as usize;
        let range = frame.velocities.f64_slice().unwrap().as_ptr_range();
        assert!(range.contains(&(slot as *const f64)));
    }

    fn parsed_coords(frame: &ConFrame) -> Vec<[f64; 3]> {
        (0..frame.atom_data.len())
            .map(|index| frame.xyz_at(index))
            .collect()
    }

    /// Cloning shares the positions column. A later row write copies that
    /// column. Dropping the frame that still owns the old allocation must
    /// not free the column the other frame reads, and the accessor reads
    /// the row that was written.
    #[test]
    fn cloned_row_write_leaves_atom_coordinates_readable() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let mut frame = crate::iterators::ConFrameIterator::new(text)
            .next()
            .expect("frame")
            .expect("parse");
        let snapshot = parsed_coords(&frame);
        let cloned = frame.clone();
        {
            let row = frame.positions.f64_mut_slice().expect("f64 positions");
            row[0] = 42.0;
        }
        assert_eq!(cloned.xyz_at(0), snapshot[0]);
        drop(cloned);
        assert_eq!(frame.xyz_at(0)[0], 42.0);
        assert_eq!(frame.positions.as_f64_row(0)[0], 42.0);
    }

    /// Replacing the public positions field drops the old column. The
    /// accessor reads the new column and does not touch the dropped one.
    #[test]
    fn replacing_positions_leaves_atom_coordinates_readable() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let mut frame = crate::iterators::ConFrameIterator::new(text)
            .next()
            .expect("frame")
            .expect("parse");
        let n = frame.positions.nrows();
        frame.positions = crate::storage_dtype::FloatArray2::zeros_f64(n, 3);
        assert_eq!(frame.positions.as_f64_row(0), [0.0; 3]);
        assert_eq!(frame.xyz_at(0), [0.0; 3]);
    }

    /// A store through the positions column is the value the accessor returns.
    #[test]
    fn a_column_write_is_seen_by_the_atom_accessor() {
        let text = include_str!("../resources/test/tiny_cuh2.con");
        let mut frame = crate::iterators::ConFrameIterator::new(text)
            .next()
            .expect("frame")
            .expect("parse");
        frame.set_x_at(0, 42.0);
        assert_eq!(frame.x_at(0), 42.0);
        assert_eq!(frame.positions.as_f64_row(0)[0], 42.0);
        {
            let row = frame.positions.f64_mut_slice().expect("f64 positions");
            row[1] = 7.0;
        }
        assert_eq!(frame.y_at(0), 7.0);
    }

    /// A writer storing whole `AtomicU64` values and a reader using
    /// [`atomic_load_f64`] do not tear a double. ThreadSanitizer is the
    /// check that the two sides do not race.
    #[test]
    fn a_concurrent_atomic_store_is_a_whole_double() {
        use std::sync::Arc;
        use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
        let n = 1024usize;
        let buf = vec![0.0f64; n];
        let ptr = buf.as_ptr();
        assert_atomic_f64_alignment(ptr);
        let stop = Arc::new(AtomicBool::new(false));
        let stop_writer = Arc::clone(&stop);
        let addr = ptr as usize;
        let writer = std::thread::spawn(move || {
            let cells = addr as *mut u64;
            let mut value = 1u64;
            while !stop_writer.load(Ordering::Relaxed) {
                for index in 0..n {
                    unsafe {
                        AtomicU64::from_ptr(cells.add(index)).store(value, Ordering::Relaxed);
                    }
                    value = value.wrapping_add(1);
                    if value == 0 {
                        value = 1;
                    }
                }
            }
        });
        for _ in 0..64 {
            for index in 0..n {
                let loaded = unsafe { atomic_load_f64(ptr.add(index)).to_bits() };
                let _ = loaded;
            }
        }
        stop.store(true, Ordering::Relaxed);
        writer.join().expect("writer");
        for index in 0..n {
            let loaded = unsafe { atomic_load_f64(ptr.add(index)).to_bits() };
            let direct = unsafe {
                AtomicU64::from_ptr(ptr.cast_mut().cast::<u64>().add(index)).load(Ordering::Relaxed)
            };
            assert_eq!(loaded, direct);
        }
    }

    fn vel_forces_frame() -> ConFrame {
        let text = include_str!("../resources/test/tiny_cuh2_vel_forces.con");
        crate::iterators::ConFrameIterator::new(text)
            .next()
            .expect("frame")
            .expect("parse")
    }

    /// Every atom slot addresses its row of the frame's own columns.
    fn assert_slots_on_columns(frame: &ConFrame) {
        let vel = frame.velocities.f64_slice().expect("velocity column");
        let force = frame.forces.f64_slice().expect("force column");
        for (i, atom) in frame.atom_data.iter().enumerate() {
            assert_eq!(atom.velocity_slot(), vel[i * 3..].as_ptr(), "velocity {i}");
            assert_eq!(atom.force_slot(), force[i * 3..].as_ptr(), "force {i}");
            assert_eq!(atom.velocity(), Some(frame.velocities.as_f64_row(i)));
            assert_eq!(atom.force(), Some(frame.forces.as_f64_row(i)));
        }
    }

    #[test]
    fn a_column_row_write_after_a_clone_reaches_the_atoms() {
        let mut frame = vel_forces_frame();
        assert_slots_on_columns(&frame);
        let clone = frame.clone();
        frame.velocities.set_f64_row(0, [9.0, 8.0, 7.0]);
        frame.forces.set_f64_row(1, [6.0, 5.0, 4.0]);
        drop(clone);
        assert_eq!(frame.atom_data[0].velocity(), Some([9.0, 8.0, 7.0]));
        assert_eq!(frame.atom_data[1].force(), Some([6.0, 5.0, 4.0]));
        assert_slots_on_columns(&frame);
    }

    #[test]
    fn a_mutable_slice_write_after_a_clone_reaches_the_atoms() {
        let mut frame = vel_forces_frame();
        let clone = frame.clone();
        frame.velocities.f64_mut_slice().expect("f64")[3] = 42.0;
        drop(clone);
        assert_eq!(frame.atom_data[1].velocity().unwrap()[0], 42.0);
        assert_slots_on_columns(&frame);
    }

    #[test]
    fn a_clone_owns_its_columns_and_its_atoms_address_them() {
        let mut frame = vel_forces_frame();
        let before = frame.clone();
        let mut clone = frame.clone();
        assert_slots_on_columns(&clone);
        frame.atom_data[0].set_velocity(Some([1.0, 2.0, 3.0]));
        frame.atom_data[0].set_force(Some([4.0, 5.0, 6.0]));
        assert_eq!(
            clone.velocities.as_f64_row(0),
            before.velocities.as_f64_row(0)
        );
        assert_eq!(clone.forces.as_f64_row(0), before.forces.as_f64_row(0));
        assert_eq!(
            clone.atom_data[0].velocity(),
            before.atom_data[0].velocity()
        );
        clone.velocities.set_f64_row(2, [7.0, 7.0, 7.0]);
        assert_eq!(clone.atom_data[2].velocity(), Some([7.0, 7.0, 7.0]));
        assert_eq!(
            frame.atom_data[2].velocity(),
            before.atom_data[2].velocity()
        );
        drop(frame);
        assert_slots_on_columns(&clone);
    }

    #[test]
    fn unsharing_a_column_handed_out_keeps_the_atoms_on_the_frame() {
        let mut frame = vel_forces_frame();
        let handed_out = (*frame.velocities).clone();
        let original = handed_out.as_f64_row(0);
        frame.unshare_slot_columns();
        frame.atom_data[0].set_velocity(Some([3.0, 2.0, 1.0]));
        frame.velocities.set_f64_row(1, [1.0, 1.0, 1.0]);
        assert_eq!(handed_out.as_f64_row(0), original);
        drop(handed_out);
        assert_eq!(frame.velocities.as_f64_row(0), [3.0, 2.0, 1.0]);
        assert_eq!(frame.atom_data[1].velocity(), Some([1.0, 1.0, 1.0]));
        assert_slots_on_columns(&frame);
    }

    #[test]
    fn repacking_a_declared_section_rebinds_the_other_atoms() {
        let mut frame = vel_forces_frame();
        // Atom 0 takes its own tail, so the velocity column no longer
        // looks live and the section is packed again from the atoms.
        frame.atom_data[0].set_energy(Some(-1.0));
        frame.install_declared_section_soa();
        let vel = frame.velocities.f64_slice().expect("f64");
        for i in 1..frame.atom_data.len() {
            assert_eq!(frame.atom_data[i].velocity_slot(), vel[i * 3..].as_ptr());
        }
        frame.velocities.set_f64_row(3, [8.0, 8.0, 8.0]);
        assert_eq!(frame.atom_data[3].velocity(), Some([8.0, 8.0, 8.0]));
        assert_eq!(frame.atom_data[0].energy(), Some(-1.0));
    }

    #[test]
    fn dtype_projection_and_array_sync_keep_the_atoms_on_the_columns() {
        let mut frame = vel_forces_frame();
        let dtypes = frame.header.metadata.dtypes();
        frame.project_storage_dtypes(&dtypes);
        assert_slots_on_columns(&frame);
        frame.velocities.set_f64_row(0, [5.0, 5.0, 5.0]);
        assert_eq!(frame.atom_data[0].velocity(), Some([5.0, 5.0, 5.0]));
        frame.sync_arrays_from_atom_data();
        assert_slots_on_columns(&frame);
        frame.forces.set_f64_row(1, [2.0, 2.0, 2.0]);
        assert_eq!(frame.atom_data[1].force(), Some([2.0, 2.0, 2.0]));
    }

    #[test]
    fn a_reordered_frame_addresses_its_permuted_columns() {
        let frame = vel_forces_frame();
        let mut reversed = frame.clone();
        reversed.atom_data.reverse();
        let mut out = crate::correspondence::reorder_like(
            &reversed,
            &frame,
            crate::correspondence::IdentityCheck::Lenient,
        )
        .expect("same ids");
        drop(reversed);
        let n = frame.atom_data.len();
        for i in 0..n {
            assert_eq!(out.atom_data[i].atom_id, frame.atom_data[n - 1 - i].atom_id);
            assert_eq!(
                out.velocities.as_f64_row(i),
                frame.velocities.as_f64_row(n - 1 - i)
            );
        }
        assert_slots_on_columns(&out);
        out.velocities.set_f64_row(0, [4.0, 4.0, 4.0]);
        assert_eq!(out.atom_data[0].velocity(), Some([4.0, 4.0, 4.0]));
        drop(frame);
        assert_slots_on_columns(&out);
    }

    #[cfg(feature = "python")]
    #[test]
    fn a_snapshot_view_counts_its_motion_columns_and_releases_them() {
        let mut frame = vel_forces_frame();
        let held = {
            let snapshot = CoordSnapshot::copy_of(&[Some(&frame)]);
            let view = snapshot.frames[0].as_ref().expect("view");
            let vel = view.velocities.f64_slice().expect("f64");
            assert_eq!(vel.as_ptr(), frame.velocities.f64_slice().unwrap().as_ptr());
            (*view.forces).clone()
        };
        let crate::storage_dtype::Array2Storage::F64(velocities) = &mut *frame.velocities else {
            panic!("f64 velocities");
        };
        assert!(velocities.is_unique(), "the view must not keep a count");
        drop(held);
        let crate::storage_dtype::Array2Storage::F64(forces) = &mut *frame.forces else {
            panic!("f64 forces");
        };
        assert!(forces.is_unique());
        assert_slots_on_columns(&frame);
    }
}
