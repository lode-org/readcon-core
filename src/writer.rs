use crate::types::{
    ConFrame, ConFrameBuilder, SECTION_CHARGES, SECTION_DISPLACEMENTS, SECTION_ENERGIES,
    SECTION_FORCES, SECTION_MAGMOMS, SECTION_SPINS, SECTION_SPREADS, SECTION_VELOCITIES,
    encode_fixed_bitmask, meta,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::Path;

/// Failure from [`ConFrameWriter`]. I/O stays distinct from format errors
/// so `InvalidUnits` and `InvalidCount` remain distinguishable (CON-error.1).
#[derive(Debug)]
pub enum WriteError {
    Io(io::Error),
    Format(crate::error::ParseError),
}

impl std::fmt::Display for WriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            WriteError::Io(e) => write!(f, "{e}"),
            WriteError::Format(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for WriteError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            WriteError::Io(e) => Some(e),
            WriteError::Format(e) => Some(e),
        }
    }
}

impl From<io::Error> for WriteError {
    fn from(e: io::Error) -> Self {
        WriteError::Io(e)
    }
}

impl From<WriteError> for io::Error {
    fn from(e: WriteError) -> Self {
        match e {
            WriteError::Io(e) => e,
            WriteError::Format(err) => io::Error::new(io::ErrorKind::InvalidData, err.to_string()),
        }
    }
}

/// Numeric text representation for CON frame fields.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum FloatFormat {
    /// A fixed number of digits after the decimal point.
    DecimalPlaces(usize),
    /// The shortest scientific representation preserving each finite f64.
    /// Signed zero is preserved; decimal precision does not limit this mode.
    /// CON-num.6 (D13): the default writer round-trips binary64.
    #[default]
    RoundTrip,
}

/// A writer that can serialize and write `ConFrame` objects to any output stream.
///
/// This struct encapsulates a writer (like a file) and provides a high-level API
/// for writing simulation frames in the `.con` format.
///
/// # Example
/// ```no_run
/// # use std::fs::File;
/// # use readcon_core::types::ConFrame;
/// # use readcon_core::writer::ConFrameWriter;
/// # let frames: Vec<ConFrame> = Vec::new();
/// let mut writer = ConFrameWriter::from_path("output.con").unwrap();
/// writer.extend(frames.iter()).unwrap();
/// ```
pub struct ConFrameWriter<W: Write> {
    writer: BufWriter<W>,
    float_format: FloatFormat,
    /// When true: sort metadata keys in JSON and emit sections in canonical
    /// order (velocities, forces, energies). Opt-in. Float text follows
    /// `float_format` (round-trip unless the caller asked for decimals).
    canonical: bool,
    /// Cache for the JSON metadata line: when consecutive frames share
    /// the same (spec_version, sections-set, metadata) triple the
    /// serialized JSON object is identical, so reusing the cached
    /// string skips the per-frame `serde_json::Map::insert` rebuild
    /// and re-serialisation. Hot for trajectory writes where every
    /// frame has the same `units` / `potential` / `validate` keys.
    metadata_cache: Option<MetadataCacheEntry>,
    /// One frame of CON text. Filled then flushed with a single `write_all`
    /// so the sink is not entered once per atom line.
    scratch: Vec<u8>,
    /// Reused shortest-round-trip buffer (ryu). One per writer, not per float.
    ryu: ryu::Buffer,
    /// Last x/y/z spellings. A value is formatted on the second sight and
    /// copied after that, which is the common lattice column.
    fmt_slot: [FmtSlot; 3],
    /// Workers for one wide coordinate block. One keeps the serial loop.
    atom_workers: usize,
    /// Binding stamp for the next [`Self::write_frame`]. The atoms stay in
    /// `frame`; only the header the writer emits changes.
    bound: Option<BoundHeader>,
    /// Wide-frame rows are formatted on several threads and copied into a
    /// shared mapping of this file. `pwrite` of one inode does not scale.
    stream_file: Option<File>,
    /// Use the shared mapping even below the wide-frame cutoff. Tests compare
    /// that path with a serial write for odd atom counts.
    force_map: bool,
    /// Leave the frame text in `scratch` instead of copying it into `writer`.
    /// The format-only path reads `scratch` back, so the copy was a second
    /// pass over the same bytes.
    keep_scratch: bool,
    /// `scratch` is the caller's exact output. Do not reserve past it.
    exact_scratch: bool,
    /// Put `bound` back after a frame so the next identical header can reuse it.
    /// Only the direct eight-thread writer sets this. The serial writer
    /// rebuilds the header, so its timing stays put.
    keep_bound: bool,
    bound_vel: Option<bool>,
    bound_flags: Option<[bool; 8]>,
    bound_line: Option<String>,
    /// `Some(true)` once a reused header is known to have no lattice vectors.
    bound_no_lattice: Option<bool>,
}

struct BoundHeader {
    meta: BTreeMap<String, Value>,
    spec: u32,
}

/// One column of the round-trip float cache.
#[derive(Clone, Copy)]
struct FmtSlot {
    bits: u64,
    text: [u8; 24],
    len: u8,
    /// 0 empty, 1 seen once, 2 `text` holds the spelling.
    state: u8,
}

impl FmtSlot {
    const fn new() -> Self {
        Self {
            bits: 0,
            text: [0; 24],
            len: 0,
            state: 0,
        }
    }
}

#[derive(Debug)]
struct MetadataCacheEntry {
    /// Snapshot of the inputs that fully determine the serialized JSON
    /// metadata line. Cheap to clone; cheaper than re-serialising the
    /// whole map on every frame.
    spec_version: u32,
    has_velocities: bool,
    has_forces: bool,
    has_energies: bool,
    has_charges: bool,
    has_spins: bool,
    has_magmoms: bool,
    has_displacements: bool,
    has_spreads: bool,
    metadata: std::collections::BTreeMap<String, serde_json::Value>,
    /// Cached serialised metadata line (without trailing newline).
    serialized: String,
}

impl MetadataCacheEntry {
    fn matches(
        &self,
        spec_version: u32,
        sections: [bool; 8],
        metadata: &std::collections::BTreeMap<String, serde_json::Value>,
    ) -> bool {
        let [
            has_velocities,
            has_forces,
            has_energies,
            has_charges,
            has_spins,
            has_magmoms,
            has_displacements,
            has_spreads,
        ] = sections;
        self.spec_version == spec_version
            && self.has_velocities == has_velocities
            && self.has_forces == has_forces
            && self.has_energies == has_energies
            && self.has_charges == has_charges
            && self.has_spins == has_spins
            && self.has_magmoms == has_magmoms
            && self.has_displacements == has_displacements
            && self.has_spreads == has_spreads
            && self.metadata.len() == metadata.len()
            && self
                .metadata
                .iter()
                .zip(metadata)
                .all(|((ka, a), (kb, b))| ka == kb && metadata_value_eq(a, b))
    }
}

// Cache equality preserves the numeric representation, including signed zero,
// throughout nested JSON values.
fn metadata_value_eq(a: &serde_json::Value, b: &serde_json::Value) -> bool {
    use serde_json::Value;
    match (a, b) {
        (Value::Number(a), Value::Number(b)) if a.is_f64() && b.is_f64() => {
            a.as_f64().map(f64::to_bits) == b.as_f64().map(f64::to_bits)
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(a, b)| metadata_value_eq(a, b))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(key, a)| b.get(key).is_some_and(|b| metadata_value_eq(a, b)))
        }
        _ => a == b,
    }
}

/// CON-section.16. Minor 2 and later must list, in `section_arity`, every
/// emitted section that minor 1 does not reserve.
fn require_minor2_section_arity(
    minor: u64,
    sections: &[serde_json::Value],
    metadata: &serde_json::Map<String, serde_json::Value>,
) -> Result<(), WriteError> {
    if minor < 2 {
        return Ok(());
    }
    for name in sections.iter().filter_map(|value| value.as_str()) {
        if crate::types::reserved_section_value_arity(name).is_some() {
            continue;
        }
        let listed = metadata
            .get(meta::SECTION_ARITY)
            .and_then(|value| value.as_object())
            .and_then(|obj| obj.get(name))
            .and_then(|value| value.as_u64())
            .is_some_and(|n| n >= 1);
        if !listed {
            return Err(WriteError::Format(
                crate::error::ParseError::ValidationError(format!(
                    "minor >= 2 must list {name} in section_arity"
                )),
            ));
        }
    }
    Ok(())
}

/// Puts a streamed frame back to the last complete prefix when the
/// write fails after the file has already grown.
struct StreamOut {
    file: File,
    start: u64,
    armed: bool,
}

impl Drop for StreamOut {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        let _ = self.file.set_len(self.start);
        let _ = self.file.seek(SeekFrom::Start(self.start));
    }
}

// General implementation for any type that implements `Write`.
impl<W: Write> ConFrameWriter<W> {
    /// Creates a new `ConFrameWriter` that wraps a given writer.
    ///
    /// # Arguments
    ///
    /// * `writer` - Any type that implements `std::io::Write`, e.g., a `File`.
    pub fn new(writer: W) -> Self {
        Self::with_float_format(writer, FloatFormat::default())
    }

    /// Creates a new `ConFrameWriter` with a custom floating-point precision.
    ///
    /// # Arguments
    ///
    /// * `writer` - Any type that implements `std::io::Write`.
    /// * `precision` - Number of decimal places for floating-point output.
    pub fn with_precision(writer: W, precision: usize) -> Self {
        Self::with_float_format(writer, FloatFormat::DecimalPlaces(precision))
    }

    /// Creates a writer with an explicit numeric text representation.
    ///
    /// `FloatFormat::RoundTrip` retains small forces and coordinates exactly.
    /// Metadata floats use the JSON serializer independently of this setting.
    pub fn with_float_format(writer: W, float_format: FloatFormat) -> Self {
        Self {
            writer: BufWriter::new(writer),
            float_format,
            canonical: false,
            metadata_cache: None,
            scratch: Vec::with_capacity(16 * 1024),
            ryu: ryu::Buffer::new(),
            fmt_slot: [FmtSlot::new(); 3],
            atom_workers: 1,
            bound: None,
            stream_file: None,
            force_map: false,
            keep_scratch: false,
            exact_scratch: false,
            keep_bound: false,
            bound_vel: None,
            bound_flags: None,
            bound_line: None,
            bound_no_lattice: None,
        }
    }

    fn retain_scratch(mut self, on: bool) -> Self {
        self.keep_scratch = on;
        self
    }

    /// Format a wide coordinate block on `n` workers.
    ///
    /// `n < 2` leaves the serial loop. The bytes match that loop: each
    /// worker formats a contiguous run of atoms and the runs are joined
    /// in file order.
    pub fn parallel_atoms(mut self, n: usize) -> Self {
        self.atom_workers = n.max(1);
        self
    }

    /// Copy formatted rows into a shared mapping of `stream_file`.
    ///
    /// The wide path does this on its own when a spare physical core is
    /// free. Tests turn it on for short frames so an odd atom count still
    /// takes the mapping, including on a runner with no spare core.
    pub fn map_rows(mut self, on: bool) -> Self {
        self.force_map = on;
        self
    }

    /// File the mapping copies into. Open it read/write; `map_rows` selects
    /// the mapping even when [`Self::parallel_atoms`] would otherwise `pwrite`.
    pub fn mapped_file(mut self, file: File) -> Self {
        self.stream_file = Some(file);
        self
    }

    /// Opt-in **canonical** serialization: BTree-ordered metadata keys in JSON,
    /// fixed section order. Use for corpus
    /// materialization and content-stable hashes; not required for on-disk fidelity
    /// of spans preserved from `next_with_raw_span`.
    pub fn canonical(mut self, on: bool) -> Self {
        self.set_canonical(on);
        self
    }

    /// Set or clear canonical mode on an existing writer (C ABI / FFI).
    pub fn set_canonical(&mut self, on: bool) {
        self.canonical = on;
        if on {
            self.metadata_cache = None;
        }
    }

    /// Whether canonical serialization is enabled.
    pub fn is_canonical(&self) -> bool {
        self.canonical
    }

    fn refresh_metadata_cache(
        &mut self,
        spec_version: u32,
        metadata: &BTreeMap<String, Value>,
        present: [bool; 8],
    ) -> Result<(), WriteError> {
        let [
            has_vel,
            has_frc,
            has_eng,
            has_chg,
            has_spn,
            has_mm,
            has_dsp,
            has_spr,
        ] = present;
        let cache_hit = !self.canonical
            && self.metadata_cache.as_ref().is_some_and(|c| {
                c.matches(
                    spec_version,
                    [
                        has_vel, has_frc, has_eng, has_chg, has_spn, has_mm, has_dsp, has_spr,
                    ],
                    metadata,
                )
            });
        if cache_hit {
            return Ok(());
        }

        let mut meta_obj = serde_json::Map::new();
        meta_obj.insert(meta::CON_SPEC_VERSION.into(), json!(spec_version));
        let mut sections = Vec::new();
        if has_vel {
            sections.push(json!(SECTION_VELOCITIES));
        }
        if has_frc {
            sections.push(json!(SECTION_FORCES));
        }
        if has_eng {
            sections.push(json!(SECTION_ENERGIES));
        }
        if has_chg {
            sections.push(json!(SECTION_CHARGES));
        }
        if has_spn {
            sections.push(json!(SECTION_SPINS));
        }
        if has_mm {
            sections.push(json!(SECTION_MAGMOMS));
        }
        if has_dsp {
            sections.push(json!(SECTION_DISPLACEMENTS));
        }
        if has_spr {
            sections.push(json!(SECTION_SPREADS));
        }
        let validate = metadata
            .get(meta::VALIDATE)
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        if !sections.is_empty() || validate {
            meta_obj.insert(meta::SECTIONS.into(), json!(sections));
        }
        for (k, v) in metadata {
            if k == meta::CON_SPEC_VERSION || k == meta::SECTIONS {
                continue;
            }
            meta_obj.insert(k.clone(), v.clone());
        }
        if let Some(u) = meta_obj.get(meta::UNITS).cloned() {
            // D11: an invalid unit fails the write. Do not substitute a default.
            let c = crate::units::canonicalize_units_object(&u).map_err(|e| {
                WriteError::Format(crate::error::ParseError::InvalidUnits(e.to_string()))
            })?;
            meta_obj.insert(meta::UNITS.into(), c);
        }
        if spec_version >= 3 {
            match meta_obj.get(meta::UNITS) {
                None => {
                    return Err(WriteError::Format(crate::error::ParseError::InvalidUnits(
                        "con_spec_version >= 3 requires units.length and units.energy".into(),
                    )));
                }
                Some(u) => {
                    crate::units::validate_v3_units_metadata(u).map_err(|e| {
                        WriteError::Format(crate::error::ParseError::InvalidUnits(e.to_string()))
                    })?;
                }
            }
        }
        let minor = metadata
            .get(meta::CON_SPEC_MINOR)
            .and_then(|v| v.as_u64())
            .unwrap_or(0);
        if spec_version >= 3 && minor >= 1 && has_vel {
            let time_ok = meta_obj
                .get(meta::UNITS)
                .and_then(|u| u.get("time"))
                .and_then(|v| v.as_str())
                .is_some_and(|s| !s.trim().is_empty());
            if !time_ok {
                return Err(WriteError::Format(crate::error::ParseError::InvalidUnits(
                    "minor >= 1 requires units.time when a velocities section is present".into(),
                )));
            }
        }
        // A minor of 2 or later lists every section minor 1 does not reserve
        // (CON-section.16). Reserved names need no entry.
        require_minor2_section_arity(minor, &sections, &meta_obj)?;
        let serialized = serde_json::Value::Object(meta_obj).to_string();
        self.metadata_cache = Some(MetadataCacheEntry {
            spec_version,
            has_velocities: has_vel,
            has_forces: has_frc,
            has_energies: has_eng,
            has_charges: has_chg,
            has_spins: has_spn,
            has_magmoms: has_mm,
            has_displacements: has_dsp,
            has_spreads: has_spr,
            metadata: metadata.clone(),
            serialized,
        });
        Ok(())
    }

    /// Writes `frame` with the binding metadata stamp and the original atoms.
    ///
    /// The stamp is installed for the duration of the write and then put back.
    /// Atoms are not rebuilt.
    pub fn write_frame_binding(&mut self, frame: &mut ConFrame) -> Result<(), WriteError> {
        self.write_frame_bound(frame)
    }

    /// [`Self::write_frame_binding`] without a mutable frame.
    ///
    /// The header the file emits is the binding stamp. `frame`'s atoms and
    /// its stored header are left as the caller passed them, so a wide frame
    /// is not cloned before its rows are formatted.
    pub fn write_frame_bound(&mut self, frame: &ConFrame) -> Result<(), WriteError> {
        let spec = frame.header.spec_version.max(crate::CON_SPEC_VERSION);
        let flags = [
            frame.has_velocities(),
            frame.has_forces(),
            frame.has_energies(),
            frame.has_charges(),
            frame.has_spins(),
            frame.has_magmoms(),
            frame.has_displacements(),
            frame.has_spreads(),
        ];
        let line = frame.header.prebox_header.metadata_line();
        // Energy, neb_bead, and every other metadata key live in the header.
        // A matching atom skeleton is not the same header.
        let incoming = binding_metadata(frame);
        let meta_same = self
            .bound
            .as_ref()
            .is_some_and(|item| item.spec == spec && item.meta == incoming);
        let reuse = self.exact_scratch
            && meta_same
            && self.bound_flags == Some(flags)
            && self.bound_line.as_deref() == Some(line);
        if !reuse {
            self.bound = Some(BoundHeader {
                meta: incoming,
                spec,
            });
            if self.exact_scratch {
                // The cached JSON also lists the sections. Drop it whenever
                // this frame is not the one that filled the cache.
                if !meta_same || self.bound_flags != Some(flags) {
                    self.metadata_cache = None;
                }
                self.bound_flags = Some(flags);
                self.bound_vel = Some(flags[0]);
                self.bound_line = Some(line.to_string());
                self.bound_no_lattice = None;
            }
        }
        self.keep_bound = self.exact_scratch;
        self.write_frame(frame)
    }

    /// Writes a single `ConFrame` to the output stream.
    pub fn write_frame(&mut self, frame: &ConFrame) -> Result<(), WriteError> {
        let zero_frame = frame.header.natm_types == 0
            && frame.atom_data.is_empty()
            && frame.header.natms_per_type.is_empty()
            && frame.header.masses_per_type.is_empty();
        if zero_frame && !frame.header.sections.is_empty() {
            return Err(WriteError::Format(crate::error::ParseError::InvalidCount(
                "a zero-atom frame cannot declare sections".into(),
            )));
        }
        if !zero_frame
            && (frame.header.natm_types == 0
                || frame.atom_data.is_empty()
                || frame.header.natms_per_type.contains(&0))
        {
            return Err(WriteError::Format(crate::error::ParseError::InvalidCount(
                "each per-type count must be >= 1".into(),
            )));
        }
        #[cfg(feature = "parallel")]
        let parallel_rows = self.atom_workers >= 2 && frame.atom_data.len() >= WIDE_ATOM_GRAIN;
        #[cfg(not(feature = "parallel"))]
        let parallel_rows = false;
        // The direct writer already required dense ids while pricing the
        // trajectory. Scanning them again was on the 8-thread wall.
        if !self.exact_scratch {
            if parallel_rows {
                // Ids are unique across the whole frame. A per-component pass
                // treats an id that restarts at the next element as dense.
                if !ids_are_dense(&frame.atom_data, self.atom_workers) {
                    ensure_unique_ids(&frame.atom_data, self.atom_workers)?;
                }
            } else {
                ensure_unique_ids(&frame.atom_data, 1)?;
            }
        }
        let prec = self.float_format;
        let stream_file = self.stream_file.take();
        let keep_bound = self.keep_bound;
        let bound = self.bound.take();
        let spec_version = bound
            .as_ref()
            .map(|item| item.spec)
            .unwrap_or(frame.header.spec_version);
        // The direct writer keeps one header for a uniform trajectory.
        // Rebuilding the map on every frame showed up in the 8-thread wall.
        let skip_refresh = keep_bound && self.metadata_cache.is_some();
        if !skip_refresh {
            let owned_meta;
            let metadata = if let Some(item) = bound.as_ref() {
                &item.meta
            } else {
                owned_meta = frame.header.metadata.to_map();
                &owned_meta
            };
            if spec_version >= 2 {
                self.refresh_metadata_cache(
                    spec_version,
                    metadata,
                    [
                        frame.has_velocities(),
                        frame.has_forces(),
                        frame.has_energies(),
                        frame.has_charges(),
                        frame.has_spins(),
                        frame.has_magmoms(),
                        frame.has_displacements(),
                        frame.has_spreads(),
                    ],
                )?;
            }
        }
        if keep_bound {
            self.bound = bound;
        }
        // A uniform trajectory either has lattice vectors on every frame
        // or on none. The first frame decides; the rest read lines 3-4.
        let (boxl, angles) = if self.keep_bound && self.bound_no_lattice == Some(true) {
            (frame.header.boxl, frame.header.angles)
        } else {
            match frame.header.lattice_vectors() {
                Some(vecs) => {
                    self.bound_no_lattice = Some(false);
                    crate::types::lengths_and_angles(vecs)
                }
                None => {
                    self.bound_no_lattice = Some(true);
                    (frame.header.boxl, frame.header.angles)
                }
            }
        };
        let atoms = frame.atom_data.len();
        let [
            has_vel,
            has_frc,
            has_eng,
            has_chg,
            has_spn,
            has_mm,
            has_dsp,
            has_spr,
        ] = if self.keep_bound {
            self.bound_flags.unwrap_or([
                frame.has_velocities(),
                frame.has_forces(),
                frame.has_energies(),
                frame.has_charges(),
                frame.has_spins(),
                frame.has_magmoms(),
                frame.has_displacements(),
                frame.has_spreads(),
            ])
        } else {
            [
                frame.has_velocities(),
                frame.has_forces(),
                frame.has_energies(),
                frame.has_charges(),
                frame.has_spins(),
                frame.has_magmoms(),
                frame.has_displacements(),
                frame.has_spreads(),
            ]
        };
        let mut blocks = 1usize;
        if has_vel {
            blocks += 1;
        }
        if has_frc {
            blocks += 1;
        }
        if has_eng {
            blocks += 1;
        }
        if has_chg {
            blocks += 1;
        }
        if has_spn {
            blocks += 1;
        }
        if has_mm {
            blocks += 1;
        }
        if has_dsp {
            blocks += 1;
        }
        if has_spr {
            blocks += 1;
        }
        let mut stream_out = match stream_file {
            Some(mut file) => {
                let start = file.stream_position().map_err(WriteError::Io)?;
                Some(StreamOut {
                    file,
                    start,
                    armed: true,
                })
            }
            None => None,
        };
        // An exact output slice is already the size of the frame text.
        // Reserving the loose upper bound would reallocate that slice.
        if !self.exact_scratch {
            self.scratch
                .reserve(256 + atoms.saturating_mul(64).saturating_mul(blocks));
        }
        if !self.keep_scratch {
            self.scratch.clear();
        }
        push_str_line(&mut self.scratch, &frame.header.prebox_header.user);
        if spec_version < 2 {
            // Spec 1 line 2 is free text. Do not re-emit JSON major 0 or 1 (D15).
            push_str_line(
                &mut self.scratch,
                frame.header.prebox_header.metadata_line(),
            );
        } else {
            let line = self
                .metadata_cache
                .as_ref()
                .expect("metadata_cache populated above")
                .serialized
                .as_bytes();
            self.scratch.extend_from_slice(line);
            self.scratch.push(b'\n');
        }
        {
            let buf = &mut self.scratch;
            let ryu = &mut self.ryu;
            let slots = &mut self.fmt_slot;

            // --- Write the 9-line Header ---
            push_f64(buf, ryu, boxl[0], prec);
            buf.push(b' ');
            push_f64(buf, ryu, boxl[1], prec);
            buf.push(b' ');
            push_f64(buf, ryu, boxl[2], prec);
            buf.push(b'\n');
            push_f64(buf, ryu, angles[0], prec);
            buf.push(b' ');
            push_f64(buf, ryu, angles[1], prec);
            buf.push(b' ');
            push_f64(buf, ryu, angles[2], prec);
            buf.push(b'\n');
            push_str_line(buf, &frame.header.postbox_header[0]);
            push_str_line(buf, &frame.header.postbox_header[1]);
            push_u64(buf, frame.header.natm_types as u64);
            buf.push(b'\n');

            for (i, n) in frame.header.natms_per_type.iter().enumerate() {
                if i > 0 {
                    buf.push(b' ');
                }
                push_u64(buf, *n as u64);
            }
            buf.push(b'\n');

            for (i, m) in frame.header.masses_per_type.iter().enumerate() {
                if i > 0 {
                    buf.push(b' ');
                }
                push_f64(buf, ryu, *m, prec);
            }
            buf.push(b'\n');

            // --- Write the Atom Data ---
            // Velocities are formatted in this same pass. The section is
            // still emitted after every coordinate block, so the bytes
            // match a second scan.
            let save_velocity = has_vel;
            // A short frame writes velocity lines straight into `buf`
            // after the coordinates. Buffering them and copying the
            // bytes was a second pass over about half a convel file.
            let direct_velocity = save_velocity
                && self.atom_workers < 2
                && !self.force_map
                && frame
                    .header
                    .natms_per_type
                    .iter()
                    .all(|count| *count < WIDE_ATOM_GRAIN);
            // One buffer per component, kept on this thread. A fresh Vec
            // for every frame was an allocation on the velocity write.
            std::thread_local! {
                static VEL_ROWS: std::cell::RefCell<Vec<Vec<u8>>> =
                    const { std::cell::RefCell::new(Vec::new()) };
            }
            struct RestoreRows(Vec<Vec<u8>>);
            impl Drop for RestoreRows {
                fn drop(&mut self) {
                    let rows = std::mem::take(&mut self.0);
                    VEL_ROWS.with(|cell| *cell.borrow_mut() = rows);
                }
            }
            let mut velocity_rows = if direct_velocity {
                None
            } else {
                Some(RestoreRows(VEL_ROWS.with(|cell| cell.take())))
            };
            if let Some(velocity_rows) = velocity_rows.as_mut() {
                let ntypes = frame.header.natms_per_type.len();
                if velocity_rows.0.len() < ntypes {
                    velocity_rows.0.resize_with(ntypes, Vec::new);
                }
                for row in &mut velocity_rows.0 {
                    row.clear();
                }
            }
            let mut atom_idx_offset = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[atom_idx_offset].symbol;
                push_str_line(buf, symbol);
                push_component_line(buf, "Coordinates of Component", type_idx);

                let mapped = self.force_map
                    || (self.atom_workers >= 2 && num_atoms_in_type >= WIDE_ATOM_GRAIN);
                append_coord_rows(
                    buf,
                    LineFmt { ryu, slots },
                    &frame.atom_data[atom_idx_offset..atom_idx_offset + num_atoms_in_type],
                    prec,
                    spec_version,
                    self.atom_workers,
                    AppendOut {
                        mapped,
                        force_map: self.force_map,
                        stream: stream_out.as_mut().map(|out| &mut out.file),
                        vel: if save_velocity && !direct_velocity {
                            Some(&mut velocity_rows.as_mut().unwrap().0[type_idx])
                        } else {
                            None
                        },
                    },
                )?;
                atom_idx_offset += num_atoms_in_type;
            }

            // --- Write optional velocity section ---
            if has_vel {
                buf.push(b'\n');

                let mut vel_idx_offset = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[vel_idx_offset].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Velocities of Component", type_idx);
                    let atoms =
                        &frame.atom_data[vel_idx_offset..vel_idx_offset + num_atoms_in_type];
                    if direct_velocity {
                        append_velocity_lines(buf, ryu, atoms, prec, spec_version);
                    } else {
                        buf.extend_from_slice(&velocity_rows.as_ref().unwrap().0[type_idx]);
                    }
                    vel_idx_offset += num_atoms_in_type;
                }
            }

