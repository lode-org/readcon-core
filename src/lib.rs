// A Rust library must not choose the process allocator for its consumers.
// Final readcon artifacts opt into mimalloc with `mimalloc-allocator`: glibc's
// allocator serializes the per-frame shells of a parallel parse on one arena
// lock, while mimalloc lets those shells allocate on the parsing thread.
// `asan_run` is set only for `-Zsanitizer=address`. mimalloc's `mi_free`
// ignores the size Rust passes, so that run uses the system allocator.
// `tsan_run` is set only for `-Zsanitizer=thread`. mimalloc is not built
// with TSan, so TSan cannot see a block freed on one thread and reused on
// another, and reports the reuse as a race. That run uses the system
// allocator too.
// Miri cannot execute mimalloc either, so it uses the system allocator too.
// `static_system_alloc` remains an explicit override for the C static archive
// and existing users, although system allocation is now the library default.
#![allow(unexpected_cfgs)]
#[cfg(all(
    feature = "mimalloc-allocator",
    not(any(asan_run, tsan_run, miri)),
    not(feature = "static_system_alloc")
))]
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

#[cfg(all(
    test,
    feature = "mimalloc-allocator",
    not(any(asan_run, tsan_run, miri)),
    not(feature = "static_system_alloc")
))]
mod allocator_link_tests {
    #[cfg(all(
        not(any(asan_run, tsan_run, miri)),
        not(feature = "static_system_alloc")
    ))]
    unsafe extern "C" {
        fn mi_usable_size(ptr: *const std::ffi::c_void) -> usize;
    }

    /// Final artifacts that opt in use this allocator. `mi_usable_size` is
    /// only meaningful for mimalloc. The static archive always opts out.
    #[test]
    fn the_shipped_allocator_is_mimalloc() {
        let boxed = Box::new([0u8; 32]);
        // SAFETY: `boxed` is live, non-null, and was allocated by the active
        // mimalloc global allocator; `mi_usable_size` only reads its metadata.
        let usable = unsafe { mi_usable_size(boxed.as_ptr() as *const std::ffi::c_void) };
        assert!(
            usable >= 32,
            "global allocator is not mimalloc (usable size {usable})"
        );
    }
}

pub mod array;
#[doc(hidden)]
pub mod columns;
pub mod compression;
pub mod conbin;
pub mod correspondence;
#[cfg(feature = "cuda")]
pub mod cuda_array;
pub mod distrib;
#[cfg(feature = "mpi")]
pub mod distrib_read;
#[cfg(feature = "mpi")]
pub mod distrib_write;
pub mod error;
pub mod extxyz_scan;
mod fast_dec;
#[cfg(feature = "capi")]
pub mod ffi;
pub mod frame_index;
#[cfg(feature = "grammar")]
pub mod grammar;
pub mod helpers;
pub mod hostlabel;
/// Campaign screening scalars / CON ingest contracts for corpus stores (`readcon-db`).
pub mod index_proj;
pub mod iterators;
#[cfg(all(test, feature = "mpi"))]
pub(crate) mod mpi_launch;
pub mod parser;
pub mod pdb_scan;
/// RCSO/RCSB cooked numerics for a caller-side broadcast. No MPI in this crate.
pub mod rcso;
pub mod storage_dtype;
pub mod stream;
pub mod trajectory;
pub mod types;
pub mod units;
pub mod writer;

/// Foreign path / CON → CON write for stack migration (CLI + library).
pub mod convert;

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
/// - Version 3: same as v2 plus **required** `units` object on JSON **line 2**
///   with non-empty `length` and `energy`. Writers emit canonical names
///   (`angstrom`, `eV`). A velocities section on minor 1 also requires
///   `units.time`. See `units::canonicalize_unit_expression`.
///
/// See `docs/orgmode/spec.org` for the full specification.
pub const CON_SPEC_VERSION: u32 = 3;

/// Minor implemented by this reader. Newer minors of major 3 are accepted.
/// An unknown section is skipped only when the frame minor is greater than
/// this value and `section_arity` gives the value-field count
/// (CON-section.8, CON-section.12, D14).
pub const CON_SPEC_MINOR: u32 = 1;

/// Library version string, taken from the package version at compile time.
/// `build.rs` checks that it matches the `VERSION` file.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Breaking-change major for the public C ABI (also carried on RPC stamps).
pub const RKR_ABI_VERSION_MAJOR: u32 = 2;
/// Additive-change minor for the public C ABI (also carried on RPC stamps).
pub const RKR_ABI_VERSION_MINOR: u32 = 0;
/// Layout revision for opaque handles and exported records.
pub const RKR_ABI_LAYOUT_REVISION: u32 = 0;

pub use correspondence::{
    CorrespondenceError, IdentityCheck, atom_id_permutation, check_atom_id_consistency,
    minimum_image_delta, minimum_image_displacements, reorder_like,
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spec_version_is_current() {
        assert_eq!(CON_SPEC_VERSION, 3);
        #[cfg(feature = "capi")]
        assert_eq!(ffi::RKR_CON_SPEC_VERSION, CON_SPEC_VERSION);
    }

    #[test]
    fn test_version_matches_source() {
        let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("VERSION");
        let text = std::fs::read_to_string(&path).unwrap();
        assert_eq!(text, format!("{VERSION}\n"));
    }
}
