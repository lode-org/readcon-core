//! Unit expressions and conversion (metatomic-inspired, SI dimensional analysis).
//!
//! Supports named base units and simple products/quotients with `*`, `/`, `^`,
//! and parentheses (case-sensitive). `unit_conversion_factor(from, to)` returns
//! the multiplier `x_to = factor * x_from` when dimensions match.

use crate::error::ParseError;

/// Physical dimension exponents: L, T, M, Q (charge), Θ (temperature).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Dimension {
    pub exponents: [f64; 5],
}

impl Dimension {
    pub const ZERO: Self = Self {
        exponents: [0.0; 5],
    };
    pub const LENGTH: Self = Self {
        exponents: [1.0, 0.0, 0.0, 0.0, 0.0],
    };
    pub const TIME: Self = Self {
        exponents: [0.0, 1.0, 0.0, 0.0, 0.0],
    };
    pub const MASS: Self = Self {
        exponents: [0.0, 0.0, 1.0, 0.0, 0.0],
    };
    pub const CHARGE: Self = Self {
        exponents: [0.0, 0.0, 0.0, 1.0, 0.0],
    };

    fn mul(self, other: Self) -> Self {
        let mut e = [0.0; 5];
        for (slot, (left, right)) in e
            .iter_mut()
            .zip(self.exponents.iter().zip(other.exponents.iter()))
        {
            *slot = left + right;
        }
        Self { exponents: e }
    }

    fn div(self, other: Self) -> Self {
        let mut e = [0.0; 5];
        for (slot, (left, right)) in e
            .iter_mut()
            .zip(self.exponents.iter().zip(other.exponents.iter()))
        {
            *slot = left - right;
        }
        Self { exponents: e }
    }

    fn pow(self, p: f64) -> Self {
        let mut e = [0.0; 5];
        for (slot, exp) in e.iter_mut().zip(self.exponents.iter()) {
            *slot = exp * p;
        }
        Self { exponents: e }
    }

    fn compatible(self, other: Self) -> bool {
        self.exponents
            .iter()
            .zip(other.exponents.iter())
            .all(|(a, b)| (a - b).abs() < 1e-9)
    }
}

/// Parsed unit: SI scale factor (value in SI = factor * value_in_unit) and dimensions.
#[derive(Clone, Copy, Debug)]
struct UnitValue {
    /// Multiply quantity in this unit by `si_factor` to get SI.
    si_factor: f64,
    dim: Dimension,
}

/// M L^2 T^-2. Same exponents as `MASS * LENGTH^2 / TIME^2`.
const ENERGY: Dimension = Dimension {
    exponents: [2.0, -2.0, 1.0, 0.0, 0.0],
};

struct BaseUnit {
    name: &'static str,
    value: UnitValue,
}

const fn unit(si_factor: f64, dim: Dimension) -> UnitValue {
    UnitValue { si_factor, dim }
}

/// CODATA 2018 values. CON-units.18 fixes bohr and hartree to these
/// published decimal literals rather than values derived from rounded inputs.
const CODATA2018_BOHR_M: f64 = 5.291_772_109_03e-11;
const CODATA2018_AMU_KG: f64 = metrology::AMU;
const CODATA2018_HARTREE_J: f64 = 4.359_744_722_207_1e-18;
const CODATA2018_ELEMENTARY: f64 = metrology::E_CHARGE;
const CODATA2018_AVOGADRO: f64 = metrology::N_A;
/// CON-units.18 writes these decimals. A product of the elementary charge
/// and a power of ten is a different binary64 value.
const MEV_J: f64 = 1.602_176_634e-22;
const MEGA_EV_J: f64 = 1.602_176_634e-13;
/// Thermochemical kilocalorie, exactly 4184 joule. Not a CODATA value.
const KCAL_THERMOCHEMICAL_J: f64 = 4184.0;

