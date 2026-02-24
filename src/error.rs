use std::fmt;
use std::num::{ParseFloatError, ParseIntError};

#[derive(Debug)]
pub enum ParseError {
    IncompleteHeader,
    IncompleteFrame,
    IncompleteVelocitySection,
    InvalidVectorLength { expected: usize, found: usize },
    InvalidNumberFormat(String),
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
