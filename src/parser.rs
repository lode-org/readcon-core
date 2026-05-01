use crate::error::ParseError;
use crate::helpers::symbol_to_atomic_number;
use crate::types::{AtomDatum, ConFrame, FrameHeader, decode_fixed_bitmask};
use serde_json::Value;
use std::collections::BTreeMap;
use std::iter::Peekable;
use std::sync::Arc;

/// Parses a line of whitespace-separated f64 values using fast-float2.
///
/// This is the hot-path parser for coordinate and velocity lines. It uses
/// `fast_float2::parse` instead of `str::parse::<f64>()` for better throughput
/// on the numeric-heavy atom data lines.
///
/// # Arguments
///
/// * `line` - A string slice representing a single line of data.
/// * `n` - The exact number of f64 values expected on the line.
pub fn parse_line_of_n_f64(line: &str, n: usize) -> Result<Vec<f64>, ParseError> {
    let mut values = Vec::with_capacity(n);
    for token in line.split_ascii_whitespace() {
        values.push(parse_finite_f64(token)?);
    }
    if values.len() == n {
        Ok(values)
    } else {
        Err(ParseError::InvalidVectorLength {
            expected: n,
            found: values.len(),
        })
    }
}

/// Parses a line of whitespace-separated f64 values, accepting between `min`
/// and `max` values (inclusive). Returns a vector of exactly `max` elements,
/// padding with values from `defaults` when fewer than `max` are present.
///
/// Used for atom lines where column 5 (atom_index) is optional.
pub fn parse_line_of_range_f64(
    line: &str,
    min: usize,
    max: usize,
    defaults: &[f64],
) -> Result<Vec<f64>, ParseError> {
    let mut values = Vec::with_capacity(max);
    for token in line.split_ascii_whitespace() {
        values.push(parse_finite_f64(token)?);
    }
    if values.len() < min || values.len() > max {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found: values.len(),
        });
    }
    // Pad missing columns from defaults
    while values.len() < max {
        let idx = values.len();
        values.push(defaults[idx]);
    }
    Ok(values)
}

fn parse_finite_f64(token: &str) -> Result<f64, ParseError> {
    let val: f64 = fast_float2::parse(token)
        .map_err(|_| ParseError::InvalidNumberFormat(format!("invalid float: {token}")))?;
    if val.is_finite() {
        Ok(val)
    } else {
        Err(ParseError::InvalidNumberFormat(format!(
            "non-finite float: {token}"
        )))
    }
}

fn metadata_json_error(message: impl Into<String>) -> ParseError {
    ParseError::InvalidMetadataJson(message.into())
}

fn validate_metadata_number(key: &str, value: &Value) -> Result<(), ParseError> {
    if value.as_f64().is_some() {
        Ok(())
    } else {
        Err(metadata_json_error(format!(
            "{key} must be a finite number"
        )))
    }
}

fn validate_metadata_integer(key: &str, value: &Value) -> Result<(), ParseError> {
    if value.as_u64().is_some() {
        Ok(())
    } else {
        Err(metadata_json_error(format!(
            "{key} must be a non-negative integer"
        )))
    }
}

fn validate_metadata_schema(
    json_obj: &serde_json::Map<String, Value>,
) -> Result<(bool, Vec<String>), ParseError> {
    let validate = match json_obj.get("validate") {
        Some(Value::Bool(value)) => *value,
        Some(_) => return Err(metadata_json_error("validate must be a boolean")),
        None => false,
    };

    let sections = match json_obj.get("sections") {
        Some(Value::Array(values)) => values
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_string)
                    .ok_or_else(|| metadata_json_error("sections must be an array of strings"))
            })
            .collect::<Result<Vec<_>, _>>()?,
        Some(_) => return Err(metadata_json_error("sections must be an array of strings")),
        None if validate => {
            return Err(metadata_json_error(
                "validate=true requires a sections array, even when empty",
            ));
        }
        None => Vec::new(),
    };

    for (key, value) in json_obj {
        match key.as_str() {
            "con_spec_version" | "sections" | "validate" => {}
            "energy" | "time" | "timestep" | "convergence_fmax" | "convergence_energy" | "fmax" => {
                validate_metadata_number(key, value)?
            }
            "frame_index" | "neb_bead" | "neb_band" => validate_metadata_integer(key, value)?,
            "generator" => {
                if !value.is_string() {
                    return Err(metadata_json_error("generator must be a string"));
                }
            }
            "units" | "potential" => {
                if !value.is_object() {
                    return Err(metadata_json_error(format!("{key} must be an object")));
                }
                if key == "potential" {
                    if let Some(potential_type) = value.get("type") {
                        if !potential_type.is_string() {
                            return Err(metadata_json_error("potential.type must be a string"));
                        }
                    }
                }
            }
            "pbc" => validate_pbc_metadata(value)?,
            "lattice_vectors" => validate_lattice_vectors_metadata(value)?,
            "converged" => {
                if !value.is_boolean() {
                    return Err(metadata_json_error("converged must be a boolean"));
                }
            }
            _ => {}
        }
    }

    Ok((validate, sections))
}

