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
    UnknownSection(String),
    InvalidElementSymbol(String),
    MassInconsistency {
        symbol: String,
        header_mass: f64,
        expected_mass: f64,
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
            ParseError::UnknownSection(name) => {
                write!(f, "unknown section type in metadata: {name}")
            }
            ParseError::InvalidElementSymbol(sym) => {
                write!(f, "unrecognized element symbol: \"{sym}\"")
            }
            ParseError::MassInconsistency {
                symbol,
                header_mass,
                expected_mass,
            } => {
                write!(
                    f,
                    "mass for {symbol} in header ({header_mass:.3}) differs from \
                     standard mass ({expected_mass:.3}) by more than 10%"
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
