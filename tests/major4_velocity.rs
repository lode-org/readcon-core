//! C and C++ bindings write a major-4 frame with velocities and read
//! `units.time` and the velocity values back.

use std::path::Path;
use std::process::Command;

include!("metatensor_link.rs");

#[path = "common/plain_library.rs"]
mod plain_library;
use plain_library::library_dirs;

fn run_binding(compiler: &str, std_flag: &str, source_name: &str, binary_name: &str) {
    let dirs = library_dirs();
    if cfg!(feature = "python") && dirs.is_empty() {
        return;
    }
    assert!(
        !dirs.is_empty(),
        "a non-Python libreadcon_core was not next to the test binary"
    );
    let dir = tempfile::tempdir().unwrap();
    let source = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/c")
        .join(source_name);
    let binary = dir.path().join(binary_name);
    let mut command = Command::new(compiler);
    command
        .args([std_flag, "-Wall", "-Wextra", "-Werror", "-I", "include"])
        .arg(&source)
        .current_dir(env!("CARGO_MANIFEST_DIR"));
    for flag in link_flags_for(&dirs) {
        command.arg(flag);
    }
    let status = command.arg("-o").arg(&binary).status().expect(compiler);
    assert!(
        status.success(),
        "{compiler} failed to compile {source_name}"
    );
    let output = dir.path().join("major4.con");
    let run = Command::new(&binary)
        .arg(&output)
        .env("LD_LIBRARY_PATH", runtime_library_path(&dirs))
        .output()
        .unwrap_or_else(|err| panic!("{binary_name} failed to start: {err}"));
    assert!(
        run.status.success(),
        "{binary_name} failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&run.stdout),
        String::from_utf8_lossy(&run.stderr)
    );
}

#[test]
fn c_binding_round_trips_major4_velocity_and_units_time() {
    run_binding(
        "gcc",
        "-std=c11",
        "test_major4_velocity.c",
        "test_major4_velocity_c",
    );
}

#[test]
fn cpp_binding_round_trips_major4_velocity_and_units_time() {
    run_binding(
        "g++",
        "-std=c++17",
        "test_major4_velocity.cpp",
        "test_major4_velocity_cpp",
    );
}