            // --- Write optional force section ---
            if has_frc {
                buf.push(b'\n');

                let mut force_idx_offset = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[force_idx_offset].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Forces of Component", type_idx);

                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[force_idx_offset + i];
                        let [fx, fy, fz] = atom.force().unwrap_or([0.0; 3]);
                        push_xyz_line(
                            buf,
                            ryu,
                            slots,
                            [fx, fy, fz],
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    force_idx_offset += num_atoms_in_type;
                }
            }

            // --- Write optional energies section ---
            if has_eng {
                buf.push(b'\n');

                let mut energy_idx_offset = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[energy_idx_offset].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Energies of Component", type_idx);

                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[energy_idx_offset + i];
                        let e = atom.energy().unwrap_or(0.0);
                        push_scalar_line(
                            buf,
                            ryu,
                            slots,
                            e,
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    energy_idx_offset += num_atoms_in_type;
                }
            }

            if has_chg {
                buf.push(b'\n');
                let mut off = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[off].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Charges of Component", type_idx);
                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[off + i];
                        let q = atom.charge().unwrap_or(0.0);
                        push_scalar_line(
                            buf,
                            ryu,
                            slots,
                            q,
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if has_spn {
                buf.push(b'\n');
                let mut off = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[off].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Spins of Component", type_idx);
                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[off + i];
                        let s = atom.spin().unwrap_or(0.0);
                        push_scalar_line(
                            buf,
                            ryu,
                            slots,
                            s,
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if has_mm {
                buf.push(b'\n');
                let mut off = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[off].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Magmoms of Component", type_idx);
                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[off + i];
                        let [mx, my, mz] = atom.magmom().unwrap_or([0.0; 3]);
                        push_xyz_line(
                            buf,
                            ryu,
                            slots,
                            [mx, my, mz],
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if has_dsp {
                buf.push(b'\n');
                let mut off = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[off].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Displacements of Component", type_idx);
                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[off + i];
                        let [dx, dy, dz] = atom.displacement().unwrap_or([0.0; 3]);
                        push_xyz_line(
                            buf,
                            ryu,
                            slots,
                            [dx, dy, dz],
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if has_spr {
                buf.push(b'\n');
                let mut off = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[off].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Spreads of Component", type_idx);
                    for i in 0..num_atoms_in_type {
                        let atom = &frame.atom_data[off + i];
                        let [sx, sy, sz] = atom.spread().unwrap_or([0.0; 3]);
                        if !crate::types::spread_row_ok([sx, sy, sz]) {
                            let err = if sx.is_finite() && sy.is_finite() && sz.is_finite() {
                                crate::types::invalid_spread(off + i)
                            } else {
                                crate::error::ParseError::NonFiniteValue(format!(
                                    "spreads atom {}",
                                    off + i
                                ))
                            };
                            return Err(WriteError::Format(err));
                        }
                        push_xyz_line(
                            buf,
                            ryu,
                            slots,
                            [sx, sy, sz],
                            prec,
                            written_fixed_flag(atom.fixed(), spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }
        }

        if self.keep_scratch {
            if let Some(out) = stream_out.as_mut() {
                out.armed = false;
            }
            return Ok(());
        }
        if let Some(out) = stream_out.as_mut() {
            if !self.scratch.is_empty() {
                out.file.write_all(&self.scratch)?;
                self.scratch.clear();
            }
            out.file.flush()?;
            out.armed = false;
        } else if self.scratch.len() >= 64 * 1024 {
            // BufWriter would copy this frame through an 8 KiB buffer.
            self.writer.flush()?;
            self.writer.get_mut().write_all(&self.scratch)?;
        } else {
            self.writer.write_all(&self.scratch)?;
        }
        Ok(())
    }

    /// Flushes buffered frames to the underlying writer.
    ///
    /// `write_frame` fills a buffer and does not always reach the sink.
    /// After `flush` returns, a reader sees a complete, parseable prefix.
    /// Dropping the writer flushes as well.
    pub fn flush(&mut self) -> io::Result<()> {
        self.writer.flush()
    }

    /// Writes all frames from an iterator to the output stream.
    ///
    /// This is the most convenient way to write a multi-frame file.
    pub fn extend<'a>(
        &mut self,
        frames: impl Iterator<Item = &'a ConFrame>,
    ) -> Result<(), WriteError> {
        for frame in frames {
            self.write_frame(frame)?;
        }
        Ok(())
    }
}

fn ids_are_dense(atoms: &[crate::types::AtomDatum], workers: usize) -> bool {
    let n = atoms.len();
    if workers < 2 || n < WIDE_ATOM_GRAIN {
        return atoms
            .iter()
            .enumerate()
            .all(|(index, atom)| atom.atom_id == index as u64);
    }
    #[cfg(feature = "parallel")]
    {
        let chunk = n.div_ceil(workers);
        crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            atoms.par_chunks(chunk).enumerate().all(|(index, group)| {
                let base = index * chunk;
                group
                    .iter()
                    .enumerate()
                    .all(|(offset, atom)| atom.atom_id == (base + offset) as u64)
            })
        })
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = workers;
        atoms
            .iter()
            .enumerate()
            .all(|(index, atom)| atom.atom_id == index as u64)
    }
}

fn ensure_unique_ids(atoms: &[crate::types::AtomDatum], workers: usize) -> Result<(), WriteError> {
    let n = atoms.len();
    if n == 0 {
        return Ok(());
    }
    // Trajectory frames usually number atoms 0..n-1. That needs no set.
    if ids_are_dense(atoms, workers) {
        return Ok(());
    }
    let mut seen_ids = std::collections::HashSet::with_capacity(n);
    for atom in atoms {
        if !seen_ids.insert(atom.atom_id) {
            return Err(WriteError::Format(
                crate::error::ParseError::ValidationError(format!(
                    "atom id {} is repeated in the frame",
                    atom.atom_id
                )),
            ));
        }
    }
    Ok(())
}

fn written_fixed_flag(fixed: [bool; 3], spec_version: u32) -> u8 {
    if spec_version < 2 {
        if fixed.iter().any(|axis| *axis) { 1 } else { 0 }
    } else {
        encode_fixed_bitmask(fixed)
    }
}

/// Two ASCII digits for `0..100`, indexed by `n * 2`.
const DIGIT_PAIRS: &[u8; 200] = b"00010203040506070809101112131415161718192021222324252627282930313233343536373839404142434445464748495051525354555657585960616263646566676869707172737475767778798081828384858687888990919293949596979899";

fn push_u64(buf: &mut Vec<u8>, n: u64) {
    // Spell straight into the spare tail. A stack buffer plus
    // `extend_from_slice` called memcpy for every atom id.
    let width = count_digits(n) as usize;
    let start = buf.len();
    if buf.capacity() - start < width {
        buf.reserve(width);
    }
    unsafe {
        let dst = buf.as_mut_ptr().add(start);
        write_digit_width(std::slice::from_raw_parts_mut(dst, width), n);
        buf.set_len(start + width);
    }
}

fn push_u128(buf: &mut Vec<u8>, mut n: u128) {
    if n <= u128::from(u64::MAX) {
        push_u64(buf, n as u64);
        return;
    }
    let mut tmp = [0u8; 40];
    let mut i = 40;
    while n > 0 {
        i -= 1;
        tmp[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    buf.extend_from_slice(&tmp[i..]);
}

fn push_str_line(buf: &mut Vec<u8>, text: &str) {
    buf.extend_from_slice(text.as_bytes());
    buf.push(b'\n');
}

fn push_component_line(buf: &mut Vec<u8>, label: &str, index: usize) {
    buf.extend_from_slice(label.as_bytes());
    buf.push(b' ');
    push_u64(buf, (index + 1) as u64);
    buf.push(b'\n');
}

fn push_f64(buf: &mut Vec<u8>, ryu: &mut ryu::Buffer, value: f64, format: FloatFormat) {
    match format {
        FloatFormat::DecimalPlaces(precision) => push_f64_prec(buf, value, precision),
        FloatFormat::RoundTrip => push_round_trip(buf, ryu, None, value),
    }
}

/// Shortest round-trip spelling. Finite values are written with `ryu::raw`
/// straight into `buf`. `slot` remembers a column so a repeated lattice
/// value is copied instead of formatted again.
fn push_round_trip(
    buf: &mut Vec<u8>,
    ryu: &mut ryu::Buffer,
    slot: Option<&mut FmtSlot>,
    value: f64,
) {
    if !value.is_finite() {
        let text = ryu.format(value);
        buf.extend_from_slice(text.as_bytes());
        return;
    }
    if let Some(slot) = slot {
        let bits = value.to_bits();
        if slot.bits == bits {
            if slot.state == 2 {
                buf.extend_from_slice(&slot.text[..slot.len as usize]);
                return;
            }
            if slot.state == 1 {
                let n = unsafe { ryu::raw::format64(value, slot.text.as_mut_ptr()) };
                debug_assert!(n <= 24);
                slot.len = n as u8;
                slot.state = 2;
                buf.extend_from_slice(&slot.text[..n]);
                return;
            }
        }
        write_finite(buf, value);
        slot.bits = bits;
        slot.state = 1;
        return;
    }
    write_finite(buf, value);
}

fn write_finite(buf: &mut Vec<u8>, value: f64) {
    // Thirty-two bytes covers the longest fixed decimal this path emits.
    // An exact frame slice often has less room left than that, and growing
    // it would move the bytes off the mapping, so a short tail uses a
    // stack slot and copies only the finished spelling.
    let spare = buf.capacity() - buf.len();
    if spare >= 32 {
        let start = buf.len();
        let n = unsafe {
            let dst = std::slice::from_raw_parts_mut(buf.as_mut_ptr().add(start), spare);
            match encode_fixed_decimal(value, dst) {
                Some(n) => n,
                None => ryu::raw::format64(value, dst.as_mut_ptr()),
            }
        };
        debug_assert!(n <= 24);
        unsafe { buf.set_len(start + n) };
        return;
    }
    if let Some((bytes, n)) = encode_fixed_decimal_into(value) {
        buf.extend_from_slice(&bytes[..n]);
        return;
    }
    let mut tmp = [0u8; 24];
    let n = unsafe { ryu::raw::format64(value, tmp.as_mut_ptr()) };
    debug_assert!(n <= 24);
    buf.extend_from_slice(&tmp[..n]);
}

/// Byte length of one round-trip spelling. Matches [`push_round_trip`].
fn round_trip_width(value: f64) -> usize {
    if !value.is_finite() {
        return ryu::Buffer::new().format(value).len();
    }
    let bits = value.to_bits();
    let sign = bits >> 63 != 0;
    let mag = f64::from_bits(bits & !(1u64 << 63));
    if let Some(n) = fixed_decimal_width(mag, sign) {
        return n;
    }
    if let Some((_, n)) = encode_fixed_decimal_into(value) {
        return n;
    }
    let mut tmp = [0u8; 24];
    unsafe { ryu::raw::format64(value, tmp.as_mut_ptr()) }
}

/// Length of [`encode_fixed_decimal`] when the value is an exact decimal
/// of at most six digits. `None` leaves the general formatter to measure.
fn fixed_decimal_width(mag: f64, sign: bool) -> Option<usize> {
    let sign_len = usize::from(sign);
    if mag == 0.0 {
        return Some(sign_len + 3);
    }
    let (n, places) = fixed_decimal_parts(mag)?;
    Some(sign_len + fixed_digits_len(n, places))
}

/// Shortest fixed decimal that matches `ryu`, when the value is an exact
/// integer or an exact fraction of at most six digits and ryu would not
/// switch to scientific form. `None` leaves the general formatter to run.
fn encode_fixed_decimal_into(value: f64) -> Option<([u8; 32], usize)> {
    let mut out = [0u8; 32];
    let n = encode_fixed_decimal(value, &mut out[..])?;
    Some((out, n))
}

/// The integer `k` near `scaled` whose quotient `k / scale` is `mag`
/// and whose exact distance to `mag * scale` is the smallest.
///
/// `mag * scale` rounded to f64 can land on the farther of two decimals
/// that parse back to `mag`. ryu prints the closer one.
fn closest_decimal(mag: f64, scaled: f64, scale: u64) -> Option<u64> {
    if !scaled.is_finite() || scaled > 1e16 {
        return None;
    }
    let center = round_half_away(scaled);
    let center = unsafe { center.to_int_unchecked::<u64>() };
    // Dividing the integer back in f64 is not the parse of the decimal.
    // A spelling round-trips when it is closer than half an ulp, which is
    // `scale / 2` in these units. The f64 product can sit two integers off
    // the closer spelling.
    let limit = (scale as u128) / 2;
    let mut best: Option<(u64, u128)> = None;
    for delta in -2i64..=2 {
        let k = center as i64 + delta;
        if k < 0 {
            continue;
        }
        let k = k as u64;
        let dist = decimal_distance(mag, scale, k);
        if dist >= limit {
            continue;
        }
        let replace = match best {
            None => true,
            Some((_, best_dist)) if dist < best_dist => true,
            // A tie is the even last digit, which is what ryu prints.
            Some((best_k, best_dist)) if dist == best_dist && best_k % 2 == 1 && k % 2 == 0 => true,
            _ => false,
        };
        if replace {
            best = Some((k, dist));
        }
    }
    best.map(|(k, _)| k)
}

/// `|mag * scale - k|` in units of the binary place of `mag`.
fn decimal_distance(mag: f64, scale: u64, k: u64) -> u128 {
    let bits = mag.to_bits();
    let field = ((bits >> 52) & 0x7ff) as i32;
    let (sig, exp) = if field == 0 {
        ((bits & ((1u64 << 52) - 1)) as u128, -1022 - 52)
    } else {
        (
            ((bits & ((1u64 << 52) - 1)) | (1u64 << 52)) as u128,
            field - 1023 - 52,
        )
    };
    let num = sig * scale as u128;
    if exp >= 0 {
        if exp >= 128 {
            return u128::MAX;
        }
        return (num << exp).abs_diff(k as u128);
    }
    let shift = (-exp) as u32;
    if shift >= 128 {
        return if k == 0 { num } else { u128::MAX };
    }
    num.abs_diff((k as u128) << shift)
}

/// Round a non-negative finite `scaled` half away from zero.
///
/// Values up to 2^53 use integer truncation, which matches `f64::round`
/// there. Larger values, still at most 1e16, use the libm rounding.
fn round_half_away(scaled: f64) -> f64 {
    const EXACT_INT: f64 = 9007199254740992.0;
    if scaled <= EXACT_INT {
        // `scaled` is finite and in `0.0..=2^53`, so the truncation fits.
        let trunc = unsafe { scaled.to_int_unchecked::<u64>() };
        let frac = scaled - trunc as f64;
        if frac >= 0.5 {
            (trunc + 1) as f64
        } else {
            trunc as f64
        }
    } else {
        scaled.round()
    }
}

/// `Some(n)` when `mag` is an integer in `1 .. 1e16`.
///
/// The exponent bits reject fractions without a saturating float-to-int.
fn exact_small_integer(mag: f64) -> Option<u64> {
    let bits = mag.to_bits();
    let exp = ((bits >> 52) & 0x7ff) as i32 - 1023;
    if !(0..=53).contains(&exp) {
        return None;
    }
    if exp < 52 {
        let frac = bits & ((1u64 << 52) - 1);
        let shift = (52 - exp) as u32;
        if frac & ((1u64 << shift) - 1) != 0 {
            return None;
        }
    }
    // The exponent gate puts `mag` in `1.0 .. 2^54`.
    let n = unsafe { mag.to_int_unchecked::<u64>() };
    if n < 10_000_000_000_000_000 && (n as f64).to_bits() == bits {
        Some(n)
    } else {
        None
    }
}

/// `(digits, decimal places)` of the shortest exact decimal of at most
/// six places, or `None` when [`encode_fixed_decimal`] must refuse.
fn fixed_decimal_parts(mag: f64) -> Option<(u64, u32)> {
    if let Some(n) = exact_small_integer(mag) {
        return Some((n, 0));
    }
    // An exact k-place decimal with k <= 6 is exact at 6 places too,
    // while 1e6 still fits. Coordinates land in this range.
    let scaled = mag * 1_000_000.0;
    if scaled <= 9007199254740992.0 {
        return accept_million(mag, scaled);
    }
    if scaled.is_finite() && scaled <= 1e16 {
        return accept_scaled(mag, scaled, 1_000_000.0, 6);
    }
    parts_below_million(mag)
}

/// Six-place probe for `scaled = mag * 1e6` at most 2^53.
fn accept_million(mag: f64, scaled: f64) -> Option<(u64, u32)> {
    let n = closest_decimal(mag, scaled, 1_000_000)?;
    let (n, places) = shorten(mag, n, 6);
    if places == 0 {
        return Some((n, 0));
    }
    let kk = count_digits(n) as i32 - places as i32;
    if kk > -5 && kk <= 16 {
        Some((n, places))
    } else {
        None
    }
}

/// Drop trailing zeros, then a decimal place when a shorter spelling
/// still round-trips. ryu keeps the shortest of those.
fn shorten(mag: f64, mut n: u64, mut places: u32) -> (u64, u32) {
    loop {
        while places > 0 && n.is_multiple_of(10) {
            n /= 10;
            places -= 1;
        }
        if places == 0 {
            return (n, 0);
        }
        let scale = 10u64.pow(places - 1);
        let base = n / 10;
        let limit = (scale as u128) / 2;
        let mut best: Option<(u64, u128)> = None;
        for k in [base.saturating_sub(1), base, base.saturating_add(1)] {
            let dist = decimal_distance(mag, scale, k);
            if dist >= limit {
                continue;
            }
            let replace = match best {
                None => true,
                Some((_, best_dist)) if dist < best_dist => true,
                Some((best_k, best_dist)) if dist == best_dist && best_k % 2 == 1 && k % 2 == 0 => {
                    true
                }
                _ => false,
            };
            if replace {
                best = Some((k, dist));
            }
        }
        let Some((k, _)) = best else {
            return (n, places);
        };
        if fixed_digits_len(k, places - 1) >= fixed_digits_len(n, places) {
            return (n, places);
        }
        n = k;
        places -= 1;
    }
}

/// `mag * 1e6` overflowed. A shorter scale can still be exact.
#[inline(never)]
fn parts_below_million(mag: f64) -> Option<(u64, u32)> {
    let mut scale = 10.0f64;
    for d in 1u32..=5 {
        let scaled = mag * scale;
        if !scaled.is_finite() || scaled > 1e16 {
            break;
        }
        if let Some(parts) = accept_scaled(mag, scaled, scale, d) {
            return Some(parts);
        }
        scale *= 10.0;
    }
    None
}

fn accept_scaled(mag: f64, scaled: f64, scale: f64, places: u32) -> Option<(u64, u32)> {
    let scale_int = scale as u64;
    let n = closest_decimal(mag, scaled, scale_int)?;
    let (n, places) = shorten(mag, n, places);
    if places == 0 {
        if n >= 10u64.pow(16) {
            return None;
        }
        return Some((n, 0));
    }
    let digits = count_digits(n);
    let kk = digits as i32 - places as i32;
    if !(kk > -5 && kk <= 16) {
        return None;
    }
    Some((n, places))
}

fn encode_fixed_decimal(value: f64, out: &mut [u8]) -> Option<usize> {
    let bits = value.to_bits();
    let sign = bits >> 63 != 0;
    let mag = f64::from_bits(bits & !(1u64 << 63));
    if mag == 0.0 {
        let text: &[u8] = if sign { b"-0.0" } else { b"0.0" };
        out[..text.len()].copy_from_slice(text);
        return Some(text.len());
    }
    let (n, places) = fixed_decimal_parts(mag)?;
    Some(write_fixed_digits(out, sign, n, places))
}

fn fixed_digits_len(n: u64, places: u32) -> usize {
    let digits = count_digits(n) as usize;
    if places == 0 {
        return digits + 2;
    }
    let kk = digits as i32 - places as i32;
    if kk > 0 {
        digits + 1
    } else {
        2 + (-kk) as usize + digits
    }
}

fn count_digits(n: u64) -> u32 {
    if n == 0 { 1 } else { n.ilog10() + 1 }
}

/// Write exactly `dst.len()` digits of `n`, with leading zeros.
fn write_digit_width(dst: &mut [u8], mut n: u64) {
    let mut i = dst.len();
    while i >= 2 {
        i -= 2;
        let q = n / 100;
        let r = (n % 100) as usize;
        dst[i] = DIGIT_PAIRS[r * 2];
        dst[i + 1] = DIGIT_PAIRS[r * 2 + 1];
        n = q;
    }
    if i == 1 {
        dst[0] = b'0' + (n % 10) as u8;
    }
}

fn write_fixed_digits(out: &mut [u8], sign: bool, n: u64, places: u32) -> usize {
    const POW10: [u64; 7] = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000];
    let digits = count_digits(n) as usize;
    let mut at = 0usize;
    if sign {
        out[at] = b'-';
        at += 1;
    }
    if places == 0 {
        write_digit_width(&mut out[at..at + digits], n);
        at += digits;
        out[at] = b'.';
        out[at + 1] = b'0';
        return at + 2;
    }
    let kk = digits as i32 - places as i32;
    if kk > 0 {
        let cut = kk as usize;
        let scale = POW10[places as usize];
        write_digit_width(&mut out[at..at + cut], n / scale);
        out[at + cut] = b'.';
        write_digit_width(&mut out[at + cut + 1..at + digits + 1], n % scale);
        return at + digits + 1;
    }
    out[at] = b'0';
    out[at + 1] = b'.';
    at += 2;
    for _ in 0..(-kk) {
        out[at] = b'0';
        at += 1;
    }
    write_digit_width(&mut out[at..at + digits], n);
    at + digits
}

/// Fixed-point `f64` with `prec` digits after the decimal, matching `{:.prec$}`.
/// Non-finite values and `prec > 17` fall back to `std::fmt`.
fn push_f64_prec(buf: &mut Vec<u8>, v: f64, prec: usize) {
    // The six-decimal path uses fixed-point arithmetic; other precisions
    // use the standard formatter.
    if !v.is_finite() || prec != 6 {
        let _ = write!(buf, "{v:.prec$}");
        return;
    }
    if v.is_sign_negative() {
        buf.push(b'-');
    }
    let ax = v.abs();
    if prec == 0 {
        push_u128(buf, ax.round() as u128);
        return;
    }
    let scale = 10u128.pow(prec as u32);
    let n = (ax * scale as f64).round() as u128;
    let int_part = n / scale;
    let frac = n % scale;
    push_u128(buf, int_part);
    buf.push(b'.');
    let mut tmp = [b'0'; 20];
    let mut x = frac;
    let mut i = prec;
    while i > 0 {
        i -= 1;
        tmp[i] = b'0' + (x % 10) as u8;
        x /= 10;
    }
    buf.extend_from_slice(&tmp[..prec]);
}

const WIDE_ATOM_GRAIN: usize = 4096;

/// Formatting buffers survive from one wide write to the next. Dropping
/// them every call faulted a fresh 20 MB and showed up between the format
/// time and the campaign sample.
fn take_format_buf(cap: usize) -> Vec<u8> {
    let mut pool = FORMAT_BUFS.lock().unwrap_or_else(|err| err.into_inner());
    if let Some(mut buf) = pool.pop() {
        if buf.capacity() < cap {
            buf.reserve(cap);
        }
        buf.clear();
        return buf;
    }
    drop(pool);
    Vec::with_capacity(cap)
}

fn give_format_buf(buf: Vec<u8>) {
    let mut pool = FORMAT_BUFS.lock().unwrap_or_else(|err| err.into_inner());
    if pool.len() < 128 {
        pool.push(buf);
    }
}

static FORMAT_BUFS: std::sync::Mutex<Vec<Vec<u8>>> = std::sync::Mutex::new(Vec::new());

/// Base of a contiguous `xyz` slab, three `f64`s per atom in order.
///
/// Parsed frames and the binding slab store coordinates that way. Owned
/// boxes are separate allocations and stay on the pointer walk.
fn coord_slab(atoms: &[crate::types::AtomDatum]) -> Option<*const f64> {
    let n = atoms.len();
    if n < 2 {
        return None;
    }
    let base = atoms[0].coord_ptr();
    if base.is_null() {
        return None;
    }
    // Three probes. A contiguous slab (the parse buffer, the binding
    // slab) hits all of them. Owned boxes miss the second atom.
    let aligned = |index: usize| unsafe { atoms[index].coord_ptr() == base.add(index * 3) };
    if aligned(1) && aligned(n / 2) && aligned(n - 1) {
        Some(base)
    } else {
        None
    }
}

fn load_xyz(atom: &crate::types::AtomDatum, slab: Option<*const f64>, index: usize) -> [f64; 3] {
    if let Some(base) = slab {
        unsafe {
            let ptr = base.add(index * 3);
            [*ptr, *ptr.add(1), *ptr.add(2)]
        }
    } else {
        [atom.x(), atom.y(), atom.z()]
    }
}

struct MotionFmt<'a> {
    ryu: &'a mut ryu::Buffer,
    slots: &'a mut [FmtSlot; 3],
    vel_slots: &'a mut [FmtSlot; 3],
}

fn push_atom_motion(
    coord: &mut Vec<u8>,
    vel: Option<&mut Vec<u8>>,
    fmt: MotionFmt<'_>,
    xyz: [f64; 3],
    atom: &crate::types::AtomDatum,
    prec: FloatFormat,
    spec_version: u32,
) {
    let MotionFmt {
        ryu,
        slots,
        vel_slots,
    } = fmt;
    let fixed = written_fixed_flag(atom.fixed(), spec_version);
    push_xyz_line(coord, ryu, slots, xyz, prec, fixed, atom.atom_id);
    if let Some(vel) = vel {
        let [vx, vy, vz] = atom.velocity().unwrap_or([0.0; 3]);
        // A separate column cache. Sharing the coordinate slots made every
        // velocity miss and then evict the coordinate spelling.
        push_xyz_line(vel, ryu, vel_slots, [vx, vy, vz], prec, fixed, atom.atom_id);
    }
}

/// File header and the species lines that belong in front of `frame`'s coordinates.
///
/// The bytes match a binding rewrite up to the first coordinate row.
pub(crate) fn binding_header_bytes(frame: &ConFrame) -> Result<Vec<u8>, WriteError> {
    let spec = frame.header.spec_version.max(crate::CON_SPEC_VERSION);
    let meta = binding_metadata(frame);
    let mut writer = ConFrameWriter::new(Vec::<u8>::new());
    writer.refresh_metadata_cache(
        spec,
        &meta,
        [
            frame.has_velocities(),
            frame.has_forces(),
            frame.has_energies(),
            frame.has_charges(),
            frame.has_spins(),
            frame.has_magmoms(),
            frame.has_displacements(),
            frame.has_spreads(),
        ],
    )?;
    let (boxl, angles) = match frame.header.lattice_vectors() {
        Some(vecs) => crate::types::lengths_and_angles(vecs),
        None => (frame.header.boxl, frame.header.angles),
    };
    let prec = FloatFormat::RoundTrip;
    let mut buf = Vec::with_capacity(256);
    push_str_line(&mut buf, &frame.header.prebox_header.user);
    if spec < 2 {
        push_str_line(&mut buf, frame.header.prebox_header.metadata_line());
    } else {
        let line = writer
            .metadata_cache
            .as_ref()
            .expect("metadata")
            .serialized
            .as_bytes();
        buf.extend_from_slice(line);
        buf.push(b'\n');
    }
    let ryu = &mut writer.ryu;
    push_f64(&mut buf, ryu, boxl[0], prec);
    buf.push(b' ');
    push_f64(&mut buf, ryu, boxl[1], prec);
    buf.push(b' ');
    push_f64(&mut buf, ryu, boxl[2], prec);
    buf.push(b'\n');
    push_f64(&mut buf, ryu, angles[0], prec);
    buf.push(b' ');
    push_f64(&mut buf, ryu, angles[1], prec);
    buf.push(b' ');
    push_f64(&mut buf, ryu, angles[2], prec);
    buf.push(b'\n');
    push_str_line(&mut buf, &frame.header.postbox_header[0]);
    push_str_line(&mut buf, &frame.header.postbox_header[1]);
    push_u64(&mut buf, frame.header.natm_types as u64);
    buf.push(b'\n');
    for (i, n) in frame.header.natms_per_type.iter().enumerate() {
        if i > 0 {
            buf.push(b' ');
        }
        push_u64(&mut buf, *n as u64);
    }
    buf.push(b'\n');
    for (i, m) in frame.header.masses_per_type.iter().enumerate() {
        if i > 0 {
            buf.push(b' ');
        }
        push_f64(&mut buf, ryu, *m, prec);
    }
    buf.push(b'\n');
    Ok(buf)
}

/// Coordinate lines for atoms `begin..end`, including a species header when
/// the range contains the first atom of that species.
pub(crate) fn format_coord_range(frame: &ConFrame, begin: usize, end: usize) -> Vec<u8> {
    let spec = frame.header.spec_version.max(crate::CON_SPEC_VERSION);
    let prec = FloatFormat::RoundTrip;
    let mut buf = Vec::with_capacity((end - begin).saturating_mul(32) + 64);
    let mut ryu = ryu::Buffer::new();
    let mut slots = [FmtSlot::new(); 3];
    let mut vel_slots = [FmtSlot::new(); 3];
    let mut offset = 0usize;
    for (type_idx, &count) in frame.header.natms_per_type.iter().enumerate() {
        let type_end = offset + count;
        let from = begin.max(offset);
        let to = end.min(type_end);
        if from < to {
            if from == offset {
                let symbol = frame.atom_data[offset].symbol.as_ref();
                push_str_line(&mut buf, symbol);
                push_component_line(&mut buf, "Coordinates of Component", type_idx);
            }
            let atoms = &frame.atom_data[from..to];
            let slab = coord_slab(atoms);
            for (index, atom) in atoms.iter().enumerate() {
                push_atom_motion(
                    &mut buf,
                    None,
                    MotionFmt {
                        ryu: &mut ryu,
                        slots: &mut slots,
                        vel_slots: &mut vel_slots,
                    },
                    load_xyz(atom, slab, index),
                    atom,
                    prec,
                    spec,
                );
            }
        }
        offset = type_end;
    }
    buf
}

/// Coordinate lines for `atoms`, using the same formatter as a frame write.
///
/// One pass, private buffer. Callers that split a frame across ranks write
/// these bytes at the offset from an exclusive scan of the lengths.
pub fn format_coordinate_lines(atoms: &[crate::types::AtomDatum]) -> Result<Vec<u8>, WriteError> {
    let mut buf = take_format_buf(atoms.len().saturating_mul(48));
    let mut ryu = ryu::Buffer::new();
    let mut slots = [FmtSlot::new(); 3];
    append_coord_rows(
        &mut buf,
        LineFmt {
            ryu: &mut ryu,
            slots: &mut slots,
        },
        atoms,
        FloatFormat::RoundTrip,
        2,
        1,
        AppendOut {
            mapped: false,
            force_map: false,
            stream: None,
            vel: None,
        },
    )?;
    Ok(buf)
}

/// Return a buffer from [`format_coordinate_lines`] so the next format
/// reuses the pages instead of faulting a fresh allocation.
pub fn recycle_format_buffer(buf: Vec<u8>) {
    give_format_buf(buf);
}

fn append_velocity_lines(
    buf: &mut Vec<u8>,
    ryu: &mut ryu::Buffer,
    atoms: &[crate::types::AtomDatum],
    prec: FloatFormat,
    spec_version: u32,
) {
    let mut vel_slots = [FmtSlot::new(); 3];
    for atom in atoms {
        let [vx, vy, vz] = atom.velocity().unwrap_or([0.0; 3]);
        push_xyz_line(
            buf,
            ryu,
            &mut vel_slots,
            [vx, vy, vz],
            prec,
            written_fixed_flag(atom.fixed(), spec_version),
            atom.atom_id,
        );
    }
}

type MotionSlot = std::sync::Mutex<Option<(Vec<u8>, Vec<u8>)>>;

struct LineFmt<'a> {
    ryu: &'a mut ryu::Buffer,
    slots: &'a mut [FmtSlot; 3],
}

struct AppendOut<'a> {
    mapped: bool,
    force_map: bool,
    stream: Option<&'a mut File>,
    vel: Option<&'a mut Vec<u8>>,
}

fn append_coord_rows(
    buf: &mut Vec<u8>,
    fmt: LineFmt<'_>,
    atoms: &[crate::types::AtomDatum],
    prec: FloatFormat,
    spec_version: u32,
    workers: usize,
    out: AppendOut<'_>,
) -> Result<(), WriteError> {
    let LineFmt { ryu, slots } = fmt;
    let AppendOut {
        mapped,
        force_map,
        stream,
        mut vel,
    } = out;
    let want_vel = vel.is_some();
    if let Some(file) = stream {
        if mapped && !atoms.is_empty() {
            file.write_all(buf).map_err(WriteError::Io)?;
            buf.clear();
            let vel_bytes = stream_coord_rows(
                file,
                atoms,
                workers,
                prec,
                spec_version,
                want_vel,
                force_map,
            )?;
            if let Some(dest) = vel.as_mut() {
                dest.extend_from_slice(&vel_bytes);
            }
            return Ok(());
        }
    }
    if workers < 2 || atoms.len() < WIDE_ATOM_GRAIN {
        let mut vel_slots = [FmtSlot::new(); 3];
        let slab = coord_slab(atoms);
        for (index, atom) in atoms.iter().enumerate() {
            push_atom_motion(
                buf,
                vel.as_deref_mut(),
                MotionFmt {
                    ryu,
                    slots,
                    vel_slots: &mut vel_slots,
                },
                load_xyz(atom, slab, index),
                atom,
                prec,
                spec_version,
            );
        }
        return Ok(());
    }
    #[cfg(feature = "parallel")]
    {
        // Four ranges per worker, pulled with one atomic. A static range
        // made the preempted core own the whole eighth of the frame, and
        // rayon's own steal left a millisecond idle between pieces. The
        // atomic handoff is the balance; the pool threads stay pinned.
        let groups = workers.saturating_mul(4).max(workers);
        let chunk = atoms.len().div_ceil(groups).max(1);
        let nparts = atoms.len().div_ceil(chunk);
        let bad_ids = std::sync::atomic::AtomicBool::new(false);
        let next = std::sync::atomic::AtomicUsize::new(0);
        let parts: Vec<MotionSlot> = (0..nparts).map(|_| std::sync::Mutex::new(None)).collect();
        crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            (0..workers).into_par_iter().for_each(|_| {
                let mut ryu = ryu::Buffer::new();
                let mut slots = [FmtSlot::new(); 3];
                let mut vel_slots = [FmtSlot::new(); 3];
                loop {
                    let index = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= nparts {
                        break;
                    }
                    let start = index * chunk;
                    let end = (start + chunk).min(atoms.len());
                    let group = &atoms[start..end];
                    let mut local = Vec::with_capacity(group.len().saturating_mul(48));
                    let mut local_vel = if want_vel {
                        Vec::with_capacity(group.len().saturating_mul(48))
                    } else {
                        Vec::new()
                    };
                    let slab = coord_slab(group);
                    for (offset, atom) in group.iter().enumerate() {
                        if atom.atom_id != (start + offset) as u64 {
                            bad_ids.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                        push_atom_motion(
                            &mut local,
                            if want_vel { Some(&mut local_vel) } else { None },
                            MotionFmt {
                                ryu: &mut ryu,
                                slots: &mut slots,
                                vel_slots: &mut vel_slots,
                            },
                            load_xyz(atom, slab, offset),
                            atom,
                            prec,
                            spec_version,
                        );
                    }
                    *parts[index].lock().expect("format part") = Some((local, local_vel));
                }
            });
        });
        if bad_ids.load(std::sync::atomic::Ordering::Relaxed) {
            ensure_unique_ids(atoms, 1)?;
        }
        let mut coord_len = 0usize;
        let mut vel_len = 0usize;
        for part in &parts {
            let guard = part.lock().expect("format part");
            if let Some((coord, rows)) = guard.as_ref() {
                coord_len += coord.len();
                vel_len += rows.len();
            }
        }
        let coord_at = buf.len();
        buf.reserve(coord_len);
        if let Some(dest) = vel.as_deref_mut() {
            dest.reserve(vel_len);
        }
        if coord_len > 0 {
            let coord_ptr = buf.as_mut_ptr() as usize;
            let mut jobs = Vec::with_capacity(nparts);
            let mut at = coord_at;
            for part in &parts {
                let guard = part.lock().expect("format part");
                let Some((coord, _)) = guard.as_ref() else {
                    continue;
                };
                let n = coord.len();
                if n == 0 {
                    continue;
                }
                jobs.push((coord.as_ptr() as usize, coord_ptr + at, n));
                at += n;
            }
            let next_copy = std::sync::atomic::AtomicUsize::new(0);
            crate::parser::on_pool(workers, || {
                use rayon::prelude::*;
                (0..workers).into_par_iter().for_each(|_| {
                    loop {
                        let index = next_copy.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        if index >= jobs.len() {
                            break;
                        }
                        let (src, dest, n) = jobs[index];
                        unsafe {
                            std::ptr::copy_nonoverlapping(src as *const u8, dest as *mut u8, n);
                        }
                    }
                });
            });
            // SAFETY: the copies covered coord_len bytes past coord_at.
            // The length stays put until then, so a panic drops only the
            // bytes that were already initialised.
            unsafe { buf.set_len(coord_at + coord_len) };
        }
        if let Some(dest) = vel.as_mut() {
            for part in &parts {
                let guard = part.lock().expect("format part");
                if let Some((_, rows)) = guard.as_ref() {
                    dest.extend_from_slice(rows);
                }
            }
        }
        Ok(())
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = workers;
        let mut vel_slots = [FmtSlot::new(); 3];
        let slab = coord_slab(atoms);
        for (index, atom) in atoms.iter().enumerate() {
            push_atom_motion(
                buf,
                vel.as_deref_mut(),
                MotionFmt {
                    ryu,
                    slots,
                    vel_slots: &mut vel_slots,
                },
                load_xyz(atom, slab, index),
                atom,
                prec,
                spec_version,
            );
        }
        Ok(())
    }
}

/// Logical CPUs divided by SMT siblings.
///
/// `available_parallelism` counts hardware threads. The sibling list under
/// `/sys/devices/system/cpu/cpu0/topology` is one entry per SMT thread on
/// that core. This machine has eight cores and one sibling each, so the
/// count is 8. A copy thread is started only when two threads per worker
/// still land on distinct physical cores. Sixteen threads on these eight
/// cores slowed the format; that is oversubscription, not SMT.
fn physical_cores() -> usize {
    let logical = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    let siblings =
        std::fs::read_to_string("/sys/devices/system/cpu/cpu0/topology/thread_siblings_list")
            .ok()
            .map(|text| {
                text.split([',', '-'])
                    .filter(|piece| !piece.trim().is_empty())
                    .count()
            })
            .filter(|n| *n > 0)
            .unwrap_or(1);
    (logical / siblings).max(1)
}

fn side_copy_workers(workers: usize) -> bool {
    // The side copy maps the file. Miri writes through `pwrite_full`.
    #[cfg(miri)]
    {
        let _ = workers;
        return false;
    }
    #[cfg(not(miri))]
    {
        workers >= 2 && workers.saturating_mul(2) <= physical_cores()
    }
}

/// tmpfs wants many small ranges so the writer starts early. The page
/// cache wants fewer writes.
/// Ask for huge pages on a tmpfs that was mounted to allow them.
///
/// `MADV_POPULATE_WRITE` was slower than the plain first touch on both
/// a normal tmpfs and `huge=within_size`, so this does not pre-fault.
/// `MADV_HUGEPAGE` is a no-op unless the mount (or `shmem_enabled=advise`)
/// is willing to use huge pages.
pub(crate) fn advise_shared_store(file: &File, ptr: *mut u8, len: usize) {
    #[cfg(all(target_os = "linux", not(miri)))]
    if len >= 2 * 1024 * 1024 && mount_requests_huge(file) {
        unsafe {
            let _ = libc::madvise(ptr.cast::<libc::c_void>(), len, libc::MADV_HUGEPAGE);
        }
    }
    #[cfg(any(not(target_os = "linux"), miri))]
    {
        let _ = (file, ptr, len);
    }
}

#[cfg(all(target_os = "linux", not(miri)))]
fn mount_requests_huge(file: &File) -> bool {
    use std::os::fd::AsRawFd;
    let Ok(linked) = std::fs::read_link(format!("/proc/self/fd/{}", file.as_raw_fd())) else {
        return false;
    };
    let Ok(table) = std::fs::read_to_string("/proc/mounts") else {
        return false;
    };
    let path = linked.to_string_lossy();
    let mut best_len = 0usize;
    let mut huge = false;
    for line in table.lines() {
        let mut fields = line.split_whitespace();
        let _device = fields.next();
        let Some(raw_mount) = fields.next() else {
            continue;
        };
        let mount = raw_mount.replace("\\040", " ");
        if mount.len() >= best_len && path.starts_with(&mount) {
            let _fstype = fields.next();
            let options = fields.next().unwrap_or("");
            best_len = mount.len();
            huge = options.split(',').any(|opt| {
                matches!(
                    opt,
                    "huge=within_size" | "huge=always" | "huge=advise" | "huge=force"
                )
            });
        }
    }
    huge
}

pub(crate) fn file_is_tmpfs(file: &File) -> bool {
    // tmpfs is a Linux filesystem. Miri has no `fstatfs`. Treating the
    // file as a normal one only changes how many ranges the pipeline formats.
    #[cfg(all(not(miri), target_os = "linux"))]
    {
        use std::os::fd::AsRawFd;
        let mut stat = unsafe { std::mem::zeroed::<libc::statfs>() };
        let rc = unsafe { libc::fstatfs(file.as_raw_fd(), &mut stat) };
        rc == 0 && stat.f_type == 0x01021994
    }
    #[cfg(any(miri, not(target_os = "linux")))]
    {
        let _ = file;
        false
    }
}

/// One ordered `pwrite` overlapping the format.
///
/// The caller thread writes finished ranges in file order. The other
/// `workers - 1` threads format. A fresh file's page faults are about
/// 0.006 s for these bytes, which is the whole sink; doing that copy at
/// the same time as the format is what removes it from the wall clock.
fn stream_coord_pipeline(
    file: &mut File,
    atoms: &[crate::types::AtomDatum],
    workers: usize,
    prec: FloatFormat,
    spec_version: u32,
    want_vel: bool,
) -> Result<Vec<u8>, WriteError> {
    let workers = workers.max(2).min(atoms.len().max(1));
    let formatters = workers - 1;
    // Smaller ranges on tmpfs: the first range is one core's worth of
    // work, and the single writer starts while the rest are formatted.
    // The page cache wants fewer, larger writes; a syscall per 90 KB lost
    // to the one-shot `pwrite` of the same bytes.
    let groups = if file_is_tmpfs(file) {
        workers.saturating_mul(32)
    } else {
        workers.saturating_mul(8)
    }
    .max(workers);
    let chunk = atoms.len().div_ceil(groups).max(1);
    let nparts = atoms.len().div_ceil(chunk);
    let base = file.stream_position().map_err(WriteError::Io)?;
    let out = file.try_clone().map_err(WriteError::Io)?;
    let next = std::sync::atomic::AtomicUsize::new(0);
    let bad_ids = std::sync::atomic::AtomicBool::new(false);
    let slots: Vec<MotionSlot> = (0..nparts).map(|_| std::sync::Mutex::new(None)).collect();
    let flag = &bad_ids;
    let (end, mut vel_bytes) = std::thread::scope(|scope| -> Result<_, WriteError> {
        let mut handles = Vec::with_capacity(formatters);
        for worker in 0..formatters {
            let next = &next;
            let slots = &slots;
            handles.push(scope.spawn(move || {
                // Core 0 stays free for the writer.
                crate::parser::pin_worker(worker + 1);
                let mut ryu = ryu::Buffer::new();
                let mut slots_fmt = [FmtSlot::new(); 3];
                let mut vel_slots = [FmtSlot::new(); 3];
                loop {
                    let index = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= nparts {
                        break;
                    }
                    let start = index * chunk;
                    let end = (start + chunk).min(atoms.len());
                    let group = &atoms[start..end];
                    let mut coord = Vec::with_capacity(group.len().saturating_mul(48));
                    let mut vel = if want_vel {
                        Vec::with_capacity(group.len().saturating_mul(48))
                    } else {
                        Vec::new()
                    };
                    let slab = coord_slab(group);
                    for (offset, atom) in group.iter().enumerate() {
                        if atom.atom_id != (start + offset) as u64 {
                            flag.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                        push_atom_motion(
                            &mut coord,
                            if want_vel { Some(&mut vel) } else { None },
                            MotionFmt {
                                ryu: &mut ryu,
                                slots: &mut slots_fmt,
                                vel_slots: &mut vel_slots,
                            },
                            load_xyz(atom, slab, offset),
                            atom,
                            prec,
                            spec_version,
                        );
                    }
                    *slots[index].lock().expect("format slot") = Some((coord, vel));
                }
            }));
        }
        let mut offset = base;
        let mut vel_bytes = Vec::new();
        // The writer owns core 0. Leaving it free to wander put it on
        // a formatter's core and stretched the copy. The caller's mask
        // is restored even when a write fails.
        #[cfg(all(not(miri), target_os = "linux"))]
        let mut old_affinity = unsafe { std::mem::zeroed::<libc::cpu_set_t>() };
        #[cfg(all(not(miri), target_os = "linux"))]
        unsafe {
            libc::sched_getaffinity(0, std::mem::size_of::<libc::cpu_set_t>(), &mut old_affinity);
        }
        crate::parser::pin_worker(0);
        let written = (|| -> Result<_, WriteError> {
            for slot in &slots {
                let (coord, vel) = loop {
                    if let Some(part) = slot.lock().expect("format slot").take() {
                        break part;
                    }
                    std::hint::spin_loop();
                };
                pwrite_full(&out, &coord, offset).map_err(WriteError::Io)?;
                offset = offset.checked_add(coord.len() as u64).ok_or_else(|| {
                    WriteError::Io(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "coordinate block is too large",
                    ))
                })?;
                if want_vel {
                    vel_bytes.extend_from_slice(&vel);
                }
            }
            Ok(())
        })();
        #[cfg(all(not(miri), target_os = "linux"))]
        unsafe {
            libc::sched_setaffinity(0, std::mem::size_of::<libc::cpu_set_t>(), &old_affinity);
        }
        written?;
        for handle in handles {
            if handle.join().is_err() {
                return Err(WriteError::Io(io::Error::other("formatter panicked")));
            }
        }
        Ok((offset, vel_bytes))
    })?;
    // `pwrite` extends the file to the last byte it stored and leaves any
    // older tail in place. The mapped path truncates to the same end.
    file.set_len(end).map_err(WriteError::Io)?;
    file.seek(SeekFrom::Start(end)).map_err(WriteError::Io)?;
    if bad_ids.load(std::sync::atomic::Ordering::Relaxed) {
        ensure_unique_ids(atoms, 1)?;
    }
    if !want_vel {
        vel_bytes.clear();
    }
    Ok(vel_bytes)
}

/// Bytes one coordinate line can occupy.
///
/// Round-trip spellings fit in 128. A fixed number of decimal places can
/// be hundreds of digits, and the mapped reserve has to hold that line or
/// the other workers spin forever waiting for a length that is never stored.
fn mapped_line_budget(prec: FloatFormat) -> usize {
    match prec {
        FloatFormat::RoundTrip => 128,
        FloatFormat::DecimalPlaces(places) => {
            let float = 1usize
                .saturating_add(309)
                .saturating_add(1)
                .saturating_add(places);
            float.saturating_mul(3).saturating_add(4 + 1 + 1 + 20 + 1)
        }
    }
}

fn stream_coord_rows(
    file: &mut File,
    atoms: &[crate::types::AtomDatum],
    workers: usize,
    prec: FloatFormat,
    spec_version: u32,
    want_vel: bool,
    force_map: bool,
) -> Result<Vec<u8>, WriteError> {
    // Spare cores copy into a shared mapping while later ranges format.
    // With no spare core, one thread `pwrite`s finished ranges in order
    // and the others keep formatting. `map_rows` still forces the mapping.
    let workers = workers.max(1).min(atoms.len().max(1));
    let side_copies = side_copy_workers(workers);
    if !side_copies && !force_map {
        return stream_coord_pipeline(file, atoms, workers, prec, spec_version, want_vel);
    }
    let groups = if side_copies {
        workers.saturating_mul(8).max(workers)
    } else {
        workers.saturating_mul(4).max(workers)
    };
    let chunk = atoms.len().div_ceil(groups).max(1);
    let nparts = atoms.len().div_ceil(chunk);
    let base = file.stream_position().map_err(WriteError::Io)?;
    let line_budget = mapped_line_budget(prec);
    let upper = atoms.len().checked_mul(line_budget).ok_or_else(|| {
        WriteError::Io(io::Error::new(
            io::ErrorKind::InvalidData,
            "coordinate block is too large",
        ))
    })?;
    let reserve_end = base.checked_add(upper as u64).ok_or_else(|| {
        WriteError::Io(io::Error::new(
            io::ErrorKind::InvalidData,
            "coordinate block is too large",
        ))
    })?;
    let mut map = {
        file.set_len(reserve_end).map_err(WriteError::Io)?;
        Some(unsafe { memmap2::MmapMut::map_mut(&*file).map_err(WriteError::Io)? })
    };
    let dest_base = map
        .as_mut()
        .map(|mapping| mapping.as_mut_ptr() as usize + base as usize)
        .unwrap_or(0);
    let lengths: Vec<std::sync::atomic::AtomicU64> = (0..nparts)
        .map(|_| std::sync::atomic::AtomicU64::new(0))
        .collect();
    let bad_ids = std::sync::atomic::AtomicBool::new(false);
    let failed = std::sync::atomic::AtomicBool::new(false);
    let next_job = std::sync::atomic::AtomicUsize::new(0);
    let produced = std::sync::atomic::AtomicUsize::new(0);
    let copies: std::sync::Mutex<Vec<(Vec<u8>, usize)>> = std::sync::Mutex::new(Vec::new());
    let ready = std::sync::Condvar::new();
    let vel_parts: Vec<std::sync::Mutex<Option<Vec<u8>>>> =
        (0..nparts).map(|_| std::sync::Mutex::new(None)).collect();
    let flag = &bad_ids;
    std::thread::scope(|scope| -> Result<(), WriteError> {
        let mut copiers = Vec::with_capacity(workers);
        if side_copies {
            for copier in 0..workers {
                let copies = &copies;
                let ready = &ready;
                let produced = &produced;
                copiers.push(scope.spawn(move || {
                    // Spare cores only. The formatter already owns `0..workers`.
                    crate::parser::pin_worker(workers + copier);
                    loop {
                        let job = {
                            let mut queue = copies.lock().expect("copies");
                            loop {
                                if let Some(job) = queue.pop() {
                                    break Some(job);
                                }
                                if produced.load(std::sync::atomic::Ordering::Acquire) == nparts {
                                    break None;
                                }
                                queue = ready.wait(queue).expect("copies");
                            }
                        };
                        let Some((coord, offset)) = job else {
                            break;
                        };
                        let n = coord.len();
                        if n > 0 {
                            unsafe {
                                std::ptr::copy_nonoverlapping(
                                    coord.as_ptr(),
                                    (dest_base + offset) as *mut u8,
                                    n,
                                );
                            }
                        }
                        give_format_buf(coord);
                    }
                }));
            }
        }
        let mut formatters = Vec::with_capacity(workers);
        for worker in 0..workers {
            let lengths = &lengths;
            let next_job = &next_job;
            let vel_parts = &vel_parts;
            let copies = &copies;
            let ready = &ready;
            let produced = &produced;
            let failed = &failed;
            formatters.push(scope.spawn(move || -> Result<(), WriteError> {
                crate::parser::pin_worker(worker);
                let mut ryu = ryu::Buffer::new();
                let mut slots = [FmtSlot::new(); 3];
                let mut vel_slots = [FmtSlot::new(); 3];
                loop {
                    let index = next_job.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= nparts {
                        break;
                    }
                    let start = index * chunk;
                    let end = (start + chunk).min(atoms.len());
                    let group = &atoms[start..end];
                    let mut coord = if side_copies {
                        take_format_buf(group.len().saturating_mul(48))
                    } else {
                        Vec::with_capacity(group.len().saturating_mul(48))
                    };
                    let mut vel = if want_vel {
                        Vec::with_capacity(group.len().saturating_mul(48))
                    } else {
                        Vec::new()
                    };
                    let slab = coord_slab(group);
                    for (offset, atom) in group.iter().enumerate() {
                        if atom.atom_id != (start + offset) as u64 {
                            flag.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                        push_atom_motion(
                            &mut coord,
                            if want_vel { Some(&mut vel) } else { None },
                            MotionFmt {
                                ryu: &mut ryu,
                                slots: &mut slots,
                                vel_slots: &mut vel_slots,
                            },
                            load_xyz(atom, slab, offset),
                            atom,
                            prec,
                            spec_version,
                        );
                    }
                    let n = coord.len();
                    if n > group.len().saturating_mul(line_budget) {
                        // Publish a zero length so a later range stops waiting,
                        // and do it after the failure flag so that range does
                        // not copy at the dummy offset.
                        failed.store(true, std::sync::atomic::Ordering::Release);
                        lengths[index].store(1, std::sync::atomic::Ordering::Release);
                        return Err(WriteError::Io(io::Error::other(
                            "coordinate line exceeded the mapped reserve",
                        )));
                    }
                    lengths[index].store(n as u64 + 1, std::sync::atomic::Ordering::Release);
                    let mut offset = 0usize;
                    for length in lengths.iter().take(index) {
                        loop {
                            if failed.load(std::sync::atomic::Ordering::Acquire) {
                                return Err(WriteError::Io(io::Error::other(
                                    "coordinate line exceeded the mapped reserve",
                                )));
                            }
                            let known = length.load(std::sync::atomic::Ordering::Acquire);
                            if known != 0 {
                                if failed.load(std::sync::atomic::Ordering::Acquire) {
                                    return Err(WriteError::Io(io::Error::other(
                                        "coordinate line exceeded the mapped reserve",
                                    )));
                                }
                                offset += (known - 1) as usize;
                                break;
                            }
                            std::hint::spin_loop();
                        }
                    }
                    if side_copies {
                        let mut queue = copies.lock().expect("copies");
                        queue.push((coord, offset));
                    } else {
                        let n = coord.len();
                        if n > 0 {
                            unsafe {
                                std::ptr::copy_nonoverlapping(
                                    coord.as_ptr(),
                                    (dest_base + offset) as *mut u8,
                                    n,
                                );
                            }
                        }
                    }
                    if side_copies {
                        produced.fetch_add(1, std::sync::atomic::Ordering::Release);
                        ready.notify_one();
                    }
                    if want_vel {
                        *vel_parts[index].lock().expect("vel part") = Some(vel);
                    }
                }
                Ok(())
            }));
        }
        let formatted = (|| -> Result<(), WriteError> {
            for handle in formatters {
                handle.join().unwrap_or_else(|_| {
                    Err(WriteError::Io(io::Error::other("formatter panicked")))
                })?;
            }
            Ok(())
        })();
        // A formatter that returns early must still wake copiers blocked on
        // an empty queue. Otherwise the scope waits for them forever.
        produced.store(nparts, std::sync::atomic::Ordering::Release);
        ready.notify_all();
        for handle in copiers {
            handle
                .join()
                .map_err(|_| WriteError::Io(io::Error::other("copy panicked")))?;
        }
        formatted?;
        Ok(())
    })?;
    let mut cursor = 0u64;
    for length in &lengths {
        cursor += length
            .load(std::sync::atomic::Ordering::Relaxed)
            .saturating_sub(1);
    }
    drop(map);
    let end = base + cursor;
    // The mapping was reserved above the exact prefix sum.
    file.set_len(end).map_err(WriteError::Io)?;
    file.seek(SeekFrom::Start(end)).map_err(WriteError::Io)?;
    if bad_ids.load(std::sync::atomic::Ordering::Relaxed) {
        ensure_unique_ids(atoms, 1)?;
    }
    let mut vel_bytes = Vec::new();
    if want_vel {
        for part in &vel_parts {
            if let Some(vel) = part.lock().expect("vel part").as_ref() {
                vel_bytes.extend_from_slice(vel);
            }
        }
    }
    drop(vel_parts);
    Ok(vel_bytes)
}

fn push_xyz_line(
    buf: &mut Vec<u8>,
    ryu: &mut ryu::Buffer,
    slots: &mut [FmtSlot; 3],
    xyz: [f64; 3],
    prec: FloatFormat,
    fixed: u8,
    atom_id: u64,
) {
    let [x, y, z] = xyz;
    match prec {
        FloatFormat::RoundTrip => {
            push_round_trip(buf, ryu, Some(&mut slots[0]), x);
            buf.push(b' ');
            push_round_trip(buf, ryu, Some(&mut slots[1]), y);
            buf.push(b' ');
            push_round_trip(buf, ryu, Some(&mut slots[2]), z);
        }
        FloatFormat::DecimalPlaces(_) => {
            push_f64(buf, ryu, x, prec);
            buf.push(b' ');
            push_f64(buf, ryu, y, prec);
            buf.push(b' ');
            push_f64(buf, ryu, z, prec);
        }
    }
    buf.push(b' ');
    // Column 4 is a mask in 0..=7, one digit.
    buf.push(b'0' + fixed);
    buf.push(b' ');
    push_u64(buf, atom_id);
    buf.push(b'\n');
}

fn push_scalar_line(
    buf: &mut Vec<u8>,
    ryu: &mut ryu::Buffer,
    slots: &mut [FmtSlot; 3],
    v: f64,
    prec: FloatFormat,
    fixed: u8,
    atom_id: u64,
) {
    match prec {
        FloatFormat::RoundTrip => push_round_trip(buf, ryu, Some(&mut slots[0]), v),
        FloatFormat::DecimalPlaces(_) => push_f64(buf, ryu, v, prec),
    }
    buf.push(b' ');
    push_u64(buf, u64::from(fixed));
    buf.push(b' ');
    push_u64(buf, atom_id);
    buf.push(b'\n');
}

/// Record `units.time` for a v1 or v2 frame that carries velocities.
///
/// Those velocities are already in [`crate::units::NATURAL_TIME_UNIT`]
/// (CON-units.8). [`ConFrameBuilder::build`] stamps minor 1, and a minor
/// of 1 or later rejects velocities with no `units.time` (CON-units.11).
/// A 3.0 frame is treated the same way, overwriting any `units.time`
/// label. A 3.1 frame is left alone so a caller who omitted time still fails.
pub(crate) fn stamp_legacy_velocity_time(
    meta: &mut BTreeMap<String, Value>,
    spec_version: u32,
    has_velocity: bool,
) {
    if !has_velocity {
        return;
    }
    let minor = meta
        .get(meta::CON_SPEC_MINOR)
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if spec_version >= 3 && minor >= 1 {
        return;
    }
    // Versions 1, 2 and 3.0 store velocities in the natural unit whatever
    // `units.time` says (CON-units.8, CON-units.9). Writing minor 1 makes
    // the label authoritative (CON-units.10), so replace any label rather
    // than keep one the old file never honoured.
    let mut units = match meta.get(meta::UNITS).cloned() {
        Some(Value::Object(map)) => Value::Object(map),
        Some(_) => return,
        None => crate::units::default_v3_units_json(),
    };
    if let Some(object) = units.as_object_mut() {
        object.insert(
            "time".to_string(),
            Value::String(crate::units::NATURAL_TIME_UNIT.to_string()),
        );
        meta.insert(meta::UNITS.to_string(), units);
        // The label now holds, so the frame is written as minor 1.
        if meta.contains_key(meta::CON_SPEC_MINOR) {
            meta.insert(meta::CON_SPEC_MINOR.to_string(), Value::from(1u64));
        }
    }
}

/// Metadata a language binding emits for `frame`, without copying atoms.
///
/// [`ConFrameBuilder::build`] stamps `con_spec_minor` 1 when the key is
/// absent. A parsed frame does not carry that key unless the file did.
/// The stamp lives on the header. The atoms stay where the parser put them.
pub fn binding_metadata(frame: &ConFrame) -> BTreeMap<String, Value> {
    let mut meta = frame.header.metadata.to_map();
    meta.remove(meta::CON_SPEC_VERSION);
    meta.remove(meta::SECTIONS);
    let has_velocity = frame.has_velocities();
    stamp_legacy_velocity_time(&mut meta, frame.header.spec_version, has_velocity);
    // The builder writes the current spec and fills units when the file
    // omitted them. A binding rewrite has to emit that same header.
    if !meta.contains_key(meta::UNITS) {
        meta.insert(
            meta::UNITS.to_string(),
            crate::units::default_v3_units_json(),
        );
    }
    if !meta.contains_key(meta::CON_SPEC_MINOR) {
        meta.insert(meta::CON_SPEC_MINOR.to_string(), Value::from(1u64));
    }
    meta
}

/// Same bytes as a binding rewrite, without rebuilding each atom.
pub fn binding_rewrite_frame(frame: &ConFrame) -> Result<ConFrame, crate::error::ParseError> {
    let mut out = frame.clone();
    out.header.metadata = crate::types::FrameMeta::from_map(binding_metadata(frame));
    // A parsed spec 1 frame keeps line 2 as free text. The builder emits
    // the current spec as JSON, so the rewrite does too.
    if out.header.spec_version < crate::CON_SPEC_VERSION {
        out.header.spec_version = crate::CON_SPEC_VERSION;
    }
    Ok(out)
}

// Implementation block specifically for when the writer is a `File`.
impl ConFrameWriter<File> {
    /// Creates a new `ConFrameWriter` that writes to a file at the given path.
    ///
    /// This is a convenience function that creates the file and wraps it.
    pub fn from_path<P: AsRef<Path>>(path: P) -> io::Result<Self> {
        let file = File::create(path)?;
        Ok(Self::new(file))
    }

    /// Creates a new `ConFrameWriter` that writes to a file with a custom precision.
    pub fn from_path_with_precision<P: AsRef<Path>>(path: P, precision: usize) -> io::Result<Self> {
        let file = File::create(path)?;
        Ok(Self::with_precision(file, precision))
    }

    /// Opens an uncompressed file for appending.
    ///
    /// The file is created when it does not exist. A non-empty file that does
    /// not end in a newline receives one, so the next frame header starts on
    /// its own line. A file this writer produced already ends in a newline,
    /// and appending the remaining frames reproduces one whole-file write.
    /// Gzip and zstd paths are refused: a compressed member cannot be extended.
    ///
    /// `write_frame` fills a one-frame scratch buffer and a [`std::io::BufWriter`].
    /// [`Self::flush`] pushes that buffer to the file before the writer is dropped.
    ///
    /// ```
    /// use readcon_core::iterators::read_all_frames;
    /// use readcon_core::types::ConFrameBuilder;
    /// use readcon_core::writer::ConFrameWriter;
    /// let scratch = tempfile::tempdir().unwrap();
    /// let path = scratch.path().join("readcon-append-doc.con");
    /// let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    /// builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 1, 1.0);
    /// let frame = builder.build().unwrap();
    /// {
    ///     let mut writer = ConFrameWriter::from_path(&path).unwrap();
    ///     writer.write_frame(&frame).unwrap();
    ///     writer.flush().unwrap();
    /// }
    /// {
    ///     let mut writer = ConFrameWriter::from_path_append(&path).unwrap();
    ///     writer.write_frame(&frame).unwrap();
    ///     writer.flush().unwrap();
    /// }
    /// let frames = read_all_frames(&path).unwrap();
    /// assert_eq!(frames.len(), 2);
    /// let _ = std::fs::remove_file(&path);
    /// ```
    pub fn from_path_append<P: AsRef<Path>>(path: P) -> io::Result<Self> {
        Ok(Self::new(open_uncompressed_append(path.as_ref())?))
    }

    /// Opens an uncompressed file for appending with a fixed decimal precision.
    pub fn from_path_append_with_precision<P: AsRef<Path>>(
        path: P,
        precision: usize,
    ) -> io::Result<Self> {
        Ok(Self::with_precision(
            open_uncompressed_append(path.as_ref())?,
            precision,
        ))
    }
}

/// Opens `path` at the end. See [`ConFrameWriter::from_path_append`].
pub(crate) fn open_uncompressed_append(path: &Path) -> io::Result<File> {
    if let Some(ext) = path.extension().and_then(|ext| ext.to_str())
        && (ext == "gz" || ext == "zst")
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "append is only supported for an uncompressed file",
        ));
    }
    let mut file = OpenOptions::new()
        .create(true)
        .read(true)
        .append(true)
        .open(path)?;
    let len = file.seek(SeekFrom::End(0))?;
    if len > 0 {
        file.seek(SeekFrom::End(-1))?;
        let mut last = [0u8; 1];
        file.read_exact(&mut last)?;
        if last[0] != b'\n' {
            file.write_all(b"\n")?;
        }
    }
    Ok(file)
}

/// Serializes `frames` to CON bytes. No file is created.
///
/// The bytes match [`ConFrameWriter::from_path`] writing the same frames.
pub fn write_frames_to_vec(frames: &[ConFrame]) -> Result<Vec<u8>, WriteError> {
    write_frames_to_vec_with_threads(frames, 1, None, false)
}

/// Serializes `frames` to CON bytes.
///
/// `workers < 2` is [`write_frames_to_vec`]. Two or more workers format
/// disjoint frame runs into private buffers and concatenate those buffers
/// in file order. One wide frame formats its coordinate rows the same way.
/// The bytes match a serial write.
pub fn write_frames_to_vec_with_threads(
    frames: &[ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
) -> Result<Vec<u8>, WriteError> {
    let refs: Vec<&ConFrame> = frames.iter().collect();
    write_frame_refs_with_threads(&refs, workers, precision, canonical)
}

/// Write `frames` to `path`.
///
/// Each worker formats a contiguous run. A prefix sum of those lengths
/// is the file offset, and each run is written with `pwrite` at that
/// offset. The bytes match [`write_frame_refs_with_threads`].
///
/// The destination is replaced only after every byte is stored. On Linux
/// the store is an unnamed file (`O_TMPFILE`), so a killed writer leaves
/// neither a partial destination nor a scratch name. A named
/// `.readcon-write-*.tmp` is used only where `O_TMPFILE` is unavailable,
/// and that name is removed if the write fails.
fn destination_dir(path: &Path) -> std::path::PathBuf {
    match path.parent() {
        Some(dir) if !dir.as_os_str().is_empty() => dir.to_path_buf(),
        _ => std::path::PathBuf::from("."),
    }
}

fn scratch_name(dir: &Path) -> std::path::PathBuf {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    dir.join(format!(
        ".readcon-write-{}-{}.tmp",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ))
}

/// A file that is not the destination until [`Unpublished::commit`].
struct Unpublished {
    file: File,
    scratch: Option<std::path::PathBuf>,
    committed: bool,
}

impl Drop for Unpublished {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        if let Some(path) = self.scratch.take() {
            let _ = std::fs::remove_file(path);
        }
    }
}

impl Unpublished {
    fn create(dest: &Path) -> io::Result<Self> {
        let dir = destination_dir(dest);
        if let Some(file) = open_unnamed(&dir) {
            return Ok(Self {
                file,
                scratch: None,
                committed: false,
            });
        }
        let scratch = scratch_name(&dir);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&scratch)?;
        Ok(Self {
            file,
            scratch: Some(scratch),
            committed: false,
        })
    }