fn validate_pbc_metadata(value: &Value) -> Result<(), ParseError> {
    let Some(values) = value.as_array() else {
        return Err(metadata_json_error("pbc must be a length-3 boolean array"));
    };
    if values.len() != 3 || values.iter().any(|entry| !entry.is_boolean()) {
        return Err(metadata_json_error("pbc must be a length-3 boolean array"));
    }
    Ok(())
}

fn validate_lattice_vectors_metadata(value: &Value) -> Result<(), ParseError> {
    let Some(rows) = value.as_array() else {
        return Err(metadata_json_error(
            "lattice_vectors must be a 3x3 numeric array",
        ));
    };
    if rows.len() != 3 {
        return Err(metadata_json_error(
            "lattice_vectors must be a 3x3 numeric array",
        ));
    }
    for row in rows {
        let Some(entries) = row.as_array() else {
            return Err(metadata_json_error(
                "lattice_vectors must be a 3x3 numeric array",
            ));
        };
        if entries.len() != 3 || entries.iter().any(|entry| entry.as_f64().is_none()) {
            return Err(metadata_json_error(
                "lattice_vectors must be a 3x3 numeric array",
            ));
        }
    }
    Ok(())
}

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
    let prebox2_raw = lines.next().ok_or(ParseError::IncompleteHeader)?;

    // Line 2: if it starts with '{', parse as JSON metadata (spec v2+).
    // Otherwise treat as a legacy (pre-v2) file with spec_version = 1.
    let trimmed = prebox2_raw.trim();
    let (spec_version, metadata, sections, validate) = if trimmed.starts_with('{') {
        let json_val: serde_json::Value = serde_json::from_str(trimmed)
            .map_err(|e| ParseError::InvalidMetadataJson(e.to_string()))?;
        let json_obj = json_val
            .as_object()
            .ok_or_else(|| ParseError::InvalidMetadataJson("expected a JSON object".to_string()))?;
        let ver = json_obj
            .get("con_spec_version")
            .and_then(|v| v.as_u64())
            .ok_or(ParseError::MissingSpecVersion)? as u32;
        if ver > crate::CON_SPEC_VERSION {
            return Err(ParseError::UnsupportedSpecVersion(ver));
        }
        let (validate, secs) = validate_metadata_schema(json_obj)?;
        let mut meta = BTreeMap::new();
        for (k, v) in json_obj {
            if k == "con_spec_version" {
                continue;
            }
            if k == "sections" {
                // Don't store sections in metadata -- it's in the dedicated field.
                continue;
            }
            meta.insert(k.clone(), v.clone());
        }
        (ver, meta, secs, validate)
    } else {
        // Legacy file: no JSON metadata line.
        (1_u32, BTreeMap::new(), Vec::new(), false)
    };
    let prebox2 = prebox2_raw.to_string();

    let boxl_vec = parse_line_of_n_f64(lines.next().ok_or(ParseError::IncompleteHeader)?, 3)?;
    let angles_vec = parse_line_of_n_f64(lines.next().ok_or(ParseError::IncompleteHeader)?, 3)?;
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
    let masses_per_type = parse_line_of_n_f64(
        lines.next().ok_or(ParseError::IncompleteHeader)?,
        natm_types,
    )?;
    if validate {
        validate_header_geometry(&boxl_vec, &angles_vec, natm_types, &natms_per_type)?;
        validate_masses(&masses_per_type)?;
    }
    Ok(FrameHeader {
        prebox_header: [prebox1, prebox2],
        boxl: boxl_vec.try_into().unwrap(),
        angles: angles_vec.try_into().unwrap(),
        postbox_header: [postbox1, postbox2],
        natm_types,
        natms_per_type,
        masses_per_type,
        spec_version,
        metadata,
        sections,
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
///Generated by test
///{"con_spec_version":2}
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
    let validate = strict_validation_enabled(&header);
    let total_atoms: usize = header.natms_per_type.iter().sum();
    let mut atom_data = Vec::with_capacity(total_atoms);

    let mut global_atom_idx: u64 = 0;
    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        // Create a reference-counted string for the symbol once per component.
        let symbol: Arc<str> = Arc::from(
            lines
                .next()
                .ok_or(ParseError::IncompleteFrame)?
                .trim()
                .to_string(),
        );
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
        }
        for _ in 0..*num_atoms {
            let coord_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            // Column 5 (atom_index) is optional; defaults to sequential index.
            let defaults = [0.0, 0.0, 0.0, 0.0, global_atom_idx as f64];
            let vals = parse_line_of_range_f64(coord_line, 4, 5, &defaults)?;
            let (fixed, atom_id) = if validate {
                parse_identity_columns(coord_line, "coordinate")?
            } else {
                (decode_fixed_bitmask(vals[3] as u8), vals[4] as u64)
            };
            atom_data.push(AtomDatum {
                // This is a cheap reference-count increment, not a full string clone.
                symbol: Arc::clone(&symbol),
                x: vals[0],
                y: vals[1],
                z: vals[2],
                fixed,
                atom_id,
                vx: None,
                vy: None,
                vz: None,
                fx: None,
                fy: None,
                fz: None,
            });
            global_atom_idx += 1;
        }
    }
    Ok(ConFrame { header, atom_data })
}

