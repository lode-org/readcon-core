use crate::types::{
    ConFrame, SECTION_CHARGES, SECTION_DISPLACEMENTS, SECTION_ENERGIES, SECTION_FORCES,
    SECTION_MAGMOMS, SECTION_SPINS, SECTION_SPREADS, SECTION_VELOCITIES, encode_fixed_bitmask,
    meta,
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
    /// Wide-frame rows are formatted on several threads and written to this
    /// file as each chunk finishes, so the disk write overlaps the format.
    stream_file: Option<File>,
    /// Leave the frame text in `scratch` instead of copying it into `writer`.
    /// The format-only path reads `scratch` back, so the copy was a second
    /// pass over the same bytes.
    keep_scratch: bool,
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
            keep_scratch: false,
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
        has_vel: bool,
        has_frc: bool,
        has_eng: bool,
        has_chg: bool,
        has_spn: bool,
        has_mm: bool,
        has_dsp: bool,
        has_spr: bool,
    ) -> Result<(), WriteError> {
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
        self.bound = Some(BoundHeader {
            meta: binding_metadata(frame),
            spec,
        });
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
        if parallel_rows && self.stream_file.is_some() {
            // The coordinate formatter reads every atom. The id compare
            // rides that pass; a separate scan walked the whole frame first.
        } else if parallel_rows {
            if !ids_are_dense(&frame.atom_data, self.atom_workers) {
                ensure_unique_ids(&frame.atom_data, self.atom_workers)?;
            }
        } else {
            ensure_unique_ids(&frame.atom_data, 1)?;
        }
        let prec = self.float_format;
        let mut stream_file = self.stream_file.take();
        let bound = self.bound.take();
        let spec_version = bound
            .as_ref()
            .map(|item| item.spec)
            .unwrap_or(frame.header.spec_version);
        let metadata = bound
            .as_ref()
            .map(|item| &item.meta)
            .unwrap_or(&frame.header.metadata);
        if spec_version >= 2 {
            self.refresh_metadata_cache(
                spec_version,
                metadata,
                frame.has_velocities(),
                frame.has_forces(),
                frame.has_energies(),
                frame.has_charges(),
                frame.has_spins(),
                frame.has_magmoms(),
                frame.has_displacements(),
                frame.has_spreads(),
            )?;
        }
        let (boxl, angles) = match frame.header.lattice_vectors() {
            Some(vecs) => crate::types::lengths_and_angles(vecs),
            None => (frame.header.boxl, frame.header.angles),
        };
        let atoms = frame.atom_data.len();
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
        self.scratch
            .reserve(256 + atoms.saturating_mul(64).saturating_mul(blocks));
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
            let save_velocity = frame.has_velocities();
            let mut velocity_rows = Vec::new();
            let mut atom_idx_offset = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[atom_idx_offset].symbol;
                push_str_line(buf, symbol);
                push_component_line(buf, "Coordinates of Component", type_idx);

                let mut vel_buf = Vec::new();
                append_coord_rows(
                    buf,
                    ryu,
                    slots,
                    &frame.atom_data[atom_idx_offset..atom_idx_offset + num_atoms_in_type],
                    prec,
                    spec_version,
                    self.atom_workers,
                    stream_file.as_mut(),
                    if save_velocity {
                        Some(&mut vel_buf)
                    } else {
                        None
                    },
                )?;
                if save_velocity {
                    velocity_rows.push(vel_buf);
                }
                atom_idx_offset += num_atoms_in_type;
            }

            // --- Write optional velocity section ---
            if frame.has_velocities() {
                buf.push(b'\n');

                let mut vel_idx_offset = 0;
                for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate()
                {
                    let symbol = &frame.atom_data[vel_idx_offset].symbol;
                    push_str_line(buf, symbol);
                    push_component_line(buf, "Velocities of Component", type_idx);
                    buf.extend_from_slice(&velocity_rows[type_idx]);
                    vel_idx_offset += num_atoms_in_type;
                }
            }

            // --- Write optional force section ---
            if frame.has_forces() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    force_idx_offset += num_atoms_in_type;
                }
            }

            // --- Write optional energies section ---
            if frame.has_energies() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    energy_idx_offset += num_atoms_in_type;
                }
            }

            if frame.has_charges() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if frame.has_spins() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if frame.has_magmoms() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if frame.has_displacements() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }

            if frame.has_spreads() {
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
                            written_fixed_flag(atom.fixed, spec_version),
                            atom.atom_id,
                        );
                    }
                    off += num_atoms_in_type;
                }
            }
        }

        if self.keep_scratch {
            return Ok(());
        }
        if let Some(mut file) = stream_file {
            if !self.scratch.is_empty() {
                file.write_all(&self.scratch)?;
                self.scratch.clear();
            }
            file.flush()?;
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
        return crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            atoms.par_chunks(chunk).enumerate().all(|(index, group)| {
                let base = index * chunk;
                group
                    .iter()
                    .enumerate()
                    .all(|(offset, atom)| atom.atom_id == (base + offset) as u64)
            })
        });
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

