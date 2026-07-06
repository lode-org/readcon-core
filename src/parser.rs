use crate::error::ParseError;
use crate::helpers::symbol_to_atomic_number;
use crate::types::{
    AtomDatum, ConFrame, FrameHeader, PreboxHeader, SECTION_ENERGIES, SECTION_FORCES,
    SECTION_VELOCITIES,
    decode_fixed_bitmask, meta,
};
use serde_json::Value;
use std::collections::BTreeMap;
use std::iter::Peekable;
use std::sync::Arc;

/// Line source with peek for section detection (blank-line separators).
///
/// Implemented by the memchr cursor on the hot iterator path and by
/// `Peekable<I>` for tests / ad-hoc callers.
pub trait LineStream<'a> {
    fn next_line(&mut self) -> Option<&'a str>;
    fn peek_line(&mut self) -> Option<&'a str>;
}

impl<'a, I> LineStream<'a> for Peekable<I>
where
    I: Iterator<Item = &'a str>,
{
    #[inline]
    fn next_line(&mut self) -> Option<&'a str> {
        Iterator::next(self)
    }
    #[inline]
    fn peek_line(&mut self) -> Option<&'a str> {
        Peekable::peek(self).copied()
    }
}

/// Hot-path: parse up to 5 whitespace-separated f64s into a stack buffer.
/// Returns count of tokens actually present (before padding).
/// Pads `out[found..max]` from `defaults` when `found < max` and `found >= min`.
///
/// Single-pass over the line bytes: skip ASCII whitespace, then
/// [`fast_float2::parse_partial`] (Eisel–Lemire / SIMD-class decimal kernel)
/// with a token-boundary check. No `SplitWhitespace`, no per-token `&str`,
/// no heap `Vec`. Prefer this over allocating [`parse_line_of_n_f64`] on atom lines.
#[inline]
pub fn parse_line_of_range_f64_stack(
    line: &str,
    min: usize,
    max: usize,
    defaults: &[f64],
    out: &mut [f64; 5],
) -> Result<usize, ParseError> {
    debug_assert!(max <= 5 && min <= max && defaults.len() >= max);
    let bytes = line.as_bytes();
    let n = bytes.len();
    let mut i = 0usize;
    let mut found = 0usize;
    while found < max {
        while i < n && bytes[i].is_ascii_whitespace() {
            i += 1;
        }
        if i >= n {
            break;
        }
        let (val, consumed) = fast_float2::parse_partial::<f64, _>(&bytes[i..]).map_err(|_| {
            // Best-effort token for the error message (up to next whitespace).
            let end = bytes[i..]
                .iter()
                .position(|b| b.is_ascii_whitespace())
                .map(|k| i + k)
                .unwrap_or(n);
            let token = String::from_utf8_lossy(&bytes[i..end]);
            ParseError::InvalidNumberFormat(format!("invalid float: {token}"))
        })?;
        let next = i + consumed;
        // Reject partial tokens like "1.2abc" (must end at whitespace or EOS).
        if next < n && !bytes[next].is_ascii_whitespace() {
            let end = bytes[i..]
                .iter()
                .position(|b| b.is_ascii_whitespace())
                .map(|k| i + k)
                .unwrap_or(n);
            let token = String::from_utf8_lossy(&bytes[i..end]);
            return Err(ParseError::InvalidNumberFormat(format!(
                "invalid float: {token}"
            )));
        }
        out[found] = val;
        found += 1;
        i = next;
    }
    while i < n && bytes[i].is_ascii_whitespace() {
        i += 1;
    }
    // Reject trailing extra tokens (same contract as the old split loop).
    if i < n {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found: found + 1,
        });
    }
    if found < min || found > max {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found,
        });
    }
    while found < max {
        out[found] = defaults[found];
        found += 1;
    }
    Ok(found)
}

