pub mod array;
pub mod compression;
pub mod error;
pub mod ffi;
pub mod helpers;
pub mod iterators;
pub mod parser;
pub mod types;
pub mod units;
pub mod writer;

#[cfg(feature = "metatensor")]
pub mod metatensor_export;

/// Chemfiles multi-format import (real impl behind `chemfiles` feature; stubs otherwise).
pub mod chemfiles_import;

/// Chemfiles selection grammar on CON frames (real impl behind `chemfiles` feature; stubs otherwise).
pub mod chemfiles_selection;

#[cfg(feature = "rpc")]
pub mod rpc;

// Re-export for generated capnp code which references crate::ReadCon_capnp
#[cfg(feature = "rpc")]
pub use rpc::read_con_capnp as ReadCon_capnp;

#[cfg(feature = "python")]
pub mod python;

/// CON/convel format spec version implemented by this build.
///
/// - Version 1: column 5 present but semantics undefined. Readers MAY
///   ignore it. No JSON metadata line.
/// - Version 2: column 5 is the original atom index before type-based
///   grouping; JSON line 2 with at least `{"con_spec_version": 2}`.
/// - Version 3: same as v2 plus **required** `metadata["units"]` object
///   with non-empty `length` and `energy` unit strings (see `units` module).
///
/// See `docs/orgmode/spec.org` for the full specification.
pub const CON_SPEC_VERSION: u32 = 3;

/// Library version string, injected from Cargo.toml at compile time.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spec_version_is_current() {
        assert_eq!(CON_SPEC_VERSION, 3);
        assert_eq!(ffi::RKR_CON_SPEC_VERSION, CON_SPEC_VERSION);
    }

    #[test]
    fn test_version_matches_cargo() {
        assert_eq!(VERSION, "0.13.1");
    }
}
