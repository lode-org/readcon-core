//! Accepted-corpus rewrites through C, Python, Julia, and Fortran.

use readcon_core::iterators::read_all_frames;
use readcon_core::writer::{ConFrameWriter, binding_rewrite_frame};
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

struct Accepted {
    id: String,
    path: String,
}

fn unquote(raw: &str) -> String {
    let text = raw.trim();
    if text.len() >= 2 && text.starts_with('"') && text.ends_with('"') {
        text[1..text.len() - 1].to_string()
    } else {
        text.to_string()
    }
}

fn accepted_cases() -> Vec<Accepted> {
    let text = std::fs::read_to_string(repo_root().join("resources/conformance/manifest.toml"))
        .expect("conformance manifest");
    let mut cases = Vec::new();
    let mut valid = false;
    let mut current: Option<Accepted> = None;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if line == "[[valid]]" || line == "[[invalid]]" {
            if valid {
                if let Some(case) = current.take() {
                    cases.push(case);
                }
            }
            valid = line == "[[valid]]";
            current = valid.then(|| Accepted {
                id: String::new(),
                path: String::new(),
            });
            continue;
        }
        if !valid {
            continue;
        }
        let Some((key, val)) = line.split_once('=') else {
            continue;
        };
        let case = current.as_mut().expect("valid case");
        match key.trim() {
            "id" => case.id = unquote(val),
            "path" => case.path = unquote(val),
            _ => {}
        }
    }
    if valid {
        if let Some(case) = current {
            cases.push(case);
        }
    }
    cases
}

fn write_bytes(frames: &[readcon_core::types::ConFrame]) -> Vec<u8> {
    let mut buf = Vec::new();
    {
        let mut writer = ConFrameWriter::new(&mut buf);
        writer.extend(frames.iter()).expect("write");
    }
    buf
}

#[test]
fn binding_rewrite_emits_con_spec_minor_for_every_accepted_file() {
    let root = repo_root().join("resources/conformance");
    let cases = accepted_cases();
    assert!(
        cases.len() >= 10,
        "expected the accepted corpus, found {}",
        cases.len()
    );
    for case in &cases {
        let frames = read_all_frames(&root.join(&case.path)).unwrap_or_else(|err| {
            panic!("{}: {err}", case.id);
        });
        assert!(!frames.is_empty(), "{}: no frames", case.id);
        let rewritten: Vec<_> = frames
            .iter()
            .map(|frame| {
                binding_rewrite_frame(frame).unwrap_or_else(|err| panic!("{}: {err}", case.id))
            })
            .collect();
        let text = String::from_utf8(write_bytes(&rewritten)).expect("utf-8");
        let metadata_lines: Vec<_> = text.lines().filter(|line| line.starts_with('{')).collect();
        assert!(
            !metadata_lines.is_empty(),
            "{}: rewrite produced no JSON metadata line",
            case.id
        );
        for line in metadata_lines {
            assert!(
                line.contains("\"con_spec_minor\":"),
                "{}: metadata line lacks con_spec_minor: {line}",
                case.id
            );
        }
    }
}

fn frame_with_every_section() -> readcon_core::types::ConFrame {
    use readcon_core::types::ConFrameBuilder;
    let mut builder = ConFrameBuilder::new([10.0, 11.0, 12.0], [90.0, 90.0, 90.0]);
    builder
        .add_atom("Cu", 1.0, 2.0, 3.0, [false, false, true], 7, 63.546)
        .with_velocity([0.1, 0.2, 0.3])
        .with_force([1.0, 0.0, -1.0])
        .with_energy(-1.5)
        .with_charge(0.25)
        .with_spin(0.5)
        .with_magmom([0.0, 0.0, 1.25])
        .with_displacement([0.01, 0.02, 0.03])
        .with_spread([0.04, 0.05, 0.06]);
    builder.build().expect("section frame")
}

fn time_label(frame: &readcon_core::types::ConFrame) -> Option<&str> {
    use readcon_core::types::meta;
    frame
        .header
        .metadata
        .get(meta::UNITS)
        .and_then(|units| units.get("time"))
        .and_then(|time| time.as_str())
}

