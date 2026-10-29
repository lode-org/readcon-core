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
    /// A count field is not an unsigned integer, or a per-type count is 0
    /// when the type count is 1 or more. A type count of 0 is legal.
    /// Clauses CON-count.1 and CON-error.3 (D4).
    InvalidCount(String),
    /// A unit expression is missing, mistyped, or the wrong dimension.
    /// A minor of 1 or later with velocities and no `units.time` is this
    /// class on read and on write.
    /// Clauses CON-units.11, CON-units.12, CON-units.13, and CON-units.14 (D11).
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

impl ParseError {
    /// Field text the error names, when the message carries one.
    pub(crate) fn offending_token(&self) -> Option<&str> {
        match self {
            ParseError::NonFiniteValue(token) => Some(token),
            ParseError::InvalidNumberFormat(msg) => msg
                .strip_prefix("invalid float: ")
                .or_else(|| msg.strip_prefix("invalid integer: "))
                .or_else(|| msg.strip_prefix("integer out of range 0..=2^64-1: ")),
            ParseError::InvalidCount(msg) => msg
                .strip_prefix("count field is not an unsigned integer: ")
                .or_else(|| msg.strip_prefix("count field is out of range: ")),
            ParseError::InvalidFixedFlag(msg) => {
                msg.strip_prefix("column 4 flag \"")?.split('"').next()
            }
            ParseError::ValidationError(msg) => match msg.split_once(" symbol mismatch: ") {
                Some((_, rest)) => rest.split_once(", found ").map(|(_, symbol)| symbol),
                None => msg.strip_prefix("unknown component symbol "),
            },
            _ => None,
        }
    }
}

/// Where in a buffer a [`ParseError`] was detected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ErrorLocation {
    /// 0-based index of the frame that failed.
    pub frame: usize,
    /// 1-based line in the buffer (CON-error.2). A missing line at end of
    /// input is the line after the last one.
    pub line: u64,
    /// 1-based character column of the offending field, when the error
    /// names one.
    pub column: Option<u64>,
    /// Byte offset of the start of that line.
    pub byte_offset: usize,
}

/// A [`ParseError`] with its [`ErrorLocation`]. Opt-in through
/// [`crate::iterators::ConFrameIterator::next_located`] and
/// [`crate::iterators::locate_first_error`].
#[derive(Debug)]
pub struct LocatedParseError {
    pub error: ParseError,
    pub location: ErrorLocation,
}

impl fmt::Display for LocatedParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let loc = &self.location;
        write!(f, "line {}", loc.line)?;
        if let Some(column) = loc.column {
            write!(f, ", column {column}")?;
        }
        write!(f, " (frame {}): {}", loc.frame, self.error)
    }
}

impl std::error::Error for LocatedParseError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.error)
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
