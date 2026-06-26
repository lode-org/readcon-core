//! Chemfiles → CON conversion.
//!
//! Real implementation requires the `chemfiles` Cargo feature (links libchemfiles).
//! Without it, path/memory helpers are still present and return
//! [`ChemfilesImportError::FeatureDisabled`] so call sites compile uniformly.

#[cfg(feature = "chemfiles")]
#[path = "chemfiles_import_imp.rs"]
mod imp;

#[cfg(feature = "chemfiles")]
pub use imp::*;

#[cfg(not(feature = "chemfiles"))]
mod stubs {
    use std::fmt;
    use std::path::Path;

    use crate::types::ConFrame;

    /// Prefix for unmapped chemfiles frame properties in CON metadata.
    pub const CHEMFILES_EXTRA_PREFIX: &str = "chemfiles::";
    /// Per-atom property bag key in frame metadata.
    pub const CHEMFILES_ATOM_PROPS_KEY: &str = "chemfiles_atom_properties";
    /// Display names in chemfiles / `atom_id` order.
    pub const CHEMFILES_ATOM_NAMES_KEY: &str = "chemfiles_atom_names";
    /// Atomic types in chemfiles / `atom_id` order.
    pub const CHEMFILES_ATOM_TYPES_KEY: &str = "chemfiles_atom_types";

    /// Errors from chemfiles I/O or conversion (or missing feature).
    #[derive(Debug)]
    pub enum ChemfilesImportError {
        /// Atom / property count mismatch or other structural problem.
        InvalidFrame(String),
        /// I/O while reading a trajectory path.
        Io(std::io::Error),
        /// This build was compiled without the `chemfiles` Cargo feature.
        FeatureDisabled,
    }

    impl fmt::Display for ChemfilesImportError {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            match self {
                ChemfilesImportError::InvalidFrame(msg) => {
                    write!(f, "invalid chemfiles frame: {msg}")
                }
                ChemfilesImportError::Io(e) => write!(f, "I/O error: {e}"),
                ChemfilesImportError::FeatureDisabled => write!(
                    f,
                    "chemfiles support is not enabled in this build; rebuild with `--features chemfiles` \
(Python: `maturin develop --features python,chemfiles` or install the `chemfiles` extra from source — see docs)"
                ),
            }
        }
    }

    impl std::error::Error for ChemfilesImportError {
        fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
            match self {
                ChemfilesImportError::Io(e) => Some(e),
                ChemfilesImportError::InvalidFrame(_) | ChemfilesImportError::FeatureDisabled => {
                    None
                }
            }
        }
    }

    impl From<std::io::Error> for ChemfilesImportError {
        fn from(e: std::io::Error) -> Self {
            ChemfilesImportError::Io(e)
        }
    }

    fn disabled<T>() -> Result<T, ChemfilesImportError> {
        Err(ChemfilesImportError::FeatureDisabled)
    }

    /// Open a trajectory with chemfiles and convert every step to [`ConFrame`].
    ///
    /// Stub without the `chemfiles` feature — always returns [`ChemfilesImportError::FeatureDisabled`].
    pub fn con_frames_from_trajectory_path<P: AsRef<Path>>(
        _path: P,
    ) -> Result<Vec<ConFrame>, ChemfilesImportError> {
        disabled()
    }

    /// Read the first frame from a trajectory path.
    ///
    /// Stub without the `chemfiles` feature — always returns [`ChemfilesImportError::FeatureDisabled`].
    pub fn con_frame_from_trajectory_path<P: AsRef<Path>>(
        _path: P,
    ) -> Result<ConFrame, ChemfilesImportError> {
        disabled()
    }

    /// Read a trajectory from an in-memory buffer (chemfiles memory reader).
    ///
    /// Stub without the `chemfiles` feature — always returns [`ChemfilesImportError::FeatureDisabled`].
    pub fn con_frames_from_memory(
        _data: &str,
        _format: &str,
    ) -> Result<Vec<ConFrame>, ChemfilesImportError> {
        disabled()
    }

    /// Whether this build linked libchemfiles and implements import/selection.
    pub const fn chemfiles_enabled() -> bool {
        false
    }
}

#[cfg(not(feature = "chemfiles"))]
pub use stubs::*;

#[cfg(feature = "chemfiles")]
/// Whether this build linked libchemfiles and implements import/selection.
pub const fn chemfiles_enabled() -> bool {
    true
}

#[cfg(test)]
mod stub_tests {
    use super::*;

    #[test]
    fn chemfiles_enabled_matches_feature() {
        assert_eq!(chemfiles_enabled(), cfg!(feature = "chemfiles"));
    }

    #[cfg(not(feature = "chemfiles"))]
    #[test]
    fn trajectory_path_stub_is_feature_disabled() {
        let err = con_frame_from_trajectory_path("nope.xyz").unwrap_err();
        assert!(matches!(err, ChemfilesImportError::FeatureDisabled));
        let msg = err.to_string();
        assert!(msg.contains("chemfiles"), "{msg}");
    }
}