#[test]
fn binding_rewrite_stamps_legacy_velocity_time_and_keeps_sections() {
    use readcon_core::types::meta;
    use readcon_core::units::NATURAL_TIME_UNIT;
    use serde_json::json;

    let built = frame_with_every_section();
    let atom = &built.atom_data[0];
    assert_eq!(atom.velocity(), Some([0.1, 0.2, 0.3]));
    // v3 minor 1 already carries the label contract, so the stamp returns.
    let kept = binding_rewrite_frame(&built).expect("rewrite minor 1");
    let kept_atom = &kept.atom_data[0];
    assert_eq!(kept_atom.velocity(), Some([0.1, 0.2, 0.3]));
    assert_eq!(kept_atom.force(), Some([1.0, 0.0, -1.0]));
    assert_eq!(kept_atom.energy(), Some(-1.5));
    assert_eq!(kept_atom.charge(), Some(0.25));
    assert_eq!(kept_atom.spin(), Some(0.5));
    assert_eq!(kept_atom.magmom(), Some([0.0, 0.0, 1.25]));
    assert_eq!(kept_atom.displacement(), Some([0.01, 0.02, 0.03]));
    assert_eq!(kept_atom.spread(), Some([0.04, 0.05, 0.06]));
    assert_eq!(time_label(&kept), None);

    let mut legacy = built.clone();
    legacy.header.spec_version = 2;
    legacy
        .header
        .metadata
        .insert(meta::CON_SPEC_MINOR.into(), json!(0));
    legacy.header.metadata.insert(
        meta::UNITS.into(),
        json!({"length": "angstrom", "energy": "eV", "mass": "amu"}),
    );
    let stamped = binding_rewrite_frame(&legacy).expect("rewrite v2 units object");
    assert_eq!(time_label(&stamped), Some(NATURAL_TIME_UNIT));
    assert_eq!(
        stamped
            .header
            .metadata
            .get(meta::CON_SPEC_MINOR)
            .and_then(|minor| minor.as_u64()),
        Some(1)
    );
    assert_eq!(stamped.atom_data[0].velocity(), Some([0.1, 0.2, 0.3]));

    let mut bare = built.clone();
    bare.header.spec_version = 1;
    bare.header.metadata.remove(meta::UNITS);
    bare.header.metadata.remove(meta::CON_SPEC_MINOR);
    let filled = binding_rewrite_frame(&bare).expect("rewrite without units");
    assert_eq!(time_label(&filled), Some(NATURAL_TIME_UNIT));

    let mut odd = built.clone();
    odd.header.spec_version = 2;
    odd.header
        .metadata
        .insert(meta::CON_SPEC_MINOR.into(), json!(0));
    odd.header.metadata.insert(meta::UNITS.into(), json!("fs"));
    let left = binding_rewrite_frame(&odd).expect("rewrite non-object units");
    assert_eq!(
        left.header
            .metadata
            .get(meta::UNITS)
            .and_then(|units| units.as_str()),
        Some("fs")
    );
    assert_eq!(left.atom_data[0].force(), Some([1.0, 0.0, -1.0]));
}

#[test]
fn compressed_path_writers_round_trip_a_frame() {
    use readcon_core::types::ConFrameBuilder;
    let mut builder = ConFrameBuilder::new([10.0, 11.0, 12.0], [90.0, 90.0, 90.0]);
    builder.add_atom("Cu", 1.0, 2.0, 3.0, [false; 3], 7, 63.546);
    let frame = builder.build().expect("plain frame");
    let dir = tempfile::tempdir().expect("tempdir");

    let gz = dir.path().join("frame.con.gz");
    {
        let mut writer = ConFrameWriter::from_path_gzip(&gz).expect("gzip writer");
        writer.extend(std::iter::once(&frame)).expect("write gzip");
    }
    let read = read_all_frames(&gz).expect("read gzip");
    assert_eq!(read.len(), 1);
    assert_eq!(read[0].atom_data[0].atom_id, 7);

    #[cfg(feature = "zstd")]
    {
        let zs = dir.path().join("frame.con.zst");
        {
            let mut writer = ConFrameWriter::from_path_zstd(&zs).expect("zstd writer");
            writer.extend(std::iter::once(&frame)).expect("write zstd");
        }
        let read = read_all_frames(&zs).expect("read zstd");
        assert_eq!(read.len(), 1);
        assert_eq!(read[0].atom_data[0].atom_id, 7);
    }
}

fn tool_runs(name: &str) -> bool {
    Command::new(name)
        .arg("--version")
        .output()
        .is_ok_and(|out| out.status.success())
}

fn exports_symbol(lib: &Path, symbol: &str) -> bool {
    let Ok(out) = Command::new("nm").arg("-D").arg(lib).output() else {
        return false;
    };
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .any(|line| line.split_whitespace().nth(2) == Some(symbol))
}

fn is_fresh(path: &Path) -> bool {
    let Ok(built) = std::fs::metadata(path).and_then(|meta| meta.modified()) else {
        return false;
    };
    for rel in [
        "src/writer.rs",
        "src/ffi.rs",
        "src/python.rs",
        "src/types.rs",
        "fortran/ReadCon/src/readcon.f90",
        "include/readcon-core.h",
        "include/readcon-core-mpi.h",
        "src/distrib_write.rs",
        "examples/eon_mpi_band.cpp",
    ] {
        let Ok(modified) =
            std::fs::metadata(repo_root().join(rel)).and_then(|meta| meta.modified())
        else {
            continue;
        };
        if modified > built {
            return false;
        }
    }
    true
}

