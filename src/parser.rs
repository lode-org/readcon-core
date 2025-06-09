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