/// Accepted spellings, sorted for binary search. `MeV` and `meV` are different
/// names. There is no case fold (CON-units.16).
const BASE_UNITS: &[BaseUnit] = &[
    BaseUnit {
        name: "A",
        value: unit(1e-10, Dimension::LENGTH),
    },
    BaseUnit {
        name: "AMU",
        value: unit(CODATA2018_AMU_KG, Dimension::MASS),
    },
    BaseUnit {
        name: "Angstrom",
        value: unit(1e-10, Dimension::LENGTH),
    },
    BaseUnit {
        name: "Da",
        value: unit(CODATA2018_AMU_KG, Dimension::MASS),
    },
    BaseUnit {
        name: "Ha",
        value: unit(CODATA2018_HARTREE_J, ENERGY),
    },
    BaseUnit {
        name: "J",
        value: unit(1.0, ENERGY),
    },
    BaseUnit {
        name: "MeV",
        value: unit(MEGA_EV_J, ENERGY),
    },
    BaseUnit {
        name: "a0",
        value: unit(CODATA2018_BOHR_M, Dimension::LENGTH),
    },
    BaseUnit {
        name: "amu",
        value: unit(CODATA2018_AMU_KG, Dimension::MASS),
    },
    BaseUnit {
        name: "angstrom",
        value: unit(1e-10, Dimension::LENGTH),
    },
    BaseUnit {
        name: "bohr",
        value: unit(CODATA2018_BOHR_M, Dimension::LENGTH),
    },
    BaseUnit {
        name: "dalton",
        value: unit(CODATA2018_AMU_KG, Dimension::MASS),
    },
    BaseUnit {
        name: "e",
        value: unit(CODATA2018_ELEMENTARY, Dimension::CHARGE),
    },
    BaseUnit {
        name: "eV",
        value: unit(CODATA2018_ELEMENTARY, ENERGY),
    },
    BaseUnit {
        name: "electron_charge",
        value: unit(CODATA2018_ELEMENTARY, Dimension::CHARGE),
    },
    BaseUnit {
        name: "ev",
        value: unit(CODATA2018_ELEMENTARY, ENERGY),
    },
    BaseUnit {
        name: "femtosecond",
        value: unit(1e-15, Dimension::TIME),
    },
    BaseUnit {
        name: "fs",
        value: unit(1e-15, Dimension::TIME),
    },
    BaseUnit {
        name: "hartree",
        value: unit(CODATA2018_HARTREE_J, ENERGY),
    },
    BaseUnit {
        name: "j",
        value: unit(1.0, ENERGY),
    },
    BaseUnit {
        name: "joule",
        value: unit(1.0, ENERGY),
    },
    BaseUnit {
        name: "kJ",
        value: unit(1000.0, ENERGY),
    },
    BaseUnit {
        name: "kcal",
        value: unit(KCAL_THERMOCHEMICAL_J, ENERGY),
    },
    BaseUnit {
        name: "kg",
        value: unit(1.0, Dimension::MASS),
    },
    BaseUnit {
        name: "kilogram",
        value: unit(1.0, Dimension::MASS),
    },
    BaseUnit {
        name: "kj",
        value: unit(1000.0, ENERGY),
    },
    BaseUnit {
        name: "m",
        value: unit(1.0, Dimension::LENGTH),
    },
    BaseUnit {
        name: "meV",
        value: unit(MEV_J, ENERGY),
    },
    BaseUnit {
        name: "meter",
        value: unit(1.0, Dimension::LENGTH),
    },
    BaseUnit {
        name: "metre",
        value: unit(1.0, Dimension::LENGTH),
    },
    BaseUnit {
        name: "mev",
        value: unit(MEV_J, ENERGY),
    },
    BaseUnit {
        name: "mol",
        value: unit(CODATA2018_AVOGADRO, Dimension::ZERO),
    },
    BaseUnit {
        name: "nanometer",
        value: unit(1e-9, Dimension::LENGTH),
    },
    BaseUnit {
        name: "nanosecond",
        value: unit(1e-9, Dimension::TIME),
    },
    BaseUnit {
        name: "nm",
        value: unit(1e-9, Dimension::LENGTH),
    },
    BaseUnit {
        name: "ns",
        value: unit(1e-9, Dimension::TIME),
    },
    BaseUnit {
        name: "picosecond",
        value: unit(1e-12, Dimension::TIME),
    },
    BaseUnit {
        name: "ps",
        value: unit(1e-12, Dimension::TIME),
    },
    BaseUnit {
        name: "s",
        value: unit(1.0, Dimension::TIME),
    },
    BaseUnit {
        name: "second",
        value: unit(1.0, Dimension::TIME),
    },
    BaseUnit {
        name: "u",
        value: unit(CODATA2018_AMU_KG, Dimension::MASS),
    },
    BaseUnit {
        name: "Å",
        value: unit(1e-10, Dimension::LENGTH),
    },
    BaseUnit {
        name: "å",
        value: unit(1e-10, Dimension::LENGTH),
    },
];

