use crate::types::{
    ConFrame, SECTION_CHARGES, SECTION_ENERGIES, SECTION_FORCES, SECTION_MAGMOMS, SECTION_SPINS,
    SECTION_VELOCITIES, encode_fixed_bitmask, meta,
};
use serde_json::json;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

/// Default floating-point precision used for writing coordinates, cell dimensions, and masses.
const DEFAULT_FLOAT_PRECISION: usize = 6;

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
    precision: usize,
    /// When true: sort metadata keys in JSON, emit sections in canonical
    /// order (velocities, forces, energies), fixed precision suitable for
    /// content-stable corpus writes / semantic-ish dedup. Opt-in so default
    /// writes keep historical float formatting.
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
    metadata: std::collections::BTreeMap<String, serde_json::Value>,
    /// Cached serialised metadata line (without trailing newline).
    serialized: String,
}

impl MetadataCacheEntry {
    fn matches(
        &self,
        spec_version: u32,
        has_velocities: bool,
        has_forces: bool,
        has_energies: bool,
        has_charges: bool,
        has_spins: bool,
        has_magmoms: bool,
        metadata: &std::collections::BTreeMap<String, serde_json::Value>,
    ) -> bool {
        self.spec_version == spec_version
            && self.has_velocities == has_velocities
            && self.has_forces == has_forces
            && self.has_energies == has_energies
            && self.has_charges == has_charges
            && self.has_spins == has_spins
            && self.has_magmoms == has_magmoms
            && &self.metadata == metadata
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
        Self {
            writer: BufWriter::new(writer),
            precision: DEFAULT_FLOAT_PRECISION,
            canonical: false,
            metadata_cache: None,
            scratch: Vec::with_capacity(16 * 1024),
        }
    }

    /// Creates a new `ConFrameWriter` with a custom floating-point precision.
    ///
    /// # Arguments
    ///
    /// * `writer` - Any type that implements `std::io::Write`.
    /// * `precision` - Number of decimal places for floating-point output.
    pub fn with_precision(writer: W, precision: usize) -> Self {
        Self {
            writer: BufWriter::new(writer),
            precision,
            canonical: false,
            metadata_cache: None,
            scratch: Vec::with_capacity(16 * 1024),
        }
    }

    /// Opt-in **canonical** serialization: BTree-ordered metadata keys in JSON,
    /// fixed section order, stable float precision (default 6). Use for corpus
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