/// Parses a line of whitespace-separated f64 values using fast-float2.
///
/// This is the hot-path parser for coordinate and velocity lines. It uses
/// `fast_float2::parse` instead of `str::parse::<f64>()` for better throughput
/// on the numeric-heavy atom data lines. Fixed-width atom lines use
/// [`parse_line_of_range_f64_stack`] to avoid a heap `Vec` per line.
///
/// # Arguments
///
/// * `line` - A string slice representing a single line of data.
/// * `n` - The exact number of f64 values expected on the line.
pub fn parse_line_of_n_f64(line: &str, n: usize) -> Result<Vec<f64>, ParseError> {
    if n <= 5 {
        let defaults = [0.0f64; 5];
        let mut buf = [0.0f64; 5];
        parse_line_of_range_f64_stack(line, n, n, &defaults, &mut buf)?;
        return Ok(buf[..n].to_vec());
    }
    let mut values = Vec::with_capacity(n);
    for token in line.split_ascii_whitespace() {
        let val: f64 = fast_float2::parse(token)
            .map_err(|_| ParseError::InvalidNumberFormat(format!("invalid float: {token}")))?;
        values.push(val);
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
/// Prefer [`parse_line_of_range_f64_stack`] on the atom hot path (`max <= 5`).
pub fn parse_line_of_range_f64(
    line: &str,
    min: usize,
    max: usize,
    defaults: &[f64],
) -> Result<Vec<f64>, ParseError> {
    if max <= 5 {
        let mut buf = [0.0f64; 5];
        parse_line_of_range_f64_stack(line, min, max, defaults, &mut buf)?;
        return Ok(buf[..max].to_vec());
    }
    let mut values = Vec::with_capacity(max);
    for token in line.split_ascii_whitespace() {
        let val: f64 = fast_float2::parse(token)
            .map_err(|_| ParseError::InvalidNumberFormat(format!("invalid float: {token}")))?;
        values.push(val);
    }
    if values.len() < min || values.len() > max {
        return Err(ParseError::InvalidVectorLength {
            expected: max,
            found: values.len(),
        });
    }
    while values.len() < max {
        let idx = values.len();
        values.push(defaults[idx]);
    }
    Ok(values)
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

/// Validates a parsed metadata JSON object against the spec v2 schema.
///
/// Type-checks the `validate` and `sections` keys, then runs per-key
/// schema checks for the recommended metadata keys. Used by the
/// builder/Python `set_metadata_json` paths to fail fast on malformed
/// input, and by the parser when the file requested strict validation
/// via `"validate": true`.
pub fn validate_metadata_schema(
    json_obj: &serde_json::Map<String, Value>,
) -> Result<(), ParseError> {
    let strict_requested = match json_obj.get(meta::VALIDATE) {
        Some(Value::Bool(b)) => *b,
        Some(_) => return Err(metadata_json_error("validate must be a boolean")),
        None => false,
    };

    match json_obj.get(meta::SECTIONS) {
        Some(Value::Array(values)) => {
            if values.iter().any(|entry| !entry.is_string()) {
                return Err(metadata_json_error("sections must be an array of strings"));
            }
        }
        Some(_) => return Err(metadata_json_error("sections must be an array of strings")),
        None if strict_requested => {
            return Err(metadata_json_error(
                "validate=true requires a sections array, even when empty",
            ));
        }
        None => {}
    }

    for (key, value) in json_obj {
        match key.as_str() {
            meta::CON_SPEC_VERSION | meta::SECTIONS | meta::VALIDATE => {}
            meta::ENERGY
            | meta::TIME
            | meta::TIMESTEP
            | meta::CONVERGENCE_FMAX
            | meta::CONVERGENCE_ENERGY
            | meta::FMAX => validate_metadata_number(key, value)?,
            meta::FRAME_INDEX | meta::NEB_BEAD | meta::NEB_BAND => {
                validate_metadata_integer(key, value)?
            }
            meta::GENERATOR if !value.is_string() => {
                return Err(metadata_json_error("generator must be a string"));
            }
            meta::GENERATOR => {}
            meta::UNITS | meta::POTENTIAL if !value.is_object() => {
                return Err(metadata_json_error(format!("{key} must be an object")));
            }
            meta::POTENTIAL => {
                if let Some(potential_type) = value.get("type")
                    && !potential_type.is_string()
                {
                    return Err(metadata_json_error("potential.type must be a string"));
                }
            }
            meta::UNITS => {
                // Full v3 checks (required keys) run when con_spec_version >= 3.
            }
            meta::PBC => validate_pbc_metadata(value)?,
            meta::BONDS => validate_bonds_metadata(value)?,
            meta::LATTICE_VECTORS => validate_lattice_vectors_metadata(value)?,
            meta::CONVERGED if !value.is_boolean() => {
                return Err(metadata_json_error("converged must be a boolean"));
            }
            meta::CONVERGED => {}
            _ => {}
        }
    }

    Ok(())
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

/// Validate optional `bonds` frame topology metadata.
///
/// Each element is either a length-2 non-negative integer pair `[i, j]` or an
/// object `{"i": i, "j": j, "order"?: integer}`. Indices are 0-based into
/// `atom_data` order (parser does not yet know atom count at metadata time;
/// bounds are enforced when projecting to chemfiles / selection).
fn validate_bonds_metadata(value: &Value) -> Result<(), ParseError> {
    let Some(items) = value.as_array() else {
        return Err(metadata_json_error("bonds must be an array"));
    };
    for (idx, item) in items.iter().enumerate() {
        if let Some(pair) = item.as_array() {
            if pair.len() != 2 {
                return Err(metadata_json_error(format!(
                    "bonds[{idx}] pair must have exactly two indices"
                )));
            }
            for (k, entry) in pair.iter().enumerate() {
                let Some(n) = entry.as_u64() else {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}][{k}] must be a non-negative integer"
                    )));
                };
                if n > u32::MAX as u64 {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}][{k}] index exceeds u32"
                    )));
                }
            }
            continue;
        }
        if let Some(obj) = item.as_object() {
            for key in ["i", "j"] {
                let Some(entry) = obj.get(key) else {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}] object must include \"{key}\""
                    )));
                };
                let Some(n) = entry.as_u64() else {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}].{key} must be a non-negative integer"
                    )));
                };
                if n > u32::MAX as u64 {
                    return Err(metadata_json_error(format!(
                        "bonds[{idx}].{key} index exceeds u32"
                    )));
                }
            }
            if let Some(order) = obj.get("order")
                && order.as_i64().is_none()
            {
                return Err(metadata_json_error(format!(
                    "bonds[{idx}].order must be an integer when present"
                )));
            }
            continue;
        }
        return Err(metadata_json_error(format!(
            "bonds[{idx}] must be [i, j] or {{\"i\": i, \"j\": j, \"order\"?: ...}}"
        )));
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
    let (spec_version, metadata, sections, validate, sections_declared) = if trimmed.starts_with('{') {
        let json_val: serde_json::Value = serde_json::from_str(trimmed)
            .map_err(|e| ParseError::InvalidMetadataJson(e.to_string()))?;
        let json_obj = json_val
            .as_object()
            .ok_or_else(|| ParseError::InvalidMetadataJson("expected a JSON object".to_string()))?;
        let ver = json_obj
            .get(meta::CON_SPEC_VERSION)
            .and_then(|v| v.as_u64())
            .ok_or(ParseError::MissingSpecVersion)? as u32;
        if ver > crate::CON_SPEC_VERSION {
            return Err(ParseError::UnsupportedSpecVersion(ver));
        }
        if ver >= 3 {
            match json_obj.get(meta::UNITS) {
                Some(u) => crate::units::validate_v3_units_metadata(u).map_err(|e| {
                    ParseError::ValidationError(format!("v3 units: {e}"))
                })?,
                None => {
                    return Err(ParseError::ValidationError(
                        "con_spec_version >= 3 requires metadata \"units\" with length and energy"
                            .into(),
                    ));
                }
            }
        }

        // Single pass over the JSON object: collect sections, capture the
        // validate flag, copy the rest into metadata. Folds the previous
        // pre-extract get(validate) + re-iterate pattern into one walk.
        let mut sections: Vec<String> = Vec::new();
        let mut metadata = BTreeMap::new();
        let mut sections_declared = false;
        let mut validate = false;
        for (k, v) in json_obj {
            match k.as_str() {
                meta::CON_SPEC_VERSION => {}
                meta::SECTIONS => {
                    sections_declared = true;
                    let arr = v.as_array().ok_or_else(|| {
                        metadata_json_error("sections must be an array of strings")
                    })?;
                    sections.reserve(arr.len());
                    for entry in arr {
                        let s = entry.as_str().ok_or_else(|| {
                            metadata_json_error("sections must be an array of strings")
                        })?;
                        sections.push(s.to_string());
                    }
                }
                meta::VALIDATE => {
                    validate = match v {
                        Value::Bool(b) => *b,
                        _ => return Err(metadata_json_error("validate must be a boolean")),
                    };
                    metadata.insert(k.clone(), v.clone());
                }
                _ => {
                    metadata.insert(k.clone(), v.clone());
                }
            }
        }

        // Strict-mode schema check fires only when the file requested
        // it. Hot-path parses (validate=false) skip the per-key match.
        if validate {
            validate_metadata_schema(json_obj)?;
        }

        (ver, metadata, sections, validate, sections_declared)
    } else {
        // Legacy file: no JSON metadata line.
        (1_u32, BTreeMap::new(), Vec::new(), false, false)
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
        prebox_header: PreboxHeader {
            user: prebox1,
            metadata_line: prebox2,
        },
        boxl: boxl_vec.try_into().unwrap(),
        angles: angles_vec.try_into().unwrap(),
        postbox_header: [postbox1, postbox2],
        natm_types,
        natms_per_type,
        masses_per_type,
        spec_version,
        metadata,
        sections,
        strict_validation: validate,
        sections_declared,
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
    let validate = header.strict_validation;
    let total_atoms: usize = header.natms_per_type.iter().sum();
    let mut atom_data = Vec::with_capacity(total_atoms);
    // SoA positions: default f64 fills a flat `Vec` then one Arc wrap (profile:
    // per-row ArcArray mut checks were a real cost on multi-atom parse).
    use crate::storage_dtype::{ElementKind, FloatArray2, StorageDtypes};
    let dt = StorageDtypes::from_metadata(&header.metadata).unwrap_or_default();
    let f64_positions = dt.positions == ElementKind::Float64;
    let mut pos_flat = if f64_positions {
        vec![0.0f64; total_atoms.saturating_mul(3)]
    } else {
        Vec::new()
    };
    let mut positions_other = if f64_positions {
        None
    } else {
        Some(FloatArray2::zeros(dt.positions, total_atoms, 3))
    };

    let mut global_atom_idx: u64 = 0;
    let mut atom_i = 0usize;
    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        // Allocate the per-component Arc<str> directly from the trimmed
        // line; going through a String intermediate would add a second
        // allocation and copy for no semantic gain.
        let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
        let symbol: Arc<str> = Arc::from(symbol_line.trim());
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol.as_ref(), coord_label)?;
        }
        for _ in 0..*num_atoms {
            let coord_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            // Column 5 (atom_index) is optional; defaults to sequential index.
            let defaults = [0.0, 0.0, 0.0, 0.0, global_atom_idx as f64];
            let mut vals = [0.0f64; 5];
            parse_line_of_range_f64_stack(coord_line, 4, 5, &defaults, &mut vals)?;
            let (fixed, atom_id) = if validate {
                parse_identity_columns(coord_line, "coordinate", 3, 4, 5)?
            } else {
                (decode_fixed_bitmask(vals[3] as u8), vals[4] as u64)
            };
            let xyz = [vals[0], vals[1], vals[2]];
            if f64_positions {
                let o = atom_i * 3;
                pos_flat[o] = xyz[0];
                pos_flat[o + 1] = xyz[1];
                pos_flat[o + 2] = xyz[2];
            } else if let Some(ref mut pos) = positions_other {
                pos.set_f64_row(atom_i, xyz);
            }
            atom_data.push(AtomDatum {
                // This is a cheap reference-count increment, not a full string clone.
                symbol: Arc::clone(&symbol),
                x: xyz[0],
                y: xyz[1],
                z: xyz[2],
                fixed,
                atom_id,
                velocity: None,
                force: None,
                energy: None,
            });
            global_atom_idx += 1;
            atom_i += 1;
        }
    }
    let positions = if f64_positions {
        FloatArray2::from_f64_row_major(total_atoms, 3, pos_flat)
    } else {
        positions_other.expect("non-f64 positions allocated")
    };
    // Sections still attach to AoS; assemble uses prefilled positions (no second pos pass).
    Ok(crate::types::con_frame_from_atom_data_with_positions(
        header, atom_data, positions,
    ))
}

