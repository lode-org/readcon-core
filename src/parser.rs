use crate::error::ParseError;
use crate::types::{AtomDatum, ConFrame, FrameHeader};
use std::iter::Peekable;
use std::rc::Rc;

/// Parses a line of whitespace-separated values into a vector of a specific type.
///
/// This generic helper function takes a string slice, splits it by whitespace,
/// and attempts to parse each substring into the target type `T`. The type `T`
/// must implement `std::str::FromStr`.
///
/// # Arguments
///
/// * `line` - A string slice representing a single line of data.
/// * `n` - The exact number of values expected on the line.
///
/// # Errors
///
/// * `ParseError::InvalidVectorLength` if the number of parsed values is not equal to `n`.
/// * Propagates any error from the `parse()` method of the target type `T`.
///
/// # Example
///
/// ```
/// use readcon_core::parser::parse_line_of_n;
/// let line = "10.5 20.0 30.5";
/// let values: Vec<f64> = parse_line_of_n(line, 3).unwrap();
/// assert_eq!(values, vec![10.5, 20.0, 30.5]);
///
/// let result = parse_line_of_n::<i32>(line, 2);
/// assert!(result.is_err());
/// ```
pub fn parse_line_of_n<T: std::str::FromStr>(line: &str, n: usize) -> Result<Vec<T>, ParseError>
where
    ParseError: From<<T as std::str::FromStr>::Err>,
{
    let values: Vec<T> = line
        .split_whitespace()
        .map(|s| s.parse::<T>())
        .collect::<Result<_, _>>()?;

    if values.len() == n {
        Ok(values)
    } else {
        Err(ParseError::InvalidVectorLength {
            expected: n,
            found: values.len(),
        })
    }
}

/// Parses the 9-line header of a `.con` file frame from an iterator.
///
/// This function consumes the next 9 lines from the given line iterator to
/// construct a `FrameHeader`. The iterator is advanced by 9 lines on success.
///
/// # Arguments
///
/// * `lines` - A mutable reference to an iterator that yields string slices.
///
/// # Errors
///
/// * `ParseError::IncompleteHeader` if the iterator has fewer than 9 lines remaining.
/// * Propagates any errors from `parse_line_of_n` if the numeric data within
///   the header is malformed.
///
/// # Panics
///
/// This function will panic if the intermediate vectors for box dimensions or angles,
/// after being successfully parsed, cannot be converted into fixed-size arrays.
/// This should not happen if `parse_line_of_n` is used correctly with `n=3`.
pub fn parse_frame_header<'a>(
    lines: &mut impl Iterator<Item = &'a str>,
) -> Result<FrameHeader, ParseError> {
    let prebox1 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    let prebox2 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    let boxl_vec = parse_line_of_n::<f64>(lines.next().ok_or(ParseError::IncompleteHeader)?, 3)?;
    let angles_vec = parse_line_of_n::<f64>(lines.next().ok_or(ParseError::IncompleteHeader)?, 3)?;
    let postbox1 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    let postbox2 = lines
        .next()
        .ok_or(ParseError::IncompleteHeader)?
        .to_string();
    let natm_types =
        parse_line_of_n::<usize>(lines.next().ok_or(ParseError::IncompleteHeader)?, 1)?[0];
    let natms_per_type = parse_line_of_n::<usize>(
        lines.next().ok_or(ParseError::IncompleteHeader)?,
        natm_types,
    )?;
    let masses_per_type = parse_line_of_n::<f64>(
        lines.next().ok_or(ParseError::IncompleteHeader)?,
        natm_types,
    )?;
    Ok(FrameHeader {
        prebox_header: [prebox1, prebox2],
        boxl: boxl_vec.try_into().unwrap(),
        angles: angles_vec.try_into().unwrap(),
        postbox_header: [postbox1, postbox2],
        natm_types,
        natms_per_type,
        masses_per_type,
    })
}

