use std::fmt;
use std::num::{ParseFloatError, ParseIntError};

#[derive(Debug)]
pub enum ParseError {
    IncompleteHeader,
    IncompleteFrame,
    IncompleteVelocitySection,
    InvalidVectorLength {
        expected: usize,
        found: usize,
    },
    InvalidNumberFormat(String),
    MissingSpecVersion,
    UnsupportedSpecVersion(u32),
    InvalidMetadataJson(String),
    IncompleteForceSection,
    IncompleteEnergySection,
    /// Declared optional section was incomplete or mislabeled.
    IncompleteSection(String),
    UnknownSection(String),
    ValidationError(String),
    /// NaN, Inf, Infinity, or a signed or mixed-case spelling, in any mode.
    /// Clause CON-num.1 (D1).
    NonFiniteValue(String),
    /// Column 4 is not a legal integer flag. Clause CON-mask.5 (D8).
    InvalidFixedFlag(String),
    /// A type count, per-type count, or atom count is not >= 1.
    /// Clause CON-count.2 (D4).
    InvalidCount(String),
    /// A unit expression is missing, mistyped, or the wrong dimension.
    /// Clauses CON-units.9 and CON-units.10 (D11).
    InvalidUnits(String),
    /// Unknown major, or JSON `con_spec_version` 0 or 1.
    /// Clause CON-line2.5 (D15).
    UnsupportedVersion(u32),
    /// An in-place builder mutation
    /// (`ConFrameBuilder::set_atom_position` / `set_atom_velocity` /
    /// `set_atom_force` / `set_atom_energy` / `set_atom_fixed` /
    /// `set_atom_mass` / clear_*) was called with an atom index past
    /// the current length. Surfaces as `IndexError` in PyO3 and as
    /// `RKR_STATUS_INDEX_OUT_OF_BOUNDS` over the C ABI.
    IndexOutOfBounds {
        index: usize,
        len: usize,
    },
    /// Two atoms share a CON type (symbol) but their masses differ
    /// beyond [`crate::types::ConFrameBuilder::TYPE_MASS_ABS_TOL`].
    /// CON line 9 stores one mass per type, so the builder cannot
    /// represent per-atom mass variation inside a type.
    MassMismatch {
        symbol: String,
        first_mass: f64,
        found_mass: f64,
        atom_index: usize,
    },
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::IncompleteHeader => {
                write!(f, "file ended unexpectedly while parsing frame header")
            }
            ParseError::IncompleteFrame => {
                write!(f, "file ended unexpectedly while reading atom data")
            }
            ParseError::IncompleteVelocitySection => {
                write!(f, "file ended unexpectedly while reading velocity section")
            }
            ParseError::InvalidVectorLength { expected, found } => {
                write!(f, "expected {expected} values on line, found {found}")
            }
            ParseError::InvalidNumberFormat(msg) => {
                write!(f, "invalid number format: {msg}")
            }
            ParseError::MissingSpecVersion => {
                write!(
                    f,
                    "line 2 must be a JSON object containing \"con_spec_version\""
                )
            }
            ParseError::UnsupportedSpecVersion(v) | ParseError::UnsupportedVersion(v) => {
                write!(f, "unsupported con_spec_version: {v}")
            }
            ParseError::InvalidMetadataJson(msg) => {
                write!(f, "invalid JSON metadata on line 2: {msg}")
            }
            ParseError::IncompleteForceSection => {
                write!(f, "file ended unexpectedly while reading force section")
            }
            ParseError::IncompleteEnergySection => {
                write!(f, "file ended unexpectedly while reading energy section")
            }
            ParseError::IncompleteSection(name) => {
                write!(f, "file ended unexpectedly while reading {name} section")
            }
            ParseError::UnknownSection(name) => {
                write!(f, "unknown section type in metadata: {name}")
            }
            ParseError::ValidationError(msg) => {
                write!(f, "CON validation failed: {msg}")
            }
            ParseError::NonFiniteValue(token) => {
                write!(f, "non-finite value: {token}")
            }
            ParseError::InvalidFixedFlag(msg) => {
                write!(f, "invalid fixed flag: {msg}")
            }
            ParseError::InvalidCount(msg) => {
                write!(f, "invalid count: {msg}")
            }
            ParseError::InvalidUnits(msg) => {
                write!(f, "invalid units: {msg}")
            }
            ParseError::IndexOutOfBounds { index, len } => {
                write!(
                    f,
                    "atom index {index} is out of bounds (builder holds {len} atoms)"
                )
            }
            ParseError::MassMismatch {
                symbol,
                first_mass,
                found_mass,
                atom_index,
            } => {
                write!(
                    f,
                    "atoms of type {symbol} have inconsistent masses: first {first_mass}, atom {atom_index} has {found_mass} (CON stores one mass per type)"
                )
            }
        }
    }
}

impl std::error::Error for ParseError {}

impl ParseError {
    /// Stable class name from the v3.1 error table (CON-error.1).
    pub fn class_name(&self) -> &'static str {
        match self {
            ParseError::IncompleteHeader => "IncompleteHeader",
            ParseError::IncompleteFrame => "IncompleteFrame",
            ParseError::IncompleteVelocitySection => "IncompleteVelocitySection",
            ParseError::InvalidVectorLength { .. } => "InvalidVectorLength",
            ParseError::InvalidNumberFormat(_) => "InvalidNumberFormat",
            ParseError::MissingSpecVersion => "MissingSpecVersion",
            ParseError::UnsupportedSpecVersion(_) | ParseError::UnsupportedVersion(_) => {
                "UnsupportedVersion"
            }
            ParseError::InvalidMetadataJson(_) => "InvalidMetadataJson",
            ParseError::IncompleteForceSection => "IncompleteForceSection",
            ParseError::IncompleteEnergySection => "IncompleteEnergySection",
            ParseError::IncompleteSection(_) => "IncompleteSection",
            ParseError::UnknownSection(_) => "UnknownSection",
            ParseError::ValidationError(_) => "ValidationError",
            ParseError::IndexOutOfBounds { .. } => "IndexOutOfBounds",
            ParseError::MassMismatch { .. } => "MassMismatch",
            ParseError::NonFiniteValue(_) => "NonFiniteValue",
            ParseError::InvalidFixedFlag(_) => "InvalidFixedFlag",
            ParseError::InvalidCount(_) => "InvalidCount",
            ParseError::InvalidUnits(_) => "InvalidUnits",
        }
    }

    /// 1-based file line when this failure is tied to a known header line.
    /// Metadata failures are line 2 of a single-frame file (CON-error.2).
    /// Other failures report the line recorded by the iterator, or 0 when
    /// the producing call did not have a cursor.
    pub fn line(&self) -> u32 {
        match self {
            ParseError::MissingSpecVersion
            | ParseError::InvalidMetadataJson(_)
            | ParseError::UnsupportedSpecVersion(_)
            | ParseError::UnsupportedVersion(_) => 2,
            _ => 0,
        }
    }
}

impl From<ParseFloatError> for ParseError {
    fn from(e: ParseFloatError) -> Self {
        ParseError::InvalidNumberFormat(e.to_string())
    }
}

impl From<ParseIntError> for ParseError {
    fn from(e: ParseIntError) -> Self {
        ParseError::InvalidNumberFormat(e.to_string())
    }
}

impl From<serde_json::Error> for ParseError {
    fn from(e: serde_json::Error) -> Self {
        ParseError::InvalidMetadataJson(e.to_string())
    }
}