/// Skip optional velocity/force/energy blocks after the coordinate section without
/// materializing section data (structure-only walk).
fn skip_optional_sections<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
) -> Result<(), ParseError> {
    let total_atoms: usize = header.natms_per_type.iter().sum();
    let block_lines = total_atoms + header.natm_types.saturating_mul(2);

    if !header.sections.is_empty() {
        // Declared section list: each is blank separator + same-shaped block.
        for _section in &header.sections {
            match lines.peek_line() {
                Some(line) if line.trim().is_empty() => {
                    let _ = lines.next_line();
                }
                _ => return Err(ParseError::IncompleteFrame),
            }
            for _ in 0..block_lines {
                lines.next_line().ok_or(ParseError::IncompleteFrame)?;
            }
        }
    } else {
        // Legacy: zero or more blank-separator section blocks (e.g. .convel velocities).
        loop {
            match lines.peek_line() {
                Some(line) if line.trim().is_empty() => {
                    let _ = lines.next_line();
                    for _ in 0..block_lines {
                        lines.next_line().ok_or(ParseError::IncompleteFrame)?;
                    }
                }
                _ => break,
            }
        }
    }
    Ok(())
}

/// Parse one frame's coordinates only: owned `(N, 3)` f64 matrix, **no**
/// [`AtomDatum`] / symbol Arc / mass-id assembly.
///
/// Shares the same float kernel as [`parse_single_frame`]. Optional sections are
/// structure-skipped (not stored). Prefer for coordinate-only multi-frame loads;
/// use [`parse_single_frame`] when full-frame fidelity is required.
pub fn parse_single_frame_positions<'a, L>(
    lines: &mut L,
) -> Result<ndarray::Array2<f64>, ParseError>
where
    L: Iterator<Item = &'a str> + LineStream<'a>,
{
    let header = parse_frame_header(lines)?;
    let validate = header.strict_validation;
    let total_atoms: usize = header.natms_per_type.iter().sum();
    let mut pos_flat = vec![0.0f64; total_atoms.saturating_mul(3)];
    let mut global_atom_idx: u64 = 0;
    let mut atom_i = 0usize;

    for (type_idx, num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
        let symbol = symbol_line.trim();
        let coord_label = lines.next().ok_or(ParseError::IncompleteFrame)?;
        if validate {
            validate_coordinate_component(type_idx, symbol, coord_label)?;
        }
        for _ in 0..*num_atoms {
            let coord_line = lines.next().ok_or(ParseError::IncompleteFrame)?;
            let defaults = [0.0, 0.0, 0.0, 0.0, global_atom_idx as f64];
            let mut vals = [0.0f64; 5];
            parse_line_of_range_f64_stack(coord_line, 4, 5, &defaults, &mut vals)?;
            if validate {
                let _ = parse_identity_columns(coord_line, "coordinate", 3, 4, 5)?;
            }
            let o = atom_i * 3;
            pos_flat[o] = vals[0];
            pos_flat[o + 1] = vals[1];
            pos_flat[o + 2] = vals[2];
            global_atom_idx += 1;
            atom_i += 1;
        }
    }
    skip_optional_sections(lines, &header)?;
    ndarray::Array2::from_shape_vec((total_atoms, 3), pos_flat).map_err(|e| {
        ParseError::ValidationError(format!("positions shape error: {e}"))
    })
}