fn strict_validation_enabled(header: &FrameHeader) -> bool {
    header
        .metadata
        .get("validate")
        .and_then(|value| value.as_bool())
        .unwrap_or(false)
}

fn validate_header_geometry(
    boxl: &[f64],
    angles: &[f64],
    natm_types: usize,
    natms_per_type: &[usize],
) -> Result<(), ParseError> {
    if boxl.iter().any(|length| *length <= 0.0)
        || angles.iter().any(|angle| *angle <= 0.0 || *angle >= 180.0)
    {
        return Err(ParseError::ValidationError(
            "cell geometry must have positive lengths and angles between 0 and 180 degrees"
                .to_string(),
        ));
    }
    if natm_types == 0 || natms_per_type.iter().any(|count| *count == 0) {
        return Err(ParseError::ValidationError(
            "atom counts must contain at least one atom per component".to_string(),
        ));
    }
    Ok(())
}

fn validate_masses(masses_per_type: &[f64]) -> Result<(), ParseError> {
    if masses_per_type.iter().any(|mass| *mass <= 0.0) {
        return Err(ParseError::ValidationError(
            "component masses must be positive".to_string(),
        ));
    }
    Ok(())
}

fn validate_coordinate_component(
    type_idx: usize,
    symbol: &str,
    label: &str,
) -> Result<(), ParseError> {
    let expected_label = format!("Coordinates of Component {}", type_idx + 1);
    if label.trim() != expected_label {
        return Err(ParseError::ValidationError(format!(
            "expected coordinate label {expected_label:?}, found {label:?}"
        )));
    }
    if symbol != "X" && symbol_to_atomic_number(symbol) == 0 {
        return Err(ParseError::ValidationError(format!(
            "unknown component symbol {symbol}"
        )));
    }
    Ok(())
}

