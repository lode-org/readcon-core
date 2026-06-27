//! Unit expressions and conversion (metatomic-inspired, SI dimensional analysis).
//!
//! Supports named base units and simple products/quotients with `*`, `/`, `^`,
//! and parentheses (case-insensitive). `unit_conversion_factor(from, to)` returns
//! the multiplier `x_to = factor * x_from` when dimensions match.

use crate::error::ParseError;
use std::collections::HashMap;

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
        for i in 0..5 {
            e[i] = self.exponents[i] + other.exponents[i];
        }
        Self { exponents: e }
    }

    fn div(self, other: Self) -> Self {
        let mut e = [0.0; 5];
        for i in 0..5 {
            e[i] = self.exponents[i] - other.exponents[i];
        }
        Self { exponents: e }
    }

    fn pow(self, p: f64) -> Self {
        let mut e = [0.0; 5];
        for i in 0..5 {
            e[i] = self.exponents[i] * p;
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
#[derive(Clone, Debug)]
struct UnitValue {
    /// Multiply quantity in this unit by `si_factor` to get SI.
    si_factor: f64,
    dim: Dimension,
}

fn base_table() -> HashMap<&'static str, UnitValue> {
    let mut m = HashMap::new();
    let ins = |m: &mut HashMap<&'static str, UnitValue>, names: &[&'static str], u: UnitValue| {
        for n in names {
            m.insert(*n, u.clone());
        }
    };
    // Length → meters
    ins(
        &mut m,
        &["m", "meter", "metre"],
        UnitValue {
            si_factor: 1.0,
            dim: Dimension::LENGTH,
        },
    );
    ins(
        &mut m,
        &["angstrom", "a", "å"],
        UnitValue {
            si_factor: 1e-10,
            dim: Dimension::LENGTH,
        },
    );
    ins(
        &mut m,
        &["nm", "nanometer"],
        UnitValue {
            si_factor: 1e-9,
            dim: Dimension::LENGTH,
        },
    );
    ins(
        &mut m,
        &["bohr", "a0"],
        UnitValue {
            si_factor: 5.291_772_109_03e-11,
            dim: Dimension::LENGTH,
        },
    );
    // Time → seconds
    ins(
        &mut m,
        &["s", "second"],
        UnitValue {
            si_factor: 1.0,
            dim: Dimension::TIME,
        },
    );
    ins(
        &mut m,
        &["fs", "femtosecond"],
        UnitValue {
            si_factor: 1e-15,
            dim: Dimension::TIME,
        },
    );
    ins(
        &mut m,
        &["ps", "picosecond"],
        UnitValue {
            si_factor: 1e-12,
            dim: Dimension::TIME,
        },
    );
    // Mass → kg
    ins(
        &mut m,
        &["kg", "kilogram"],
        UnitValue {
            si_factor: 1.0,
            dim: Dimension::MASS,
        },
    );
    ins(
        &mut m,
        &["u", "amu", "dalton", "da"],
        UnitValue {
            si_factor: 1.660_539_066_60e-27,
            dim: Dimension::MASS,
        },
    );
    // Energy → joule (M L^2 T^-2)
    let energy_dim = Dimension::MASS
        .mul(Dimension::LENGTH.pow(2.0))
        .div(Dimension::TIME.pow(2.0));
    ins(
        &mut m,
        &["j", "joule"],
        UnitValue {
            si_factor: 1.0,
            dim: energy_dim,
        },
    );
    ins(
        &mut m,
        &["ev"],
        UnitValue {
            si_factor: 1.602_176_634e-19,
            dim: energy_dim,
        },
    );
    ins(
        &mut m,
        &["mev"],
        UnitValue {
            si_factor: 1.602_176_634e-22,
            dim: energy_dim,
        },
    );
    ins(
        &mut m,
        &["hartree", "ha"],
        UnitValue {
            si_factor: 4.359_744_722_207_1e-18,
            dim: energy_dim,
        },
    );
    // Charge
    ins(
        &mut m,
        &["e", "electron_charge"],
        UnitValue {
            si_factor: 1.602_176_634e-19,
            dim: Dimension::CHARGE,
        },
    );
    // mol (dimensionless for our 5-vector — treat as ZERO so kcal/mol works as energy/mol scale)
    ins(
        &mut m,
        &["mol"],
        UnitValue {
            si_factor: 1.0 / 6.022_140_76e23,
            dim: Dimension::ZERO,
        },
    );
    ins(
        &mut m,
        &["kcal"],
        UnitValue {
            si_factor: 4184.0,
            dim: energy_dim,
        },
    );
    ins(
        &mut m,
        &["kj"],
        UnitValue {
            si_factor: 1000.0,
            dim: energy_dim,
        },
    );
    m
}

/// Parse a unit expression into SI factor and dimension.
pub fn parse_unit_expression(expr: &str) -> Result<(f64, Dimension), ParseError> {
    let s: String = expr.chars().filter(|c| !c.is_whitespace()).collect();
    if s.is_empty() {
        return Err(ParseError::ValidationError("empty unit expression".into()));
    }
    let table = base_table();
    parse_expr(&s.to_ascii_lowercase(), &table)
}

fn parse_expr(
    s: &str,
    table: &HashMap<&str, UnitValue>,
) -> Result<(f64, Dimension), ParseError> {
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
        let (atom_f, atom_d, consumed) = parse_atom(&s[i..], table)?;
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

fn parse_atom(
    s: &str,
    table: &HashMap<&str, UnitValue>,
) -> Result<(f64, Dimension, usize), ParseError> {
    let bytes = s.as_bytes();
    if bytes.is_empty() {
        return Err(ParseError::ValidationError("trailing operator in unit".into()));
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
                    let (f, d) = parse_expr(inner, table)?;
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
    while j < bytes.len() && (bytes[j].is_ascii_alphanumeric() || bytes[j] == b'_' || bytes[j] > 127)
    {
        j += 1;
    }
    if j == 0 {
        return Err(ParseError::ValidationError(format!(
            "expected unit name in '{s}'"
        )));
    }
    let name = &s[..j];
    let base = table.get(name).ok_or_else(|| {
        ParseError::ValidationError(format!("unknown unit '{name}'"))
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
            return Err(ParseError::ValidationError("expected exponent after ^".into()));
        }
        let mut p: f64 = rest[start..k].parse().map_err(|_| {
            ParseError::ValidationError("invalid unit exponent".into())
        })?;
        if neg {
            p = -p;
        }
        return Ok((f.powf(p), d.pow(p), k));
    }
    Ok((f, d, 0))
}

/// Multiplicative factor: `value_in_to = factor * value_in_from`.
pub fn unit_conversion_factor(from_unit: &str, to_unit: &str) -> Result<f64, ParseError> {
    let (f_from, d_from) = parse_unit_expression(from_unit)?;
    let (f_to, d_to) = parse_unit_expression(to_unit)?;
    if !d_from.compatible(d_to) {
        return Err(ParseError::ValidationError(format!(
            "incompatible units '{from_unit}' and '{to_unit}'"
        )));
    }
    Ok(f_from / f_to)
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

/// CON v3 requires `units` object with non-empty `length` and `energy` strings.
pub fn validate_v3_units_metadata(units: &serde_json::Value) -> Result<(), ParseError> {
    let obj = units.as_object().ok_or_else(|| {
        ParseError::ValidationError("units must be a JSON object".into())
    })?;
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

/// Default LODE units object for new v3 frames.
pub fn default_v3_units_json() -> serde_json::Value {
    serde_json::json!({
        "length": "angstrom",
        "energy": "eV",
        "mass": "amu",
        "time": "fs"
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
