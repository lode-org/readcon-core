use crate::error::ParseError;
use crate::types::FrameHeader;

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
pub fn parse_single_frame(lines: &mut impl Iterator<Item = str>) -> Result<String, ParseError> {
    Err(ParseError::IncompleteFrame)
}
