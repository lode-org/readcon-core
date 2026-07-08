//! Foreign path or CON → multi-frame CON write (migration surface).
//!
//! Used by the CLI (`readcon-core convert …`) and callable from Rust without
//! inventing a second conversion stack. Non-CON inputs require the `chemfiles`
//! feature at runtime ([`chemfiles_import::chemfiles_enabled`]).

use std::fmt;
use std::io;
use std::path::Path;

use crate::chemfiles_import::{self, ChemfilesImportError};
use crate::compression;
use crate::iterators::ConFrameIterator;
use crate::types::ConFrame;
use crate::writer::ConFrameWriter;

/// Outcome of a successful convert.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConvertReport {
    /// Number of frames written.
    pub n_frames: usize,
    /// Atom count of the last frame (0 if no frames — should not happen on success).
    pub n_atoms_last: usize,
    /// True when the input was treated as native CON/convel (no chemfiles).
    pub native_con: bool,
}

/// Errors from path conversion.
#[derive(Debug)]
pub enum ConvertError {
    /// Input path does not exist or is not a file.
    InputMissing(String),
    /// No frames could be read.
    Empty,
    /// I/O while reading or writing.
    Io(io::Error),
    /// CON parse failure.
    Parse(String),
    /// Chemfiles import failure (includes feature disabled).
    Chemfiles(ChemfilesImportError),
}

impl fmt::Display for ConvertError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConvertError::InputMissing(p) => write!(f, "input not found: {p}"),
            ConvertError::Empty => write!(f, "no frames produced from input"),
            ConvertError::Io(e) => write!(f, "I/O error: {e}"),
            ConvertError::Parse(msg) => write!(f, "parse error: {msg}"),
            ConvertError::Chemfiles(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for ConvertError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ConvertError::Io(e) => Some(e),
            ConvertError::Chemfiles(e) => Some(e),
            _ => None,
        }
    }
}

impl From<io::Error> for ConvertError {
    fn from(e: io::Error) -> Self {
        ConvertError::Io(e)
    }
}

impl From<ChemfilesImportError> for ConvertError {
    fn from(e: ChemfilesImportError) -> Self {
        ConvertError::Chemfiles(e)
    }
}

/// True when the path looks like native CON/convel (including compressed suffixes).
pub fn path_looks_like_con(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    // strip compression
    let base = name
        .strip_suffix(".gz")
        .or_else(|| name.strip_suffix(".zst"))
        .unwrap_or(&name);
    base.ends_with(".con") || base.ends_with(".convel")
}

/// Read frames from a path: native CON/convel via the hot-path iterator, else chemfiles.
pub fn read_frames_for_convert(input: &Path) -> Result<(Vec<ConFrame>, bool), ConvertError> {
    if !input.is_file() {
        return Err(ConvertError::InputMissing(input.display().to_string()));
    }
    if path_looks_like_con(input) {
        // gzip/zstd-aware (same path as library readers)
        let contents = compression::read_file_contents(input).map_err(|e| {
            ConvertError::Io(io::Error::other(e.to_string()))
        })?;
        let text = contents
            .as_str()
            .map_err(|e| ConvertError::Parse(format!("input is not valid UTF-8: {e}")))?;
        let mut frames = Vec::new();
        for item in ConFrameIterator::new(text) {
            match item {
                Ok(f) => frames.push(f),
                Err(e) => {
                    return Err(ConvertError::Parse(e.to_string()));
                }
            }
        }
        if frames.is_empty() {
            return Err(ConvertError::Empty);
        }
        Ok((frames, true))
    } else {
        if !chemfiles_import::chemfiles_enabled() {
            return Err(ConvertError::Chemfiles(
                ChemfilesImportError::FeatureDisabled,
            ));
        }
        let frames = chemfiles_import::con_frames_from_trajectory_path(input)?;
        if frames.is_empty() {
            return Err(ConvertError::Empty);
        }
        Ok((frames, false))
    }
}

/// Convert `input` (CON or chemfiles-readable foreign format) to CON at `output`.
///
/// Returns a [`ConvertReport`]. Fails if the foreign path needs chemfiles and
/// this build is lean, or if zero frames are produced.
pub fn convert_path_to_con(input: &Path, output: &Path) -> Result<ConvertReport, ConvertError> {
    let (frames, native_con) = read_frames_for_convert(input)?;
    let n_frames = frames.len();
    let n_atoms_last = frames.last().map(|f| f.atom_data.len()).unwrap_or(0);
    let mut writer = ConFrameWriter::from_path(output)?;
    writer
        .extend(frames.iter())
        .map_err(|e| ConvertError::Io(io::Error::other(e.to_string())))?;
    Ok(ConvertReport {
        n_frames,
        n_atoms_last,
        native_con,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    fn fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/test")
            .join(name)
    }

    #[test]
    fn path_looks_like_con_suffixes() {
        assert!(path_looks_like_con(Path::new("a.con")));
        assert!(path_looks_like_con(Path::new("a.convel")));
        assert!(path_looks_like_con(Path::new("a.con.gz")));
        assert!(!path_looks_like_con(Path::new("a.xyz")));
        assert!(!path_looks_like_con(Path::new("a.pdb")));
    }

    #[test]
    fn convert_native_con_roundtrip() {
        let dir = tempfile_dir();
        let out = dir.join("out.con");
        let report = convert_path_to_con(&fixture("tiny_multi_cuh2.con"), &out).unwrap();
        assert!(report.native_con);
        assert_eq!(report.n_frames, 2);
        assert_eq!(report.n_atoms_last, 4);
        let (back, native) = read_frames_for_convert(&out).unwrap();
        assert!(native);
        assert_eq!(back.len(), 2);
        assert_eq!(back[0].atom_data.len(), 4);
        assert_eq!(back[0].atom_data[0].atom_id, 0);
    }

    #[test]
    #[cfg(feature = "chemfiles")]
    fn convert_xyz_via_chemfiles() {
        let dir = tempfile_dir();
        let xyz = dir.join("water.xyz");
        fs::write(
            &xyz,
            "3\nwater migrate\nO 0 0 0\nH 0.96 0 0\nH -0.24 0.93 0\n",
        )
        .unwrap();
        let out = dir.join("water.con");
        let report = convert_path_to_con(&xyz, &out).unwrap();
        assert!(!report.native_con);
        assert_eq!(report.n_frames, 1);
        assert_eq!(report.n_atoms_last, 3);
        let (back, _) = read_frames_for_convert(&out).unwrap();
        assert_eq!(back[0].atom_data.len(), 3);
        let symbols: Vec<_> = back[0]
            .atom_data
            .iter()
            .map(|a| a.symbol.as_ref())
            .collect();
        assert!(symbols.contains(&"O"));
        assert_eq!(symbols.iter().filter(|s| **s == "H").count(), 2);
    }

    #[test]
    #[cfg(not(feature = "chemfiles"))]
    fn convert_xyz_fails_without_chemfiles() {
        let dir = tempfile_dir();
        let xyz = dir.join("water.xyz");
        fs::write(&xyz, "3\nx\nO 0 0 0\nH 1 0 0\nH 0 1 0\n").unwrap();
        let out = dir.join("water.con");
        let err = convert_path_to_con(&xyz, &out).unwrap_err();
        assert!(matches!(
            err,
            ConvertError::Chemfiles(ChemfilesImportError::FeatureDisabled)
        ));
    }

    fn tempfile_dir() -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "readcon-convert-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }
}
