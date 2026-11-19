use std::fmt;
use std::num::{ParseFloatError, ParseIntError};

#[derive(Debug, Clone)]
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
    /// A sidecar read failed for a reason other than a missing file.
    Io(String),
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
            ParseError::Io(msg) => write!(f, "index read failed: {msg}"),
        }
    }
}

impl std::error::Error for ParseError {}

/// Start of the text of a [`ParseError::NonFiniteValue`] that names a cell field.
const CELL_FIELD: &str = "cell field ";
const CELL_VALUE_JOINT: &str = " is ";

impl ParseError {
    /// A cell number that is NaN or infinite, as [`ParseError::NonFiniteValue`].
    ///
    /// `field` is the name the caller knows the number by, for example
    /// `boxl[1]`, `angles[2]`, `cell[4]`, or `lattice_vectors[0][2]`.
    /// `value` is its spelling: the token of a file, or the Rust rendering of
    /// the number (`NaN`, `inf`, `-inf`). [`Self::in_frame`] adds the frame.
    pub fn non_finite_cell(field: &str, value: impl std::fmt::Display) -> Self {
        ParseError::NonFiniteValue(format!("{CELL_FIELD}{field}{CELL_VALUE_JOINT}{value}"))
    }

    /// Recover the typed error from the text a `String`-error layer carries.
    ///
    /// For a layer that can carry only text: a Cap'n Proto failure, or the
    /// `String` form of a [`ConvertError`]. A message made by `to_string` on
    /// a cell error comes back as the same error; any other message gives
    /// `None`.
    #[must_use]
    pub fn from_cell_text(message: &str) -> Option<Self> {
        let rest = message.strip_prefix("non-finite value: ")?;
        rest.starts_with(CELL_FIELD)
            .then(|| ParseError::NonFiniteValue(rest.to_string()))
    }

    /// Recover any [`ParseError::NonFiniteValue`], of a cell or of an atom
    /// row, from its `to_string` text. Any other message gives `None`.
    #[must_use]
    pub fn from_non_finite_text(message: &str) -> Option<Self> {
        let rest = message.strip_prefix("non-finite value: ")?;
        (!rest.is_empty()).then(|| ParseError::NonFiniteValue(rest.to_string()))
    }

    /// True for the error [`Self::non_finite_cell`] makes.
    pub fn is_non_finite_cell(&self) -> bool {
        matches!(self, ParseError::NonFiniteValue(text) if text.starts_with(CELL_FIELD))
    }

    /// The 0-based frame a non-finite cell error names, if it names one.
    #[must_use]
    pub fn named_frame(&self) -> Option<u64> {
        let ParseError::NonFiniteValue(text) = self else {
            return None;
        };
        let rest = text.strip_prefix(CELL_FIELD)?;
        let (field, _) = rest.split_once(CELL_VALUE_JOINT)?;
        let (_, frame) = field.split_once(" of frame ")?;
        frame.parse().ok()
    }

    /// Names `frame` (0-based) in a non-finite cell error that does not name
    /// one yet. Every other error, and a cell error that already names a
    /// frame, is returned as it was.
    #[must_use]
    pub fn in_frame(self, frame: u64) -> Self {
        let ParseError::NonFiniteValue(text) = &self else {
            return self;
        };
        let Some(rest) = text.strip_prefix(CELL_FIELD) else {
            return self;
        };
        match rest.split_once(CELL_VALUE_JOINT) {
            Some((field, value)) if !field.contains(' ') => ParseError::NonFiniteValue(format!(
                "{CELL_FIELD}{field} of frame {frame}{CELL_VALUE_JOINT}{value}"
            )),
            _ => self,
        }
    }
}

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
            ParseError::Io(_) => "Io",
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

/// Error of a reader, writer, or converter for a format other than CON text:
/// the extended-XYZ and PDB scanners and the Cap'n Proto frame converters.
///
/// A failure with a CON error class, such as a non-finite cell, is
/// [`ConvertError::Parse`] and keeps its [`ParseError`]. The format's own
/// diagnostics are [`ConvertError::Message`]. `Display` is the inner text in
/// both cases.
#[derive(Debug, Clone)]
pub enum ConvertError {
    Parse(ParseError),
    Message(String),
}

impl ConvertError {
    /// The typed error, when this failure has a CON error class.
    pub fn parse_error(&self) -> Option<&ParseError> {
        match self {
            ConvertError::Parse(error) => Some(error),
            ConvertError::Message(_) => None,
        }
    }

    /// True for the error [`ParseError::non_finite_cell`] makes.
    pub fn is_non_finite_cell(&self) -> bool {
        self.parse_error()
            .is_some_and(ParseError::is_non_finite_cell)
    }

    /// [`ParseError::in_frame`] on a typed error. A message is returned as
    /// it was.
    #[must_use]
    pub fn in_frame(self, frame: u64) -> Self {
        match self {
            ConvertError::Parse(error) => ConvertError::Parse(error.in_frame(frame)),
            message => message,
        }
    }
}

impl fmt::Display for ConvertError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConvertError::Parse(error) => write!(f, "{error}"),
            ConvertError::Message(message) => f.write_str(message),
        }
    }
}

impl std::error::Error for ConvertError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ConvertError::Parse(error) => Some(error),
            ConvertError::Message(_) => None,
        }
    }
}

/// A [`ConvertError::Message`] equals its text. A typed error equals no
/// string.
impl PartialEq<str> for ConvertError {
    fn eq(&self, other: &str) -> bool {
        matches!(self, ConvertError::Message(message) if message == other)
    }
}

impl PartialEq<&str> for ConvertError {
    fn eq(&self, other: &&str) -> bool {
        self == *other
    }
}

impl From<ParseError> for ConvertError {
    fn from(error: ParseError) -> Self {
        ConvertError::Parse(error)
    }
}

impl From<String> for ConvertError {
    fn from(message: String) -> Self {
        ConvertError::Message(message)
    }
}

impl From<&str> for ConvertError {
    fn from(message: &str) -> Self {
        ConvertError::Message(message.to_string())
    }
}

/// The text of the error. [`ParseError::from_cell_text`] recovers a
/// non-finite cell error from it.
impl From<ConvertError> for String {
    fn from(error: ConvertError) -> Self {
        error.to_string()
    }
}

/// A parse failure plus the 1-based file line and 0-based frame index.
///
/// The line is the cursor that produced the error. Metadata helpers that
/// report line 2 are used only when that cursor is still 0.
#[derive(Debug)]
pub struct LocatedParseError {
    pub error: ParseError,
    pub line: u32,
    pub frame_index: u64,
}

impl LocatedParseError {
    pub fn new(error: ParseError, cursor_line: u32, frame_index: u64) -> Self {
        let line = if cursor_line != 0 {
            cursor_line
        } else {
            error.line()
        };
        Self {
            error: error.in_frame(frame_index),
            line,
            frame_index,
        }
    }
}

impl fmt::Display for LocatedParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.error)
    }
}

impl std::error::Error for LocatedParseError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.error)
    }
}