/// Parses a complete frame from a `.con` file, including its header and atomic data.
///
/// This function first parses the complete frame header and then uses the information within it
/// (specifically the number of atom types and atoms per type) to parse the subsequent
/// atom coordinate blocks.
///
/// # Arguments
///
/// * `lines` - A mutable reference to an iterator that yields string slices for the frame.
///
/// # Errors
///
/// * `ParseError::IncompleteFrame` if the iterator ends before all expected
///   atomic data has been read.
/// * Propagates any errors from the underlying calls to `parse_frame_header` and
///   `parse_line_of_n`.
///
/// # Example
///
/// ```
/// use readcon_core::parser::parse_single_frame;
///
/// let frame_text = r#"
///PREBOX LINE 1
///PREBOX LINE 2
///10.0 10.0 10.0
///90.0 90.0 90.0
///POSTBOX LINE 1
///POSTBOX LINE 2
///2
///1 1
///12.011 1.008
///C
///Coordinates of Component 1
///1.0 1.0 1.0 0.0 1
///H
///Coordinates of Component 2
///2.0 2.0 2.0 0.0 2
/// "#;
///
/// let mut lines = frame_text.trim().lines();
/// let con_frame = parse_single_frame(&mut lines).unwrap();
///
/// assert_eq!(con_frame.header.natm_types, 2);
/// assert_eq!(con_frame.atom_data.len(), 2);
/// assert_eq!(&*con_frame.atom_data[0].symbol, "C");
/// assert_eq!(con_frame.atom_data[1].atom_id, 2);
/// ```
pub fn parse_single_frame<'a>(
    lines: &mut impl Iterator<Item = &'a str>,
) -> Result<ConFrame, ParseError> {
    let header = parse_frame_header(lines)?;
    let total_atoms: usize = header.natms_per_type.iter().sum();
    let mut atom_data = Vec::with_capacity(total_atoms);

    for num_atoms in &header.natms_per_type {
        // Create a reference-counted string for the symbol once per component.
        let symbol = Rc::new(
            lines
                .next()
                .ok_or(ParseError::IncompleteFrame)?
                .trim()
                .to_string(),
        );
        // Consume and discard the "Coordinates of Component X" line.
        lines.next().ok_or(ParseError::IncompleteFrame)?;
        for _ in 0..*num_atoms {
            let coord_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            let vals = parse_line_of_n::<f64>(coord_line, 5)?;
            atom_data.push(AtomDatum {
                // This is now a cheap reference-count increment, not a full string clone.
                symbol: Rc::clone(&symbol),
                x: vals[0],
                y: vals[1],
                z: vals[2],
                is_fixed: vals[3] != 0.0,
                atom_id: vals[4] as u64,
                vx: None,
                vy: None,
                vz: None,
            });
        }
    }
    Ok(ConFrame { header, atom_data })
}

/// Attempts to parse an optional velocity section following coordinate blocks.
///
/// In `.convel` files, after all coordinate blocks there is a blank separator line
/// followed by per-component velocity blocks with the same structure as coordinate
/// blocks (symbol line, "Velocities of Component N" line, then atom lines with
/// `vx vy vz fixed atomID`).
///
/// This function peeks at the next line. If it is blank (or contains only whitespace),
/// it consumes the blank line and parses velocity data into the existing `atom_data`.
/// If the next line is not blank (or is absent), no velocities are parsed.
///
/// Returns `Ok(true)` if velocities were found and parsed, `Ok(false)` otherwise.
pub fn parse_velocity_section<'a, I>(
    lines: &mut Peekable<I>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError>
