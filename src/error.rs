#[derive(Debug)]
pub enum ParseError {
    IncompleteHeader,
    IncompleteFrame,
    InvalidVectorLength { expected: usize, found: usize },
    InvalidNumberFormat(String),
}
