//! Scratch directory for unit tests and doctests.
//!
//! Cargo does not set `CARGO_TARGET_TMPDIR` for those. The directory is
//! `build/test` under this crate, which is gitignored. Nothing on the
//! read or write path calls [`root`]; a library build does not create
//! the directory until a test or doctest does.

use std::path::PathBuf;

/// `build/test` under the crate root, created when it is missing.
pub fn root() -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("build")
        .join("test");
    std::fs::create_dir_all(&dir).expect("create build/test");
    dir
}
