use std::fmt;
use std::num::{ParseFloatError, ParseIntError};

#[derive(Debug)]
pub enum ParseError {
    IncompleteHeader,
    IncompleteFrame,
    IncompleteVelocitySection,
    InvalidVectorLength { expected: usize, found: usize },
    InvalidNumberFormat(String),
    MissingSpecVersion,
    UnsupportedSpecVersion(u32),
    InvalidMetadataJson(String),
    IncompleteForceSection,
    IncompleteEnergySection,
    UnknownSection(String),
    ValidationError(String),
    /// An in-place builder mutation
    /// (`ConFrameBuilder::set_atom_position` / `set_atom_velocity` /
    /// `set_atom_force` / `set_atom_energy` / `set_atom_fixed` /
    /// `set_atom_mass` / clear_*) was called with an atom index past
    /// the current length. Surfaces as `IndexError` in PyO3 and as
    /// `RKR_STATUS_INDEX_OUT_OF_BOUNDS` over the C ABI.
    IndexOutOfBounds { index: usize, len: usize },
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
                    "line 1 must be a JSON object containing \"con_spec_version\""
                )
            }
            ParseError::UnsupportedSpecVersion(v) => {
                write!(f, "unsupported con_spec_version: {v}")
            }
            ParseError::InvalidMetadataJson(msg) => {
                write!(f, "invalid JSON metadata on line 1: {msg}")
            }
            ParseError::IncompleteForceSection => {
                write!(f, "file ended unexpectedly while reading force section")
            }
            ParseError::IncompleteEnergySection => {
                write!(f, "file ended unexpectedly while reading energy section")
            }
            ParseError::UnknownSection(name) => {
                write!(f, "unknown section type in metadata: {name}")
            }
            ParseError::ValidationError(msg) => {
                write!(f, "CON validation failed: {msg}")
            }
            ParseError::IndexOutOfBounds { index, len } => {
                write!(
                    f,
                    "atom index {index} is out of bounds (builder holds {len} atoms)"
                )
            }
        }
    }
}

impl std::error::Error for ParseError {}

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