fn push_u64(buf: &mut Vec<u8>, n: u64) {
    // Two digits per division. u64 stays in a hardware remainder; the old
    // path widened every atom id to u128 and called the software divider.
    const DIGITS: &[u8; 200] = b"00010203040506070809101112131415161718192021222324252627282930313233343536373839404142434445464748495051525354555657585960616263646566676869707172737475767778798081828384858687888990919293949596979899";
    let mut tmp = [0u8; 20];
    let mut i = 20;
    let mut n = n;
    while n >= 100 {
        let q = n / 100;
        let r = (n % 100) as usize;
        i -= 2;
        tmp[i] = DIGITS[r * 2];
        tmp[i + 1] = DIGITS[r * 2 + 1];
        n = q;
    }
    if n < 10 {
        i -= 1;
        tmp[i] = b'0' + n as u8;
    } else {
        let r = n as usize;
        i -= 2;
        tmp[i] = DIGITS[r * 2];
        tmp[i + 1] = DIGITS[r * 2 + 1];
    }
    buf.extend_from_slice(&tmp[i..]);
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
    if let Some((bytes, n)) = encode_fixed_decimal_into(value) {
        buf.extend_from_slice(&bytes[..n]);
        return;
    }
    buf.reserve(24);
    // `format64` writes at most 24 bytes and does not handle non-finite values.
    let n = unsafe { ryu::raw::format64(value, buf.as_mut_ptr().add(buf.len())) };
    debug_assert!(n <= 24);
    unsafe { buf.set_len(buf.len() + n) };
}

/// Shortest fixed decimal that matches `ryu`, when the value is an exact
/// integer or an exact fraction of at most six digits and ryu would not
/// switch to scientific form. `None` leaves the general formatter to run.
fn encode_fixed_decimal_into(value: f64) -> Option<([u8; 32], usize)> {
    let mut out = [0u8; 32];
    let n = encode_fixed_decimal(value, &mut out)?;
    Some((out, n))
}

fn encode_fixed_decimal(value: f64, out: &mut [u8; 32]) -> Option<usize> {
    let bits = value.to_bits();
    let sign = bits >> 63 != 0;
    let mag = f64::from_bits(bits & !(1u64 << 63));
    if mag == 0.0 {
        let text: &[u8] = if sign { b"-0.0" } else { b"0.0" };
        out[..text.len()].copy_from_slice(text);
        return Some(text.len());
    }
    if mag <= 1e16 && mag.fract() == 0.0 {
        let n = mag as u64;
        if n < 10u64.pow(16) && n as f64 == mag {
            return Some(write_fixed_digits(out, sign, n, 0));
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
                return Some(write_fixed_digits(out, sign, n, 0));
            }
            let digits = count_digits(n);
            let kk = digits as i32 - places as i32;
            if !(kk > -5 && kk <= 16) {
                return None;
            }
            return Some(write_fixed_digits(out, sign, n, places));
        }
        scale *= 10.0;
    }
    None
}

fn count_digits(mut n: u64) -> u32 {
    let mut digits = 1u32;
    while n >= 10 {
        n /= 10;
        digits += 1;
    }
    digits
}

