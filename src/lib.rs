pub mod error;
pub mod ffi;
pub mod helpers;
pub mod iterators;
pub mod parser;
pub mod types;
pub mod writer;

#[cfg(feature = "rpc")]
pub mod rpc;

#[cfg(feature = "python")]
pub mod python;

/// CON/convel format spec version implemented by this build.
///
/// - Version 1: column 5 present but semantics undefined. Readers MAY ignore it.
/// - Version 2: column 5 is the original atom index before type-based grouping.
///   Readers MUST parse and preserve it. Writers MUST write the stored value.
pub const CON_SPEC_VERSION: u32 = 2;

/// Library version string, injected from Cargo.toml at compile time.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spec_version_is_2() {
        assert_eq!(CON_SPEC_VERSION, 2);
        assert_eq!(ffi::RKR_CON_SPEC_VERSION, CON_SPEC_VERSION);
    }

    #[test]
    fn test_version_matches_cargo() {
        assert_eq!(VERSION, "0.5.0");
    }
}