#[cfg(test)]
pub(crate) fn cached_unit_table_addr() -> usize {
    BASE_UNITS.as_ptr() as usize
}

fn lookup_base(name: &str) -> Option<&'static UnitValue> {
    BASE_UNITS
        .binary_search_by(|entry| entry.name.cmp(name))
        .ok()
        .map(|index| &BASE_UNITS[index].value)
}

/// Parse a unit expression into SI factor and dimension.
///
/// ASCII spaces and tabs are removed (CON-units.17). Names are exact
/// spellings: `MeV` is megaelectronvolt and `meV` is millielectronvolt.
pub fn parse_unit_expression(expr: &str) -> Result<(f64, Dimension), ParseError> {
    let s: String = expr.chars().filter(|c| *c != ' ' && *c != '\t').collect();
    if s.is_empty() {
        return Err(ParseError::ValidationError("empty unit expression".into()));
    }
    parse_expr(&s)
}

fn parse_expr(s: &str) -> Result<(f64, Dimension), ParseError> {
    // Split on * and / with left-associative scan; handle ^N on atoms.
    let mut factor = 1.0_f64;
    let mut dim = Dimension::ZERO;
    let mut i = 0;
    let bytes = s.as_bytes();
    let mut pending_div = false;
    while i < bytes.len() {
        if bytes[i] == b'*' {
            i += 1;
            continue;
        }
        if bytes[i] == b'/' {
            pending_div = true;
            i += 1;
            continue;
        }
        let (atom_f, atom_d, consumed) = parse_atom(&s[i..])?;
        i += consumed;
        if pending_div {
            factor /= atom_f;
            dim = dim.div(atom_d);
            pending_div = false;
        } else {
            factor *= atom_f;
            dim = dim.mul(atom_d);
        }
    }
    Ok((factor, dim))
}

fn parse_atom(s: &str) -> Result<(f64, Dimension, usize), ParseError> {
    let bytes = s.as_bytes();
    if bytes.is_empty() {
        return Err(ParseError::ValidationError(
            "trailing operator in unit".into(),
        ));
    }
    if bytes[0] == b'(' {
        let mut depth = 0;
        for (j, &b) in bytes.iter().enumerate() {
            if b == b'(' {
                depth += 1;
            } else if b == b')' {
                depth -= 1;
                if depth == 0 {
                    let inner = &s[1..j];
                    let (f, d) = parse_expr(inner)?;
                    let mut end = j + 1;
                    let (f2, d2, extra) = apply_power(f, d, &s[end..])?;
                    end += extra;
                    return Ok((f2, d2, end));
                }
            }
        }
        return Err(ParseError::ValidationError("unbalanced '(' in unit".into()));
    }
    // identifier [ ^ number ]
    let mut j = 0;
    while j < bytes.len()
        && (bytes[j].is_ascii_alphanumeric() || bytes[j] == b'_' || bytes[j] > 127)
    {
        j += 1;
    }
    if j == 0 {
        return Err(ParseError::ValidationError(format!(
            "expected unit name in '{s}'"
        )));
    }
    let name = &s[..j];
    let base = lookup_base(name).ok_or_else(|| {
        ParseError::ValidationError(format!(
            "unknown unit '{name}'; unit symbols are case-sensitive \
             (meV is milli, MeV is mega)"
        ))
    })?;
    let mut end = j;
    let (f, d, extra) = apply_power(base.si_factor, base.dim, &s[end..])?;
    end += extra;
    Ok((f, d, end))
}

