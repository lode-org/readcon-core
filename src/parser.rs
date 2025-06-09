use crate::error::ParseError;
use crate::types::{AtomDatum, ConFrame, FrameHeader};

/// Helper function to parse a line of N space separated values.
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

/// Consume 9 lines to build the FrameHeader
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

/// Main parsing function for a single frame
pub fn parse_single_frame<'a>(
    lines: &mut impl Iterator<Item = &'a str>,
) -> Result<ConFrame, ParseError> {
    let header = parse_frame_header(lines)?;
    let mut atom_data = Vec::new();
    for num_atoms in &header.natms_per_type {
        let symbol = lines
            .next()
            .ok_or(ParseError::IncompleteFrame)?
            .trim()
            .to_string();
        // Consume and discard the "Coordinates of Component X" line.
        lines.next().ok_or(ParseError::IncompleteFrame)?;
        for _ in 0..*num_atoms {
            let coord_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            let vals = parse_line_of_n::<f64>(coord_line, 5)?;
            atom_data.push(AtomDatum {
                symbol: symbol.clone(),
                x: vals[0],
                y: vals[1],
                z: vals[2],
                is_fixed: vals[3] != 0.0,
                atom_id: vals[4] as u64,
            });
        }
    }
    Ok(ConFrame { header, atom_data })
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
        assert_eq!(frame.atom_data[0].symbol, "1");
        assert_eq!(frame.atom_data[0].atom_id, 1);
        assert_eq!(frame.atom_data[5].symbol, "2");
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
}