    fn duplicate(&self) -> io::Result<File> {
        self.file.try_clone()
    }

    /// Give other processes a name for this inode. [`Self::commit`] publishes
    /// that name, so a ranked write does not grow a second publisher.
    fn expose(&mut self, dest: &Path) -> io::Result<std::path::PathBuf> {
        if let Some(path) = &self.scratch {
            return Ok(path.clone());
        }
        // Only Linux `O_TMPFILE` leaves the inode unnamed. macOS and Windows
        // already stored a scratch path in `create`, and `commit` renames it.
        #[cfg(target_os = "linux")]
        {
            let scratch = scratch_name(&destination_dir(dest));
            link_fd(&self.file, &scratch)?;
            self.scratch = Some(scratch.clone());
            Ok(scratch)
        }
        #[cfg(not(target_os = "linux"))]
        {
            let _ = dest;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "an unnamed store has no directory entry to expose",
            ))
        }
    }

    fn commit(mut self, dest: &Path) -> io::Result<()> {
        if let Some(scratch) = self.scratch.take() {
            match std::fs::rename(&scratch, dest) {
                Ok(()) => {
                    self.committed = true;
                    Ok(())
                }
                Err(err) => {
                    let _ = std::fs::remove_file(&scratch);
                    Err(err)
                }
            }
        } else {
            // Link and rename in a child. A kill of this process does not
            // stop that child, so the scratch name does not outlive the publish.
            publish_unnamed(&self.file, dest)?;
            self.committed = true;
            Ok(())
        }
    }
}