    fn refresh_metadata_cache(&mut self, frame: &ConFrame) {
        let spec_version = frame.header.spec_version;
        let has_vel = frame.has_velocities();
        let has_frc = frame.has_forces();
        let has_eng = frame.has_energies();
        let has_chg = frame.has_charges();
        let has_spn = frame.has_spins();
        let has_mm = frame.has_magmoms();

        let cache_hit = !self.canonical
            && self.metadata_cache.as_ref().is_some_and(|c| {
                c.matches(
                    spec_version,
                    has_vel,
                    has_frc,
                    has_eng,
                    has_chg,
                    has_spn,
                    has_mm,
                    &frame.header.metadata,
                )
            });
        if cache_hit {
            return;
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
        let validate = frame
            .header
            .metadata
            .get(meta::VALIDATE)
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        if !sections.is_empty() || validate {
            meta_obj.insert(meta::SECTIONS.into(), json!(sections));
        }
        for (k, v) in &frame.header.metadata {
            if k == meta::CON_SPEC_VERSION || k == meta::SECTIONS {
                continue;
            }
            meta_obj.insert(k.clone(), v.clone());
        }
        if let Some(u) = meta_obj.get(meta::UNITS).cloned() {
            if let Ok(c) = crate::units::canonicalize_units_object(&u) {
                meta_obj.insert(meta::UNITS.into(), c);
            }
        }
        if spec_version >= 3 {
            let need_default = match meta_obj.get(meta::UNITS) {
                None => true,
                Some(u) => crate::units::validate_v3_units_metadata(u).is_err(),
            };
            if need_default {
                meta_obj.insert(meta::UNITS.into(), crate::units::default_v3_units_json());
            }
        }
        let serialized = serde_json::Value::Object(meta_obj).to_string();
        self.metadata_cache = Some(MetadataCacheEntry {
            spec_version,
            has_velocities: has_vel,
            has_forces: has_frc,
            has_energies: has_eng,
            has_charges: has_chg,
            has_spins: has_spn,
            has_magmoms: has_mm,
            metadata: frame.header.metadata.clone(),
            serialized,
        });
    }

    /// Writes a single `ConFrame` to the output stream.
    pub fn write_frame(&mut self, frame: &ConFrame) -> io::Result<()> {
        let prec = self.precision;
        self.refresh_metadata_cache(frame);
        let meta_line = self
            .metadata_cache
            .as_ref()
            .expect("metadata_cache populated above")
            .serialized
            .clone();
        self.scratch.clear();
        {
        let buf = &mut self.scratch;

        // --- Write the 9-line Header ---
        let _ = writeln!(buf, "{}", frame.header.prebox_header.user);
        let _ = writeln!(buf, "{meta_line}");
        push_f64_prec(buf, frame.header.boxl[0], prec);
        buf.push(b' ');
        push_f64_prec(buf, frame.header.boxl[1], prec);
        buf.push(b' ');
        push_f64_prec(buf, frame.header.boxl[2], prec);
        buf.push(b'\n');
        push_f64_prec(buf, frame.header.angles[0], prec);
        buf.push(b' ');
        push_f64_prec(buf, frame.header.angles[1], prec);
        buf.push(b' ');
        push_f64_prec(buf, frame.header.angles[2], prec);
        buf.push(b'\n');
        let _ = writeln!(buf, "{}", frame.header.postbox_header[0]);
        let _ = writeln!(buf, "{}", frame.header.postbox_header[1]);
        let _ = writeln!(buf, "{}", frame.header.natm_types);

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
            push_f64_prec(buf, *m, prec);
        }
        buf.push(b'\n');

        // --- Write the Atom Data ---
        let mut atom_idx_offset = 0;
        for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
            let symbol = &frame.atom_data[atom_idx_offset].symbol;
            let _ = writeln!(buf, "{symbol}");
            let _ = writeln!(buf, "Coordinates of Component {}", type_idx + 1);

            for i in 0..num_atoms_in_type {
                let atom = &frame.atom_data[atom_idx_offset + i];
                push_xyz_line(
                    buf,
                    atom.x,
                    atom.y,
                    atom.z,
                    prec,
                    encode_fixed_bitmask(atom.fixed),
                    atom.atom_id,
                );
            }
            atom_idx_offset += num_atoms_in_type;
        }

        // --- Write optional velocity section ---
        if frame.has_velocities() {
            buf.push(b'\n');

            let mut vel_idx_offset = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[vel_idx_offset].symbol;
                let _ = writeln!(buf, "{symbol}");
                let _ = writeln!(buf, "Velocities of Component {}", type_idx + 1);

                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[vel_idx_offset + i];
                    let [vx, vy, vz] = atom.velocity.unwrap_or([0.0; 3]);
                    push_xyz_line(
                        buf,
                        vx,
                        vy,
                        vz,
                        prec,
                        encode_fixed_bitmask(atom.fixed),
                        atom.atom_id,
                    );
                }
                vel_idx_offset += num_atoms_in_type;
            }
        }

        // --- Write optional force section ---
        if frame.has_forces() {
            buf.push(b'\n');

            let mut force_idx_offset = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[force_idx_offset].symbol;
                let _ = writeln!(buf, "{symbol}");
                let _ = writeln!(buf, "Forces of Component {}", type_idx + 1);

                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[force_idx_offset + i];
                    let [fx, fy, fz] = atom.force.unwrap_or([0.0; 3]);
                    push_xyz_line(
                        buf,
                        fx,
                        fy,
                        fz,
                        prec,
                        encode_fixed_bitmask(atom.fixed),
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
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[energy_idx_offset].symbol;
                let _ = writeln!(buf, "{symbol}");
                let _ = writeln!(buf, "Energies of Component {}", type_idx + 1);

                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[energy_idx_offset + i];
                    let e = atom.energy.unwrap_or(0.0);
                    push_scalar_line(
                        buf,
                        e,
                        prec,
                        encode_fixed_bitmask(atom.fixed),
                        atom.atom_id,
                    );
                }
                energy_idx_offset += num_atoms_in_type;
            }
        }

        if frame.has_charges() {
            buf.push(b'\n');
            let mut off = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[off].symbol;
                let _ = writeln!(buf, "{symbol}");
                let _ = writeln!(buf, "Charges of Component {}", type_idx + 1);
                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[off + i];
                    let q = atom.charge.unwrap_or(0.0);
                    push_scalar_line(
                        buf,
                        q,
                        prec,
                        encode_fixed_bitmask(atom.fixed),
                        atom.atom_id,
                    );
                }
                off += num_atoms_in_type;
            }
        }

        if frame.has_spins() {
            buf.push(b'\n');
            let mut off = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[off].symbol;
                let _ = writeln!(buf, "{symbol}");
                let _ = writeln!(buf, "Spins of Component {}", type_idx + 1);
                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[off + i];
                    let s = atom.spin.unwrap_or(0.0);
                    push_scalar_line(
                        buf,
                        s,
                        prec,
                        encode_fixed_bitmask(atom.fixed),
                        atom.atom_id,
                    );
                }
                off += num_atoms_in_type;
            }
        }

        if frame.has_magmoms() {
            buf.push(b'\n');
            let mut off = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[off].symbol;
                let _ = writeln!(buf, "{symbol}");
                let _ = writeln!(buf, "Magmoms of Component {}", type_idx + 1);
                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[off + i];
                    let [mx, my, mz] = atom.magmom.unwrap_or([0.0; 3]);
                    push_xyz_line(
                        buf,
                        mx,
                        my,
                        mz,
                        prec,
                        encode_fixed_bitmask(atom.fixed),
                        atom.atom_id,
                    );
                }
                off += num_atoms_in_type;
            }
        }
        }

        self.writer.write_all(&self.scratch)
    }

    /// Writes all frames from an iterator to the output stream.
    ///
    /// This is the most convenient way to write a multi-frame file.
    pub fn extend<'a>(&mut self, frames: impl Iterator<Item = &'a ConFrame>) -> io::Result<()> {
        for frame in frames {
            self.write_frame(frame)?;
        }
        Ok(())
    }
}

