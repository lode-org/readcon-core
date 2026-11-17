//! The C API and the C++ wrapper refuse a NaN or infinite cell.

use std::path::Path;
use std::process::Command;

include!("metatensor_link.rs");

#[path = "common/plain_library.rs"]
mod plain_library;
use plain_library::library_dirs;

#[test]
fn cpp_builder_and_reader_refuse_a_non_finite_cell() {
    let dirs = library_dirs();
    if cfg!(feature = "python") && dirs.is_empty() {
        return;
    }
    assert!(
        !dirs.is_empty(),
        "a non-Python libreadcon_core was not next to the test binary"
    );
    let dir = tempfile::tempdir().unwrap();
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/c/test_cell_finite.cpp");
    let binary = dir.path().join("test_cell_finite");
    let mut command = Command::new("g++");
    command
        .args(["-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", "include"])
        .arg(&source);
    for flag in link_flags_for(&dirs) {
        command.arg(flag);
    }
    let status = command.arg("-o").arg(&binary).status().expect("g++");
    assert!(status.success(), "g++ failed to compile the cell test");
    let run = Command::new(&binary)
        .arg(dir.path())
        .env("LD_LIBRARY_PATH", runtime_library_path(&dirs))
        .status()
        .expect("run cell test");
    assert!(run.success(), "a non-finite cell was accepted");
}