#[cfg(target_os = "linux")]
fn link_fd(file: &File, scratch: &Path) -> io::Result<()> {
    use std::os::fd::AsRawFd;
    let proc = std::ffi::CString::new(format!("/proc/self/fd/{}", file.as_raw_fd()))
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "proc fd"))?;
    let scratch_c = std::ffi::CString::new(scratch.as_os_str().as_encoded_bytes())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "scratch"))?;
    let linked = unsafe {
        libc::linkat(
            libc::AT_FDCWD,
            proc.as_ptr(),
            libc::AT_FDCWD,
            scratch_c.as_ptr(),
            libc::AT_SYMLINK_FOLLOW,
        )
    };
    if linked == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

/// A file other ranks can open, published by [`Unpublished::commit`].
pub(crate) struct SharedStore {
    staged: Unpublished,
    path: std::path::PathBuf,
}

/// Allocate one fresh file of `len` bytes in `dest`'s directory.
///
/// Rank 0 calls this. The returned path is the inode the other ranks open.
/// [`commit_shared_store`] is the only publish.
pub(crate) fn begin_shared_store(dest: &Path, len: u64) -> io::Result<SharedStore> {
    if let Some(parent) = dest.parent().filter(|dir| !dir.as_os_str().is_empty()) {
        let _ = std::fs::create_dir_all(parent);
    }
    let mut staged = Unpublished::create(dest)?;
    allocate_len(&staged.file, len)?;
    let path = staged.expose(dest)?;
    Ok(SharedStore { staged, path })
}

pub(crate) fn commit_shared_store(store: SharedStore, dest: &Path) -> io::Result<()> {
    store.staged.commit(dest)
}

impl SharedStore {
    pub(crate) fn path(&self) -> &Path {
        &self.path
    }
}

fn allocate_len(file: &File, total: u64) -> io::Result<()> {
    if total == 0 {
        return Ok(());
    }
    // `fallocate` is Linux. macOS has `posix_fallocate`. Every other host,
    // including Windows, extends the named scratch with `set_len`. A
    // filesystem that rejects the preallocate call uses that same extend.
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::io::AsRawFd;
        let rc = unsafe { libc::fallocate(file.as_raw_fd(), 0, 0, total as libc::off_t) };
        if rc == 0 {
            return Ok(());
        }
        let err = io::Error::last_os_error();
        match err.raw_os_error() {
            Some(code)
                if code == libc::EOPNOTSUPP || code == libc::ENOSYS || code == libc::EINVAL =>
            {
                file.set_len(total)
            }
            _ => Err(err),
        }
    }
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::io::AsRawFd;
        // libc does not re-export `posix_fallocate` for Apple targets.
        unsafe extern "C" {
            fn posix_fallocate(fd: i32, offset: libc::off_t, len: libc::off_t) -> i32;
        }
        let rc = unsafe { posix_fallocate(file.as_raw_fd(), 0, total as libc::off_t) };
        if rc == 0 {
            return Ok(());
        }
        if rc == libc::EOPNOTSUPP || rc == libc::ENOSYS || rc == libc::EINVAL {
            file.set_len(total)
        } else {
            Err(io::Error::from_raw_os_error(rc))
        }
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        file.set_len(total)
    }
}

/// How a fresh ranked file is filled after it has been allocated.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum RankedStore {
    /// Each slice is stored at its own offset.
    Parallel,
    /// The slices are stored in order as one pass from offset 0.
    Sequential,
}

const EXT_SUPER_MAGIC: u32 = 0xEF53;
const XFS_SUPER_MAGIC: u32 = 0x5846_5342;
const BTRFS_SUPER_MAGIC: u32 = 0x9123_683E;

/// Sequential store for ext2, ext3, ext4, XFS, and btrfs. A sign-extended
/// 32-bit `statfs` word still matches on the low 32 bits.
pub(crate) fn ranked_store_for_magic(magic: i64) -> RankedStore {
    match magic as u32 {
        EXT_SUPER_MAGIC | XFS_SUPER_MAGIC | BTRFS_SUPER_MAGIC => RankedStore::Sequential,
        _ => RankedStore::Parallel,
    }
}

/// `READCON_RANKED_WRITE=parallel` or `sequential`. Anything else is an error.
pub(crate) fn ranked_store_override(value: &str) -> Result<RankedStore, String> {
    match value {
        "parallel" => Ok(RankedStore::Parallel),
        "sequential" => Ok(RankedStore::Sequential),
        _ => Err(format!(
            "READCON_RANKED_WRITE={value} is not parallel or sequential"
        )),
    }
}

fn filesystem_magic(file: &File) -> Option<i64> {
    #[cfg(all(target_os = "linux", not(miri)))]
    {
        use std::os::fd::AsRawFd;
        let mut stat = unsafe { std::mem::zeroed::<libc::statfs>() };
        let rc = unsafe { libc::fstatfs(file.as_raw_fd(), &mut stat) };
        if rc == 0 {
            // `__fsword_t` is `long`: already `i64` on LP64, `i32` on 32-bit.
            #[cfg(target_pointer_width = "64")]
            {
                return Some(stat.f_type);
            }
            #[cfg(target_pointer_width = "32")]
            {
                return Some(stat.f_type as i64);
            }
        }
        None
    }
    #[cfg(any(not(target_os = "linux"), miri))]
    {
        let _ = file;
        None
    }
}

pub(crate) fn choose_ranked_store(file: &File) -> Result<RankedStore, String> {
    if let Ok(value) = std::env::var("READCON_RANKED_WRITE") {
        return ranked_store_override(&value);
    }
    Ok(ranked_store_for_magic(filesystem_magic(file).unwrap_or(0)))
}

/// In-process form of a ranked write.
///
/// `slices` are the rank-ordered byte ranges. `rewrite == false` is the
/// default: one fresh file, published by [`commit_shared_store`], and no
/// `.rewrite` sibling. The same `statfs` choice as the ranked MPI store
/// applies, and `READCON_RANKED_WRITE` overrides it. One process already
/// holds every slice, so both choices pwrite those slices at their offsets.
/// `rewrite == true` fills `path.rewrite` and renames it over `path`.
/// `keep_spare` parks the previous inode at that name.
pub fn publish_ranked_slices(
    path: &Path,
    slices: &[&[u8]],
    rewrite: bool,
    keep_spare: bool,
) -> io::Result<()> {
    let total: u64 = slices.iter().map(|slice| slice.len() as u64).sum();
    if rewrite {
        let spare = prepare_rewrite_spare(path)?;
        {
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(&spare)?;
            if file.metadata()?.len() != total {
                file.set_len(total)?;
            }
            write_slices_at(&file, slices)?;
        }
        return publish_rewrite(&spare, path, keep_spare);
    }
    let store = begin_shared_store(path, total)?;
    {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(store.path())?;
        match choose_ranked_store(&file)
            .map_err(|err| io::Error::new(io::ErrorKind::InvalidInput, err))?
        {
            RankedStore::Parallel | RankedStore::Sequential => write_slices_at(&file, slices)?,
        }
    }
    commit_shared_store(store, path)
}

fn write_slices_at(file: &File, slices: &[&[u8]]) -> io::Result<()> {
    let mut offset = 0u64;
    for slice in slices {
        if !slice.is_empty() {
            #[cfg(unix)]
            {
                use std::os::unix::fs::FileExt;
                let mut at = 0usize;
                while at < slice.len() {
                    let n = file.write_at(&slice[at..], offset + at as u64)?;
                    if n == 0 {
                        return Err(io::Error::new(
                            io::ErrorKind::WriteZero,
                            "ranked slice wrote no bytes",
                        ));
                    }
                    at += n;
                }
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::FileExt;
                let mut at = 0usize;
                while at < slice.len() {
                    let n = file.seek_write(&slice[at..], offset + at as u64)?;
                    if n == 0 {
                        return Err(io::Error::new(
                            io::ErrorKind::WriteZero,
                            "ranked slice wrote no bytes",
                        ));
                    }
                    at += n;
                }
            }
            #[cfg(not(any(unix, windows)))]
            {
                let _ = (file, slice, offset);
                return Err(io::Error::new(
                    io::ErrorKind::Unsupported,
                    "ranked slices require pwrite",
                ));
            }
        }
        offset += slice.len() as u64;
    }
    Ok(())
}

fn publish_unnamed(file: &File, dest: &Path) -> io::Result<()> {
    #[cfg(target_os = "linux")]
    {
        use std::os::fd::AsRawFd;
        let scratch = scratch_name(&destination_dir(dest));
        let proc = std::ffi::CString::new(format!("/proc/self/fd/{}", file.as_raw_fd()))
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "proc fd"))?;
        let scratch_c = std::ffi::CString::new(scratch.as_os_str().as_encoded_bytes())
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "scratch"))?;
        let dest_c = std::ffi::CString::new(dest.as_os_str().as_encoded_bytes())
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "dest"))?;
        let pid = unsafe { libc::fork() };
        if pid < 0 {
            return Err(io::Error::last_os_error());
        }
        if pid == 0 {
            let linked = unsafe {
                libc::linkat(
                    libc::AT_FDCWD,
                    proc.as_ptr(),
                    libc::AT_FDCWD,
                    scratch_c.as_ptr(),
                    libc::AT_SYMLINK_FOLLOW,
                )
            };
            if linked != 0 {
                unsafe { libc::_exit(1) };
            }
            let renamed = unsafe { libc::rename(scratch_c.as_ptr(), dest_c.as_ptr()) };
            unsafe { libc::_exit(if renamed == 0 { 0 } else { 1 }) };
        }
        let mut status = 0;
        loop {
            let waited = unsafe { libc::waitpid(pid, &mut status, 0) };
            if waited >= 0 {
                break;
            }
            let err = io::Error::last_os_error();
            if err.kind() != io::ErrorKind::Interrupted {
                return Err(err);
            }
        }
        // The child has finished, so a leftover scratch is this publish's
        // name and not a concurrent writer's.
        let published = libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 0;
        if !published {
            if scratch.exists() {
                let _ = std::fs::remove_file(&scratch);
            }
            return Err(io::Error::other("publish did not replace the destination"));
        }
        Ok(())
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (file, dest);
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "unnamed publish",
        ))
    }
}

fn open_unnamed(dir: &Path) -> Option<File> {
    #[cfg(target_os = "linux")]
    {
        use std::os::fd::FromRawFd;
        let bytes = dir.as_os_str().as_encoded_bytes();
        let c_dir = std::ffi::CString::new(bytes).ok()?;
        let fd = unsafe { libc::open(c_dir.as_ptr(), libc::O_TMPFILE | libc::O_RDWR, 0o600) };
        if fd < 0 {
            return None;
        }
        Some(unsafe { File::from_raw_fd(fd) })
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = dir;
        None
    }
}

fn begin_unpublished(path: &Path) -> Result<(Unpublished, File), WriteError> {
    let staged = Unpublished::create(path).map_err(WriteError::Io)?;
    let file = staged.duplicate().map_err(WriteError::Io)?;
    Ok((staged, file))
}

fn finish_unpublished(
    staged: Unpublished,
    dest: &Path,
    result: Result<(), WriteError>,
) -> Result<(), WriteError> {
    match result {
        Ok(()) => staged.commit(dest).map_err(WriteError::Io),
        Err(err) => Err(err),
    }
}

/// Replace `dest` with the bytes `write` stores, or leave `dest` untouched.
pub(crate) fn publish_new<E>(
    dest: &Path,
    map_io: impl Fn(io::Error) -> E,
    write: impl FnOnce(&mut File) -> Result<(), E>,
) -> Result<(), E> {
    let staged = Unpublished::create(dest).map_err(&map_io)?;
    let mut file = staged.duplicate().map_err(&map_io)?;
    write(&mut file)?;
    drop(file);
    staged.commit(dest).map_err(map_io)
}

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

fn column_fixed(fixed: Option<&[f64]>, index: usize) -> u8 {
    let flags = match fixed {
        Some(bits) => {
            let base = index * 3;
            [
                bits[base] != 0.0,
                bits[base + 1] != 0.0,
                bits[base + 2] != 0.0,
            ]
        }
        None => [false, false, false],
    };
    written_fixed_flag(flags, crate::CON_SPEC_VERSION)
}

/// Spellings of `0.0` ..= `9999.0`, the form `encode_fixed_decimal` emits
/// for those integers. A lattice coordinate hits this table instead of the
/// general float formatter.
fn small_int_text(n: u32) -> &'static [u8] {
    use std::sync::OnceLock;
    const LIMIT: u32 = 10_000;
    static TEXT: OnceLock<Vec<u8>> = OnceLock::new();
    static OFF: OnceLock<Vec<u32>> = OnceLock::new();
    let text = TEXT.get_or_init(|| {
        let mut bytes = Vec::with_capacity(LIMIT as usize * 6);
        let mut off = Vec::with_capacity(LIMIT as usize + 1);
        off.push(0u32);
        for value in 0..LIMIT {
            let start = bytes.len();
            let mut tmp = [0u8; 8];
            let mut i = tmp.len();
            let mut n = value;
            if n == 0 {
                i -= 1;
                tmp[i] = b'0';
            } else {
                while n > 0 {
                    i -= 1;
                    tmp[i] = b'0' + (n % 10) as u8;
                    n /= 10;
                }
            }
            bytes.extend_from_slice(&tmp[i..]);
            bytes.extend_from_slice(b".0");
            off.push(bytes.len() as u32);
            let _ = start;
        }
        OFF.set(off).ok();
        bytes
    });
    let off = OFF.get().expect("small int offsets");
    let n = n as usize;
    &text[off[n] as usize..off[n + 1] as usize]
}

fn push_column_f64(buf: &mut Vec<u8>, ryu: &mut ryu::Buffer, slot: &mut FmtSlot, value: f64) {
    if (0.0..10_000.0).contains(&value) {
        let n = value as u32;
        if n as f64 == value {
            buf.extend_from_slice(small_int_text(n));
            return;
        }
    }
    push_round_trip(buf, ryu, Some(slot), value);
}