fn parse_identity_columns(line: &str, row_kind: &str) -> Result<([bool; 3], u64), ParseError> {
    let columns = line.split_ascii_whitespace().collect::<Vec<_>>();
    if columns.len() != 5 {
        return Err(ParseError::ValidationError(format!(
            "{row_kind} rows require fixed_flag and atom_id columns in validate mode"
        )));
    }
    let fixed_flag = columns[3].parse::<u8>().map_err(|_| {
        ParseError::ValidationError(format!("{row_kind} fixed_flag must be an integer bitmask"))
    })?;
    if fixed_flag > 7 {
        return Err(ParseError::ValidationError(format!(
            "{row_kind} fixed_flag must be between 0 and 7"
        )));
    }
    let atom_id = columns[4].parse::<u64>().map_err(|_| {
        ParseError::ValidationError(format!("{row_kind} atom_id must be an integer"))
    })?;
    Ok((decode_fixed_bitmask(fixed_flag), atom_id))
}

fn validate_section_component(
    section: &str,
    type_idx: usize,
    atom_idx: usize,
    symbol: &str,
    label: &str,
    header: &FrameHeader,
    atom_data: &[AtomDatum],
) -> Result<(), ParseError> {
    let expected_label = format!("{section} of Component {}", type_idx + 1);
    if label.trim() != expected_label {
        return Err(ParseError::ValidationError(format!(
            "expected section label {expected_label:?}, found {label:?}"
        )));
    }

    if header.natms_per_type[type_idx] == 0 {
        return Ok(());
    }

    let expected_symbol = atom_data
        .get(atom_idx)
        .map(|atom| atom.symbol.as_ref())
        .ok_or_else(|| {
            ParseError::ValidationError(format!(
                "{section} component {} has no coordinate atom to validate against",
                type_idx + 1
            ))
        })?;
    if symbol != expected_symbol {
        return Err(ParseError::ValidationError(format!(
            "{section} component {} symbol mismatch: expected {expected_symbol}, found {symbol}",
            type_idx + 1
        )));
    }

    Ok(())
}

