//! Compile and run the C, C++, and Fortran examples, and the Rust spec query.

use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;

static CWD: Mutex<()> = Mutex::new(());

fn plain_library(dir: &std::path::Path) -> bool {
    let so = dir.join("libreadcon_core.so");
    if !so.is_file() {
        return dir.join("libreadcon_core.a").is_file();
    }
    // A Python extension defines PyExc_* and cannot link a C example alone.
    let listed = Command::new("nm")
        .args(["-D"])
        .arg(&so)
        .output()
        .map(|out| String::from_utf8_lossy(&out.stdout).into_owned())
        .unwrap_or_default();
    !listed.contains("PyExc_BaseException")
}

fn library_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    let mut dir = std::env::current_exe().unwrap();
    dir.pop();
    for _ in 0..8 {
        if plain_library(&dir) {
            dirs.push(dir.clone());
        }
        if !dir.pop() {
            break;
        }
    }
    let build = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/debug/build/readcon-core");
    if let Ok(entries) = fs::read_dir(&build) {
        for entry in entries.flatten() {
            let out = entry.path().join("out");
            if plain_library(&out) {
                dirs.push(out);
            }
        }
    }
    assert!(
        !dirs.is_empty(),
        "a non-Python libreadcon_core was not next to the test binary"
    );
    dirs
}

fn link_flags() -> Vec<String> {
    let mut flags = Vec::new();
    for dir in library_dirs() {
        flags.push(format!("-L{}", dir.display()));
        flags.push(format!("-Wl,-rpath,{}", dir.display()));
    }
    flags.push("-lreadcon_core".to_string());
    flags
}

fn gxx() -> String {
    std::env::var("CXX").unwrap_or_else(|_| "g++".to_string())
}

#[test]
fn c_and_cpp_examples_match_frames_by_atom_id() {
    let dir = tempfile::tempdir().unwrap();
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/c/test_doc_examples.cpp");
    let binary = dir.path().join("test_doc_examples");
    let mut command = Command::new(gxx());
    command
        .args(["-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", "include"])
        .arg(&source);
    for flag in link_flags() {
        command.arg(flag);
    }
    let status = command.arg("-o").arg(&binary).output().expect("g++");
    assert!(
        status.status.success(),
        "g++ failed to compile the documented C and C++ calls\n{}",
        String::from_utf8_lossy(&status.stderr)
    );
    let run = Command::new(&binary)
        .arg(dir.path())
        .env(
            "LD_LIBRARY_PATH",
            library_dirs()
                .iter()
                .map(|path| path.display().to_string())
                .collect::<Vec<_>>()
                .join(":"),
        )
        .status()
        .expect("run documented C and C++ example");
    assert!(run.success(), "documented C and C++ example failed");
}

#[test]
fn fortran_add_atom_example_links() {
    let gfortran = std::env::var("FC").unwrap_or_else(|_| "gfortran".to_string());
    if Command::new(&gfortran).arg("--version").status().is_err() {
        panic!("{gfortran} is required to compile the Fortran example");
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dir = tempfile::tempdir().unwrap();
    let module_src = root.join("fortran/ReadCon/src/readcon.f90");
    let program = dir.path().join("doc_add_atom.f90");
    fs::write(
        &program,
        r#"program doc_add_atom
  use readcon
  use, intrinsic :: iso_fortran_env, only: int64, real64
  implicit none
  type(builder_t) :: bd
  integer :: st
  real(real64) :: vel(3), frc(3)
  vel = [0.1d0, 0.0d0, 0.0d0]
  frc = [0.0d0, 0.0d0, 0.0d0]
  bd = new_builder([10.0d0, 10.0d0, 10.0d0], [90.0d0, 90.0d0, 90.0d0])
  st = bd%add_atom("H", 0.0d0, 0.0d0, 0.0d0, .false., .false., .false., &
       1_int64, 1.0d0)
  if (st /= 0) error stop 1
  st = bd%add_atom_full("H", 0.0d0, 0.0d0, 0.0d0, .false., .false., .false., &
       1_int64, 1.0d0, velocity=vel, force=frc)
  if (st /= 0) error stop 2
end program
"#,
    )
    .unwrap();
    let module_obj = dir.path().join("readcon.o");
    let compiled = Command::new(&gfortran)
        .args(["-c", "-J"])
        .arg(dir.path())
        .arg(&module_src)
        .arg("-o")
        .arg(&module_obj)
        .status()
        .expect("gfortran module");
    assert!(compiled.success(), "gfortran failed on readcon.f90");
    let binary = dir.path().join("doc_add_atom");
    let mut command = Command::new(&gfortran);
    command.arg(&program).arg(&module_obj);
    for flag in link_flags() {
        command.arg(flag);
    }
    let linked = command
        .arg("-o")
        .arg(&binary)
        .output()
        .expect("gfortran link");
    assert!(
        linked.status.success(),
        "gfortran failed to link the documented add_atom calls\n{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    let run = Command::new(&binary)
        .env(
            "LD_LIBRARY_PATH",
            library_dirs()
                .iter()
                .map(|path| path.display().to_string())
                .collect::<Vec<_>>()
                .join(":"),
        )
        .status()
        .expect("run fortran example");
    assert!(run.success(), "documented Fortran add_atom example failed");
}

#[test]
fn howto_rust_spec_query_reads_a_frame() {
    let _cwd = CWD.lock().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("input.con");
    let mut builder =
        readcon_core::types::ConFrameBuilder::new([10.0, 10.0, 10.0], [90.0, 90.0, 90.0]);
    builder.add_atom("H", 0.0, 0.0, 0.0, [false; 3], 1, 1.0);
    let frame = builder.build().unwrap();
    readcon_core::writer::ConFrameWriter::from_path(&path)
        .unwrap()
        .write_frame(&frame)
        .unwrap();
    let previous = std::env::current_dir().unwrap();
    std::env::set_current_dir(dir.path()).unwrap();
    let result = std::panic::catch_unwind(|| {
        use readcon_core::{CON_SPEC_VERSION, VERSION};
        assert_eq!(CON_SPEC_VERSION, 3);
        println!("readcon-core {} (spec v{})", VERSION, CON_SPEC_VERSION);
        use readcon_core::iterators::read_first_frame;
        let frame = read_first_frame(std::path::Path::new("input.con")).unwrap();
        println!("File spec version: {}", frame.header.spec_version);
        println!("Extra metadata: {:?}", frame.header.metadata);
        assert_eq!(frame.header.spec_version, 3);
    });
    std::env::set_current_dir(previous).unwrap();
    result.unwrap();
}