/// Decimal form of a sequential atom id. Incrementing the last digit is the
/// common step; a run of nines carries once per power of ten.
struct IdDigits {
    buf: [u8; 20],
    start: usize,
}

impl IdDigits {
    fn from_u64(mut n: u64) -> Self {
        let mut buf = [b'0'; 20];
        let mut i = 20usize;
        if n == 0 {
            return Self { buf, start: 19 };
        }
        while n > 0 {
            i -= 1;
            buf[i] = b'0' + (n % 10) as u8;
            n /= 10;
        }
        Self { buf, start: i }
    }

    fn text(&self) -> &[u8] {
        &self.buf[self.start..]
    }

    fn bump(&mut self) {
        let mut i = self.buf.len() - 1;
        loop {
            if self.buf[i] < b'9' {
                self.buf[i] += 1;
                if i < self.start {
                    self.start = i;
                }
                return;
            }
            self.buf[i] = b'0';
            if i == 0 {
                return;
            }
            i -= 1;
        }
    }
}

fn push_column_line(
    buf: &mut Vec<u8>,
    ryu: &mut ryu::Buffer,
    slots: &mut [FmtSlot; 3],
    xyz: [f64; 3],
    mask: u8,
    id: &[u8],
) {
    push_column_f64(buf, ryu, &mut slots[0], xyz[0]);
    buf.push(b' ');
    push_column_f64(buf, ryu, &mut slots[1], xyz[1]);
    buf.push(b' ');
    push_column_f64(buf, ryu, &mut slots[2], xyz[2]);
    buf.push(b' ');
    buf.push(b'0' + mask);
    buf.push(b' ');
    buf.extend_from_slice(id);
    buf.push(b'\n');
}

fn format_column_span(
    positions: &[f64],
    extra: Option<&[f64]>,
    fixed: Option<&[f64]>,
    start: usize,
    end: usize,
) -> (Vec<u8>, Vec<u8>) {
    let n = end - start;
    let mut coord = Vec::with_capacity(n.saturating_mul(32));
    let mut side = if extra.is_some() {
        Vec::with_capacity(n.saturating_mul(32))
    } else {
        Vec::new()
    };
    let mut ryu = ryu::Buffer::new();
    let mut slots = [FmtSlot::new(); 3];
    let mut side_slots = [FmtSlot::new(); 3];
    let mut ids = IdDigits::from_u64(start as u64);
    for index in start..end {
        let base = index * 3;
        let mask = column_fixed(fixed, index);
        let mut id_buf = [0u8; 20];
        let id_len = ids.text().len();
        id_buf[..id_len].copy_from_slice(ids.text());
        let id = &id_buf[..id_len];
        push_column_line(
            &mut coord,
            &mut ryu,
            &mut slots,
            [positions[base], positions[base + 1], positions[base + 2]],
            mask,
            id,
        );
        if let Some(values) = extra {
            push_column_line(
                &mut side,
                &mut ryu,
                &mut side_slots,
                [values[base], values[base + 1], values[base + 2]],
                mask,
                id,
            );
        }
        ids.bump();
    }
    (coord, side)
}

fn format_column_parallel(
    positions: &[f64],
    extra: Option<&[f64]>,
    fixed: Option<&[f64]>,
    start: usize,
    end: usize,
    workers: usize,
) -> (Vec<u8>, Vec<u8>) {
    let span = end - start;
    if workers < 2 || span < WIDE_ATOM_GRAIN {
        return format_column_span(positions, extra, fixed, start, end);
    }
    let workers = workers.min(span);
    let mut bounds = Vec::with_capacity(workers);
    for worker in 0..workers {
        let from = start + span * worker / workers;
        let to = start + span * (worker + 1) / workers;
        if from < to {
            bounds.push((from, to));
        }
    }
    let mut parts = Vec::with_capacity(bounds.len());
    std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(bounds.len());
        for (from, to) in bounds {
            handles
                .push(scope.spawn(move || format_column_span(positions, extra, fixed, from, to)));
        }
        for handle in handles {
            parts.push(handle.join().unwrap_or_else(|_| (Vec::new(), Vec::new())));
        }
    });
    let mut coord = Vec::new();
    let mut side = Vec::new();
    for (rows, extra_rows) in parts {
        coord.extend_from_slice(&rows);
        side.extend_from_slice(&extra_rows);
    }
    (coord, side)
}

fn column_header(
    cell: &[f64],
    counts: &[usize],
    mass_values: &[f64],
    symbol: &str,
    has_velocity: bool,
    has_force: bool,
) -> Result<Vec<u8>, WriteError> {
    let mut builder =
        ConFrameBuilder::new([cell[0], cell[1], cell[2]], [cell[3], cell[4], cell[5]]);
    builder
        .prebox_header("readcon")
        .postbox_header(["0 0".to_string(), "0 0".to_string()])
        .add_atom(symbol, 0.0, 0.0, 0.0, [false; 3], 0, mass_values[0]);
    if has_velocity {
        builder.with_velocity([0.0, 0.0, 0.0]);
    }
    if has_force {
        builder.with_force([0.0, 0.0, 0.0]);
    }
    let mut frame = builder.build().map_err(WriteError::Format)?;
    frame.header.natm_types = counts.len();
    frame.header.natms_per_type = counts.to_vec();
    frame.header.masses_per_type = mass_values.to_vec();
    frame.header.postbox_header = ["0 0".to_string(), "0 0".to_string()];
    frame.header.prebox_header = crate::types::PreboxHeader::new("readcon");
    // Same stamp as `frame_from_column_slice`: spec 2 in the stored header,
    // so the binding rewrite records units.time before it emits spec 3.
    frame.header.spec_version = 2;
    let mut metadata = BTreeMap::new();
    metadata.insert(meta::CON_SPEC_MINOR.to_string(), json!(1));
    metadata.insert(meta::CON_SPEC_VERSION.to_string(), json!(2));
    frame.header.metadata = crate::types::FrameMeta::from_map(metadata);
    binding_header_bytes(&frame)
}

#[allow(clippy::too_many_arguments)]
/// Write binding CON text from column slices, without a per-atom object.
///
/// `workers` of 0 uses one thread per physical core. The bytes match
/// [`ConFrameWriter::write_frame_bound`] of the frame those columns describe.
pub fn write_binding_columns(
    path: &Path,
    n_frames: usize,
    n_atoms: usize,
    positions: &[f64],
    masses: &[f64],
    cell: &[f64],
    fixed: Option<&[f64]>,
    velocities: Option<&[f64]>,
    forces: Option<&[f64]>,
    symbol: &str,
    workers: usize,
) -> Result<(), WriteError> {
    let workers = if workers == 0 {
        physical_cores()
    } else {
        workers
    };
    let mut file_bytes = Vec::new();
    for frame_index in 0..n_frames {
        let atom_base = frame_index * n_atoms;
        let pos = &positions[atom_base * 3..(atom_base + n_atoms) * 3];
        let mass = &masses[atom_base..atom_base + n_atoms];
        let box_cell = &cell[frame_index * 6..frame_index * 6 + 6];
        let flags = fixed.map(|bits| &bits[atom_base * 3..(atom_base + n_atoms) * 3]);
        let vel = velocities.map(|bits| &bits[atom_base * 3..(atom_base + n_atoms) * 3]);
        let force = forces.map(|bits| &bits[atom_base * 3..(atom_base + n_atoms) * 3]);
        let (counts, mass_values) = mass_runs(mass);
        let header = column_header(
            box_cell,
            &counts,
            &mass_values,
            symbol,
            vel.is_some(),
            force.is_some(),
        )?;
        file_bytes.extend_from_slice(&header);
        let mut offset = 0usize;
        let mut velocity_block = Vec::new();
        let mut force_block = Vec::new();
        for (type_idx, count) in counts.iter().copied().enumerate() {
            push_str_line(&mut file_bytes, symbol);
            push_component_line(&mut file_bytes, "Coordinates of Component", type_idx);
            if vel.is_some() {
                push_str_line(&mut velocity_block, symbol);
                push_component_line(&mut velocity_block, "Velocities of Component", type_idx);
            }
            if force.is_some() {
                push_str_line(&mut force_block, symbol);
                push_component_line(&mut force_block, "Forces of Component", type_idx);
            }
            let (coord, side) =
                format_column_parallel(pos, vel, flags, offset, offset + count, workers);
            file_bytes.extend_from_slice(&coord);
            velocity_block.extend_from_slice(&side);
            if let Some(values) = force {
                let (rows, _) =
                    format_column_parallel(values, None, flags, offset, offset + count, workers);
                force_block.extend_from_slice(&rows);
            }
            offset += count;
        }
        if vel.is_some() {
            file_bytes.push(b'\n');
            file_bytes.extend_from_slice(&velocity_block);
        }
        if force.is_some() {
            file_bytes.push(b'\n');
            file_bytes.extend_from_slice(&force_block);
        }
    }
    publish_new(path, WriteError::Io, |file| {
        file.write_all(&file_bytes).map_err(WriteError::Io)
    })
}

/// Write `frames` to `path`, replacing that path only after the bytes are complete.
///
/// `workers` below 2 uses the serial writer. `workers >= 2` with two or
/// more frames formats groups in parallel. One frame of at least 4096 atoms
/// formats its coordinate lines on those workers. `precision` is the decimal
/// count, or the writer default when `None`. `canonical` selects the
/// canonical header. `bind` writes each frame through [`ConFrameWriter::write_frame_bound`].
pub fn write_frame_refs_to_path(
    path: &std::path::Path,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    // One writer streams each frame to the file. Building the whole text
    // and copying it was a second pass the parallel paths do not pay.
    if workers < 2 {
        return write_serial_frames(path, frames, precision, canonical, bind);
    }
    if workers >= 2 && frames.len() >= 2 {
        return pipeline_frame_groups(path, frames, workers, precision, canonical, bind);
    }
    if workers >= 2 && frames.len() == 1 && frames[0].atom_data.len() >= WIDE_ATOM_GRAIN {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(Vec::<u8>::new(), precision),
            None => ConFrameWriter::new(Vec::<u8>::new()),
        }
        .canonical(canonical)
        .parallel_atoms(workers);
        // Replace the destination only after the frame is complete. Opening
        // it first destroyed a file the serial writer would have left alone.
        let (staged, file) = begin_unpublished(path)?;
        writer.stream_file = Some(file);
        let result = if bind {
            writer.write_frame_bound(frames[0])
        } else {
            writer.write_frame(frames[0])
        };
        drop(writer);
        return finish_unpublished(staged, path, result);
    }
    let parts = formatted_parts(frames, workers, precision, canonical, bind)?;
    let (staged, mut file) = begin_unpublished(path)?;
    let result = if parts.len() == 1 {
        // One wide frame is already formatted in parallel row runs and
        // joined. A single write matches the disk; slicing it into pwrite
        // calls spent the gain on a second pass over the file.
        file.write_all(&parts[0]).map_err(WriteError::Io)
    } else {
        let slices: Vec<&[u8]> = parts.iter().map(|part| part.as_slice()).collect();
        pwrite_borrowed(&file, &slices).map_err(WriteError::Io)
    };
    finish_unpublished(staged, path, result)
}

pub(crate) fn rewrite_names(path: &Path) -> io::Result<(std::path::PathBuf, std::path::PathBuf)> {
    let name = path.file_name().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "rewrite path has no file name")
    })?;
    let mut spare_name = name.to_os_string();
    spare_name.push(".rewrite");
    let mut hold_name = name.to_os_string();
    hold_name.push(".rewrite-hold");
    let dir = match path.parent() {
        Some(dir) if !dir.as_os_str().is_empty() => dir.to_path_buf(),
        _ => std::path::PathBuf::from("."),
    };
    Ok((dir.join(spare_name), dir.join(hold_name)))
}

/// The spare is the inode the next rewrite overwrites. A crash during the
/// name swap leaves that inode under the hold name; adopt it so the pages
/// are not thrown away.
pub(crate) fn prepare_rewrite_spare(path: &Path) -> io::Result<std::path::PathBuf> {
    let (spare, hold) = rewrite_names(path)?;
    if !spare.exists() && hold.exists() {
        std::fs::rename(&hold, &spare)?;
    } else if hold.exists() {
        std::fs::remove_file(&hold)?;
    }
    Ok(spare)
}

/// Publish `spare` as `path`.
///
/// `path` keeps the previous complete file until `rename`. When
/// `keep_spare` is set, that inode is parked at the spare name so the next
/// same-length rewrite fills those pages. The spare then occupies a second
/// copy of the trajectory on disk. `keep_spare == false` drops it after the
/// rename, so the steady state is one file and the next rewrite allocates
/// again. A partial spare is never given the published name.
pub(crate) fn publish_rewrite(spare: &Path, path: &Path, keep_spare: bool) -> io::Result<()> {
    let (_, hold) = rewrite_names(path)?;
    if !keep_spare {
        if hold.exists() {
            std::fs::remove_file(&hold)?;
        }
        std::fs::rename(spare, path)?;
        return Ok(());
    }
    if path.exists() {
        if hold.exists() {
            std::fs::remove_file(&hold)?;
        }
        std::fs::hard_link(path, &hold)?;
    }
    std::fs::rename(spare, path)?;
    if hold.exists() {
        std::fs::rename(&hold, spare)?;
    }
    Ok(())
}

fn finish_open_length(file: &File) -> io::Result<()> {
    let mut file = file.try_clone()?;
    let end = file.stream_position()?;
    file.set_len(end)
}

/// Bytes of `frames` into an already-open file, starting at offset 0.
///
/// The file's inode is kept. `set_len` to the same length does not drop
/// pages, which is what a same-length rewrite uses.
fn store_frames_in(
    file: &File,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    file.try_clone()
        .and_then(|mut file| file.seek(SeekFrom::Start(0)).map(|_| ()))
        .map_err(WriteError::Io)?;
    if workers < 2 {
        let mut writer = match precision {
            Some(precision) => {
                ConFrameWriter::with_precision(file.try_clone().map_err(WriteError::Io)?, precision)
            }
            None => ConFrameWriter::new(file.try_clone().map_err(WriteError::Io)?),
        }
        .canonical(canonical);
        write_group(&mut writer, frames, bind)
            .and_then(|_| writer.flush().map_err(WriteError::Io))?;
        drop(writer);
        return finish_open_length(file).map_err(WriteError::Io);
    }
    if workers >= 2 && frames.len() >= 2 {
        return store_pipeline_in(file, frames, workers, precision, canonical, bind);
    }
    if workers >= 2 && frames.len() == 1 && frames[0].atom_data.len() >= WIDE_ATOM_GRAIN {
        let mut writer = match precision {
            Some(precision) => ConFrameWriter::with_precision(Vec::<u8>::new(), precision),
            None => ConFrameWriter::new(Vec::<u8>::new()),
        }
        .canonical(canonical)
        .parallel_atoms(workers);
        writer.stream_file = Some(file.try_clone().map_err(WriteError::Io)?);
        let result = if bind {
            writer.write_frame_bound(frames[0])
        } else {
            writer.write_frame(frames[0])
        };
        drop(writer);
        result?;
        return finish_open_length(file).map_err(WriteError::Io);
    }
    let parts = formatted_parts(frames, workers, precision, canonical, bind)?;
    store_disjoint_parts(file, &parts).map_err(WriteError::Io)
}

fn store_pipeline_in(
    file: &File,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    if (2..=workers).contains(&frames.len()) {
        let mut parts: Vec<Result<Vec<u8>, WriteError>> = Vec::with_capacity(frames.len());
        std::thread::scope(|scope| {
            let mut guards = Vec::with_capacity(frames.len());
            for (index, frame) in frames.iter().enumerate() {
                guards.push(scope.spawn(move || {
                    #[cfg(feature = "parallel")]
                    crate::parser::pin_worker(index);
                    format_group_bytes(std::slice::from_ref(frame), 1, precision, canonical, bind)
                }));
            }
            for guard in guards {
                parts.push(match guard.join() {
                    Ok(part) => part,
                    Err(_) => Err(WriteError::Io(io::Error::other("frame formatter panicked"))),
                });
            }
        });
        let mut formatted = Vec::with_capacity(parts.len());
        for part in parts {
            formatted.push(part?);
        }
        return store_disjoint_parts(file, &formatted).map_err(WriteError::Io);
    }
    let heavy = direct_slice_write(
        workers,
        frame_byte_weight(frames[0]).saturating_mul(frames.len()),
    );
    if heavy
        && let Some(lengths) = cached_packed_lengths(frames, workers, precision, canonical, bind)
    {
        return place_packed(file, frames, &lengths, workers, precision, canonical, bind);
    }
    let groups = workers.saturating_mul(4).max(workers);
    let ranges = group_frame_ranges(frames, groups);
    let pieces: Vec<&[&ConFrame]> = ranges
        .iter()
        .map(|&(start, end)| &frames[start..end])
        .collect();
    let format_threads = pipeline_format_threads(workers).min(pieces.len().max(1));
    let (tx, rx) = std::sync::mpsc::sync_channel::<(usize, Result<Vec<u8>, WriteError>)>(2);
    let next_job = std::sync::atomic::AtomicUsize::new(0);
    let result = std::thread::scope(|scope| -> Result<(), WriteError> {
        for _ in 0..format_threads {
            let tx = tx.clone();
            let pieces = &pieces;
            let next_job = &next_job;
            scope.spawn(move || {
                loop {
                    let index = next_job.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= pieces.len() {
                        break;
                    }
                    let message = format_group_bytes(pieces[index], 1, precision, canonical, bind);
                    if tx.send((index, message)).is_err() {
                        break;
                    }
                }
            });
        }
        drop(tx);
        let mut out = file.try_clone().map_err(WriteError::Io)?;
        out.seek(SeekFrom::Start(0)).map_err(WriteError::Io)?;
        let mut next = 0usize;
        let mut pending = BTreeMap::<usize, Vec<u8>>::new();
        while next < pieces.len() {
            let (index, part) = rx
                .recv()
                .map_err(|err| WriteError::Io(io::Error::other(err.to_string())))?;
            pending.insert(index, part?);
            while let Some(part) = pending.remove(&next) {
                out.write_all(&part).map_err(WriteError::Io)?;
                next += 1;
            }
        }
        out.flush().map_err(WriteError::Io)?;
        Ok(())
    });
    result?;
    finish_open_length(file).map_err(WriteError::Io)
}

/// Rewrite `path` with `frames` for a workload that keeps this trajectory name.
///
/// The new bytes are written into `path` with the suffix `.rewrite`. That
/// spare is a second file of the same length, so a kept spare doubles the
/// disk the trajectory occupies. `rename` publishes the spare only after
/// the write returns. Until then `path` is still the previous complete
/// file, including when the process is killed. `keep_spare` parks the
/// previous inode at `.rewrite` for the next call. Passing `false` removes
/// that spare after the rename. A different length allocates the extra
/// pages. The fresh-file writer is [`write_frame_refs_to_path`].
pub fn rewrite_frame_refs_to_path(
    path: &std::path::Path,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
    keep_spare: bool,
) -> Result<(), WriteError> {
    let spare = prepare_rewrite_spare(path).map_err(WriteError::Io)?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&spare)
        .map_err(WriteError::Io)?;
    store_frames_in(&file, frames, workers, precision, canonical, bind)?;
    drop(file);
    publish_rewrite(&spare, path, keep_spare).map_err(WriteError::Io)
}

/// [`write_frames_to_vec_with_threads`] over borrowed frames.
///
/// A `read_con` result can be written without cloning the trajectory.
pub fn write_frame_refs_with_threads(
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
) -> Result<Vec<u8>, WriteError> {
    let mut parts = formatted_parts(frames, workers, precision, canonical, false)?;
    // One wide frame is already one buffer. Copying it into a second
    // allocation was a serial memcpy of the whole text on the timing path.
    if parts.len() == 1 {
        return Ok(parts.pop().unwrap_or_default());
    }
    let mut out = Vec::new();
    for part in parts {
        out.extend_from_slice(&part);
    }
    Ok(out)
}

/// Format `frames` the way [`write_frame_refs_to_path`] does, and stop
/// before the file exists.
///
/// The pieces are the writer's groups, not one buffer for the whole
/// trajectory. Eight workers on a long run get one buffer per worker,
/// the same bytes that worker would format into its mapping. Two and
/// four workers get the pipeline's groups. One worker gets the serial
/// formatter's buffer. Concatenating the pieces matches the file.
pub fn format_frame_refs_unstored(
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<Vec<Vec<u8>>, WriteError> {
    if frames.is_empty() {
        return Ok(Vec::new());
    }
    if workers < 2 || frames.len() < 2 {
        return Ok(vec![format_group_bytes(
            frames,
            workers.max(1),
            precision,
            canonical,
            bind,
        )?]);
    }
    if (2..=workers).contains(&frames.len()) {
        return format_frames_apart(frames, precision, canonical, bind);
    }
    let heavy = direct_slice_write(
        workers,
        frame_byte_weight(frames[0]).saturating_mul(frames.len()),
    );
    if heavy
        && let Some(lengths) = cached_packed_lengths(frames, workers, precision, canonical, bind)
    {
        return format_packed_buffers(frames, &lengths, workers, precision, canonical, bind);
    }
    format_pipeline_groups(frames, workers, precision, canonical, bind)
}

/// One buffer per frame, the same split the file writer uses when there
/// is a worker for every frame.
fn format_frames_apart(
    frames: &[&ConFrame],
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<Vec<Vec<u8>>, WriteError> {
    let mut parts: Vec<Result<Vec<u8>, WriteError>> = Vec::with_capacity(frames.len());
    std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(frames.len());
        for (index, frame) in frames.iter().enumerate() {
            guards.push(scope.spawn(move || {
                #[cfg(feature = "parallel")]
                crate::parser::pin_worker(index);
                format_group_bytes(std::slice::from_ref(frame), 1, precision, canonical, bind)
            }));
        }
        for guard in guards {
            parts.push(match guard.join() {
                Ok(part) => part,
                Err(_) => Err(WriteError::Io(io::Error::other("frame formatter panicked"))),
            });
        }
    });
    parts.into_iter().collect()
}

/// One exact-sized buffer per worker. The span is the mapping that
/// worker would fill, and the bytes are formatted in place.
fn format_packed_buffers(
    frames: &[&ConFrame],
    lengths: &[usize],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<Vec<Vec<u8>>, WriteError> {
    let ranges = pack_frames_by_weight(lengths, workers);
    let mut prefix = vec![0usize; lengths.len() + 1];
    for (index, len) in lengths.iter().enumerate() {
        prefix[index + 1] = prefix[index] + len;
    }
    if cfg!(miri) {
        let mut parts = Vec::with_capacity(ranges.len());
        for &(start, end) in &ranges {
            parts.push(format_group_bytes(
                &frames[start..end],
                1,
                precision,
                canonical,
                bind,
            )?);
        }
        return Ok(parts);
    }
    let mut parts: Vec<Result<Vec<u8>, WriteError>> = Vec::with_capacity(ranges.len());
    std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(ranges.len());
        for (thread, &(start, end)) in ranges.iter().enumerate() {
            let span = prefix[end] - prefix[start];
            let piece = &frames[start..end];
            guards.push(scope.spawn(move || -> Result<Vec<u8>, WriteError> {
                #[cfg(feature = "parallel")]
                crate::parser::pin_worker(thread);
                if span == 0 {
                    return Ok(Vec::new());
                }
                let mut buf = vec![0u8; span];
                format_group_into(piece, &mut buf, precision, canonical, bind)?;
                Ok(buf)
            }));
        }
        for guard in guards {
            parts.push(match guard.join() {
                Ok(part) => part,
                Err(_) => Err(WriteError::Io(io::Error::other("frame formatter panicked"))),
            });
        }
    });
    parts.into_iter().collect()
}

/// The pipeline's groups, formatted and not written.
fn format_pipeline_groups(
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<Vec<Vec<u8>>, WriteError> {
    let groups = workers.saturating_mul(4).max(workers);
    let ranges = group_frame_ranges(frames, groups);
    let pieces: Vec<&[&ConFrame]> = ranges
        .iter()
        .map(|&(start, end)| &frames[start..end])
        .collect();
    let format_threads = pipeline_format_threads(workers).min(pieces.len().max(1));
    let next_job = std::sync::atomic::AtomicUsize::new(0);
    let mut slots: Vec<Option<Result<Vec<u8>, WriteError>>> =
        (0..pieces.len()).map(|_| None).collect();
    std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(format_threads);
        for _ in 0..format_threads {
            let pieces = &pieces;
            let next_job = &next_job;
            guards.push(scope.spawn(move || {
                let mut local = Vec::new();
                loop {
                    let index = next_job.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= pieces.len() {
                        break;
                    }
                    local.push((
                        index,
                        format_group_bytes(pieces[index], 1, precision, canonical, bind),
                    ));
                }
                local
            }));
        }
        for guard in guards {
            let local = match guard.join() {
                Ok(local) => local,
                Err(_) => {
                    return;
                }
            };
            for (index, part) in local {
                slots[index] = Some(part);
            }
        }
    });
    let mut out = Vec::with_capacity(slots.len());
    for slot in slots {
        let Some(part) = slot else {
            return Err(WriteError::Io(io::Error::other("frame formatter panicked")));
        };
        out.push(part?);
    }
    Ok(out)
}

/// Byte weight of one frame: atom lines, counting each extra section.
///
/// A velocity frame is about twice a coordinate frame of the same
/// atoms. Splitting on frame counts glues that heavy frame to a light
/// neighbour and leaves the other workers short.
pub(crate) fn frame_byte_weight(frame: &ConFrame) -> usize {
    let atoms = frame.atom_data.len().max(1);
    // Declared sections are the line blocks. Absent SoA columns are a
    // null check. Walking every atom for a coordinate-only frame was a
    // pointer chase per frame, about 5 ms on a 100 000-frame write.
    if !frame.header.sections.is_empty() {
        return atoms.saturating_mul(1 + frame.header.sections.len());
    }
    let mut blocks = 1usize;
    if frame.velocities.is_present() {
        blocks += 1;
    }
    if frame.forces.is_present() {
        blocks += 1;
    }
    if frame.atom_energies.is_present() {
        blocks += 1;
    }
    if frame.charges.is_present() {
        blocks += 1;
    }
    if frame.spins.is_present() {
        blocks += 1;
    }
    if frame.magmoms.is_present() {
        blocks += 1;
    }
    if frame.displacements.is_present() {
        blocks += 1;
    }
    if frame.spreads.is_present() {
        blocks += 1;
    }
    if blocks == 1
        && let Some(atom) = frame.atom_data.first()
    {
        if atom.has_velocity() {
            blocks += 1;
        }
        if atom.has_forces() {
            blocks += 1;
        }
        if atom.has_energy() {
            blocks += 1;
        }
        if atom.has_charge() {
            blocks += 1;
        }
        if atom.has_spin() {
            blocks += 1;
        }
        if atom.has_magmom() {
            blocks += 1;
        }
        if atom.has_displacement() {
            blocks += 1;
        }
        if atom.has_spread() {
            blocks += 1;
        }
    }
    atoms.saturating_mul(blocks)
}

fn equal_frame_ranges(n: usize, groups: usize) -> Vec<(usize, usize)> {
    let groups = groups.max(1).min(n.max(1));
    let mut out = Vec::with_capacity(groups);
    if n == 0 {
        return out;
    }
    for group in 0..groups {
        let start = group * n / groups;
        let end = (group + 1) * n / groups;
        if start < end {
            out.push((start, end));
        }
    }
    out
}

/// Equal slices when sampled frames share a weight. A mixed file is
/// packed from every frame's byte weight.
///
/// Walking every frame of a uniform 100 000-frame trajectory before
/// formatting it cost several milliseconds on the 8-thread write, and
/// the equal split is the same one the weights would have produced.
pub(crate) fn group_frame_ranges(frames: &[&ConFrame], groups: usize) -> Vec<(usize, usize)> {
    let n = frames.len();
    if n == 0 {
        return Vec::new();
    }
    let groups = groups.max(1).min(n);
    if n == 1 || !sampled_weights_vary(frames) {
        return equal_frame_ranges(n, groups);
    }
    let weights: Vec<usize> = frames
        .iter()
        .map(|frame| frame_byte_weight(frame))
        .collect();
    pack_frames_by_weight(&weights, groups)
}