fn apply_power(f: f64, d: Dimension, rest: &str) -> Result<(f64, Dimension, usize), ParseError> {
    let bytes = rest.as_bytes();
    if bytes.first() == Some(&b'^') {
        let mut k = 1;
        let neg = bytes.get(1) == Some(&b'-');
        if neg {
            k = 2;
        }
        let start = k;
        while k < bytes.len() && (bytes[k].is_ascii_digit() || bytes[k] == b'.') {
            k += 1;
        }
        if k == start {
            return Err(ParseError::ValidationError(
                "expected exponent after ^".into(),
            ));
        }
        let mut p: f64 = rest[start..k]
            .parse()
            .map_err(|_| ParseError::ValidationError("invalid unit exponent".into()))?;
        if neg {
            p = -p;
        }
        return Ok((f.powf(p), d.pow(p), k));
    }
    Ok((f, d, 0))
}

/// Multiplicative factor: `value_in_to = factor * value_in_from`.
///
/// The names are the ones accepted in a CON `units` object. The table is
/// built once per process and reused by every reader.
///
/// ```
/// use readcon_core::units::unit_conversion_factor;
/// let meters = unit_conversion_factor("angstrom", "m").unwrap();
/// assert!((meters - 1.0e-10).abs() < 1.0e-20);
/// ```
pub fn unit_conversion_factor(from_unit: &str, to_unit: &str) -> Result<f64, ParseError> {
    unit_conversion_factor_for_version(crate::CON_SPEC_VERSION, from_unit, to_unit)
}

/// Multiplicative factor from `from_unit` to `to_unit` under a CON major.
pub fn unit_conversion_factor_for_version(
    spec_version: u32,
    from_unit: &str,
    to_unit: &str,
) -> Result<f64, ParseError> {
    let _ = spec_version;
    let (f_from, d_from) = parse_unit_expression(from_unit)?;
    let (f_to, d_to) = parse_unit_expression(to_unit)?;
    if !d_from.compatible(d_to) {
        return Err(ParseError::ValidationError(format!(
            "incompatible units '{from_unit}' and '{to_unit}'"
        )));
    }
    Ok(f_from / f_to)
}

/// Time unit that velocities in this frame are stored in (D10).
///
/// Versions 1, 2, and every minor of major 3 are the natural unit
/// regardless of a `units.time` label (CON-units.8, CON-units.9).
/// Major 4 and later take `units.time` as authoritative (CON-units.10).
/// `override_unit` must not replace that assignment (CON-units.15).
/// A value that differs from the assigned unit is `InvalidUnits`.
pub fn velocity_file_time_unit(
    spec_version: u32,
    metadata: &serde_json::Map<String, serde_json::Value>,
    override_unit: Option<&str>,
) -> Result<String, ParseError> {
    if spec_version < 4 {
        return Ok(NATURAL_TIME_UNIT.to_string());
    }
    let assigned = assigned_velocity_time(metadata)?;
    if let Some(unit) = override_unit {
        validate_unit_for_quantity("time", unit)?;
        let both_natural = is_natural_time_spelling(unit) && is_natural_time_spelling(&assigned);
        if unit != assigned && !both_natural {
            return Err(ParseError::InvalidUnits(
                "a consumer must not replace the time unit the clauses assign".into(),
            ));
        }
    }
    Ok(assigned)
}

fn assigned_velocity_time(
    metadata: &serde_json::Map<String, serde_json::Value>,
) -> Result<String, ParseError> {
    let time = metadata
        .get(crate::types::meta::UNITS)
        .and_then(|u| u.get("time"))
        .and_then(|t| t.as_str())
        .filter(|s| !s.is_empty());
    match time {
        Some(unit) => {
            validate_unit_for_quantity("time", unit)?;
            Ok(unit.to_string())
        }
        None => Err(ParseError::InvalidUnits(
            "major >= 4 velocities require units.time".into(),
        )),
    }
}

/// Multiply a file velocity by this to land in [`NATURAL_TIME_UNIT`].
///
/// Velocity scales as 1/time, so the factor is the reciprocal of
/// [`unit_conversion_factor`] from the file time unit to the natural unit.
pub fn velocity_scale_to_natural(file_time: &str) -> Result<f64, ParseError> {
    validate_unit_for_quantity("time", file_time)?;
    let factor = unit_conversion_factor(file_time, NATURAL_TIME_UNIT)?;
    if factor == 0.0 || !factor.is_finite() {
        return Err(ParseError::InvalidUnits(format!(
            "time unit '{file_time}' has a zero scale"
        )));
    }
    Ok(1.0 / factor)
}