fn validate_section_atom_identity(
    section: &str,
    atom_idx: usize,
    fixed: [bool; 3],
    atom_id: u64,
    atom_data: &[AtomDatum],
) -> Result<(), ParseError> {
    let atom = atom_data.get(atom_idx).ok_or_else(|| {
        ParseError::ValidationError(format!(
            "{section} row {atom_idx} has no coordinate atom to validate against"
        ))
    })?;

    if atom.fixed != fixed {
        return Err(ParseError::ValidationError(format!(
            "{section} row {atom_idx} fixed mask mismatch for atom_id {}",
            atom.atom_id
        )));
    }
    if atom.atom_id != atom_id {
        return Err(ParseError::ValidationError(format!(
            "{section} row {atom_idx} atom_id mismatch: expected {}, found {atom_id}",
            atom.atom_id
        )));
    }

    Ok(())
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
    let validate = strict_validation_enabled(header);
    // Peek at the next line to check for blank separator
    match lines.peek() {
        Some(line) if line.trim().is_empty() => {
            // Consume the blank separator
            lines.next();
        }
        _ => return Ok(false),
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        // Symbol line
        let symbol = lines
            .next()
            .ok_or(ParseError::IncompleteVelocitySection)?
            .trim();

        // "Velocities of Component N" line
        let comp_line = lines.next().ok_or(ParseError::IncompleteVelocitySection)?;
        // Validate it looks like a velocity header (optional strictness)
        if !comp_line.contains("Velocities of Component") {
            return Err(ParseError::IncompleteVelocitySection);
        }
        if validate {
            validate_section_component(
                "Velocities",
                type_idx,
                atom_idx,
                symbol,
                comp_line,
                header,
                atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let vel_line = lines.next().ok_or(ParseError::IncompleteVelocitySection)?;
            // Column 5 (atom_index) is optional in velocity lines too.
            let defaults = [0.0, 0.0, 0.0, 0.0, atom_idx as f64];
            let vals = parse_line_of_range_f64(vel_line, 4, 5, &defaults)?;
            if validate {
                let (fixed, atom_id) = parse_identity_columns(vel_line, "velocities")?;
                validate_section_atom_identity("velocities", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].vx = Some(vals[0]);
                atom_data[atom_idx].vy = Some(vals[1]);
                atom_data[atom_idx].vz = Some(vals[2]);
            }
            atom_idx += 1;
        }
    }

    Ok(true)
}

/// Attempts to parse a force section following coordinate (and optional velocity) blocks.
///
/// Force sections mirror velocity sections: a blank separator line followed by per-component
/// force blocks (symbol line, "Forces of Component N" line, then atom lines with
/// `fx fy fz fixed_flag atom_id`).
///
/// Returns `Ok(true)` if forces were found and parsed, `Ok(false)` otherwise.
pub fn parse_force_section<'a, I>(
    lines: &mut Peekable<I>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError>
where
    I: Iterator<Item = &'a str>,
{
    let validate = strict_validation_enabled(header);
    // Peek at the next line to check for blank separator
    match lines.peek() {
        Some(line) if line.trim().is_empty() => {
            lines.next();
        }
        _ => return Ok(false),
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next()
            .ok_or(ParseError::IncompleteForceSection)?
            .trim();

        let comp_line = lines.next().ok_or(ParseError::IncompleteForceSection)?;
        if !comp_line.contains("Forces of Component") {
            return Err(ParseError::IncompleteForceSection);
        }
        if validate {
            validate_section_component(
                "Forces", type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let force_line = lines.next().ok_or(ParseError::IncompleteForceSection)?;
            let defaults = [0.0, 0.0, 0.0, 0.0, atom_idx as f64];
            let vals = parse_line_of_range_f64(force_line, 4, 5, &defaults)?;
            if validate {
                let (fixed, atom_id) = parse_identity_columns(force_line, "forces")?;
                validate_section_atom_identity("forces", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].fx = Some(vals[0]);
                atom_data[atom_idx].fy = Some(vals[1]);
                atom_data[atom_idx].fz = Some(vals[2]);
            }
            atom_idx += 1;
        }
    }

    Ok(true)
}

/// Parses declared sections from a frame's header metadata.
///
/// If `header.sections` is non-empty (v2 file with `"sections"` key in JSON),
/// parses each declared section in order. Otherwise falls back to legacy
/// blank-separator velocity detection.
pub fn parse_declared_sections<'a, I>(
    lines: &mut Peekable<I>,
    header: &mut FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<(), ParseError>
where
    I: Iterator<Item = &'a str>,
{
    if header.sections.is_empty() && !sections_key_declared(header) {
        // Legacy: try velocity detection via blank separator
        let found = parse_velocity_section(lines, header, atom_data)?;
        if found {
            header.sections.push("velocities".to_string());
        }
    } else {
        for section in header.sections.clone() {
            match section.as_str() {
                "velocities" => {
                    let found = parse_velocity_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteVelocitySection);
                    }
                }
                "forces" => {
                    let found = parse_force_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteForceSection);
                    }
                }
                other => return Err(ParseError::UnknownSection(other.to_string())),
            }
        }
    }
    Ok(())
}