where
    I: Iterator<Item = &'a str>,
{
    // Peek at the next line to check for blank separator
    match lines.peek() {
        Some(line) if line.trim().is_empty() => {
            // Consume the blank separator
            lines.next();
        }
        _ => return Ok(false),
    }

    let mut atom_idx = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        // Symbol line
        let _symbol = lines
            .next()
            .ok_or(ParseError::IncompleteVelocitySection)?
            .trim();

        // "Velocities of Component N" line
        let comp_line = lines
            .next()
            .ok_or(ParseError::IncompleteVelocitySection)?;
        // Validate it looks like a velocity header (optional strictness)
        if !comp_line.contains("Velocities of Component") {
            return Err(ParseError::IncompleteVelocitySection);
        }
        let _ = type_idx; // suppress unused warning

        for _ in 0..num_atoms {
            let vel_line = lines
                .next()
                .ok_or(ParseError::IncompleteVelocitySection)?;
            let vals = parse_line_of_n::<f64>(vel_line, 5)?;
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].vx = Some(vals[0]);
                atom_data[atom_idx].vy = Some(vals[1]);
                atom_data[atom_idx].vz = Some(vals[2]);
                // vals[3] is fixed flag, vals[4] is atom_id (redundant with coords)
            }
            atom_idx += 1;
        }
    }

    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_line_of_n_success() {
        let line = "1.0 2.5 -3.0";
        let values = parse_line_of_n::<f64>(line, 3).unwrap();
        assert_eq!(values, vec![1.0, 2.5, -3.0]);
    }

    #[test]
    fn test_parse_line_of_n_too_short() {
        let line = "1.0 2.5";
        let result = parse_line_of_n::<f64>(line, 3);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 3,
                found: 2
            }
        ));
    }

    #[test]
    fn test_parse_line_of_n_too_long() {
        let line = "1.0 2.5 -3.0 4.0";
        let result = parse_line_of_n::<f64>(line, 3);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 3,
                found: 4
            }
        ));
    }

    #[test]
    fn test_parse_line_of_n_invalid_float() {
        let line = "1.0 abc -3.0";
        let result = parse_line_of_n::<f64>(line, 3);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidNumberFormat(_)
        ));
    }

    #[test]
    fn test_parse_frame_header_success() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        match parse_frame_header(&mut line_it) {
            Ok(header) => {
                assert_eq!(header.prebox_header, ["PREBOX1", "PREBOX2"]);
                assert_eq!(header.boxl, [10.0, 20.0, 30.0]);
                assert_eq!(header.angles, [90.0, 90.0, 90.0]);
                assert_eq!(header.postbox_header, ["POSTBOX1", "POSTBOX2"]);
                assert_eq!(header.natm_types, 2);
                assert_eq!(header.natms_per_type, vec![1, 1]);
                assert_eq!(header.masses_per_type, vec![12.011, 1.008]);
            }
            Err(e) => {
                panic!(
                    "Parsing failed when it should have succeeded. Error: {:?}",
                    e
                );
            }
        }
    }

    #[test]
    fn test_parse_frame_header_missing_line() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            // Missing masses_per_type
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ParseError::IncompleteHeader));
    }

    #[test]
    fn test_parse_frame_header_invalid_natms_per_type() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1 1", // 3 values, but natm_types is 2
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 2,
                found: 3
            }
        ));
    }

    #[test]
    fn test_parse_single_frame_success() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "3 3",
            "12.011 1.008",
            "1",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0.0 1",
            "1.0940 0.0 0.0 0.0 2",
            "-0.5470 0.9499 0.0 0.0 3",
            "2",
            "Coordinates of Component 2",
            "5.0 5.0 5.0 0.0 4",
            "6.0940 5.0 5.0 0.0 5",
            "5.5470 5.9499 5.0 0.0 6",
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();

        assert_eq!(frame.header.natm_types, 2);
        assert_eq!(frame.header.natms_per_type, vec![3, 3]);
        assert_eq!(frame.header.masses_per_type, vec![12.011, 1.008]);
        assert_eq!(frame.atom_data.len(), 6);
        assert_eq!(&*frame.atom_data[0].symbol, "1");
        assert_eq!(frame.atom_data[0].atom_id, 1);
        assert_eq!(&*frame.atom_data[5].symbol, "2");
        assert_eq!(frame.atom_data[5].atom_id, 6);
    }

    #[test]
    fn test_parse_single_frame_missing_line() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "3 3",
            "12.011 1.008",
            "1",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0.0 1",
            "1.0940 0.0 0.0 0.0 2",
            "-0.5470 0.9499 0.0 0.0 3",
            // Missing "2" line for Component 2 atoms
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_single_frame(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ParseError::IncompleteFrame));
    }

    #[test]
    fn test_parse_single_frame_invalid_atom_coords() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "3 3",
            "12.011 1.008",
            "1",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0.0 1",
            "1.0940 0.0 0.0 0.0 2",
            "-0.5470 0.9499 0.0 0.0 3",
            "2",
            "Coordinates of Component 2",
            "5.0 5.0 5.0 0.0", // Missing atom_id
            "6.0940 5.0 5.0 0.0 5",
            "5.5470 5.9499 5.0 0.0 6",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_single_frame(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 5,
                found: 4
            }
        ));
    }

    #[test]
    fn test_parse_velocity_section_present() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "63.546 1.008",
            "Cu",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 1.0 0",
            "H",
            "Coordinates of Component 2",
            "1.0 2.0 3.0 0.0 1",
            "",
            "Cu",
            "Velocities of Component 1",
            "0.1 0.2 0.3 1.0 0",
            "H",
            "Velocities of Component 2",
            "0.4 0.5 0.6 0.0 1",
        ];
        let mut line_it = lines.iter().copied().peekable();
        // Parse the frame first (consuming 15 lines)
        let mut frame =
            parse_single_frame(&mut line_it).expect("coordinate parsing should succeed");
        assert!(!frame.has_velocities());

        // Now parse the velocity section
        let has_vel =
            parse_velocity_section(&mut line_it, &frame.header, &mut frame.atom_data)
                .expect("velocity parsing should succeed");
        assert!(has_vel);
        assert_eq!(frame.atom_data[0].vx, Some(0.1));
        assert_eq!(frame.atom_data[0].vy, Some(0.2));
        assert_eq!(frame.atom_data[0].vz, Some(0.3));
        assert_eq!(frame.atom_data[1].vx, Some(0.4));
        assert_eq!(frame.atom_data[1].vy, Some(0.5));
        assert_eq!(frame.atom_data[1].vz, Some(0.6));
    }

    #[test]
    fn test_parse_velocity_section_absent() {
        let lines = vec![
            "PREBOX1",
            "PREBOX2",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
            "C",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0.0 1",
        ];
        let mut line_it = lines.iter().copied().peekable();
        let mut frame = parse_single_frame(&mut line_it).expect("parse should succeed");
        let has_vel =
            parse_velocity_section(&mut line_it, &frame.header, &mut frame.atom_data)
                .expect("should succeed with no velocities");
        assert!(!has_vel);
        assert_eq!(frame.atom_data[0].vx, None);
    }
}