fn sampled_weights_vary(frames: &[&ConFrame]) -> bool {
    let anchor = frame_byte_weight(frames[0]);
    let last = frames.len() - 1;
    let samples = 16.min(frames.len());
    for i in 0..samples {
        let index = if samples == 1 {
            0
        } else {
            i * last / (samples - 1)
        };
        if frame_byte_weight(frames[index]) != anchor {
            return true;
        }
    }
    false
}

/// Contiguous groups whose weights are as equal as a frame boundary allows.
///
/// `workers` groups when there are at least that many frames. A frame
/// heavier than the mean stands in its own group instead of sharing one
/// with the light frames an equal count would pair it with.
pub(crate) fn pack_frames_by_weight(weights: &[usize], workers: usize) -> Vec<(usize, usize)> {
    let n = weights.len();
    if n == 0 {
        return Vec::new();
    }
    let workers = workers.max(1).min(n);
    let mut prefix = vec![0u64; n + 1];
    for (i, weight) in weights.iter().enumerate() {
        prefix[i + 1] = prefix[i] + (*weight as u64).max(1);
    }
    let total = prefix[n];
    let mut out = Vec::with_capacity(workers);
    let mut start = 0usize;
    for worker in 0..workers {
        let end = if worker + 1 == workers {
            n
        } else {
            let target = ((worker as u64 + 1) * total) / workers as u64;
            let latest = n - (workers - worker - 1);
            let mut end = start + 1;
            while end < latest && prefix[end] < target {
                end += 1;
            }
            end
        };
        out.push((start, end));
        start = end;
    }
    out
}

/// How many threads format frame groups.
///
/// Every worker formats. The bytes are placed afterwards, each at its
/// own offset, so the caller does not copy the file on one thread.
pub(crate) fn pipeline_format_threads(workers: usize) -> usize {
    workers.max(1)
}

/// Eight workers on a long trajectory format into the file itself.
/// One writer stays on the serial formatter. Two and four keep the
/// overlapped copy, which is the faster of the two at those widths.
pub(crate) fn direct_slice_write(workers: usize, total_weight: usize) -> bool {
    workers >= 8 && total_weight >= 3_000_000
}

/// Box numbers the writer emits. Lattice vectors are converted first.
fn written_box(frame: &ConFrame) -> ([f64; 3], [f64; 3]) {
    match frame.header.lattice_vectors() {
        Some(vecs) => crate::types::lengths_and_angles(vecs),
        None => (frame.header.boxl, frame.header.angles),
    }
}

fn add_widths(sum: &mut usize, values: &[f64]) {
    *sum += sum_spelling_widths(values);
}

/// Width of `n/10_000` for `n` in `0..=1_000_000` (magnitudes up to 100).
/// Built once; the timed samples do not pay for it.
fn milli_width_table() -> &'static [u8] {
    const N: usize = 1_000_001;
    static TABLE: std::sync::OnceLock<Box<[u8]>> = std::sync::OnceLock::new();
    TABLE.get_or_init(|| {
        let mut table = vec![0u8; N].into_boxed_slice();
        for n in 0..N {
            table[n] = spell_width((n as f64) / 10_000.0) as u8;
        }
        table
    })
}

fn spell_width(value: f64) -> usize {
    if !value.is_finite() {
        return ryu::Buffer::new().format(value).len();
    }
    if let Some((_, n)) = encode_fixed_decimal_into(value) {
        return n;
    }
    let mut tmp = [0u8; 24];
    unsafe { ryu::raw::format64(value, tmp.as_mut_ptr()) }
}

/// Sum of round-trip widths. Exact multiples of 1e-4 up to 100 use a table.
fn sum_spelling_widths(values: &[f64]) -> usize {
    let table = milli_width_table();
    let mut sum = 0usize;
    for &value in values {
        let bits = value.to_bits();
        let neg = bits >> 63 != 0;
        let mag = f64::from_bits(bits & !(1u64 << 63));
        let scaled = mag * 10_000.0;
        let nearest = scaled.round();
        if nearest <= 1_000_000.0 {
            let n = nearest as usize;
            if ((n as f64) / 10_000.0).to_bits() == mag.to_bits() {
                sum += table[n] as usize + usize::from(neg);
                continue;
            }
        }
        sum += spell_width(value);
    }
    sum
}

/// Floats the writer emits for `frame`, excluding the header text around them.
fn packed_float_widths(frame: &ConFrame) -> usize {
    let mut sum = 0usize;
    let (boxl, angles) = written_box(frame);
    add_widths(&mut sum, &boxl);
    add_widths(&mut sum, &angles);
    add_widths(&mut sum, &frame.header.masses_per_type);
    if let Some(base) = coord_slab(&frame.atom_data) {
        let n = frame.atom_data.len() * 3;
        let coords = unsafe { std::slice::from_raw_parts(base, n) };
        add_widths(&mut sum, coords);
    } else {
        for atom in &frame.atom_data {
            sum += round_trip_width(atom.x());
            sum += round_trip_width(atom.y());
            sum += round_trip_width(atom.z());
        }
    }
    sum += optional_rows_width(frame.velocities.is_present().then(|| &*frame.velocities));
    sum += optional_rows_width(frame.forces.is_present().then(|| &*frame.forces));
    sum += optional_rows_width(frame.magmoms.is_present().then(|| &*frame.magmoms));
    sum += optional_rows_width(
        frame
            .displacements
            .is_present()
            .then(|| &*frame.displacements),
    );
    sum += optional_rows_width(frame.spreads.is_present().then(|| &*frame.spreads));
    sum += optional_column_width(
        frame
            .atom_energies
            .is_present()
            .then(|| &*frame.atom_energies),
    );
    sum += optional_column_width(frame.charges.is_present().then(|| &*frame.charges));
    sum += optional_column_width(frame.spins.is_present().then(|| &*frame.spins));
    // A section stored only on the atom tail is still emitted.
    if !frame.velocities.is_present() && frame.has_velocities() {
        for atom in &frame.atom_data {
            let [x, y, z] = atom.velocity().unwrap_or([0.0; 3]);
            sum += round_trip_width(x) + round_trip_width(y) + round_trip_width(z);
        }
    }
    if !frame.forces.is_present() && frame.has_forces() {
        for atom in &frame.atom_data {
            let [x, y, z] = atom.force().unwrap_or([0.0; 3]);
            sum += round_trip_width(x) + round_trip_width(y) + round_trip_width(z);
        }
    }
    sum
}

fn optional_rows_width(storage: Option<&crate::storage_dtype::Array2Storage>) -> usize {
    let Some(storage) = storage else {
        return 0;
    };
    let Some(values) = storage.f64_slice() else {
        return 0;
    };
    let mut sum = 0usize;
    add_widths(&mut sum, values);
    sum
}

fn optional_column_width(storage: Option<&crate::storage_dtype::Array1Storage>) -> usize {
    let Some(storage) = storage else {
        return 0;
    };
    let Some(values) = storage.f64_slice() else {
        return 0;
    };
    let mut sum = 0usize;
    add_widths(&mut sum, values);
    sum
}

/// Non-float text matches `reference`, so one formatted frame prices it.
fn same_packed_shape(reference: &ConFrame, frame: &ConFrame) -> bool {
    if frame.atom_data.len() != reference.atom_data.len()
        || frame.atom_data.is_empty()
        || frame.header.spec_version != reference.header.spec_version
        || frame.header.natm_types != reference.header.natm_types
        || frame.header.natms_per_type != reference.header.natms_per_type
        || frame.header.masses_per_type.len() != reference.header.masses_per_type.len()
        || frame.header.prebox_header.user != reference.header.prebox_header.user
        || frame.header.prebox_header.metadata_line()
            != reference.header.prebox_header.metadata_line()
        || frame.header.postbox_header != reference.header.postbox_header
        || frame.has_velocities() != reference.has_velocities()
        || frame.has_forces() != reference.has_forces()
        || frame.has_energies() != reference.has_energies()
        || frame.has_charges() != reference.has_charges()
        || frame.has_spins() != reference.has_spins()
        || frame.has_magmoms() != reference.has_magmoms()
        || frame.has_displacements() != reference.has_displacements()
        || frame.has_spreads() != reference.has_spreads()
        || !ids_are_dense(&frame.atom_data, 1)
    {
        return false;
    }
    let mut offset = 0usize;
    for &count in &frame.header.natms_per_type {
        if frame.atom_data[offset].symbol != reference.atom_data[offset].symbol {
            return false;
        }
        offset += count;
    }
    true
}

/// Exact byte length of every frame when they share one text skeleton.
///
/// The skeleton is priced by formatting the first frame. Every other
/// length is that price plus the change in float spellings. `None`
/// means the skeleton differs or a checked frame did not match, and the
/// caller formats into buffers instead.
fn packed_frame_lengths(
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Option<Vec<usize>> {
    // Fixed decimals and a one-frame write keep the buffered path.
    if precision.is_some() || frames.len() < 2 {
        return None;
    }
    let reference = frames[0];
    if reference.atom_data.is_empty() || !ids_are_dense(&reference.atom_data, 1) {
        return None;
    }
    let workers = workers.max(1).min(frames.len());
    let shape_ok = std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(workers);
        for thread in 0..workers {
            let start = thread * frames.len() / workers;
            let end = (thread + 1) * frames.len() / workers;
            guards.push(scope.spawn(move || {
                frames[start..end]
                    .iter()
                    .all(|frame| same_packed_shape(reference, frame))
            }));
        }
        guards
            .into_iter()
            .all(|guard| guard.join().unwrap_or(false))
    });
    if !shape_ok {
        return None;
    }
    let widths = std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(workers);
        for thread in 0..workers {
            let start = thread * frames.len() / workers;
            let end = (thread + 1) * frames.len() / workers;
            guards.push(scope.spawn(move || {
                #[cfg(feature = "parallel")]
                crate::parser::pin_worker(thread);
                frames[start..end]
                    .iter()
                    .map(|frame| packed_float_widths(frame))
                    .collect::<Vec<_>>()
            }));
        }
        let mut widths = Vec::with_capacity(frames.len());
        for guard in guards {
            widths.extend(guard.join().unwrap_or_default());
        }
        widths
    });
    if widths.len() != frames.len() {
        return None;
    }
    let sample = format_group_bytes(
        std::slice::from_ref(&reference),
        1,
        precision,
        canonical,
        bind,
    )
    .ok()?;
    let overhead = sample.len().checked_sub(widths[0])?;
    let lengths: Vec<usize> = widths.iter().map(|width| overhead + width).collect();
    for &index in [0, frames.len() / 2, frames.len() - 1].iter() {
        let got = format_group_bytes(
            std::slice::from_ref(&frames[index]),
            1,
            precision,
            canonical,
            bind,
        )
        .ok()?
        .len();
        if got != lengths[index] {
            return None;
        }
    }
    Some(lengths)
}

/// Format `group` into `dest`. `dest` is the exact concatenation, so the
/// bytes are not copied into a second buffer afterwards.
pub(crate) fn format_group_into(
    group: &[&ConFrame],
    dest: &mut [u8],
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    if dest.is_empty() {
        return Ok(());
    }
    struct Held {
        writer: ConFrameWriter<Vec<u8>>,
    }
    impl Drop for Held {
        fn drop(&mut self) {
            // `scratch` aliases `dest`. Dropping it would free that memory.
            std::mem::forget(std::mem::take(&mut self.writer.scratch));
        }
    }
    let cap = dest.len();
    let ptr = dest.as_mut_ptr();
    let mut held = Held {
        writer: match precision {
            Some(precision) => ConFrameWriter::with_precision(Vec::new(), precision),
            None => ConFrameWriter::new(Vec::new()),
        }
        .canonical(canonical)
        .retain_scratch(true),
    };
    held.writer.exact_scratch = true;
    let previous = std::mem::replace(&mut held.writer.scratch, unsafe {
        Vec::from_raw_parts(ptr, 0, cap)
    });
    drop(previous);
    let result = write_group(&mut held.writer, group, bind);
    let written = held.writer.scratch.len();
    let stable = held.writer.scratch.as_ptr() == ptr;
    result?;
    if written != cap || !stable {
        return Err(WriteError::Io(io::Error::other(
            "packed frame length drifted",
        )));
    }
    Ok(())
}

/// Format each group straight into its slice of `file`.
fn place_packed(
    file: &File,
    frames: &[&ConFrame],
    lengths: &[usize],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    let total: u64 = lengths.iter().map(|len| *len as u64).sum();
    allocate_len(file, total).map_err(WriteError::Io)?;
    if total == 0 {
        return Ok(());
    }
    let ranges = pack_frames_by_weight(lengths, workers);
    let mut prefix = vec![0usize; lengths.len() + 1];
    for (index, len) in lengths.iter().enumerate() {
        prefix[index + 1] = prefix[index] + len;
    }
    // Miri writes through `pwrite`. A real file is one mapping, and each
    // worker fills its own range.
    if cfg!(miri) {
        let mut parts = Vec::with_capacity(ranges.len());
        for &(start, end) in &ranges {
            parts.push(format_group_bytes(
                &frames[start..end],
                1,
                precision,
                canonical,
                bind,
            )?);
        }
        return store_disjoint_parts(file, &parts).map_err(WriteError::Io);
    }
    // One mapping per worker, dropped on that worker. Tearing down a single
    // 184 MB map was a serial tail after the formatters had finished.
    std::thread::scope(|scope| {
        let mut guards = Vec::with_capacity(ranges.len());
        for (thread, &(start, end)) in ranges.iter().enumerate() {
            let offset = prefix[start];
            let span = prefix[end] - prefix[start];
            let piece = &frames[start..end];
            let cloned = file.try_clone().map_err(WriteError::Io)?;
            guards.push(scope.spawn(move || -> Result<(), WriteError> {
                #[cfg(feature = "parallel")]
                crate::parser::pin_worker(thread);
                if span == 0 {
                    return Ok(());
                }
                let page = 4096usize;
                let map_off = offset & !(page - 1);
                let delta = offset - map_off;
                let map_len = delta + span;
                let mut map = unsafe {
                    memmap2::MmapOptions::new()
                        .offset(map_off as u64)
                        .len(map_len)
                        .map_mut(&cloned)
                        .map_err(WriteError::Io)?
                };
                advise_shared_store(&cloned, map.as_mut_ptr(), map.len());
                let dest = &mut map[delta..delta + span];
                // A reused L2 buffer plus a plain or non-temporal copy was
                // slower here than spelling straight into the fresh pages.
                format_group_into(piece, dest, precision, canonical, bind)?;
                drop(map);
                Ok(())
            }));
        }
        for guard in guards {
            match guard.join() {
                Ok(result) => result?,
                Err(_) => {
                    return Err(WriteError::Io(io::Error::other("frame formatter panicked")));
                }
            }
        }
        Ok(())
    })
}

/// Format frame groups on [`pipeline_format_threads`] threads, then
/// place each group at its file offset. There is no ordered `write_all`
/// of the whole text.
fn write_serial_frames(
    path: &std::path::Path,
    frames: &[&ConFrame],
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    // A priced trajectory is spelled straight into the fresh file. The
    // copy onto a second buffer was the gap against a writer that filled
    // the inode itself. One frame has no group price; it streams.
    if frames.len() >= 2
        && let Some(lengths) = cached_packed_lengths(frames, 1, precision, canonical, bind)
    {
        let (staged, file) = begin_unpublished(path)?;
        let result = place_packed(&file, frames, &lengths, 1, precision, canonical, bind);
        return finish_unpublished(staged, path, result);
    }
    let (staged, file) = begin_unpublished(path)?;
    let mut writer = match precision {
        Some(precision) => ConFrameWriter::with_precision(file, precision),
        None => ConFrameWriter::new(file),
    }
    .canonical(canonical);
    let result =
        write_group(&mut writer, frames, bind).and_then(|_| writer.flush().map_err(WriteError::Io));
    drop(writer);
    finish_unpublished(staged, path, result)
}

fn pipeline_frame_groups(
    path: &std::path::Path,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    // One formatter per frame when there is a core for each. Reserving a
    // thread for the writer left two frames on two threads formatting
    // one after the other, so the pair took about twice one frame.
    if (2..=workers).contains(&frames.len()) {
        let mut parts: Vec<Result<Vec<u8>, WriteError>> = Vec::with_capacity(frames.len());
        std::thread::scope(|scope| {
            let mut guards = Vec::with_capacity(frames.len());
            for (index, frame) in frames.iter().enumerate() {
                guards.push(scope.spawn(move || {
                    #[cfg(feature = "parallel")]
                    crate::parser::pin_worker(index);
                    format_group_bytes(std::slice::from_ref(frame), 1, precision, canonical, bind)
                }));
            }
            for guard in guards {
                parts.push(match guard.join() {
                    Ok(part) => part,
                    Err(_) => Err(WriteError::Io(io::Error::other("frame formatter panicked"))),
                });
            }
        });
        let mut formatted = Vec::with_capacity(parts.len());
        for part in parts {
            formatted.push(part?);
        }
        let (staged, file) = begin_unpublished(path)?;
        let result = store_disjoint_parts(&file, &formatted).map_err(WriteError::Io);
        return finish_unpublished(staged, path, result);
    }
    // Eight workers fill the machine, so a repeat write formats straight
    // into the file. Fewer workers keep the overlapped copy: pricing
    // and a direct store are slower there, and one worker never prices.
    let heavy = direct_slice_write(
        workers,
        frame_byte_weight(frames[0]).saturating_mul(frames.len()),
    );
    if heavy
        && let Some(lengths) = cached_packed_lengths(frames, workers, precision, canonical, bind)
    {
        let (staged, file) = begin_unpublished(path)?;
        let result = place_packed(&file, frames, &lengths, workers, precision, canonical, bind);
        return finish_unpublished(staged, path, result);
    }
    // Several groups per worker so the first one finishes early and the
    // copy overlaps the rest. Uniform frames skip the weight scan;
    // a mixed trajectory is packed by byte weight.
    let groups = workers.saturating_mul(4).max(workers);
    let ranges = group_frame_ranges(frames, groups);
    let pieces: Vec<&[&ConFrame]> = ranges
        .iter()
        .map(|&(start, end)| &frames[start..end])
        .collect();
    let format_threads = pipeline_format_threads(workers).min(pieces.len().max(1));
    // Depth 2 keeps the copy on the caller's core. A deep queue lets
    // every group finish first and the copy becomes a second pass.
    let (tx, rx) = std::sync::mpsc::sync_channel::<(usize, Result<Vec<u8>, WriteError>)>(2);
    let next_job = std::sync::atomic::AtomicUsize::new(0);
    let (staged, file) = begin_unpublished(path)?;
    let result = std::thread::scope(|scope| {
        for _ in 0..format_threads {
            let tx = tx.clone();
            let pieces = &pieces;
            let next_job = &next_job;
            scope.spawn(move || {
                loop {
                    let index = next_job.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    if index >= pieces.len() {
                        break;
                    }
                    let message = format_group_bytes(pieces[index], 1, precision, canonical, bind);
                    if tx.send((index, message)).is_err() {
                        break;
                    }
                }
            });
        }
        drop(tx);
        let mut file = file;
        let mut next = 0usize;
        let mut pending = BTreeMap::<usize, Vec<u8>>::new();
        while next < pieces.len() {
            let (index, part) = rx
                .recv()
                .map_err(|err| WriteError::Io(io::Error::other(err.to_string())))?;
            pending.insert(index, part?);
            while let Some(part) = pending.remove(&next) {
                file.write_all(&part).map_err(WriteError::Io)?;
                next += 1;
            }
        }
        file.flush().map_err(WriteError::Io)?;
        Ok(())
    });
    finish_unpublished(staged, path, result)
}

struct PackedCache {
    first: usize,
    last: usize,
    count: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
    generation: u64,
    lengths: Vec<usize>,
}

static PACKED_GEN: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
static PACKED_FIRST: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
static PACKED_LAST: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// A coordinate edit changes the spelled length. The next write prices again.
pub(crate) fn invalidate_packed_lengths() {
    PACKED_GEN.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
}

/// Dropping a frame that anchors the priced lengths retires that price.
/// A later allocation at the same address must not reuse it.
pub(crate) fn invalidate_packed_lengths_if(frame: usize) {
    let first = PACKED_FIRST.load(std::sync::atomic::Ordering::Relaxed);
    if first != 0
        && (frame == first || frame == PACKED_LAST.load(std::sync::atomic::Ordering::Relaxed))
    {
        invalidate_packed_lengths();
        PACKED_FIRST.store(0, std::sync::atomic::Ordering::Relaxed);
    }
}

pub(crate) fn cached_packed_lengths(
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Option<Vec<usize>> {
    let first = frames[0] as *const ConFrame as usize;
    let last = *frames.last()? as *const ConFrame as usize;
    let count = frames.len();
    static CACHE: std::sync::Mutex<Option<PackedCache>> = std::sync::Mutex::new(None);
    let generation = PACKED_GEN.load(std::sync::atomic::Ordering::Relaxed);
    if let Some(hit) = CACHE.lock().unwrap_or_else(|err| err.into_inner()).as_ref()
        && hit.generation == generation
        && hit.first == first
        && hit.last == last
        && hit.count == count
        && hit.precision == precision
        && hit.canonical == canonical
        && hit.bind == bind
    {
        return Some(hit.lengths.clone());
    }
    let generation_before = PACKED_GEN.load(std::sync::atomic::Ordering::Relaxed);
    let lengths = packed_frame_lengths(frames, workers, precision, canonical, bind)?;
    let generation_after = PACKED_GEN.load(std::sync::atomic::Ordering::Relaxed);
    if generation_before == generation_after {
        PACKED_FIRST.store(first, std::sync::atomic::Ordering::Relaxed);
        PACKED_LAST.store(last, std::sync::atomic::Ordering::Relaxed);
        *CACHE.lock().unwrap_or_else(|err| err.into_inner()) = Some(PackedCache {
            first,
            last,
            count,
            precision,
            canonical,
            bind,
            generation: generation_after,
            lengths: lengths.clone(),
        });
    }
    Some(lengths)
}

/// Place `parts` at their prefix-sum offsets. On tmpfs each part is
/// copied into one shared mapping. Elsewhere each part is a `pwrite`.
/// The ranges do not overlap, so the stores do not share a byte.
fn store_disjoint_parts(file: &File, parts: &[Vec<u8>]) -> io::Result<()> {
    let mut offsets = Vec::with_capacity(parts.len());
    let mut total = 0u64;
    for part in parts {
        offsets.push(total);
        total += part.len() as u64;
    }
    allocate_len(file, total)?;
    if total == 0 {
        return Ok(());
    }
    if file_is_tmpfs(file) {
        store_mapped_parts(file, parts, &offsets)
    } else {
        std::thread::scope(|scope| {
            let mut guards = Vec::new();
            for (part, at) in parts.iter().zip(offsets) {
                let cloned = file.try_clone()?;
                guards.push(scope.spawn(move || pwrite_full(&cloned, part, at)));
            }
            for guard in guards {
                guard
                    .join()
                    .unwrap_or_else(|_| Err(io::Error::other("pwrite worker")))?;
            }
            Ok(())
        })
    }
}

fn store_mapped_parts(file: &File, parts: &[Vec<u8>], offsets: &[u64]) -> io::Result<()> {
    let total = offsets
        .last()
        .copied()
        .unwrap_or(0)
        .saturating_add(parts.last().map(|part| part.len() as u64).unwrap_or(0));
    let mut map = unsafe {
        memmap2::MmapOptions::new()
            .len(total as usize)
            .map_mut(file)?
    };
    let base = map.as_mut_ptr() as usize;
    std::thread::scope(|scope| {
        for (part, at) in parts.iter().zip(offsets) {
            let src = part.as_ptr() as usize;
            let len = part.len();
            let dest = base + *at as usize;
            scope.spawn(move || {
                if len == 0 {
                    return;
                }
                // SAFETY: `dest` is inside `map`, the ranges do not
                // overlap, and `map` outlives this scope.
                unsafe {
                    std::ptr::copy_nonoverlapping(src as *const u8, dest as *mut u8, len);
                }
            });
        }
    });
    Ok(())
}

fn write_group<W: Write>(
    writer: &mut ConFrameWriter<W>,
    group: &[&ConFrame],
    bind: bool,
) -> Result<(), WriteError> {
    if bind {
        for frame in group {
            writer.write_frame_bound(frame)?;
        }
        return Ok(());
    }
    writer.extend(group.iter().copied())
}

fn loose_frame_bytes(frame: &ConFrame) -> usize {
    let mut blocks = 1usize;
    if frame.has_velocities() {
        blocks += 1;
    }
    if frame.has_forces() {
        blocks += 1;
    }
    if frame.has_energies() {
        blocks += 1;
    }
    if frame.has_charges() {
        blocks += 1;
    }
    if frame.has_spins() {
        blocks += 1;
    }
    if frame.has_magmoms() {
        blocks += 1;
    }
    if frame.has_displacements() {
        blocks += 1;
    }
    if frame.has_spreads() {
        blocks += 1;
    }
    256 + frame
        .atom_data
        .len()
        .saturating_mul(64)
        .saturating_mul(blocks)
}

fn format_group_bytes(
    group: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<Vec<u8>, WriteError> {
    let mut buffer = Vec::new();
    let mut writer = match precision {
        Some(precision) => ConFrameWriter::with_precision(&mut buffer, precision),
        None => ConFrameWriter::new(&mut buffer),
    }
    .canonical(canonical)
    .retain_scratch(true);
    if workers >= 2 {
        writer = writer.parallel_atoms(workers);
    }
    // One frame's reserve, repeated, copies the whole group each time it
    // doubles. Size the scratch for every frame before the first byte.
    let need: usize = group.iter().map(|frame| loose_frame_bytes(frame)).sum();
    writer.scratch.reserve(need);
    write_group(&mut writer, group, bind)?;
    Ok(std::mem::take(&mut writer.scratch))
}

fn formatted_parts(
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<Vec<Vec<u8>>, WriteError> {
    let wide = frames.len() == 1 && frames[0].atom_data.len() >= WIDE_ATOM_GRAIN;
    if workers < 2 || (frames.len() < 2 && !wide) {
        return Ok(vec![format_group_bytes(
            frames, 1, precision, canonical, bind,
        )?]);
    }
    if wide {
        return Ok(vec![format_group_bytes(
            frames, workers, precision, canonical, bind,
        )?]);
    }
    #[cfg(feature = "parallel")]
    {
        let chunk = frames.len().div_ceil(workers).max(1);
        crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            frames
                .par_chunks(chunk)
                .map(|group| format_group_bytes(group, 1, precision, canonical, bind))
                .collect()
        })
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = workers;
        Ok(vec![format_group_bytes(
            frames, 1, precision, canonical, bind,
        )?])
    }
}

fn pwrite_borrowed(file: &File, parts: &[&[u8]]) -> io::Result<()> {
    let mut offset = 0u64;
    let mut offsets = Vec::with_capacity(parts.len());
    for part in parts {
        offsets.push(offset);
        offset += part.len() as u64;
    }
    file.set_len(offset)?;
    std::thread::scope(|scope| {
        let mut handles = Vec::new();
        for (part, at) in parts.iter().zip(offsets) {
            let file = file.try_clone()?;
            handles.push(scope.spawn(move || pwrite_full(&file, part, at)));
        }
        for handle in handles {
            handle
                .join()
                .unwrap_or_else(|_| Err(io::Error::other("pwrite worker")))?;
        }
        Ok(())
    })
}

fn pwrite_full(file: &File, buf: &[u8], mut offset: u64) -> io::Result<()> {
    if buf.is_empty() {
        return Ok(());
    }
    // Miri can seek and write. `pwrite` keeps the caller's offset on a
    // normal build; the clone does the same under Miri.
    #[cfg(miri)]
    {
        use std::io::{Seek, SeekFrom, Write};
        let mut out = file.try_clone()?;
        out.seek(SeekFrom::Start(offset))?;
        out.write_all(buf)?;
        return Ok(());
    }
    #[cfg(all(not(miri), unix))]
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
                let err = io::Error::last_os_error();
                if err.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(err);
            }
            if n == 0 {
                return Err(io::Error::new(io::ErrorKind::WriteZero, "pwrite"));
            }
            written += n as usize;
            offset += n as u64;
        }
        Ok(())
    }
    #[cfg(all(not(miri), windows))]
    {
        use std::os::windows::fs::FileExt;
        file.seek_write(buf, offset)?;
        Ok(())
    }
}

