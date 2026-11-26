//! Cargo does not compile a build script with `cfg(test)`.
//! This target includes the same module `build.rs` does, so
//! `cargo test` runs those link-plan tests.

#[path = "../support/python_link.rs"]
mod python_link;