fn push_u64(buf: &mut Vec<u8>, n: u64) {
    push_u128(buf, u128::from(n));
}

fn push_u128(buf: &mut Vec<u8>, mut n: u128) {
    let mut tmp = [0u8; 40];
    let mut i = 40;
    if n == 0 {
        buf.push(b'0');
        return;
    }
    while n > 0 {
        i -= 1;
        tmp[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    buf.extend_from_slice(&tmp[i..]);
}

/// Fixed-point `f64` with `prec` digits after the decimal, matching `{:.prec$}`.
/// Non-finite values and `prec > 17` fall back to `std::fmt`.
fn push_f64_prec(buf: &mut Vec<u8>, v: f64, prec: usize) {
    if !v.is_finite() || prec > 17 {
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

fn push_xyz_line(buf: &mut Vec<u8>, x: f64, y: f64, z: f64, prec: usize, fixed: u8, atom_id: u64) {
    push_f64_prec(buf, x, prec);
    buf.push(b' ');
    push_f64_prec(buf, y, prec);
    buf.push(b' ');
    push_f64_prec(buf, z, prec);
    buf.push(b' ');
    push_u64(buf, u64::from(fixed));
    buf.push(b' ');
    push_u64(buf, atom_id);
    buf.push(b'\n');
}

fn push_scalar_line(buf: &mut Vec<u8>, v: f64, prec: usize, fixed: u8, atom_id: u64) {
    push_f64_prec(buf, v, prec);
    buf.push(b' ');
    push_u64(buf, u64::from(fixed));
    buf.push(b' ');
    push_u64(buf, atom_id);
    buf.push(b'\n');
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
    use super::push_f64_prec;

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
}