fn write_fixed_digits(out: &mut [u8; 32], sign: bool, mut n: u64, places: u32) -> usize {
    let mut tmp = [0u8; 20];
    let mut i = tmp.len();
    if n == 0 {
        tmp[i - 1] = b'0';
        i -= 1;
    } else {
        while n > 0 {
            i -= 1;
            tmp[i] = b'0' + (n % 10) as u8;
            n /= 10;
        }
    }
    let digs = &tmp[i..];
    let mut at = 0usize;
    if sign {
        out[at] = b'-';
        at += 1;
    }
    if places == 0 {
        out[at..at + digs.len()].copy_from_slice(digs);
        at += digs.len();
        out[at] = b'.';
        out[at + 1] = b'0';
        return at + 2;
    }
    let kk = digs.len() as i32 - places as i32;
    if kk > 0 {
        let cut = kk as usize;
        out[at..at + cut].copy_from_slice(&digs[..cut]);
        at += cut;
        out[at] = b'.';
        at += 1;
        out[at..at + digs.len() - cut].copy_from_slice(&digs[cut..]);
        at += digs.len() - cut;
        return at;
    }
    out[at] = b'0';
    out[at + 1] = b'.';
    at += 2;
    for _ in 0..(-kk) {
        out[at] = b'0';
        at += 1;
    }
    out[at..at + digs.len()].copy_from_slice(digs);
    at + digs.len()
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

fn push_atom_motion(
    coord: &mut Vec<u8>,
    vel: Option<&mut Vec<u8>>,
    ryu: &mut ryu::Buffer,
    slots: &mut [FmtSlot; 3],
    vel_slots: &mut [FmtSlot; 3],
    atom: &crate::types::AtomDatum,
    prec: FloatFormat,
    spec_version: u32,
) {
    let fixed = written_fixed_flag(atom.fixed, spec_version);
    push_xyz_line(
        coord,
        ryu,
        slots,
        [atom.x, atom.y, atom.z],
        prec,
        fixed,
        atom.atom_id,
    );
    if let Some(vel) = vel {
        let [vx, vy, vz] = atom.velocity().unwrap_or([0.0; 3]);
        // A separate column cache. Sharing the coordinate slots made every
        // velocity miss and then evict the coordinate spelling.
        push_xyz_line(vel, ryu, vel_slots, [vx, vy, vz], prec, fixed, atom.atom_id);
    }
}

/// Coordinate lines for `atoms`, using the same formatter as a frame write.
///
/// One pass, private buffer. Callers that split a frame across ranks write
/// these bytes at the offset from an exclusive scan of the lengths.
pub fn format_coordinate_lines(atoms: &[crate::types::AtomDatum]) -> Result<Vec<u8>, WriteError> {
    let mut buf = Vec::with_capacity(atoms.len().saturating_mul(48));
    let mut ryu = ryu::Buffer::new();
    let mut slots = [FmtSlot::new(); 3];
    append_coord_rows(
        &mut buf,
        &mut ryu,
        &mut slots,
        atoms,
        FloatFormat::RoundTrip,
        2,
        1,
        None,
        None,
    )?;
    Ok(buf)
}

fn append_coord_rows(
    buf: &mut Vec<u8>,
    ryu: &mut ryu::Buffer,
    slots: &mut [FmtSlot; 3],
    atoms: &[crate::types::AtomDatum],
    prec: FloatFormat,
    spec_version: u32,
    workers: usize,
    stream: Option<&mut File>,
    mut vel: Option<&mut Vec<u8>>,
) -> Result<(), WriteError> {
    let want_vel = vel.is_some();
    if let Some(file) = stream {
        if workers >= 2 && atoms.len() >= WIDE_ATOM_GRAIN {
            file.write_all(buf).map_err(WriteError::Io)?;
            buf.clear();
            let vel_bytes = stream_coord_rows(file, atoms, workers, prec, spec_version, want_vel)?;
            if let Some(dest) = vel.as_mut() {
                dest.extend_from_slice(&vel_bytes);
            }
            return Ok(());
        }
    }
    if workers < 2 || atoms.len() < WIDE_ATOM_GRAIN {
        let mut vel_slots = [FmtSlot::new(); 3];
        for atom in atoms {
            push_atom_motion(
                buf,
                vel.as_deref_mut(),
                ryu,
                slots,
                &mut vel_slots,
                atom,
                prec,
                spec_version,
            );
        }
        return Ok(());
    }
    #[cfg(feature = "parallel")]
    {
        let chunk = atoms.len().div_ceil(workers).max(1);
        let pieces: Vec<&[crate::types::AtomDatum]> = atoms.chunks(chunk).collect();
        let bad_ids = std::sync::atomic::AtomicBool::new(false);
        let parts: Vec<(Vec<u8>, Vec<u8>)> = crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            pieces
                .par_iter()
                .enumerate()
                .map(|(piece, group)| {
                    let mut local = Vec::with_capacity(group.len().saturating_mul(48));
                    let mut local_vel = if want_vel {
                        Vec::with_capacity(group.len().saturating_mul(48))
                    } else {
                        Vec::new()
                    };
                    let mut ryu = ryu::Buffer::new();
                    let mut slots = [FmtSlot::new(); 3];
                    let mut vel_slots = [FmtSlot::new(); 3];
                    let base = piece * chunk;
                    for (offset, atom) in group.iter().enumerate() {
                        if atom.atom_id != (base + offset) as u64 {
                            bad_ids.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                        push_atom_motion(
                            &mut local,
                            if want_vel { Some(&mut local_vel) } else { None },
                            &mut ryu,
                            &mut slots,
                            &mut vel_slots,
                            atom,
                            prec,
                            spec_version,
                        );
                    }
                    (local, local_vel)
                })
                .collect()
        });
        if bad_ids.load(std::sync::atomic::Ordering::Relaxed) {
            ensure_unique_ids(atoms, 1)?;
        }
        let coord_len: usize = parts.iter().map(|(coord, _)| coord.len()).sum();
        let vel_len: usize = parts.iter().map(|(_, rows)| rows.len()).sum();
        let coord_at = buf.len();
        buf.reserve(coord_len);
        // Every byte is overwritten by the copies below. Zeroing it first
        // was a serial pass over the whole block.
        unsafe { buf.set_len(coord_at + coord_len) };
        if let Some(dest) = vel.as_deref_mut() {
            dest.reserve(vel_len);
        }
        let coord_ptr = buf.as_mut_ptr() as usize;
        std::thread::scope(|scope| {
            let mut at = coord_at;
            for (coord, _) in &parts {
                let dest = coord_ptr + at;
                let src = coord.as_ptr() as usize;
                let n = coord.len();
                scope.spawn(move || unsafe {
                    std::ptr::copy_nonoverlapping(src as *const u8, dest as *mut u8, n);
                });
                at += n;
            }
        });
        if let Some(dest) = vel.as_deref_mut() {
            for (_, rows) in &parts {
                dest.extend_from_slice(rows);
            }
        }
        return Ok(());
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = workers;
        let mut vel_slots = [FmtSlot::new(); 3];
        for atom in atoms {
            push_atom_motion(
                buf,
                vel.as_deref_mut(),
                ryu,
                slots,
                &mut vel_slots,
                atom,
                prec,
                spec_version,
            );
        }
        return Ok(());
    }
}

