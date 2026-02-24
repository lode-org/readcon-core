use crate::types::ConFrame;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;

/// The floating-point precision used for writing coordinates, cell dimensions, and masses.
const FLOAT_PRECISION: usize = 6;
/// Always 0 or 1
/// The value used to indicate a fixed atom in the output file.
const FIXED_ATOM_FLAG: usize = 1;
/// The value used to indicate a non-fixed (free) atom in the output file.
const FREE_ATOM_FLAG: usize = 0;

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
        }
    }

    /// Writes a single `ConFrame` to the output stream.
    pub fn write_frame(&mut self, frame: &ConFrame) -> io::Result<()> {
        // --- Write the 9-line Header ---
        writeln!(self.writer, "{}", frame.header.prebox_header[0])?;
        writeln!(self.writer, "{}", frame.header.prebox_header[1])?;
        writeln!(
            self.writer,
            "{1:.0$} {2:.0$} {3:.0$}",
            FLOAT_PRECISION, frame.header.boxl[0], frame.header.boxl[1], frame.header.boxl[2]
        )?;
        writeln!(
            self.writer,
            "{1:.0$} {2:.0$} {3:.0$}",
            FLOAT_PRECISION, frame.header.angles[0], frame.header.angles[1], frame.header.angles[2]
        )?;
        writeln!(self.writer, "{}", frame.header.postbox_header[0])?;
        writeln!(self.writer, "{}", frame.header.postbox_header[1])?;
        writeln!(self.writer, "{}", frame.header.natm_types)?;

        let natms_str: Vec<String> = frame
            .header
            .natms_per_type
            .iter()
            .map(|n| n.to_string())
            .collect();
        writeln!(self.writer, "{}", natms_str.join(" "))?;

        let masses_str: Vec<String> = frame
            .header
            .masses_per_type
            .iter()
            .map(|m| format!("{:.1$}", m, FLOAT_PRECISION))
            .collect();
        writeln!(self.writer, "{}", masses_str.join(" "))?;

        // --- Write the Atom Data ---
        let mut atom_idx_offset = 0;
        for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
            let symbol = &frame.atom_data[atom_idx_offset].symbol;
            writeln!(self.writer, "{}", symbol)?;
            writeln!(self.writer, "Coordinates of Component {}", type_idx + 1)?;

            for i in 0..num_atoms_in_type {
                let atom = &frame.atom_data[atom_idx_offset + i];
                writeln!(
                    self.writer,
                    "{x:.prec$} {y:.prec$} {z:.prec$} {fixed_flag:.0} {atom_id}",
                    prec = FLOAT_PRECISION,
                    x = atom.x,
                    y = atom.y,
                    z = atom.z,
                    fixed_flag = if atom.is_fixed {
                        FIXED_ATOM_FLAG
                    } else {
                        FREE_ATOM_FLAG
                    },
                    atom_id = atom.atom_id
                )?;
            }
            atom_idx_offset += num_atoms_in_type;
        }

        // --- Write optional velocity section ---
        if frame.has_velocities() {
            // Blank separator line between coordinates and velocities
            writeln!(self.writer)?;

            let mut vel_idx_offset = 0;
            for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
                let symbol = &frame.atom_data[vel_idx_offset].symbol;
                writeln!(self.writer, "{}", symbol)?;
                writeln!(self.writer, "Velocities of Component {}", type_idx + 1)?;

                for i in 0..num_atoms_in_type {
                    let atom = &frame.atom_data[vel_idx_offset + i];
                    writeln!(
                        self.writer,
                        "{vx:.prec$} {vy:.prec$} {vz:.prec$} {fixed_flag:.0} {atom_id}",
                        prec = FLOAT_PRECISION,
                        vx = atom.vx.unwrap_or(0.0),
                        vy = atom.vy.unwrap_or(0.0),
                        vz = atom.vz.unwrap_or(0.0),
                        fixed_flag = if atom.is_fixed {
                            FIXED_ATOM_FLAG
                        } else {
                            FREE_ATOM_FLAG
                        },
                        atom_id = atom.atom_id
                    )?;
                }
                vel_idx_offset += num_atoms_in_type;
            }
        }

        Ok(())
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

// Implementation block specifically for when the writer is a `File`.
impl ConFrameWriter<File> {
    /// Creates a new `ConFrameWriter` that writes to a file at the given path.
    ///
    /// This is a convenience function that creates the file and wraps it.
    pub fn from_path<P: AsRef<Path>>(path: P) -> io::Result<Self> {
        let file = File::create(path)?;
        Ok(Self::new(file))
    }
}