/// Validate that `unit` has dimensions appropriate for `quantity`
/// (`length`, `energy`, `mass`, `time`, `velocity`, `force`).
pub fn validate_unit_for_quantity(quantity: &str, unit: &str) -> Result<(), ParseError> {
    let (_, dim) = parse_unit_expression(unit)?;
    let expect = match quantity {
        "length" => Dimension::LENGTH,
        "time" => Dimension::TIME,
        "mass" => Dimension::MASS,
        "energy" => Dimension::MASS
            .mul(Dimension::LENGTH.pow(2.0))
            .div(Dimension::TIME.pow(2.0)),
        "velocity" => Dimension::LENGTH.div(Dimension::TIME),
        "force" => Dimension::MASS
            .mul(Dimension::LENGTH)
            .div(Dimension::TIME.pow(2.0)),
        _ => {
            return Err(ParseError::ValidationError(format!(
                "unknown quantity '{quantity}'"
            )));
        }
    };
    if !dim.compatible(expect) {
        return Err(ParseError::ValidationError(format!(
            "unit '{unit}' is not valid for quantity '{quantity}'"
        )));
    }
    Ok(())
}

/// CON-units.2. A unit string that is present must have the matching
/// dimension, in every version that carries it (CON-units.7).
pub fn validate_present_unit_dimensions(units: &serde_json::Value) -> Result<(), ParseError> {
    let obj = units
        .as_object()
        .ok_or_else(|| ParseError::InvalidUnits("units must be a JSON object".into()))?;
    for (key, quantity) in [
        ("length", "length"),
        ("energy", "energy"),
        ("mass", "mass"),
        ("time", "time"),
        ("velocity", "velocity"),
        ("force", "force"),
    ] {
        let Some(value) = obj.get(key) else {
            continue;
        };
        let text = value
            .as_str()
            .ok_or_else(|| ParseError::InvalidUnits(format!("units.{key} must be a string")))?;
        validate_unit_for_quantity(quantity, text)
            .map_err(|err| ParseError::InvalidUnits(format!("units.{key}: {err}")))?;
    }
    Ok(())
}

/// CON v3 requires `units` object with non-empty `length` and `energy` strings.
pub fn validate_v3_units_metadata(units: &serde_json::Value) -> Result<(), ParseError> {
    validate_units_metadata_for_version(3, units)
}

/// Validate the units object under the spelling rules of its CON major.
pub fn validate_units_metadata_for_version(
    spec_version: u32,
    units: &serde_json::Value,
) -> Result<(), ParseError> {
    let _ = spec_version;
    let obj = units
        .as_object()
        .ok_or_else(|| ParseError::ValidationError("units must be a JSON object".into()))?;
    for key in ["length", "energy"] {
        let Some(v) = obj.get(key) else {
            return Err(ParseError::ValidationError(format!(
                "v3 units must include non-empty '{key}'"
            )));
        };
        let Some(s) = v.as_str() else {
            return Err(ParseError::ValidationError(format!(
                "units.{key} must be a string"
            )));
        };
        if s.trim().is_empty() {
            return Err(ParseError::ValidationError(format!(
                "units.{key} must be non-empty"
            )));
        }
        validate_unit_for_quantity(key, s)?;
    }
    // Optional keys if present must be valid for their quantity
    for (key, qty) in [
        ("mass", "mass"),
        ("time", "time"),
        ("velocity", "velocity"),
        ("force", "force"),
    ] {
        if let Some(v) = obj.get(key) {
            let s = v.as_str().ok_or_else(|| {
                ParseError::ValidationError(format!("units.{key} must be a string"))
            })?;
            validate_unit_for_quantity(qty, s)?;
        }
    }
    Ok(())
}

/// Symbol spelling of the natural time unit (CON-units.5).
/// The historical alias `(amu*angstrom^2/eV)^0.5` is the same unit.
pub const NATURAL_TIME_UNIT: &str = "(u*Å^2/eV)^0.5";