fn usable(path: &Path, python_extension: bool) -> bool {
    path.is_file() && is_fresh(path) && exports_symbol(path, "PyInit_readcon") == python_extension
}

fn cargo_lib(target_dir: &Path, features: &[&str]) -> PathBuf {
    let mut cmd = Command::new("cargo");
    cmd.current_dir(repo_root())
        .args(["build", "--lib", "--target-dir"])
        .arg(target_dir);
    if !features.is_empty() {
        cmd.arg("--features").arg(features.join(","));
    }
    let status = cmd
        .status()
        .unwrap_or_else(|err| panic!("cargo build --lib failed to start: {err}"));
    assert!(status.success(), "cargo build --lib failed");
    let lib = target_dir.join("debug/libreadcon_core.so");
    assert!(lib.is_file(), "missing {}", lib.display());
    lib
}

/// Plain cdylib for C, Fortran, and Julia, plus the Python extension.
///
/// `cargo test` does not emit the cdylib. A Python-enabled build leaves
/// libpython unresolved, and Julia refuses to load that file. Side target
/// directories keep these builds off the lock `cargo test` already holds.
fn binding_libraries() -> (PathBuf, PathBuf) {
    let root = repo_root();
    let debug = root.join("target/debug/libreadcon_core.so");
    let plain_dir = root.join("target/binding-plain");
    let py_dir = root.join("target/binding-py");
    let plain_side = plain_dir.join("debug/libreadcon_core.so");
    let py_side = py_dir.join("debug/libreadcon_core.so");
    let plain = if usable(&debug, false) {
        debug.clone()
    } else if usable(&plain_side, false) {
        plain_side
    } else {
        cargo_lib(&plain_dir, &[])
    };
    let python = if usable(&debug, true) {
        debug
    } else if usable(&py_side, true) {
        py_side
    } else {
        cargo_lib(&py_dir, &["python"])
    };
    (plain, python)
}

/// cdylib built with the mpi feature, for the C++ and Fortran collective writers.
fn mpi_library() -> Option<PathBuf> {
    for tool in ["mpicxx", "mpifort", "mpirun", "mpicc"] {
        if !tool_runs(tool) {
            eprintln!("skip MPI cross-binding rewrite: {tool} is not installed");
            return None;
        }
    }
    let root = repo_root();
    let candidates = [
        root.join("target/binding-mpi/debug/libreadcon_core.so"),
        root.join("target/debug/libreadcon_core.so"),
    ];
    for candidate in &candidates {
        if candidate.is_file()
            && is_fresh(candidate)
            && exports_symbol(candidate, "rkr_mpi_write_block_f")
        {
            return Some(candidate.clone());
        }
    }
    let dir = root.join("target/binding-mpi");
    let mut cmd = Command::new("cargo");
    cmd.current_dir(&root)
        .args(["build", "--lib", "--features", "mpi", "--target-dir"])
        .arg(&dir)
        .env("MPICC", "mpicc");
    let status = cmd
        .status()
        .unwrap_or_else(|err| panic!("cargo build --features mpi failed to start: {err}"));
    assert!(status.success(), "cargo build --features mpi failed");
    let lib = dir.join("debug/libreadcon_core.so");
    assert!(
        lib.is_file() && exports_symbol(&lib, "rkr_mpi_write_block_f"),
        "mpi build did not export rkr_mpi_write_block_f"
    );
    Some(lib)
}

#[test]
fn accepted_corpus_rewrites_are_byte_identical() {
    for tool in ["cc", "gfortran", "julia", "python3", "nm"] {
        if !tool_runs(tool) {
            eprintln!("skip cross-binding rewrite: {tool} is not installed");
            return;
        }
    }
    let (plain, python) = binding_libraries();
    let mut lib_path = plain.parent().unwrap_or(Path::new(".")).to_path_buf();
    if let Some(py_parent) = python.parent()
        && py_parent != lib_path.as_path()
    {
        lib_path = PathBuf::from(format!("{}:{}", lib_path.display(), py_parent.display()));
    }
    let script = repo_root().join("tests/cross_binding_rewrite.py");
    let mut cmd = Command::new("python3");
    cmd.arg(&script)
        .env("READCON_CORE_LIB", &plain)
        .env("READCON_PYTHON_LIB", &python)
        .env("LD_LIBRARY_PATH", &lib_path);
    if let Some(mpi_lib) = mpi_library() {
        let mut path = lib_path.clone();
        if let Some(parent) = mpi_lib.parent()
            && parent != path.as_path()
        {
            path = PathBuf::from(format!("{}:{}", parent.display(), path.display()));
        }
        cmd.env("READCON_MPI_LIB", &mpi_lib)
            .env("LD_LIBRARY_PATH", &path);
    }
    let status = cmd
        .status()
        .unwrap_or_else(|err| panic!("failed to run {}: {err}", script.display()));
    assert!(status.success(), "cross-binding rewrite comparison failed");
}