fn stream_coord_rows(
    file: &mut File,
    atoms: &[crate::types::AtomDatum],
    workers: usize,
    prec: FloatFormat,
    spec_version: u32,
    want_vel: bool,
) -> Result<Vec<u8>, WriteError> {
    let groups = workers.saturating_mul(4).max(workers);
    let chunk = atoms.len().div_ceil(groups).max(1);
    let nparts = atoms.len().div_ceil(chunk);
    let (tx, rx) = std::sync::mpsc::sync_channel::<(usize, Vec<u8>, Vec<u8>)>(2);
    // One core writes. The rest format, so the copy stays under the format.
    let format_threads = workers.saturating_sub(1).max(1);
    let next_job = std::sync::atomic::AtomicUsize::new(0);
    let pieces: Vec<&[crate::types::AtomDatum]> = atoms.chunks(chunk).collect();
    let bad_ids = std::sync::atomic::AtomicBool::new(false);
    let flag = &bad_ids;
    let vel = std::thread::scope(|scope| {
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
                    let group = pieces[index];
                    let mut local = Vec::with_capacity(group.len().saturating_mul(48));
                    let mut local_vel = if want_vel {
                        Vec::with_capacity(group.len().saturating_mul(48))
                    } else {
                        Vec::new()
                    };
                    let mut ryu = ryu::Buffer::new();
                    let mut slots = [FmtSlot::new(); 3];
                    let mut vel_slots = [FmtSlot::new(); 3];
                    let base = index * chunk;
                    for (offset, atom) in group.iter().enumerate() {
                        if atom.atom_id != (base + offset) as u64 {
                            flag.store(true, std::sync::atomic::Ordering::Relaxed);
                        }
                        push_atom_motion(
                            &mut local,
                            if want_vel { Some(&mut local_vel) } else { None },
                            &mut ryu,
                            &mut slots,
                            &mut vel_slots,
                            atom,
                            prec,
                            spec_version,
                        );
                    }
                    tx.send((index, local, local_vel)).ok();
                }
            });
        }
        drop(tx);
        let mut next = 0usize;
        let mut pending = BTreeMap::<usize, (Vec<u8>, Vec<u8>)>::new();
        let mut vel_parts = vec![Vec::new(); nparts];
        while next < nparts {
            let (index, part, vel) = rx
                .recv()
                .map_err(|err| WriteError::Io(io::Error::other(err.to_string())))?;
            pending.insert(index, (part, vel));
            while let Some((part, vel)) = pending.remove(&next) {
                file.write_all(&part).map_err(WriteError::Io)?;
                vel_parts[next] = vel;
                next += 1;
            }
        }
        let mut vel_bytes = Vec::new();
        for part in vel_parts {
            vel_bytes.extend_from_slice(&part);
        }
        Ok::<Vec<u8>, WriteError>(vel_bytes)
    })?;
    if bad_ids.load(std::sync::atomic::Ordering::Relaxed) {
        ensure_unique_ids(atoms, 1)?;
    }
    Ok(vel)
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
    let mut meta = frame.header.metadata.clone();
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
    out.header.metadata = binding_metadata(frame);
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
    /// let path = std::env::temp_dir().join(format!(
    ///     "readcon-append-doc-{}",
    ///     std::process::id()
    /// ));
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
pub fn write_frame_refs_to_path(
    path: &std::path::Path,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
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
        writer.stream_file = Some(File::create(path).map_err(WriteError::Io)?);
        return if bind {
            writer.write_frame_bound(frames[0])
        } else {
            writer.write_frame(frames[0])
        };
    }
    let parts = formatted_parts(frames, workers, precision, canonical, bind)?;
    if parts.len() == 1 {
        // One wide frame is already formatted in parallel row runs and
        // joined. A single write matches the disk; slicing it into pwrite
        // calls spent the gain on a second pass over the file.
        std::fs::write(path, &parts[0]).map_err(WriteError::Io)
    } else {
        pwrite_parts(path, &parts).map_err(WriteError::Io)
    }
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
    let parts = formatted_parts(frames, workers, precision, canonical, false)?;
    let mut out = Vec::new();
    for part in parts {
        out.extend_from_slice(&part);
    }
    Ok(out)
}