/// The eOn and ASE spelling. It mixes a name with symbols and is accepted
/// as an alias of [`NATURAL_TIME_UNIT`], not as the spelling a new frame uses.
pub const HISTORICAL_NATURAL_TIME: &str = "(amu*angstrom^2/eV)^0.5";

fn is_natural_time(compact: &str) -> bool {
    compact == NATURAL_TIME_UNIT || compact == HISTORICAL_NATURAL_TIME
}

/// Both spellings of CON-units.5, ignoring ASCII spaces and tabs.
pub fn is_natural_time_spelling(unit: &str) -> bool {
    let compact: String = unit.chars().filter(|c| !c.is_whitespace()).collect();
    is_natural_time(&compact)
}

pub fn default_v3_units_json() -> serde_json::Value {
    serde_json::json!({
        "length": "angstrom",
        "energy": "eV",
        "mass": "amu"
    })
}

fn preferred_atom(alias: &str) -> Option<&'static str> {
    // Exact spellings. `a`, `ha`, and `da` are not folded onto another unit.
    Some(match alias {
        "A" | "Å" | "å" | "angstrom" | "Angstrom" => "angstrom",
        "nm" | "nanometer" => "nm",
        "m" | "meter" | "metre" => "m",
        "bohr" | "a0" => "bohr",
        "fs" | "femtosecond" => "fs",
        "ps" | "picosecond" => "ps",
        "ns" | "nanosecond" => "ns",
        "s" | "second" => "s",
        "eV" | "ev" => "eV",
        "meV" | "mev" => "meV",
        "MeV" => "MeV",
        "hartree" | "Ha" => "hartree",
        "J" | "j" | "joule" => "J",
        "kJ" | "kj" => "kJ",
        "kcal" => "kcal",
        "amu" | "AMU" => "amu",
        "u" | "Da" | "dalton" => "u",
        "kg" | "kilogram" => "kg",
        "mol" => "mol",
        _ => return None,
    })
}

/// Rewrite a unit expression to preferred names (`A` → `angstrom`, `ev` → `eV`).
/// The expression MUST parse (`unit_conversion_factor` identity).
pub fn canonicalize_unit_expression(expr: &str) -> Result<String, ParseError> {
    canonicalize_unit_expression_for_version(crate::CON_SPEC_VERSION, expr)
}

/// Rewrite a unit expression to preferred names for a CON major.
pub fn canonicalize_unit_expression_for_version(
    spec_version: u32,
    expr: &str,
) -> Result<String, ParseError> {
    let trimmed = expr.trim();
    if trimmed.is_empty() {
        return Err(ParseError::ValidationError("empty unit".into()));
    }
    let _ = unit_conversion_factor_for_version(spec_version, trimmed, trimmed)?;
    let compact: String = trimmed.chars().filter(|c| !c.is_whitespace()).collect();
    if is_natural_time(&compact) {
        return Ok(if spec_version >= 4 {
            NATURAL_TIME_UNIT
        } else {
            HISTORICAL_NATURAL_TIME
        }
        .to_string());
    }
    let mut out = String::new();
    let bytes = compact.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let b = bytes[i];
        if matches!(b, b'*' | b'/' | b'(' | b')' | b'^') {
            if !out.is_empty() && !out.ends_with(' ') && b != b')' && b != b'^' {
                out.push(' ');
            }
            out.push(b as char);
            if b != b'(' && b != b'^' {
                out.push(' ');
            }
            i += 1;
            continue;
        }
        if b == b'-' || b.is_ascii_digit() || b == b'.' {
            out.push(b as char);
            i += 1;
            continue;
        }
        let start = i;
        while i < bytes.len() && (bytes[i].is_ascii_alphabetic() || bytes[i] > 127) {
            i += 1;
        }
        if start == i {
            return Err(ParseError::ValidationError(format!(
                "bad unit token in '{expr}'"
            )));
        }
        let atom = &compact[start..i];
        out.push_str(preferred_atom(atom).unwrap_or(atom));
    }
    let rendered = out.split_whitespace().collect::<Vec<_>>().join(" ");
    let rendered_compact: String = rendered.chars().filter(|c| !c.is_whitespace()).collect();
    if is_natural_time(&rendered_compact) {
        return Ok(if spec_version >= 4 {
            NATURAL_TIME_UNIT
        } else {
            HISTORICAL_NATURAL_TIME
        }
        .to_string());
    }
    Ok(rendered)
}