fn sections_key_declared(header: &FrameHeader) -> bool {
    serde_json::from_str::<Value>(&header.prebox_header[1])
        .ok()
        .and_then(|value| {
            value
                .as_object()
                .map(|object| object.contains_key("sections"))
        })
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::iterators::ConFrameIterator;

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
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
                assert_eq!(header.prebox_header[0], "PREBOX1");
                assert_eq!(header.spec_version, 2);
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
        let lines = [
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
    fn test_parse_frame_header_missing_spec_version() {
        let lines = vec![
            "PREBOX1",
            "{}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::MissingSpecVersion
        ));
    }

    #[test]
    fn test_parse_frame_header_legacy_no_json() {
        // A non-JSON line 2 is treated as a legacy (v1) file.
        let lines = vec![
            "PREBOX1",
            "0.0000 TIME",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).unwrap();
        assert_eq!(header.spec_version, 1);
        assert!(header.metadata.is_empty());
    }

    #[test]
    fn test_parse_frame_header_malformed_json() {
        // Line 2 starts with '{' but is not valid JSON -- this IS an error.
        let lines = vec![
            "PREBOX1",
            "{broken json",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidMetadataJson(_)
        ));
    }

    #[test]
    fn test_parse_frame_header_unsupported_version() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":999}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_frame_header(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::UnsupportedSpecVersion(999)
        ));
    }

    #[test]
    fn test_parse_frame_header_extra_metadata_preserved() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"generator\":\"test\"}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "2",
            "1 1",
            "12.011 1.008",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).unwrap();
        assert_eq!(header.spec_version, 2);
        assert_eq!(
            header.metadata.get("generator"),
            Some(&serde_json::Value::String("test".to_string()))
        );
    }

    #[test]
    fn test_parse_frame_header_invalid_natms_per_type() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
            "{\"con_spec_version\":2}",
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
        // With a valid header but truncated atom data, we get IncompleteFrame.
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
            // Missing Component 2 entirely
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_single_frame(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ParseError::IncompleteFrame));
    }

    #[test]
    fn test_parse_single_frame_missing_atom_index_defaults_sequential() {
        // Column 5 (atom_index) is optional; when absent, defaults to sequential.
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
            "5.0 5.0 5.0 0.0",       // No atom_index: defaults to 3
            "6.0940 5.0 5.0 0.0 10", // Explicit atom_index: 10
            "5.5470 5.9499 5.0 0.0", // No atom_index: defaults to 5
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();
        assert_eq!(frame.atom_data.len(), 6);
        // First type: explicit atom_index values
        assert_eq!(frame.atom_data[0].atom_id, 1);
        assert_eq!(frame.atom_data[1].atom_id, 2);
        assert_eq!(frame.atom_data[2].atom_id, 3);
        // Second type: mixed explicit and defaulted
        assert_eq!(frame.atom_data[3].atom_id, 3); // defaulted (global idx 3)
        assert_eq!(frame.atom_data[4].atom_id, 10); // explicit
        assert_eq!(frame.atom_data[5].atom_id, 5); // defaulted (global idx 5)
    }

    #[test]
    fn test_parse_single_frame_too_few_columns_fails() {
        // Only 3 columns (missing fixed_flag too) should still fail.
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
            "C",
            "Coordinates of Component 1",
            "0.0 0.0 0.0", // Only 3 values
        ];
        let mut line_it = lines.iter().copied();
        let result = parse_single_frame(&mut line_it);
        assert!(result.is_err());
        assert!(matches!(
            result.unwrap_err(),
            ParseError::InvalidVectorLength {
                expected: 5,
                found: 3
            }
        ));
    }

    #[test]
    fn test_parse_velocity_section_present() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
        let has_vel = parse_velocity_section(&mut line_it, &frame.header, &mut frame.atom_data)
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
    fn test_validate_true_accepts_matching_section_identity() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
2
1 1
63.546 1.008
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0
H
Coordinates of Component 2
1.0 2.0 3.0 0 1

Cu
Velocities of Component 1
0.1 0.2 0.3 5 0
H
Velocities of Component 2
0.4 0.5 0.6 0 1
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let frame = iter.next().unwrap().unwrap();

        assert!(frame.has_velocities());
        assert_eq!(
            frame
                .header
                .metadata
                .get("validate")
                .and_then(|v| v.as_bool()),
            Some(true)
        );
    }

    #[test]
    fn test_validate_true_rejects_section_atom_id_mismatch() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0

Cu
Velocities of Component 1
0.1 0.2 0.3 5 99
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("atom_id mismatch"));
    }

    #[test]
    fn test_validate_true_rejects_section_symbol_mismatch() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["forces"],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0

H
Forces of Component 1
0.1 0.2 0.3 5 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("symbol mismatch"));
    }

    #[test]
    fn test_validate_absent_allows_legacy_duplicate_identity_mismatch() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"]}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5 0

