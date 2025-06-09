#[derive(Debug)]
pub enum ParseError {
    IncompleteHeader,
    IncompleteFrame,
    InvalidVectorLength { expected: u64, found: u64 },
    InvalidNumberFormat(String),
}