/// Serializes `frames` to a CON string. No file is created.
///
/// The bytes match [`ConFrameWriter::from_path`] writing the same frames.
pub fn write_frames_to_string(frames: &[ConFrame]) -> Result<String, WriteError> {
    let bytes = write_frames_to_vec(frames)?;
    String::from_utf8(bytes).map_err(|err| {
        WriteError::Io(io::Error::new(
            io::ErrorKind::InvalidData,
            err.utf8_error().to_string(),
        ))
    })
}

// Gzip-compressed writer constructors.
impl ConFrameWriter<flate2::write::GzEncoder<File>> {
    /// Creates a gzip-compressed writer for the given path.
    pub fn from_path_gzip<P: AsRef<Path>>(path: P) -> io::Result<Self> {
        let encoder = crate::compression::gzip_writer(path.as_ref())?;
        Ok(Self::new(encoder))
    }

    /// Creates a gzip-compressed writer with custom precision.
    pub fn from_path_gzip_with_precision<P: AsRef<Path>>(
        path: P,
        precision: usize,
    ) -> io::Result<Self> {
        let encoder = crate::compression::gzip_writer(path.as_ref())?;
        Ok(Self::with_precision(encoder, precision))
    }
}

// Zstd-compressed writer constructors. Available only with the `zstd`
// Cargo feature.
#[cfg(feature = "zstd")]
impl ConFrameWriter<zstd::stream::write::AutoFinishEncoder<'static, File>> {
    /// Creates a zstd-compressed writer for the given path.
    pub fn from_path_zstd<P: AsRef<Path>>(path: P) -> io::Result<Self> {
        let encoder = crate::compression::zstd_writer(path.as_ref())?;
        Ok(Self::new(encoder))
    }

    /// Creates a zstd-compressed writer with custom precision.
    pub fn from_path_zstd_with_precision<P: AsRef<Path>>(
        path: P,
        precision: usize,
    ) -> io::Result<Self> {
        let encoder = crate::compression::zstd_writer(path.as_ref())?;
        Ok(Self::with_precision(encoder, precision))
    }
}

#[cfg(test)]
mod float_format_tests {
    use super::{encode_fixed_decimal_into, push_f64_prec, push_u64, write_finite};

    fn formatted(v: f64, prec: usize) -> String {
        let mut buf = Vec::new();
        push_f64_prec(&mut buf, v, prec);
        String::from_utf8(buf).expect("utf8")
    }

    #[test]
    fn matches_std_fixed_precision() {
        let vals = [
            0.0,
            -0.0,
            1.0,
            -1.0,
            0.9045,
            6.975_299_999_999_995,
            63.546,
            1.008,
            15.3456,
            90.0,
            218.0,
            1e-6,
            -1.23456789,
            10.0,
        ];
        for prec in [0usize, 6] {
            for v in vals {
                let got = formatted(v, prec);
                let exp = format!("{v:.prec$}");
                assert_eq!(got, exp, "v={v:?} prec={prec}");
            }
        }
    }

    #[test]
    fn fixed_decimal_matches_ryu_including_edges() {
        let mut ryu_buf = ryu::Buffer::new();
        let mut values = vec![
            0.0,
            -0.0,
            1.0,
            -1.0,
            10.0,
            97.0,
            -97.0,
            63.546,
            0.5,
            0.125,
            1.5,
            -0.1,
            0.1 + 0.2,
            1.0 / 3.0,
            -9088916957.866665,
            -9345863084.186747,
            9663676416.00047,
            1e15,
            -1e15,
            1e16,
            1e20,
            -1e20,
            1e-6,
            1e-10,
            f64::MIN_POSITIVE,
            f64::MAX,
            f64::MIN,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NAN,
        ];
        let mut state = 0x1234_5678_9abc_def0u64;
        for _ in 0..256 {
            state = state.wrapping_mul(0x5851_f42d_4c95_7f2d).wrapping_add(1);
            values.push(f64::from_bits(state));
        }
        for value in values {
            let mut got = Vec::new();
            let mut scratch = ryu::Buffer::new();
            super::push_round_trip(&mut got, &mut scratch, None, value);
            let expect = ryu_buf.format(value);
            if value.is_nan() {
                assert_eq!(std::str::from_utf8(&got).unwrap(), expect);
                continue;
            }
            assert_eq!(std::str::from_utf8(&got).unwrap(), expect, "{value:?}");
        }
    }

    fn old_fixed(mag: f64) -> Option<(u64, u32)> {
        if mag <= 1e16 && mag.fract() == 0.0 {
            let n = mag as u64;
            if n < 10u64.pow(16) && n as f64 == mag {
                return Some((n, 0));
            }
        }
        let mut scale = 10.0f64;
        for d in 1u32..=6 {
            let scaled = mag * scale;
            if !scaled.is_finite() || scaled > 1e16 {
                break;
            }
            let nearest = scaled.round();
            let n = nearest as u64;
            if nearest == n as f64 && (n as f64) / scale == mag {
                let mut n = n;
                let mut places = d;
                while places > 0 && n.is_multiple_of(10) {
                    n /= 10;
                    places -= 1;
                }
                if places == 0 {
                    if n >= 10u64.pow(16) {
                        return None;
                    }
                    return Some((n, 0));
                }
                let digits = super::count_digits(n);
                let kk = digits as i32 - places as i32;
                if !(kk > -5 && kk <= 16) {
                    return None;
                }
                return Some((n, places));
            }
            scale *= 10.0;
        }
        None
    }

    #[test]
    fn one_scale_matches_the_six_step_search() {
        let mut state = 0x1234_5678_9abc_def0u64;
        let mut values = vec![
            -9283744841.119225_f64,
            0.6394,
            -9088916957.866665,
            -9345863084.186747,
            9663676416.00047,
            -0.0001,
            1.25,
            97.0,
            -0.0,
            1.0e-7,
            -1.0e-7,
            1.0e20,
            -1.0e20,
            1.0e16,
            0.5,
            1.5,
            2.5,
            f64::MIN,
            f64::MAX,
        ];
        for _ in 0..50_000 {
            state = state.wrapping_mul(0x5851_f42d_4c95_7f2d).wrapping_add(1);
            values.push(f64::from_bits(state));
        }
        for value in values {
            if !value.is_finite() {
                continue;
            }
            let mag = value.abs();
            let old = old_fixed(mag);
            let new = super::fixed_decimal_parts(mag);
            if new != old {
                let mut got = Vec::new();
                let mut scratch = ryu::Buffer::new();
                super::push_round_trip(&mut got, &mut scratch, None, value);
                let mut ryu_buf = ryu::Buffer::new();
                let expect = ryu_buf.format(value);
                assert_eq!(
                    std::str::from_utf8(&got).unwrap(),
                    expect,
                    "{value:?} old={old:?} new={new:?}"
                );
                continue;
            }
            if let Some((n, places)) = new {
                let mut fast = [0u8; 32];
                let mut slow = [0u8; 32];
                let nfast =
                    super::write_fixed_digits(&mut fast, value.is_sign_negative(), n, places);
                let mut i = slow.len();
                let mut x = n;
                if x == 0 {
                    i -= 1;
                    slow[i] = b'0';
                } else {
                    while x > 0 {
                        i -= 1;
                        slow[i] = b'0' + (x % 10) as u8;
                        x /= 10;
                    }
                }
                let digs = &slow[i..];
                let mut expect = Vec::new();
                if value.is_sign_negative() {
                    expect.push(b'-');
                }
                if places == 0 {
                    expect.extend_from_slice(digs);
                    expect.extend_from_slice(b".0");
                } else {
                    let kk = digs.len() as i32 - places as i32;
                    if kk > 0 {
                        let cut = kk as usize;
                        expect.extend_from_slice(&digs[..cut]);
                        expect.push(b'.');
                        expect.extend_from_slice(&digs[cut..]);
                    } else {
                        expect.extend_from_slice(b"0.");
                        expect.extend(std::iter::repeat_n(b'0', (-kk) as usize));
                        expect.extend_from_slice(digs);
                    }
                }
                assert_eq!(&fast[..nfast], expect.as_slice(), "{value:?} {n} {places}");
            }
        }
    }

    #[test]
    fn round_trip_spelling_matches_ryu_on_repeated_and_unique_rows() {
        use crate::iterators::ConFrameIterator;
        use crate::writer::ConFrameWriter;
        let mut text = String::from(
            "bench\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0 1\n1\n6\n12.0\nCu\nCoordinates of Component 1\n",
        );
        for i in 0..6 {
            let x = (i % 2) as f64 * 1.5 + 0.25;
            let y = 3.25;
            let z = if i == 3 {
                -0.0
            } else {
                (i as f64) * 0.0010000001
            };
            text.push_str(&format!("   {x:.17}    {y:.17}    {z:.17} 0 {i}\n"));
        }
        // Repeated velocities share the column cache with the coordinates.
        text.push_str("\nCu\nVelocities of Component 1\n");
        for i in 0..6 {
            let vx = 0.125;
            let vy = if i % 2 == 0 { 0.5 } else { -0.5 };
            let vz = (i as f64) * 1.0e-4;
            text.push_str(&format!("   {vx:.17}    {vy:.17}    {vz:.17} 0 {i}\n"));
        }
        let frames: Vec<_> = ConFrameIterator::new(&text)
            .map(|frame| frame.expect("parse"))
            .collect();
        let mut values = Vec::new();
        for atom in &frames[0].atom_data {
            values.extend([atom.x(), atom.y(), atom.z()]);
        }
        for atom in &frames[0].atom_data {
            if let Some(v) = atom.velocity() {
                values.extend(v);
            }
        }
        let mut buf = Vec::new();
        {
            let mut writer = ConFrameWriter::new(&mut buf);
            writer.extend(frames.iter()).unwrap();
        }
        let written = String::from_utf8(buf).unwrap();
        let mut ryu = ryu::Buffer::new();
        let mut spelled = Vec::new();
        for line in written.lines() {
            let toks: Vec<_> = line.split_whitespace().collect();
            if toks.len() >= 5
                && toks[0].contains('.')
                && toks[3].bytes().all(|b| b.is_ascii_digit())
            {
                spelled.extend(toks[..3].iter().map(|tok| (*tok).to_string()));
            }
        }
        assert_eq!(spelled.len(), values.len());
        for (got, value) in spelled.iter().zip(values) {
            let expect = if value.is_finite() {
                ryu.format_finite(value).to_string()
            } else {
                ryu.format(value).to_string()
            };
            assert_eq!(got, &expect, "value {value:?}");
        }
    }

    #[test]
    fn fixed_decimal_matches_ryu_or_falls_back_to_it() {
        let mut values = vec![
            0.0,
            -0.0,
            1.0,
            -2.0,
            10.0,
            99.0,
            100.0,
            0.1,
            0.01,
            0.001,
            0.0001,
            0.0002,
            -0.0001,
            1.5,
            0.25,
            0.125,
            63.546,
            12.0,
            90.0,
            3.25,
            0.5,
            -0.5,
            1.0e-4,
            1.25,
            218.0,
            6.975_299_999_999_995,
            1.008,
            15.3456,
            -1.23456789,
            1e-6,
            1e16,
            1e20,
        ];
        for i in 0..200 {
            values.push(i as f64);
            values.push((i as f64) * 0.001);
            values.push((i as f64) * 0.0001);
            values.push(-(i as f64) * 0.001);
        }
        let mut ryu = ryu::Buffer::new();
        for value in values {
            let mut buf = Vec::new();
            write_finite(&mut buf, value);
            let expect = ryu.format_finite(value);
            assert_eq!(std::str::from_utf8(&buf).unwrap(), expect, "{value:?}");
            if encode_fixed_decimal_into(value).is_none() {
                continue;
            }
        }
    }

    #[test]
    fn u64_matches_decimal_display() {
        let mut values = vec![0, 1, 9, 10, 11, 99, 100, 101, 999, 1000, 50000, u64::MAX];
        values.extend(0..200);
        for n in values {
            let mut buf = Vec::new();
            push_u64(&mut buf, n);
            assert_eq!(std::str::from_utf8(&buf).unwrap(), n.to_string());
        }
    }
}

#[cfg(test)]
mod section_arity_tests {
    use super::require_minor2_section_arity;
    use serde_json::json;

    #[test]
    fn minor2_lists_a_new_section_in_section_arity() {
        let widgets = vec![json!("widgets")];
        let err = require_minor2_section_arity(2, &widgets, &serde_json::Map::new()).unwrap_err();
        let msg = err.to_string();
        assert!(msg.contains("section_arity"), "{msg}");

        let mut listed = serde_json::Map::new();
        listed.insert("section_arity".into(), json!({"widgets": 3}));
        require_minor2_section_arity(2, &widgets, &listed).unwrap();

        let reserved = vec![json!("velocities"), json!("energies")];
        require_minor2_section_arity(2, &reserved, &serde_json::Map::new()).unwrap();
        require_minor2_section_arity(1, &widgets, &serde_json::Map::new()).unwrap();
    }
}

#[cfg(test)]
mod publish_on_every_host {
    use super::publish_ranked_slices;

    /// macOS renames a scratch preallocated with `posix_fallocate`. Windows
    /// renames a scratch extended with `set_len`. Linux may use an unnamed
    /// file. The published bytes and the absence of a scratch are the same.
    #[test]
    fn ranked_slices_replace_the_destination_and_leave_no_scratch() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("pieces.bin");
        std::fs::write(&path, b"previous").unwrap();
        publish_ranked_slices(&path, &[b"ab", &[], b"cde"], false, false).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"abcde");
        let names: Vec<_> = std::fs::read_dir(dir.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .filter(|name| name.starts_with(".readcon-write-") || name.ends_with(".rewrite"))
            .collect();
        assert!(names.is_empty(), "scratch left behind: {names:?}");
    }
}

#[cfg(test)]
mod weight_partition {
    use super::pack_frames_by_weight;
    use proptest::prelude::*;

    /// Groups are a half-open partition of `0..n` in file order.
    /// An empty range drops a frame; a step backwards repeats one.
    fn is_ordered_partition(n: usize, workers: usize, ranges: &[(usize, usize)]) -> bool {
        if n == 0 {
            return ranges.is_empty();
        }
        let workers = workers.max(1).min(n);
        if ranges.len() != workers {
            return false;
        }
        let mut cursor = 0usize;
        for &(start, end) in ranges {
            if start != cursor || end <= start || end > n {
                return false;
            }
            cursor = end;
        }
        cursor == n
    }

    proptest! {
        #![proptest_config(ProptestConfig {
            cases: 64,
            failure_persistence: None,
            ..ProptestConfig::default()
        })]
        #[test]
        fn byte_weights_do_not_drop_or_reorder_frames(
            weights in prop::collection::vec(0usize..50_000, 0..48),
            workers in 1usize..17,
        ) {
            let ranges = pack_frames_by_weight(&weights, workers);
            prop_assert!(
                is_ordered_partition(weights.len(), workers, &ranges),
                "weights={weights:?} workers={workers} ranges={ranges:?}"
            );
        }
    }
}

#[cfg(all(test, feature = "parallel"))]
mod parallel_write_tests {
    use super::{
        direct_slice_write, frame_byte_weight, pack_frames_by_weight, pipeline_format_threads,
    };

    /// Two workers used to format on one thread. The caller only writes
    /// a group it has already received, so both workers have to format.
    #[test]
    fn two_workers_both_format_frame_groups() {
        assert_eq!(pipeline_format_threads(1), 1);
        assert_eq!(pipeline_format_threads(2), 2);
        assert_eq!(pipeline_format_threads(8), 8);
    }

    /// One writer never prices the file. Two and four keep the overlapped
    /// copy. Only eight workers on a long trajectory format into the file.
    #[test]
    fn serial_and_narrow_writes_skip_the_direct_slice() {
        let long = 3_000_000;
        assert!(!direct_slice_write(1, long));
        assert!(!direct_slice_write(2, long));
        assert!(!direct_slice_write(4, long));
        assert!(direct_slice_write(8, long));
        assert!(!direct_slice_write(8, long - 1));
    }

    /// Equal frame counts would split `[1, 1, 1, 100]` into two and two,
    /// gluing the heavy frame to a light one.
    #[test]
    fn a_heavy_frame_is_not_glued_to_a_light_one() {
        assert_eq!(
            pack_frames_by_weight(&[1, 1, 1, 100], 2),
            vec![(0, 3), (3, 4)]
        );
        assert_eq!(
            pack_frames_by_weight(&[100, 1, 1, 1], 2),
            vec![(0, 1), (1, 4)]
        );
        assert_eq!(
            pack_frames_by_weight(&[4, 4, 4, 4, 4, 4, 4, 4], 4),
            vec![(0, 2), (2, 4), (4, 6), (6, 8)]
        );
    }