/// CON-units.21. `units.velocity` does not replace the time the version rules assign.
pub fn enforce_velocity_precedence(
    spec_version: u32,
    units: &serde_json::Value,
) -> Result<(), ParseError> {
    let Some(obj) = units.as_object() else {
        return Ok(());
    };
    let Some(velocity) = obj.get("velocity").and_then(|value| value.as_str()) else {
        return Ok(());
    };
    validate_unit_for_quantity("velocity", velocity)?;
    let length = obj
        .get("length")
        .and_then(|value| value.as_str())
        .filter(|text| !text.is_empty())
        .unwrap_or("angstrom");
    let time = if spec_version >= 4 {
        match obj
            .get("time")
            .and_then(|value| value.as_str())
            .filter(|text| !text.is_empty())
        {
            Some(unit) => unit.to_string(),
            None => return Ok(()),
        }
    } else {
        NATURAL_TIME_UNIT.to_string()
    };
    let quotient = format!("({length})/({time})");
    let factor = unit_conversion_factor_for_version(spec_version, velocity, &quotient)?;
    if (factor - 1.0).abs() > 1e-9 {
        return Err(ParseError::InvalidUnits(format!(
            "units.velocity must equal units.length divided by the time unit, not '{velocity}'"
        )));
    }
    Ok(())
}

/// Rewrite every string member. Does not require v3 `length`+`energy`.
pub fn canonicalize_units_object(
    units: &serde_json::Value,
) -> Result<serde_json::Value, ParseError> {
    canonicalize_units_object_for_version(crate::CON_SPEC_VERSION, units)
}

/// Rewrite every string member under the named CON major.
pub fn canonicalize_units_object_for_version(
    spec_version: u32,
    units: &serde_json::Value,
) -> Result<serde_json::Value, ParseError> {
    let obj = units
        .as_object()
        .ok_or_else(|| ParseError::ValidationError("units must be a JSON object".into()))?;
    let mut out = serde_json::Map::new();
    for (k, v) in obj {
        let s = v
            .as_str()
            .ok_or_else(|| ParseError::ValidationError(format!("units.{k} must be a string")))?;
        out.insert(
            k.clone(),
            serde_json::Value::String(canonicalize_unit_expression_for_version(spec_version, s)?),
        );
    }
    Ok(serde_json::Value::Object(out))
}

