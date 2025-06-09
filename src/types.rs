//=============================================================================
// Data Structures - The shape of our parsed data
//=============================================================================

use std::num::{ParseFloatError, ParseIntError};

/// Represents all possible errors that can occur during `.con` file parsing.
#[derive(Debug)]
pub enum ParseError {
    /// The file ended unexpectedly while parsing a frame's 9-line header.
    IncompleteHeader,
    /// The file ended unexpectedly after the header, while reading atom data.
    IncompleteFrame,
    /// A line had a different number of values than expected.
    InvalidVectorLength {
        /// The number of values that the parser expected to find.
        expected: usize,
        /// The number of values actually found on the line.
        found: usize,
    },
    /// A value could not be parsed into the required number type (e.g., `f64` or `usize`).
    InvalidNumberFormat(String),
}

/// Allows `ParseFloatError` to be automatically converted into `ParseError`.
impl From<ParseFloatError> for ParseError {
    fn from(e: ParseFloatError) -> Self {
        ParseError::InvalidNumberFormat(e.to_string())
    }
}

/// Allows `ParseIntError` to be automatically converted into `ParseError`.
impl From<ParseIntError> for ParseError {
    fn from(e: ParseIntError) -> Self {
        ParseError::InvalidNumberFormat(e.to_string())
    }
}

/// Holds all metadata from the 9-line header of a simulation frame.
#[derive(Debug)]
pub struct FrameHeader {
    /// The two text lines preceding the box dimension data.
    pub prebox_header: [String; 2],
    /// The three box dimensions, typically Lx, Ly, and Lz.
    pub boxl: [f64; 3],
    /// The three box angles, typically alpha, beta, and gamma.
    pub angles: [f64; 3],
    /// The two text lines following the box angle data.
    pub postbox_header: [String; 2],
    /// The number of distinct atom types in the frame.
    pub natm_types: usize,
    /// A vector containing the count of atoms for each respective type.
    pub natms_per_type: Vec<usize>,
    /// A vector containing the mass for each respective atom type.
    pub masses_per_type: Vec<f64>,
}

/// Represents the data for a single atom in a frame.
#[derive(Debug)]
pub struct AtomDatum {
    /// The chemical symbol of the atom (e.g., "C", "H", "O").
    pub symbol: String,
    /// The Cartesian x-coordinate.
    pub x: f64,
    /// The Cartesian y-coordinate.
    pub y: f64,
    /// The Cartesian z-coordinate.
    pub z: f64,
    /// A flag indicating if the atom's position is fixed during a simulation.
    pub is_fixed: bool,
    /// A unique integer identifier for the atom.
    pub atom_id: u64,
}

/// Represents a single, complete simulation frame, including header and all atomic data.
#[derive(Debug)]
pub struct ConFrame {
    /// The `FrameHeader` containing the frame's metadata.
    pub header: FrameHeader,
    /// A vector holding all atomic data for the frame.
    pub atom_data: Vec<AtomDatum>,
}