Cu
Velocities of Component 1
0.1 0.2 0.3 0 99
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let frame = iter.next().unwrap().unwrap();

        assert!(frame.has_velocities());
        assert_eq!(frame.atom_data[0].atom_id, 0);
        assert_eq!(frame.atom_data[0].fixed, [true, false, true]);
    }

    #[test]
    fn test_validate_must_be_boolean_when_present() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"validate\":\"yes\",\"sections\":[]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("validate"));
    }

    #[test]
    fn test_validate_true_requires_sections_key() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"validate\":true}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("sections"));
    }

    #[test]
    fn test_sections_must_be_string_array_when_present() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[\"velocities\",7]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("sections"));
    }

    #[test]
    fn test_validate_true_rejects_non_integer_coordinate_identity_columns() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 5.0 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("fixed_flag"));
    }

    #[test]
    fn test_validate_true_rejects_non_exact_coordinate_label() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates Component 1
0.0 0.0 0.0 5 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("Coordinates of Component 1"));
    }

    #[test]
    fn test_validate_true_rejects_unknown_component_symbol() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":[],"validate":true}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Qq
Coordinates of Component 1
0.0 0.0 0.0 0 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("symbol"));
    }

    #[test]
    fn test_declared_section_must_be_present() {
        let text = r#"
PREBOX1
{"con_spec_version":2,"sections":["velocities"]}
10.0 20.0 30.0
90.0 90.0 90.0
POSTBOX1
POSTBOX2
1
1
63.546
Cu
Coordinates of Component 1
0.0 0.0 0.0 0 0
"#;
        let mut iter = ConFrameIterator::new(text.trim());
        let err = iter.next().unwrap().unwrap_err();

        assert!(matches!(err, ParseError::IncompleteVelocitySection));
    }

    #[test]
    fn test_non_finite_numeric_tokens_are_rejected() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 NaN 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidNumberFormat(_)));
        assert!(err.to_string().contains("finite"));
    }

    #[test]
    fn test_validate_true_rejects_non_physical_cell_geometry() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true}",
            "0.0 20.0 30.0",
            "90.0 180.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("cell"));
    }

    #[test]
    fn test_validate_true_rejects_reserved_metadata_type_mismatch() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true,\"energy\":\"low\"}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();

        assert!(matches!(err, ParseError::InvalidMetadataJson(_)));
        assert!(err.to_string().contains("energy"));
    }

    #[test]
    fn test_parse_velocity_section_absent() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
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
        let has_vel = parse_velocity_section(&mut line_it, &frame.header, &mut frame.atom_data)
            .expect("should succeed with no velocities");
        assert!(!has_vel);
        assert_eq!(frame.atom_data[0].vx, None);
    }

    #[test]
    fn test_parse_line_of_range_f64_exact() {
        let vals = parse_line_of_range_f64("1.0 2.0 3.0 0.0 42", 4, 5, &[0.0; 5]).unwrap();
        assert_eq!(vals, vec![1.0, 2.0, 3.0, 0.0, 42.0]);
    }

    #[test]
    fn test_parse_line_of_range_f64_padded() {
        let defaults = [0.0, 0.0, 0.0, 0.0, 99.0];
        let vals = parse_line_of_range_f64("1.0 2.0 3.0 0.0", 4, 5, &defaults).unwrap();
        assert_eq!(vals, vec![1.0, 2.0, 3.0, 0.0, 99.0]);
    }

    #[test]
    fn test_parse_line_of_range_f64_too_few() {
        let result = parse_line_of_range_f64("1.0 2.0 3.0", 4, 5, &[0.0; 5]);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_line_of_range_f64_too_many() {
        let result = parse_line_of_range_f64("1.0 2.0 3.0 0.0 5.0 6.0", 4, 5, &[0.0; 5]);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_all_four_column_lines() {
        // All atom lines have only 4 columns; atom_index defaults to sequential.
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2}",
            "10.0 10.0 10.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "3",
            "12.011",
            "C",
            "Coordinates of Component 1",
            "0.0 0.0 0.0 0",
            "1.0 0.0 0.0 0",
            "2.0 0.0 0.0 1",
        ];
        let mut line_it = lines.iter().copied();
        let frame = parse_single_frame(&mut line_it).unwrap();
        assert_eq!(frame.atom_data[0].atom_id, 0);
        assert_eq!(frame.atom_data[1].atom_id, 1);
        assert_eq!(frame.atom_data[2].atom_id, 2);
        assert!(frame.atom_data[2].is_fixed());
    }
}