fn validate_header_geometry(
    boxl: &[f64],
    angles: &[f64],
    natm_types: usize,
    natms_per_type: &[usize],
) -> Result<(), ParseError> {
    if boxl.iter().any(|length| !length.is_finite() || *length <= 0.0)
        || angles
            .iter()
            .any(|angle| !angle.is_finite() || *angle <= 0.0 || *angle >= 180.0)
    {
        return Err(ParseError::ValidationError(
            "cell geometry must have positive lengths and angles between 0 and 180 degrees"
                .to_string(),
        ));
    }
    if natm_types == 0 || natms_per_type.contains(&0) {
        return Err(ParseError::ValidationError(
            "atom counts must contain at least one atom per component".to_string(),
        ));
    }
    Ok(())
}

fn validate_masses(masses_per_type: &[f64]) -> Result<(), ParseError> {
    if masses_per_type
        .iter()
        .any(|mass| !mass.is_finite() || *mass <= 0.0)
    {
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

/// Strict-validation parser for the per-row identity columns
/// (fixed bitmask + atom_id) used by every section type.
///
/// `n_cols` is the total whitespace-separated column count expected on
/// the row in strict mode, and `(fixed_idx, atom_id_idx)` are the
/// 0-based positions of the fixed bitmask and atom_id columns inside
/// that layout. Each section calls in with its own values:
///
/// - coordinates / velocities / forces: 5 cols, fixed=3, atom_id=4
/// - energies: 3 cols, fixed=1, atom_id=2
///
/// String-based parsing on purpose: strict v2 mode rejects values that
/// are not in the canonical integer form (e.g. `5.0` for a bitmask),
/// which an f64 round-trip would silently accept.
fn parse_identity_columns(
    line: &str,
    row_kind: &str,
    fixed_idx: usize,
    atom_id_idx: usize,
    n_cols: usize,
) -> Result<([bool; 3], u64), ParseError> {
    let columns = line.split_ascii_whitespace().collect::<Vec<_>>();
    if columns.len() != n_cols {
        return Err(ParseError::ValidationError(format!(
            "{row_kind} rows require {n_cols} columns including fixed_flag and atom_id in validate mode"
        )));
    }
    let fixed_flag = columns[fixed_idx].parse::<u8>().map_err(|_| {
        ParseError::ValidationError(format!("{row_kind} fixed_flag must be an integer bitmask"))
    })?;
    if fixed_flag > 7 {
        return Err(ParseError::ValidationError(format!(
            "{row_kind} fixed_flag must be between 0 and 7"
        )));
    }
    let atom_id = columns[atom_id_idx].parse::<u64>().map_err(|_| {
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
pub fn parse_velocity_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    let validate = header.strict_validation;
    // Peek at the next line to check for blank separator
    match lines.peek_line() {
        Some(line) if line.trim().is_empty() => {
            // Consume the blank separator
            lines.next_line();
        }
        _ => return Ok(false),
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        // Symbol line
        let symbol = lines
            .next_line()
            .ok_or(ParseError::IncompleteVelocitySection)?
            .trim();

        // "Velocities of Component N" line
        let comp_line = lines.next_line().ok_or(ParseError::IncompleteVelocitySection)?;
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
            let vel_line = lines.next_line().ok_or(ParseError::IncompleteVelocitySection)?;
            // Column 5 (atom_index) is optional in velocity lines too.
            let defaults = [0.0, 0.0, 0.0, 0.0, atom_idx as f64];
            let mut vals = [0.0f64; 5];
            parse_line_of_range_f64_stack(vel_line, 4, 5, &defaults, &mut vals)?;
            if validate {
                let (fixed, atom_id) =
                    parse_identity_columns(vel_line, "velocities", 3, 4, 5)?;
                validate_section_atom_identity("velocities", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].velocity = Some([vals[0], vals[1], vals[2]]);
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
pub fn parse_force_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    let validate = header.strict_validation;
    // Peek at the next line to check for blank separator
    match lines.peek_line() {
        Some(line) if line.trim().is_empty() => {
            lines.next_line();
        }
        _ => return Ok(false),
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or(ParseError::IncompleteForceSection)?
            .trim();

        let comp_line = lines.next_line().ok_or(ParseError::IncompleteForceSection)?;
        if !comp_line.contains("Forces of Component") {
            return Err(ParseError::IncompleteForceSection);
        }
        if validate {
            validate_section_component(
                "Forces", type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let force_line = lines.next_line().ok_or(ParseError::IncompleteForceSection)?;
            let defaults = [0.0, 0.0, 0.0, 0.0, atom_idx as f64];
            let mut vals = [0.0f64; 5];
            parse_line_of_range_f64_stack(force_line, 4, 5, &defaults, &mut vals)?;
            if validate {
                let (fixed, atom_id) =
                    parse_identity_columns(force_line, "forces", 3, 4, 5)?;
                validate_section_atom_identity("forces", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].force = Some([vals[0], vals[1], vals[2]]);
            }
            atom_idx += 1;
        }
    }

    Ok(true)
}

/// Attempts to parse an energies section following coordinate (and optional
/// velocity / force) blocks.
///
/// Energy sections mirror force sections but with one scalar per atom:
/// blank separator, then per-component blocks of (symbol, "Energies of
/// Component N", and atom lines `e fixed_flag atom_id`). The two
/// trailing identity columns are optional and used only for strict
/// validation; in non-strict mode any whitespace after the energy is
/// ignored.
///
/// Returns `Ok(true)` if energies were found and parsed, `Ok(false)`
/// otherwise.
pub fn parse_energy_section<'a>(
    lines: &mut impl LineStream<'a>,
    header: &FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<bool, ParseError> {
    let validate = header.strict_validation;
    match lines.peek_line() {
        Some(line) if line.trim().is_empty() => {
            lines.next_line();
        }
        _ => return Ok(false),
    }

    let mut atom_idx: usize = 0;
    for (type_idx, &num_atoms) in header.natms_per_type.iter().enumerate() {
        let symbol = lines
            .next_line()
            .ok_or(ParseError::IncompleteEnergySection)?
            .trim();

        let comp_line = lines.next_line().ok_or(ParseError::IncompleteEnergySection)?;
        if !comp_line.contains("Energies of Component") {
            return Err(ParseError::IncompleteEnergySection);
        }
        if validate {
            validate_section_component(
                "Energies", type_idx, atom_idx, symbol, comp_line, header, atom_data,
            )?;
        }

        for _ in 0..num_atoms {
            let energy_line = lines.next_line().ok_or(ParseError::IncompleteEnergySection)?;
            // Single energy column, plus optional fixed flag and atom_id
            // for round-trip identity checks.
            let defaults = [0.0, 0.0, atom_idx as f64];
            let vals = parse_line_of_range_f64(energy_line, 1, 3, &defaults)?;
            if validate {
                let (fixed, atom_id) =
                    parse_identity_columns(energy_line, "energies", 1, 2, 3)?;
                validate_section_atom_identity("energies", atom_idx, fixed, atom_id, atom_data)?;
            }
            if atom_idx < atom_data.len() {
                atom_data[atom_idx].energy = Some(vals[0]);
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
pub fn parse_declared_sections<'a>(
    lines: &mut impl LineStream<'a>,
    header: &mut FrameHeader,
    atom_data: &mut [AtomDatum],
) -> Result<usize, ParseError> {
    let mut applied = 0usize;
    if !header.sections_declared && header.sections.is_empty() {
        // Legacy: try velocity detection via blank separator
        let found = parse_velocity_section(lines, header, atom_data)?;
        if found {
            header.sections.push(SECTION_VELOCITIES.into());
            applied = 1;
        }
    } else {
        let sections = std::mem::take(&mut header.sections);
        for section in &sections {
            match section.as_str() {
                SECTION_VELOCITIES => {
                    let found = parse_velocity_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteVelocitySection);
                    }
                    applied += 1;
                }
                SECTION_FORCES => {
                    let found = parse_force_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteForceSection);
                    }
                    applied += 1;
                }
                SECTION_ENERGIES => {
                    let found = parse_energy_section(lines, header, atom_data)?;
                    if !found {
                        return Err(ParseError::IncompleteEnergySection);
                    }
                    applied += 1;
                }
                other => return Err(ParseError::UnknownSection(other.to_string())),
            }
        }
        header.sections = sections;
    }
    Ok(applied)
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
                assert_eq!(header.prebox_header.user, "PREBOX1");
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
    fn test_v3_missing_units_rejected() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":3}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "1.0",
        ];
        let mut line_it = lines.iter().copied();
        let err = parse_frame_header(&mut line_it).unwrap_err();
        let msg = err.to_string();
        assert!(
            msg.contains("units") || msg.contains("v3"),
            "expected units error, got {msg}"
        );
    }

    #[test]
    fn test_v3_invalid_units_rejected() {
        let lines = vec![
            "PREBOX1",
            r#"{"con_spec_version":3,"units":{"length":"eV","energy":"angstrom"}}"#,
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "1.0",
        ];
        let mut line_it = lines.iter().copied();
        assert!(parse_frame_header(&mut line_it).is_err());
    }

    #[test]
    fn test_v3_valid_units_exposes_length_energy() {
        let lines = vec![
            "PREBOX1",
            r#"{"con_spec_version":3,"units":{"length":"angstrom","energy":"eV","mass":"amu","time":"fs"}}"#,
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "1.0",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).unwrap();
        assert_eq!(header.spec_version, 3);
        assert_eq!(header.length_unit(), Some("angstrom"));
        assert_eq!(header.energy_unit(), Some("eV"));
        let f = header.conversion_factor_to("length", "nm").unwrap();
        assert!((f - 0.1).abs() < 1e-12);
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
        assert_eq!(frame.atom_data[0].velocity, Some([0.1, 0.2, 0.3]));
        assert_eq!(frame.atom_data[1].velocity, Some([0.4, 0.5, 0.6]));
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
    fn test_non_finite_cell_geometry_rejected_in_strict_mode() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true}",
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

        assert!(matches!(err, ParseError::ValidationError(_)));
        assert!(err.to_string().contains("cell"));
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
    fn test_validate_true_rejects_malformed_bonds() {
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"sections\":[],\"validate\":true,\"bonds\":[[0]]}",
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
        assert!(err.to_string().contains("bonds"));
    }

    #[test]
    fn test_bonds_metadata_round_trip_in_header() {
        use crate::types::{meta, Bond};
        let lines = vec![
            "PREBOX1",
            "{\"con_spec_version\":2,\"bonds\":[[0,1],{\"i\":0,\"j\":2,\"order\":1}]}",
            "10.0 20.0 30.0",
            "90.0 90.0 90.0",
            "POSTBOX1",
            "POSTBOX2",
            "1",
            "1",
            "12.011",
        ];
        let mut line_it = lines.iter().copied();
        let header = parse_frame_header(&mut line_it).expect("header");
        let bonds = header.bonds();
        assert_eq!(bonds.len(), 2);
        assert_eq!(bonds[0], Bond::new(0, 1));
        assert_eq!(bonds[1].i, 0);
        assert_eq!(bonds[1].j, 2);
        assert_eq!(bonds[1].order, Some(1));
        assert!(header.metadata.contains_key(meta::BONDS));
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
        assert_eq!(frame.atom_data[0].velocity, None);
    }

    #[test]
    fn test_parse_line_of_range_f64_exact() {
        let vals = parse_line_of_range_f64("1.0 2.0 3.0 0.0 42", 4, 5, &[0.0; 5]).unwrap();
        assert_eq!(vals, vec![1.0, 2.0, 3.0, 0.0, 42.0]);
    }

    #[test]
    fn test_byte_scan_stack_parses_realistic_coord_line() {
        // Typical CON atom line: x y z fixed_mask [atom_id]
        let line = "   0.63939999999999997    0.90449999999999997   -0.00009999999999977 1    0";
        let defaults = [0.0, 0.0, 0.0, 0.0, 99.0];
        let mut buf = [0.0f64; 5];
        let n = parse_line_of_range_f64_stack(line, 4, 5, &defaults, &mut buf).unwrap();
        assert_eq!(n, 5);
        assert!((buf[0] - 0.6394).abs() < 1e-4);
        assert!((buf[1] - 0.9045).abs() < 1e-4);
        assert_eq!(buf[3] as u8, 1);
        assert_eq!(buf[4] as u64, 0);
        // trailing junk must error
        let bad = "1.0 2.0 3.0 1 0 EXTRA";
        assert!(parse_line_of_range_f64_stack(bad, 4, 5, &defaults, &mut buf).is_err());
        // partial non-boundary token must error
        let glued = "1.0 2.0 3.0abc 1 0";
        assert!(parse_line_of_range_f64_stack(glued, 4, 5, &defaults, &mut buf).is_err());
    }

    #[test]
    fn test_parse_line_of_range_f64_stack_matches_vec_api() {
        let defaults = [0.0, 0.0, 0.0, 0.0, 7.0];
        let line = "1.0 2.0 3.0 0.0";
        let mut buf = [0.0f64; 5];
        parse_line_of_range_f64_stack(line, 4, 5, &defaults, &mut buf).unwrap();
        let via_vec = parse_line_of_range_f64(line, 4, 5, &defaults).unwrap();
        assert_eq!(&buf[..5], via_vec.as_slice());
        assert_eq!(buf[4], 7.0);
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
