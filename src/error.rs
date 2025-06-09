use std::num::{ParseFloatError, ParseIntError};
#[derive(Debug)]
pub enum ParseError {
    IncompleteHeader,
    IncompleteFrame,
    InvalidVectorLength { expected: usize, found: usize },
    InvalidNumberFormat(String),
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
