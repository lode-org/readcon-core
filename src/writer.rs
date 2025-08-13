pub(crate) use crate::types::ConFrame;
pub(crate) use std::io::{self, Write};

/// Writes a single `ConFrame` to the given writer in the `.con` file format.
///
/// This function formats the header and atomic data according to the specific
/// structure of a `.con` file frame, including the 9-line header and the
/// per-component atom blocks.
///
/// # Arguments
///
/// * `frame` - A reference to the `ConFrame` to be written.
/// * `writer` - A mutable reference to an object that implements the `std::io::Write` trait,
///   such as a file or a `Vec<u8>`.
///
/// # Errors
///
/// This function will return any I/O errors encountered during the write operations.
pub fn write_con_frame(frame: &ConFrame, writer: &mut impl Write) -> io::Result<()> {
    // --- Write the 9-line Header ---
    writeln!(writer, "{}", frame.header.prebox_header[0])?;
    writeln!(writer, "{}", frame.header.prebox_header[1])?;
    writeln!(
        writer,
        "{:.6} {:.6} {:.6}",
        frame.header.boxl[0], frame.header.boxl[1], frame.header.boxl[2]
    )?;
    writeln!(
        writer,
        "{:.6} {:.6} {:.6}",
        frame.header.angles[0], frame.header.angles[1], frame.header.angles[2]
    )?;
    writeln!(writer, "{}", frame.header.postbox_header[0])?;
    writeln!(writer, "{}", frame.header.postbox_header[1])?;
    writeln!(writer, "{}", frame.header.natm_types)?;

    // Write the number of atoms per type, space-separated
    let natms_str: Vec<String> = frame
        .header
        .natms_per_type
        .iter()
        .map(|n| n.to_string())
        .collect();
    writeln!(writer, "{}", natms_str.join(" "))?;

    // Write the masses per type, space-separated
    let masses_str: Vec<String> = frame
        .header
        .masses_per_type
        .iter()
        .map(|m| format!("{:.6}", m))
        .collect();
    writeln!(writer, "{}", masses_str.join(" "))?;

    // --- Write the Atom Data ---
    // Keep track of which atom we are in the flat `atom_data` list.
    let mut atom_idx_offset = 0;
    for (type_idx, &num_atoms_in_type) in frame.header.natms_per_type.iter().enumerate() {
        // Find the symbol for the current component. We can get it from the first
        // atom in this component's block.
        let symbol = &frame.atom_data[atom_idx_offset].symbol;
        writeln!(writer, "{}", symbol)?;
        writeln!(writer, "Coordinates of Component {}", type_idx + 1)?;

        // Write the coordinate lines for each atom in this component.
        for i in 0..num_atoms_in_type {
            let atom = &frame.atom_data[atom_idx_offset + i];
            writeln!(
                writer,
                "{:.6} {:.6} {:.6} {} {}",
                atom.x,
                atom.y,
                atom.z,
                if atom.is_fixed { 1.0 } else { 0.0 },
                atom.atom_id
            )?;
        }
        // Move the offset to the start of the next component block.
        atom_idx_offset += num_atoms_in_type;
    }

    Ok(())
}

/// Writes an iterator of `ConFrame`s to a writer, creating a multi-frame `.con` file.
///
/// This function iterates over a collection of `ConFrame`s and calls `write_con_frame`
/// for each one, effectively concatenating them into a single output stream.
///
/// # Arguments
///
/// * `frames` - An iterator that yields references to `ConFrame`s.
/// * `writer` - A mutable reference to an object that implements `std::io::Write`.
///
/// # Errors
///
/// This function will stop and return the first I/O error encountered.
pub fn write_con_file<'a>(
    frames: impl Iterator<Item = &'a ConFrame>,
    writer: &mut impl Write,
) -> io::Result<()> {
    for frame in frames {
        write_con_frame(frame, writer)?;
    }
    Ok(())
}