/// v3 validate then canonicalize (preferred names on line 2).
pub fn canonicalize_units_metadata(
    units: &serde_json::Value,
) -> Result<serde_json::Value, ParseError> {
    validate_v3_units_metadata(units)?;
    canonicalize_units_object_for_version(3, units)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// CON-units.18: bohr and hartree use the specification's exact literals.
    #[test]
    fn con_units_18_uses_spec_codata_2018_literals() {
        let bohr = 5.291_772_109_03e-11_f64;
        let hartree = 4.359_744_722_207_1e-18_f64;
        assert_eq!(CODATA2018_BOHR_M.to_bits(), bohr.to_bits());
        assert_eq!(CODATA2018_HARTREE_J.to_bits(), hartree.to_bits());
        assert_eq!(
            parse_unit_expression("bohr").unwrap().0.to_bits(),
            bohr.to_bits()
        );
        assert_eq!(
            parse_unit_expression("hartree").unwrap().0.to_bits(),
            hartree.to_bits()
        );
    }

    #[test]
    fn base_table_is_shared_across_calls_and_threads() {
        for pair in BASE_UNITS.windows(2) {
            assert!(
                pair[0].name < pair[1].name,
                "{} is not before {}",
                pair[0].name,
                pair[1].name
            );
        }
        let energy = Dimension::MASS
            .mul(Dimension::LENGTH.pow(2.0))
            .div(Dimension::TIME.pow(2.0));
        assert!(
            parse_unit_expression("eV").unwrap().1.compatible(energy),
            "energy exponents drifted from M L^2 T^-2"
        );
        let first = cached_unit_table_addr();
        let second = cached_unit_table_addr();
        assert_eq!(first, second);
        let factors = std::thread::scope(|scope| {
            let mut joins = Vec::new();
            for _ in 0..8 {
                joins.push(scope.spawn(|| parse_unit_expression("Angstrom").unwrap().0));
            }
            joins
                .into_iter()
                .map(|join| join.join().unwrap())
                .collect::<Vec<_>>()
        });
        assert!(factors.iter().all(|factor| (*factor - 1e-10).abs() < 1e-22));
    }

    #[test]
    fn angstrom_to_nm() {
        let f = unit_conversion_factor("angstrom", "nm").unwrap();
        assert!((f - 0.1).abs() < 1e-12);
    }

    #[test]
    fn ev_to_mev() {
        let f = unit_conversion_factor("eV", "meV").unwrap();
        assert!((f - 1000.0).abs() < 1e-6);
    }

    #[test]
    fn dimensional_mismatch() {
        assert!(unit_conversion_factor("angstrom", "eV").is_err());
    }

    #[test]
    fn ev_to_kcal_per_mol_is_metatomic() {
        let f = unit_conversion_factor("eV", "kcal / mol").unwrap();
        assert!((f - 23.060_548).abs() < 1e-3, "got {f}");
        let force = unit_conversion_factor("eV / angstrom", "kJ / mol / angstrom").unwrap();
        assert!((force - 96.485_332).abs() < 1e-3, "got {force}");
        let ns = unit_conversion_factor("ns", "ps").unwrap();
        assert!((ns - 1000.0).abs() < 1e-9, "got {ns}");
    }

    #[test]
    fn validate_length_energy() {
        validate_unit_for_quantity("length", "nm").unwrap();
        validate_unit_for_quantity("energy", "hartree").unwrap();
        assert!(validate_unit_for_quantity("energy", "angstrom").is_err());
    }

    #[test]
    fn v3_units_require_length_energy() {
        assert!(validate_v3_units_metadata(&serde_json::json!({"length": "A"})).is_err());
        validate_v3_units_metadata(&default_v3_units_json()).unwrap();
    }

    #[test]
    fn default_v3_units_do_not_invent_time_fs() {
        let units = default_v3_units_json();
        assert!(units.get("time").is_none(), "{units}");
        assert_eq!(units["length"], "angstrom");
        assert_eq!(units["energy"], "eV");
        assert_eq!(units["mass"], "amu");
    }

    #[test]
    fn canonicalize_aliases() {
        assert_eq!(canonicalize_unit_expression("A").unwrap(), "angstrom");
        assert_eq!(canonicalize_unit_expression("ev").unwrap(), "eV");
        assert_eq!(canonicalize_unit_expression("femtosecond").unwrap(), "fs");
        assert_eq!(
            canonicalize_unit_expression("eV/angstrom").unwrap(),
            "eV / angstrom"
        );
        let u = canonicalize_units_metadata(&serde_json::json!({
            "length": "A",
            "energy": "ev",
            "time": "femtosecond"
        }))
        .unwrap();
        assert_eq!(u["length"], "angstrom");
        assert_eq!(u["energy"], "eV");
        assert_eq!(u["time"], "fs");
    }

    #[test]
    fn natural_time_spelling_is_pinned() {
        let spaced = "( amu * angstrom ^ 2 / eV ) ^ 0.5";
        assert_eq!(
            canonicalize_unit_expression(spaced).unwrap(),
            NATURAL_TIME_UNIT
        );
        assert!(!NATURAL_TIME_UNIT.contains(' '));
        let factor = unit_conversion_factor(NATURAL_TIME_UNIT, "fs").unwrap();
        assert!((factor - 10.180_505_710_759_414).abs() < 1e-9, "{factor}");
        let mixed = "(AMU * angstrom^2 / ev)^0.5";
        assert_eq!(
            canonicalize_unit_expression(mixed).unwrap(),
            NATURAL_TIME_UNIT
        );
    }
}