/// Format frame groups on `workers - 1` threads and write each group as
/// it finishes, in file order. Formatting the next group overlaps the
/// disk write of the one before it.
fn pipeline_frame_groups(
    path: &std::path::Path,
    frames: &[&ConFrame],
    workers: usize,
    precision: Option<usize>,
    canonical: bool,
    bind: bool,
) -> Result<(), WriteError> {
    let groups = workers.saturating_mul(4).max(workers);
    let chunk = frames.len().div_ceil(groups).max(1);
    let pieces: Vec<&[&ConFrame]> = frames.chunks(chunk).collect();
    let (tx, rx) = std::sync::mpsc::sync_channel::<(usize, Result<Vec<u8>, WriteError>)>(2);
    let format_threads = workers.saturating_sub(1).max(1);
    let next_job = std::sync::atomic::AtomicUsize::new(0);
    std::thread::scope(|scope| {
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
        let mut file = File::create(path).map_err(WriteError::Io)?;
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
    })
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
        return crate::parser::on_pool(workers, || {
            use rayon::prelude::*;
            frames
                .par_chunks(chunk)
                .map(|group| format_group_bytes(group, 1, precision, canonical, bind))
                .collect()
        });
    }
    #[cfg(not(feature = "parallel"))]
    {
        let _ = workers;
        Ok(vec![format_group_bytes(
            frames, 1, precision, canonical, bind,
        )?])
    }
}

fn pwrite_parts(path: &std::path::Path, parts: &[Vec<u8>]) -> io::Result<()> {
    let slices: Vec<&[u8]> = parts.iter().map(|part| part.as_slice()).collect();
    pwrite_borrowed(path, &slices)
}

fn pwrite_borrowed(path: &std::path::Path, parts: &[&[u8]]) -> io::Result<()> {
    let mut offset = 0u64;
    let mut offsets = Vec::with_capacity(parts.len());
    for part in parts {
        offsets.push(offset);
        offset += part.len() as u64;
    }
    let file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)?;
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
            values.extend([atom.x, atom.y, atom.z]);
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

#[cfg(all(test, feature = "parallel"))]
mod parallel_write_tests {
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
        let path = std::env::temp_dir().join(format!(
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
        let path = std::env::temp_dir().join(format!(
            "readcon-pwrite-bind-{}-{}.con",
            std::process::id(),
            one.len()
        ));
        super::write_frame_refs_to_path(&path, &refs, 4, None, false, true).unwrap();
        let got = std::fs::read(&path).unwrap();
        let _ = std::fs::remove_file(&path);
        assert_eq!(got, serial);
    }
}