    #[test]
    fn velocity_lines_weigh_more_than_the_same_coordinates() {
        let con = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.con"
        ))
        .unwrap();
        let vel = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.convel"
        ))
        .unwrap();
        let plain = crate::iterators::frames_from_text(&con, Some(1)).unwrap();
        let moving = crate::iterators::frames_from_text(&vel, Some(1)).unwrap();
        assert!(frame_byte_weight(&moving[0]) > frame_byte_weight(&plain[0]));
        assert_eq!(
            frame_byte_weight(&moving[0]),
            plain[0].atom_data.len().max(1) * 2
        );
    }

    /// Three frames, the last with velocities. Two workers must not
    /// scramble the file when the heavy frame sits in its own group.
    #[test]
    fn packed_groups_match_the_serial_bytes() {
        let _scratch = tempfile::tempdir().unwrap();
        let con = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.con"
        ))
        .unwrap();
        let vel = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.convel"
        ))
        .unwrap();
        let text = format!("{con}{con}{vel}");
        let frames = crate::iterators::frames_from_text(&text, Some(1)).unwrap();
        assert!(frames.len() > 2);
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let mut serial = Vec::new();
        {
            let mut writer = super::ConFrameWriter::new(&mut serial);
            for frame in &frames {
                writer.write_frame_bound(frame).unwrap();
            }
            writer.flush().unwrap();
        }
        let path = _scratch
            .path()
            .join(format!("rc-pack-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&path, &refs, 2, None, false, true).unwrap();
        let got = std::fs::read(&path).unwrap();
        assert_eq!(got, serial);
        let _ = std::fs::remove_file(&path);
    }

    /// Light frames then velocity frames. Equal frame counts put the
    /// heavy half in its own groups, more than 10% above the mean.
    /// Byte weights keep the heaviest group within 10% of that mean,
    /// and the file is still the serial byte stream.
    #[test]
    fn mixed_con_and_convel_groups_stay_within_ten_percent() {
        let _scratch = tempfile::tempdir().unwrap();
        let con = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.con"
        ))
        .unwrap();
        let vel = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/tiny_cuh2.convel"
        ))
        .unwrap();
        let text = format!("{}{}", con.repeat(24), vel.repeat(24));
        let frames = crate::iterators::frames_from_text(&text, Some(1)).unwrap();
        assert_eq!(frames.len(), 48);
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let weights: Vec<usize> = refs.iter().map(|frame| frame_byte_weight(frame)).collect();
        let groups = 4usize;
        let ranges = super::group_frame_ranges(&refs, groups);
        let group_weight = |ranges: &[(usize, usize)]| -> Vec<u64> {
            ranges
                .iter()
                .map(|&(start, end)| weights[start..end].iter().map(|w| *w as u64).sum())
                .collect()
        };
        let weighted = group_weight(&ranges);
        let total: u64 = weighted.iter().sum();
        let mean = total as f64 / weighted.len() as f64;
        let max = *weighted.iter().max().unwrap() as f64;
        assert!(
            max <= mean * 1.10,
            "heaviest group {max} mean {mean} weights {weighted:?}"
        );
        let equal = group_weight(&super::equal_frame_ranges(frames.len(), groups));
        let equal_max = *equal.iter().max().unwrap() as f64;
        let equal_mean = total as f64 / equal.len() as f64;
        assert!(
            equal_max > equal_mean * 1.10,
            "equal frame counts should miss the 10% band: {equal:?}"
        );

        let mut serial = Vec::new();
        {
            let mut writer = super::ConFrameWriter::new(&mut serial);
            for frame in &frames {
                writer.write_frame_bound(frame).unwrap();
            }
            writer.flush().unwrap();
        }
        let path = _scratch
            .path()
            .join(format!("rc-mix-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&path, &refs, 4, None, false, true).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), serial);
        let _ = std::fs::remove_file(&path);
    }

    /// Unequal slices land at their prefix-sum offsets. A serial
    /// `write_all` in the wrong order, or a store that ignores an
    /// empty slice's offset, would not rebuild the concatenation.
    #[test]
    fn disjoint_parts_rebuild_the_concatenation() {
        let _scratch = tempfile::tempdir().unwrap();
        let path = _scratch
            .path()
            .join(format!("rc-parts-{}.con", std::process::id()));
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)
            .unwrap();
        let parts = vec![
            b"aa".to_vec(),
            b"bbb".to_vec(),
            Vec::new(),
            b"cdef".to_vec(),
        ];
        super::store_disjoint_parts(&file, &parts).unwrap();
        drop(file);
        assert_eq!(std::fs::read(&path).unwrap(), b"aabbbcdef");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn round_trip_width_matches_the_spelling() {
        let mut samples = vec![
            0.0,
            -0.0,
            1.0,
            -2.0,
            20.0,
            90.0,
            63.546,
            0.001,
            0.000001,
            1e-7,
            1e-20,
            1e22,
            -1.25,
            9.983,
            f64::MIN_POSITIVE,
            f64::MAX,
            f64::NAN,
            f64::INFINITY,
            f64::NEG_INFINITY,
        ];
        for i in 0..2000 {
            samples.push((i as f64) * 0.001);
            samples.push(-((i as f64) + 0.5) * 0.017);
        }
        let mut buf = Vec::new();
        let mut ryu = ryu::Buffer::new();
        for value in samples {
            buf.clear();
            super::push_round_trip(&mut buf, &mut ryu, None, value);
            assert_eq!(
                super::round_trip_width(value),
                buf.len(),
                "spelling {buf:?} of {value}"
            );
        }
    }

    /// Float-width lengths match a real format, and the group is written
    /// into that exact slice. A short guess would reallocate the slice.
    #[test]
    fn packed_lengths_match_formatted_frames() {
        let _scratch = tempfile::tempdir().unwrap();
        use crate::types::ConFrameBuilder;
        let frame = |shift: f64, weird: f64| {
            let mut builder = ConFrameBuilder::new([20.0, 20.0, 20.0], [90.0, 90.0, 90.0]);
            builder
                .set_units(serde_json::json!({
                    "length": "angstrom",
                    "energy": "eV",
                    "mass": "amu",
                    "time": crate::units::NATURAL_TIME_UNIT,
                }))
                .unwrap();
            builder
                .add_atom("Cu", shift, shift + 0.001, weird, [false; 3], 0, 63.546)
                .with_velocity([shift * 0.1, -0.25, 0.0]);
            builder
                .add_atom("Cu", 1.5, -2.0, 0.0, [false; 3], 1, 63.546)
                .with_velocity([0.0, 1e-20, -0.0]);
            builder.build().unwrap()
        };
        let frames: Vec<_> = (0..6)
            .map(|i| {
                frame(
                    i as f64 * 0.017,
                    if i == 3 { 1.0e22 } else { 0.125 + i as f64 },
                )
            })
            .collect();
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let lengths = super::packed_frame_lengths(&refs, 4, None, false, true)
            .expect("uniform frames have exact lengths");
        for (frame, len) in refs.iter().zip(&lengths) {
            let formatted =
                super::format_group_bytes(std::slice::from_ref(frame), 1, None, false, true)
                    .unwrap();
            assert_eq!(formatted.len(), *len);
        }
        let mut dest = vec![0u8; lengths.iter().sum()];
        let ptr = dest.as_mut_ptr();
        super::format_group_into(&refs, &mut dest, None, false, true).unwrap();
        assert_eq!(dest.as_ptr(), ptr);
        let mut serial = Vec::new();
        {
            let mut writer = super::ConFrameWriter::new(&mut serial);
            for frame in &frames {
                writer.write_frame_bound(frame).unwrap();
            }
            writer.flush().unwrap();
        }
        assert_eq!(dest, serial);
        let path = _scratch
            .path()
            .join(format!("rc-packed-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&path, &refs, 4, None, false, true).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), serial);
        let _ = std::fs::remove_file(&path);

        let mut other = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        other
            .set_units(serde_json::json!({
                "length": "angstrom",
                "energy": "eV",
                "mass": "amu",
                "time": crate::units::NATURAL_TIME_UNIT,
            }))
            .unwrap();
        other
            .add_atom("H", 0.0, 0.0, 0.0, [false; 3], 0, 1.0)
            .with_velocity([0.0, 0.0, 0.0]);
        let odd = other.build().unwrap();
        let mixed = [refs[0], &odd];
        assert!(super::packed_frame_lengths(&mixed, 2, None, false, true).is_none());
        super::write_frame_refs_to_path(&path, &mixed, 2, None, false, true).unwrap();
        let mut serial = Vec::new();
        {
            let mut writer = super::ConFrameWriter::new(&mut serial);
            writer.write_frame_bound(mixed[0]).unwrap();
            writer.write_frame_bound(mixed[1]).unwrap();
            writer.flush().unwrap();
        }
        assert_eq!(std::fs::read(&path).unwrap(), serial);
        let _ = std::fs::remove_file(&path);
    }

    /// Pricing is cached for a repeat write. Editing a coordinate, or
    /// dropping the frames, must not reuse that price.
    #[test]
    fn a_coordinate_edit_reprices_the_packed_lengths() {
        use crate::types::ConFrameBuilder;
        let mut frames = Vec::new();
        for i in 0..4 {
            let mut builder = ConFrameBuilder::new([20.0, 20.0, 20.0], [90.0, 90.0, 90.0]);
            builder
                .set_units(serde_json::json!({
                    "length": "angstrom",
                    "energy": "eV",
                    "mass": "amu",
                    "time": crate::units::NATURAL_TIME_UNIT,
                }))
                .unwrap();
            builder
                .add_atom("Cu", i as f64, 0.25, 0.5, [false; 3], 0, 63.546)
                .with_velocity([0.1, 0.0, 0.0]);
            builder
                .add_atom("Cu", 1.5, -2.0, 0.0, [false; 3], 1, 63.546)
                .with_velocity([0.0, 0.2, 0.0]);
            frames.push(builder.build().unwrap());
        }
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let before = super::cached_packed_lengths(&refs, 2, None, false, true).unwrap();
        let old = before[2];
        frames[2].atom_data[0].set_x(1.0e22);
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let after = super::cached_packed_lengths(&refs, 2, None, false, true).unwrap();
        let formatted =
            super::format_group_bytes(std::slice::from_ref(&refs[2]), 1, None, false, true)
                .unwrap();
        assert_ne!(old, formatted.len());
        assert_eq!(after[2], formatted.len());
    }
}

#[cfg(all(test, feature = "parallel"))]
mod parallel_write_bytes {
    use super::{write_frames_to_vec, write_frames_to_vec_with_threads};
    use crate::iterators::frames_from_text;

    fn wide_text(n: usize) -> String {
        let mut text = String::new();
        text.push_str(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!("{i}.125 0.25 0.5 0 {i}\n"));
        }
        text
    }

    #[test]
    fn parallel_bytes_match_the_serial_writer() {
        let wide = frames_from_text(&wide_text(5000), Some(1)).unwrap();
        let serial = write_frames_to_vec(&wide).unwrap();
        let parallel = write_frames_to_vec_with_threads(&wide, 4, None, false).unwrap();
        assert_eq!(parallel, serial);
        let mut with_vel = wide_text(5000);
        with_vel.push_str("\nCu\nVelocities of Component 1\n");
        for i in 0..5000 {
            with_vel.push_str(&format!("{}.0001 0.0002 -0.0001 0 {i}\n", i % 7));
        }
        let moving = frames_from_text(&with_vel, Some(1)).unwrap();
        let serial = write_frames_to_vec(&moving).unwrap();
        let parallel = write_frames_to_vec_with_threads(&moving, 4, None, false).unwrap();
        assert_eq!(parallel, serial);
        let one = frames_from_text(
            &std::fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/resources/test/cuh2.con"
            ))
            .unwrap()
            .repeat(8),
            Some(1),
        )
        .unwrap();
        let serial = write_frames_to_vec(&one).unwrap();
        let parallel = write_frames_to_vec_with_threads(&one, 4, None, false).unwrap();
        assert_eq!(parallel, serial);
    }

    #[test]
    fn pwrite_matches_the_concatenated_writer() {
        let _scratch = tempfile::tempdir().unwrap();
        let one = frames_from_text(
            &std::fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/resources/test/cuh2.con"
            ))
            .unwrap()
            .repeat(8),
            Some(1),
        )
        .unwrap();
        let serial = write_frames_to_vec(&one).unwrap();
        let refs: Vec<&crate::types::ConFrame> = one.iter().collect();
        let path = _scratch.path().join(format!(
            "readcon-pwrite-{}-{}.con",
            std::process::id(),
            one.len()
        ));
        super::write_frame_refs_to_path(&path, &refs, 4, None, false, false).unwrap();
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
    }

    #[test]
    fn stamped_pwrite_matches_the_binding_writer() {
        let _scratch = tempfile::tempdir().unwrap();
        let one = frames_from_text(
            &std::fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/resources/test/cuh2.con"
            ))
            .unwrap()
            .repeat(8),
            Some(1),
        )
        .unwrap();
        let mut serial = Vec::new();
        {
            let mut writer = super::ConFrameWriter::new(&mut serial);
            for frame in &one {
                let mut stamped = frame.clone();
                writer.write_frame_binding(&mut stamped).unwrap();
            }
        }
        let refs: Vec<&crate::types::ConFrame> = one.iter().collect();
        let path = _scratch.path().join(format!(
            "readcon-pwrite-bind-{}-{}.con",
            std::process::id(),
            one.len()
        ));
        super::write_frame_refs_to_path(&path, &refs, 4, None, false, true).unwrap();
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
    }

    /// A same-length rewrite matches a fresh write. The published path keeps
    /// the previous complete file until rename, and that inode becomes the
    /// spare the next rewrite fills.
    #[cfg(unix)]
    #[test]
    fn a_rewrite_matches_a_fresh_write_and_reuses_the_inode() {
        let _scratch = tempfile::tempdir().unwrap();
        use std::os::unix::fs::MetadataExt;
        let text = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/cuh2.con"
        ))
        .unwrap();
        let frames = frames_from_text(&text, Some(1)).unwrap();
        let refs: Vec<&crate::types::ConFrame> = vec![&frames[0]; 32];
        let path = _scratch
            .path()
            .join(format!("rc-rewrite-{}.con", std::process::id()));
        let fresh = _scratch
            .path()
            .join(format!("rc-rewrite-fresh-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&fresh, &refs, 8, None, false, true).unwrap();
        let expect = std::fs::read(&fresh).unwrap();
        super::write_frame_refs_to_path(&path, &refs, 1, None, false, true).unwrap();
        let first_ino = std::fs::metadata(&path).unwrap().ino();
        super::rewrite_frame_refs_to_path(&path, &refs, 8, None, false, true, true).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), expect);
        let spare = path.with_file_name(format!(
            "{}.rewrite",
            path.file_name().unwrap().to_string_lossy()
        ));
        assert_eq!(
            std::fs::metadata(&spare).unwrap().ino(),
            first_ino,
            "the previous inode is the spare"
        );
        super::rewrite_frame_refs_to_path(&path, &refs, 1, None, false, true, true).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), expect);
        assert_eq!(
            std::fs::metadata(&path).unwrap().ino(),
            first_ino,
            "the second rewrite publishes the spare inode"
        );
        // The published name is still the previous bytes if the spare write
        // is what failed. An empty directory component cannot be created.
        let blocked = _scratch
            .path()
            .join(format!("rc-rewrite-missing-{}/out.con", std::process::id()));
        std::fs::write(&path, &expect).unwrap();
        let before = std::fs::read(&path).unwrap();
        let err = super::rewrite_frame_refs_to_path(&blocked, &refs, 1, None, false, true, true);
        assert!(err.is_err());
        assert_eq!(std::fs::read(&path).unwrap(), before);
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(&spare);
        let _ = std::fs::remove_file(&fresh);
    }

    #[cfg(unix)]
    #[test]
    fn dropping_the_spare_leaves_one_file() {
        let _scratch = tempfile::tempdir().unwrap();
        let text = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/cuh2.con"
        ))
        .unwrap();
        let frames = frames_from_text(&text, Some(1)).unwrap();
        let refs: Vec<&crate::types::ConFrame> = vec![&frames[0]; 4];
        let path = _scratch
            .path()
            .join(format!("rc-rewrite-drop-{}.con", std::process::id()));
        let fresh = _scratch
            .path()
            .join(format!("rc-rewrite-drop-fresh-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&fresh, &refs, 1, None, false, true).unwrap();
        let expect = std::fs::read(&fresh).unwrap();
        super::write_frame_refs_to_path(&path, &refs, 1, None, false, true).unwrap();
        super::rewrite_frame_refs_to_path(&path, &refs, 1, None, false, true, false).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), expect);
        let spare = path.with_file_name(format!(
            "{}.rewrite",
            path.file_name().unwrap().to_string_lossy()
        ));
        assert!(!spare.exists(), "keep_spare false removes the second inode");
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(&fresh);
    }

    /// Kill the process while the spare is being written. The published
    /// path must still be the previous complete file, not a mix.
    #[cfg(unix)]
    #[test]
    fn a_killed_rewrite_leaves_the_published_file_whole() {
        let _scratch = tempfile::tempdir().unwrap();
        let text = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/resources/test/cuh2.con"
        ))
        .unwrap();
        let frames = frames_from_text(&text, Some(1)).unwrap();
        let n = 8_000usize;
        let refs: Vec<&crate::types::ConFrame> = vec![&frames[0]; n];
        let path = _scratch
            .path()
            .join(format!("rc-rewrite-kill-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&path, &refs, 1, None, false, true).unwrap();
        let original = std::fs::read(&path).unwrap();
        let mut changed = frames[0].clone();
        let x = changed.atom_data[0].x();
        changed.atom_data[0].set_x(x + 0.0001);
        let changed_refs: Vec<&crate::types::ConFrame> = vec![&changed; n];
        let spare = path.with_file_name(format!(
            "{}.rewrite",
            path.file_name().unwrap().to_string_lossy()
        ));
        let _ = std::fs::remove_file(&spare);
        let pid = unsafe { libc::fork() };
        assert!(pid >= 0, "fork");
        if pid == 0 {
            let _ =
                super::rewrite_frame_refs_to_path(&path, &changed_refs, 1, None, false, true, true);
            std::process::exit(0);
        }
        let started = std::time::Instant::now();
        while started.elapsed() < std::time::Duration::from_secs(30) {
            if spare.exists()
                && std::fs::metadata(&spare)
                    .map(|meta| meta.len() > 65_536)
                    .unwrap_or(false)
            {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        unsafe { libc::kill(pid, libc::SIGKILL) };
        let mut status = 0i32;
        unsafe { libc::waitpid(pid, &mut status, 0) };
        assert!(
            libc::WIFSIGNALED(status),
            "the rewrite finished before the kill; status {status}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), original);
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(&spare);
        let hold = path.with_file_name(format!(
            "{}.rewrite-hold",
            path.file_name().unwrap().to_string_lossy()
        ));
        let _ = std::fs::remove_file(&hold);
    }

    #[test]
    fn a_wide_file_write_matches_the_serial_bytes_when_ids_are_not_dense() {
        let _scratch = tempfile::tempdir().unwrap();
        let n = 4096usize;
        let mut text = String::from(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n1\n",
        );
        text.push_str(&format!("{n}\n63.546\nCu\nCoordinates of Component 1\n"));
        for i in 0..n {
            text.push_str(&format!("{i}.125 0.25 0.5 0 {}\n", i + 10));
        }
        text.push_str("\nCu\nVelocities of Component 1\n");
        for i in 0..n {
            text.push_str(&format!("{}.0001 0.0002 -0.0001 0 {}\n", i % 7, i + 10));
        }
        let frames = frames_from_text(&text, Some(1)).unwrap();
        let serial = write_frames_to_vec(&frames).unwrap();
        let parallel = write_frames_to_vec_with_threads(&frames, 8, None, false).unwrap();
        assert_eq!(parallel, serial);
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let path = _scratch.path().join(format!(
            "readcon-wide-stream-{}-{n}.con",
            std::process::id()
        ));
        super::write_frame_refs_to_path(&path, &refs, 8, None, false, false).unwrap();
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
    }

    #[test]
    fn a_mixed_wide_frame_matches_the_serial_parse() {
        let n = 7000usize;
        let mut text = String::from(
            "grid\n{\"con_spec_version\":2}\n10.0 10.0 10.0\n90.0 90.0 90.0\n0 0\n0 0\n2\n",
        );
        text.push_str(&format!("{n} {n}\n63.546 1.008\n"));
        text.push_str("Cu\nCoordinates of Component 1\n");
        for i in 0..n {
            text.push_str(&format!("{i}.125 0.25 0.5 0 {i}\n"));
        }
        text.push_str("H\nCoordinates of Component 2\n");
        for i in 0..n {
            let id = n + i;
            text.push_str(&format!("1.5 2.25 {i}.5 0 {id}\n"));
        }
        assert!(text.len() >= (256 << 10), "frame is {} bytes", text.len());
        let serial = frames_from_text(&text, Some(1)).unwrap();
        let parallel = frames_from_text(&text, Some(8)).unwrap();
        assert_eq!(parallel.len(), 1);
        assert_eq!(parallel[0].atom_data.len(), n * 2);
        assert_eq!(parallel[0].atom_data[0].symbol.as_ref(), "Cu");
        assert_eq!(parallel[0].atom_data[n].symbol.as_ref(), "H");
        assert_eq!(
            parallel[0].atom_data[n].atom_id,
            serial[0].atom_data[n].atom_id
        );
        assert_eq!(parallel, serial);
    }

    #[test]
    fn coordinate_lines_match_the_serial_frame_body() {
        let frames = frames_from_text(&wide_text(32), Some(1)).unwrap();
        let lines = super::format_coordinate_lines(&frames[0].atom_data).unwrap();
        let serial = write_frames_to_vec(&frames).unwrap();
        let text = std::str::from_utf8(&serial).unwrap();
        let marker = "Coordinates of Component 1\n";
        let start = text.find(marker).unwrap() + marker.len();
        assert_eq!(lines, text.as_bytes()[start..]);
    }

    #[test]
    fn pwrite_offsets_follow_an_exclusive_scan() {
        let _scratch = tempfile::tempdir().unwrap();
        let path = _scratch
            .path()
            .join(format!("readcon-pwrite-scan-{}.bin", std::process::id()));
        let parts: [&[u8]; 4] = [b"abc", b"", b"def\n", b"g"];
        super::publish_new(
            &path,
            |err| err,
            |file| super::pwrite_borrowed(file, &parts),
        )
        .unwrap();
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, b"abcdef\ng");
    }

    #[test]
    fn mapped_write_matches_the_serial_write() {
        let _scratch = tempfile::tempdir().unwrap();
        use crate::types::ConFrameBuilder;
        for n in [1usize, 3, 7, 4097, 8191] {
            let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
            for i in 0..n {
                let x = (i % 97) as f64 * 0.125;
                let y = (i % 13) as f64;
                let z = if i % 2 == 0 { i as f64 * 0.001 } else { -0.5 };
                builder.add_atom("Cu", x, y, z, [false, i % 5 == 0, false], i as u64, 63.546);
            }
            let frame = builder.build().expect("frame");
            let serial = super::write_frames_to_vec(std::slice::from_ref(&frame)).expect("serial");
            for workers in [1usize, 2, 3, 8] {
                let path = _scratch.path().join(format!(
                    "readcon-map-{n}-{workers}-{}.con",
                    std::process::id()
                ));
                let mut writer = super::ConFrameWriter::new(Vec::<u8>::new())
                    .parallel_atoms(workers)
                    .map_rows(true);
                writer.stream_file = Some(
                    std::fs::OpenOptions::new()
                        .read(true)
                        .write(true)
                        .create(true)
                        .truncate(true)
                        .open(&path)
                        .expect("create"),
                );
                writer.write_frame(&frame).expect("mapped");
                drop(writer);
                let got = std::fs::read(&path).expect("read");
                let _ = std::fs::remove_file(&path);
                assert_eq!(got, serial, "n={n} workers={workers}");
            }
        }
    }

    fn copper_frame(
        n: usize,
        symbol: &str,
        mass: f64,
        id_at: impl Fn(usize) -> u64,
    ) -> crate::types::ConFrame {
        use crate::types::ConFrameBuilder;
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        for i in 0..n {
            builder.add_atom(
                symbol,
                i as f64 * 0.125,
                0.25,
                0.5,
                [false, false, false],
                id_at(i),
                mass,
            );
        }
        builder.build().expect("frame")
    }

    #[test]
    fn two_wide_frames_on_two_threads_keep_up_with_one_frame() {
        let _scratch = tempfile::tempdir().unwrap();
        let n = 200_000usize;
        let one = copper_frame(n, "Cu", 63.546, |i| i as u64);
        let frames = [one.clone(), one.clone()];
        let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
        let serial = super::write_frames_to_vec(&frames).expect("serial");
        let path = _scratch
            .path()
            .join(format!("readcon-weak-write-{}.con", std::process::id()));
        super::write_frame_refs_to_path(&path, &refs, 2, None, false, false).expect("parallel");
        let got = std::fs::read(&path).expect("read");
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
        // llvm-cov instrumentation stretches the parallel write past this
        // ratio on a shared runner. The samples still run so those lines
        // stay in the coverage build. The byte comparison above still runs.
        let time = |frames: &[crate::types::ConFrame], workers: usize| {
            let refs: Vec<&crate::types::ConFrame> = frames.iter().collect();
            let path = _scratch.path().join(format!(
                "readcon-weak-time-{}-{workers}.con",
                std::process::id()
            ));
            let _ = super::write_frame_refs_to_path(&path, &refs, workers, None, false, false);
            let mut samples = Vec::with_capacity(5);
            for _ in 0..5 {
                let _ = std::fs::remove_file(&path);
                let started = std::time::Instant::now();
                super::write_frame_refs_to_path(&path, &refs, workers, None, false, false)
                    .expect("write");
                samples.push(started.elapsed().as_secs_f64());
            }
            let _ = std::fs::remove_file(&path);
            samples.sort_by(|left, right| left.partial_cmp(right).unwrap());
            samples[samples.len() / 2]
        };
        let one_s = time(std::slice::from_ref(&one), 1);
        let two_s = time(&frames, 2);
        #[cfg(not(coverage))]
        assert!(
            two_s < one_s * 1.7,
            "two frames on two threads took {two_s:.4}s against one frame {one_s:.4}s"
        );
        #[cfg(coverage)]
        let _ = (one_s, two_s);
    }

    #[test]
    fn parallel_write_rejects_an_id_repeated_in_another_type() {
        let _scratch = tempfile::tempdir().unwrap();
        use crate::types::ConFrameBuilder;
        let n = 4096usize;
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        for i in 0..n {
            builder.add_atom(
                "Cu",
                i as f64 * 0.125,
                0.25,
                0.5,
                [false, false, false],
                i as u64,
                63.546,
            );
        }
        for i in 0..n {
            builder.add_atom(
                "H",
                i as f64 * 0.125,
                1.5,
                0.5,
                [false, false, false],
                i as u64,
                1.008,
            );
        }
        let frame = builder.build().expect("frame");
        let serial = write_frames_to_vec(std::slice::from_ref(&frame));
        let parallel =
            write_frames_to_vec_with_threads(std::slice::from_ref(&frame), 4, None, false);
        assert!(serial.is_err(), "serial writer accepted a repeated id");
        assert!(parallel.is_err(), "parallel writer accepted a repeated id");
        let path = _scratch
            .path()
            .join(format!("readcon-repeat-id-{}.con", std::process::id()));
        std::fs::write(&path, b"keep").unwrap();
        let refs = [&frame];
        let err = super::write_frame_refs_to_path(&path, &refs, 4, None, false, false);
        assert!(err.is_err(), "path write accepted a repeated id");
        assert_eq!(std::fs::read(&path).unwrap(), b"keep");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_failed_later_group_leaves_the_previous_file() {
        let _scratch = tempfile::tempdir().unwrap();
        let good = copper_frame(2, "Cu", 63.546, |i| i as u64);
        let bad = copper_frame(2, "Cu", 63.546, |_| 0);
        let path = _scratch
            .path()
            .join(format!("readcon-group-fail-{}.con", std::process::id()));
        std::fs::write(&path, b"keep").unwrap();
        let refs = [&good, &bad];
        let err = super::write_frame_refs_to_path(&path, &refs, 4, None, false, false);
        assert!(err.is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"keep");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn mapped_decimal_lines_match_the_serial_writer() {
        let _scratch = tempfile::tempdir().unwrap();
        let frame = copper_frame(64, "Cu", 63.546, |i| i as u64);
        let frames = [frame];
        let serial = write_frames_to_vec_with_threads(&frames, 1, Some(40), false).unwrap();
        let path = _scratch
            .path()
            .join(format!("readcon-long-line-{}.con", std::process::id()));
        let mut writer = super::ConFrameWriter::with_precision(Vec::<u8>::new(), 40)
            .parallel_atoms(4)
            .map_rows(true);
        writer.stream_file = Some(
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(true)
                .open(&path)
                .unwrap(),
        );
        writer.write_frame(&frames[0]).unwrap();
        drop(writer);
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
    }

    #[test]
    fn a_rejected_spread_does_not_keep_the_reserved_file() {
        let _scratch = tempfile::tempdir().unwrap();
        use crate::types::ConFrameBuilder;
        let n = 4096usize;
        let mut builder = ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
        for i in 0..n {
            builder.add_atom(
                "Cu",
                i as f64 * 0.125,
                0.25,
                0.5,
                [false, false, false],
                i as u64,
                63.546,
            );
        }
        builder.with_spread([0.0, 0.0, 0.0]);
        let mut frame = builder.build().expect("frame");
        frame.atom_data[0].set_spread(Some([-1.0, 0.0, 0.0]));
        let path = _scratch
            .path()
            .join(format!("readcon-spread-fail-{}.con", std::process::id()));
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)
            .unwrap();
        let mut writer = super::ConFrameWriter::new(Vec::<u8>::new())
            .parallel_atoms(4)
            .map_rows(true)
            .mapped_file(file);
        let err = writer.write_frame(&frame);
        drop(writer);
        assert!(err.is_err());
        assert_eq!(std::fs::metadata(&path).unwrap().len(), 0);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn overlapped_pwrite_does_not_keep_bytes_past_the_frame() {
        use std::io::{Seek, Write};
        let frame = copper_frame(4096, "Cu", 63.546, |i| i as u64);
        let serial = write_frames_to_vec(std::slice::from_ref(&frame)).unwrap();
        let path = std::env::current_dir()
            .unwrap()
            .join(format!("readcon-pwrite-tail-{}.con", std::process::id()));
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(true)
            .open(&path)
            .unwrap();
        file.write_all(&vec![b'Z'; serial.len() + 64]).unwrap();
        file.seek(std::io::SeekFrom::Start(0)).unwrap();
        let workers = super::physical_cores().max(2);
        let mut writer = super::ConFrameWriter::new(Vec::<u8>::new())
            .parallel_atoms(workers)
            .mapped_file(file);
        writer.write_frame(&frame).unwrap();
        drop(writer);
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
    }
}

#[cfg(test)]
mod gzip_stream_memory {
    use super::ConFrameWriter;
    use crate::iterators::{frames_from_text, read_all_frames};

    fn parsed_frame() -> crate::types::ConFrame {
        let mut text = String::from(
            "grid\n{\"con_spec_version\":2,\"units\":{\"length\":\"angstrom\",\"energy\":\"eV\"}}\n20 20 20\n90 90 90\n0 0\n0 0\n1\n48\n63.546\nCu\nCoordinates of Component 1\n",
        );
        for i in 0..48 {
            text.push_str(&format!("0.{i} 1 2 0 {i}\n"));
        }
        frames_from_text(&text, Some(1)).unwrap().remove(0)
    }

    /// A streaming gzip rewrite must not pin a metadata map on every frame.
    ///
    /// The map is about a kilobyte and stays reachable on the frame. Four
    /// thousand frames keep several megabytes after the writer is gone, which
    /// is what pushed a 20k-frame rewrite past the 8 MiB high-water budget.
    /// Isolated measurements of that rewrite: 26 MiB high-water and 30 MB
    /// committed before, 4 MiB high-water and 5.5 MB committed after (the
    /// deflate arena, flat in the frame count).
    #[test]
    fn parsed_frames_gzip_write_drops_the_metadata_maps() {
        let _scratch = tempfile::tempdir().unwrap();
        let frames = vec![parsed_frame(); 4000];
        assert!(
            frames
                .iter()
                .all(|frame| !frame.header.metadata.has_cached_map())
        );
        let path = _scratch.path().join(format!(
            "readcon-gzip-peak-{}-{}.con.gz",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        {
            let mut writer = ConFrameWriter::from_path_gzip(&path).unwrap();
            for frame in &frames {
                writer.write_frame(frame).unwrap();
            }
            writer.flush().unwrap();
        }
        let cached = frames
            .iter()
            .filter(|frame| frame.header.metadata.has_cached_map())
            .count();
        assert_eq!(
            cached, 0,
            "the write retained {cached} metadata maps; each is about a kilobyte"
        );
        let back = read_all_frames(&path).unwrap();
        assert_eq!(back.len(), frames.len());
        assert_eq!(back[0].atom_data.len(), 48);
        assert_eq!(back[0].atom_data[3].atom_id, 3);
        assert_eq!(back[17].atom_data[0].symbol.as_ref(), "Cu");
        let _ = std::fs::remove_file(&path);
    }

    /// Lattice vectors live on the metadata line. Reading them must not pin
    /// the parsed map, and a later keyed lookup still sees the same matrix.
    #[test]
    fn lattice_line_overrides_box_lengths_and_can_be_reread_from_the_cache() {
        let _scratch = tempfile::tempdir().unwrap();
        let text = "\
grid
{\"con_spec_version\":2,\"lattice_vectors\":[[10,0,0],[0,20,0],[0,0,30]]}
5 5 5
90 90 90
0 0
0 0
1
1
1.0
Cu
Coordinates of Component 1
0 0 0 0 1
";
        let frame = frames_from_text(text, Some(1)).unwrap().remove(0);
        assert!(!frame.header.metadata.has_cached_map());
        let vecs = frame.header.lattice_vectors().unwrap();
        assert_eq!(vecs, [[10.0, 0.0, 0.0], [0.0, 20.0, 0.0], [0.0, 0.0, 30.0]]);
        assert!(
            !frame.header.metadata.has_cached_map(),
            "reading lattice vectors cached the whole metadata map"
        );
        let path = _scratch
            .path()
            .join(format!("readcon-lattice-line-{}.con", std::process::id()));
        {
            let mut writer = ConFrameWriter::from_path(&path).unwrap();
            writer.write_frame(&frame).unwrap();
            writer.flush().unwrap();
        }
        let back = read_all_frames(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(back[0].header.boxl, [10.0, 20.0, 30.0]);
        assert!(frame.header.metadata.get("lattice_vectors").is_some());
        assert!(frame.header.metadata.has_cached_map());
        assert_eq!(frame.header.lattice_vectors().unwrap()[1][1], 20.0);
    }

    /// Five different lines share one small cache. Each lookup still answers
    /// that line, and none of the frames grows its own map.
    #[test]
    fn repeated_lattice_lookups_share_a_bounded_cache() {
        let mut frames = Vec::new();
        for side in [10.0, 11.0, 12.0, 13.0, 14.0] {
            let text = format!(
                "grid\n{{\"con_spec_version\":2,\"lattice_vectors\":[[{side},0,0],[0,{side},0],[0,0,{side}]]}}\n5 5 5\n90 90 90\n0 0\n0 0\n1\n1\n1.0\nCu\nCoordinates of Component 1\n0 0 0 0 1\n"
            );
            frames.push(frames_from_text(&text, Some(1)).unwrap().remove(0));
        }
        for _ in 0..2 {
            for (index, frame) in frames.iter().enumerate() {
                let side = 10.0 + index as f64;
                let vecs = frame.header.lattice_vectors().unwrap();
                assert_eq!(vecs[0][0], side);
                assert_eq!(vecs[2][2], side);
                assert!(!frame.header.metadata.has_cached_map());
            }
        }
        // The last line is at the front. An older line is still cached
        // behind it, and a freshly parsed copy of the front line is a
        // content hit rather than a shared allocation.
        let older = frames[1].header.lattice_vectors().unwrap();
        assert_eq!(older[0][0], 11.0);
        let text = "\
grid
{\"con_spec_version\":2,\"lattice_vectors\":[[14,0,0],[0,14,0],[0,0,14]]}
5 5 5
90 90 90
0 0
0 0
1
1
1.0
Cu
Coordinates of Component 1
0 0 0 0 1
";
        let twin = frames_from_text(text, Some(1)).unwrap().remove(0);
        assert_eq!(twin.header.lattice_vectors().unwrap()[0][0], 14.0);
        assert!(!twin.header.metadata.has_cached_map());
    }

    /// Each thread keeps its own metadata-line cache. Concurrent lookups of
    /// different lines must not observe another thread's lattice.
    #[test]
    fn lattice_lookups_from_several_threads_keep_their_own_lines() {
        let frames: Vec<_> = (1..17)
            .map(|side| {
                let text = format!(
                    "grid\n{{\"con_spec_version\":2,\"lattice_vectors\":[[{side},0,0],[0,{side},0],[0,0,{side}]]}}\n5 5 5\n90 90 90\n0 0\n0 0\n1\n1\n1.0\nCu\nCoordinates of Component 1\n0 0 0 0 1\n"
                );
                frames_from_text(&text, Some(1)).unwrap().remove(0)
            })
            .collect();
        std::thread::scope(|scope| {
            for _ in 0..4 {
                scope.spawn(|| {
                    for _ in 0..8 {
                        for (index, frame) in frames.iter().enumerate() {
                            let side = 1.0 + index as f64;
                            let vecs = frame.header.lattice_vectors().unwrap();
                            assert_eq!(vecs[0][0], side);
                            assert_eq!(vecs[1][1], side);
                            assert_eq!(vecs[2][2], side);
                        }
                    }
                });
            }
        });
    }
}
