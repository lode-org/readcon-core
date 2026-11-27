//! The Python module and a second PyO3 extension that consumes the default
//! readcon rlib must coexist even after the process static-TLS reserve is full.

use std::path::{Path, PathBuf};
use std::process::Command;

#[cfg(target_os = "linux")]
fn assert_production_cdylib_omits_libpython(dynamic: &str) {
    let needed: Vec<&str> = dynamic
        .lines()
        .filter_map(|line| {
            let (_, rest) = line.split_once("Shared library: [")?;
            Some(rest.trim_end_matches(']').trim())
        })
        .collect();
    let linked: Vec<&str> = needed
        .into_iter()
        .filter(|name| {
            let lower = name.to_ascii_lowercase();
            lower.contains("libpython")
                || lower.contains("python.framework")
                || lower.starts_with("python3")
                || lower == "python"
        })
        .collect();
    assert!(
        linked.is_empty(),
        "production cdylib NEEDED libpython or a Python framework: {linked:?}\n{dynamic}"
    );
    assert!(
        !dynamic.to_ascii_lowercase().contains("python.framework"),
        "production cdylib records a Python framework link:\n{dynamic}"
    );
}

fn work_dir() -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let base = std::env::var_os("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .map(|path| {
            if path.is_absolute() {
                path
            } else {
                root.join(path)
            }
        })
        .unwrap_or_else(|| root.join("target"));
    base.join("python-rlib-dlopen")
}

#[cfg(target_os = "linux")]
#[test]
fn python_module_and_rlib_consumer_load_together() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let work = work_dir();
    let _ = std::fs::remove_dir_all(&work);
    std::fs::create_dir_all(work.join("consumer/src")).expect("consumer source");

    let wheel_target = work.join("wheel-target");
    // Same switch maturin >= 1.9.4 exports so the cdylib does not link libpython.
    let wheel_build = Command::new("cargo")
        .args([
            "rustc",
            "--locked",
            "--release",
            "--lib",
            "--features",
            "python",
            "--crate-type",
            "cdylib",
            "--target-dir",
        ])
        .arg(&wheel_target)
        .env("PYO3_BUILD_EXTENSION_MODULE", "1")
        .arg("--manifest-path")
        .arg(root.join("Cargo.toml"))
        .status()
        .expect("cargo rustc wheel module");
    assert!(wheel_build.success(), "Python module build failed");
    let wheel = wheel_target.join("release/libreadcon_core.so");
    assert!(wheel.is_file(), "missing {}", wheel.display());
    let wheel_symbols = Command::new("nm")
        .args(["--defined-only", wheel.to_str().unwrap()])
        .output()
        .expect("nm wheel module");
    assert!(wheel_symbols.status.success());
    assert!(
        String::from_utf8_lossy(&wheel_symbols.stdout)
            .lines()
            .any(|line| line
                .split_whitespace()
                .last()
                .is_some_and(|symbol| symbol.starts_with("mi_"))),
        "Python module contains no defined mimalloc symbol"
    );
    let wheel_dynamic = Command::new("readelf")
        .args(["-d", wheel.to_str().unwrap()])
        .output()
        .expect("readelf wheel dynamic section");
    assert!(wheel_dynamic.status.success());
    let dynamic = String::from_utf8_lossy(&wheel_dynamic.stdout);
    assert!(
        !dynamic.contains("STATIC_TLS"),
        "Python module sets DF_STATIC_TLS"
    );
    assert_production_cdylib_omits_libpython(&dynamic);
    let wheel_relocs = Command::new("readelf")
        .args(["-r", wheel.to_str().unwrap()])
        .output()
        .expect("readelf wheel relocations");
    assert!(wheel_relocs.status.success());
    assert!(
        !String::from_utf8_lossy(&wheel_relocs.stdout).contains("TPOFF"),
        "Python module contains initial-exec TLS relocations"
    );

    let manifest = format!(
        r#"[package]
name = "readcon-rlib-consumer"
version = "0.0.0"
edition = "2024"

[lib]
name = "_consumer"
crate-type = ["cdylib"]

[dependencies]
pyo3 = {{ version = "0.28", features = ["extension-module"] }}
readcon-core = {{ path = "{}" }}
"#,
        root.display()
    );
    std::fs::write(work.join("consumer/Cargo.toml"), manifest).expect("consumer manifest");
    std::fs::write(
        work.join("consumer/src/lib.rs"),
        r#"use pyo3::prelude::*;

#[pyfunction]
fn atomic_number(symbol: &str) -> u64 {
    readcon_core::helpers::symbol_to_atomic_number(symbol)
}

#[pymodule]
fn _consumer(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(atomic_number, module)?)?;
    Ok(())
}
"#,
    )
    .expect("consumer source");

    let consumer_target = work.join("consumer-target");
    let consumer_build = Command::new("cargo")
        .args(["build", "--release", "--offline", "--target-dir"])
        .arg(&consumer_target)
        .current_dir(work.join("consumer"))
        .status()
        .expect("cargo build consumer");
    assert!(consumer_build.success(), "consumer extension build failed");
    let consumer = consumer_target.join("release/lib_consumer.so");
    assert!(consumer.is_file(), "missing {}", consumer.display());
    let consumer_symbols = Command::new("nm")
        .args(["--defined-only", consumer.to_str().unwrap()])
        .output()
        .expect("nm consumer");
    assert!(consumer_symbols.status.success());
    assert!(
        !String::from_utf8_lossy(&consumer_symbols.stdout)
            .lines()
            .any(|line| line
                .split_whitespace()
                .last()
                .is_some_and(|s| s.starts_with("mi_"))),
        "default rlib consumer contains mimalloc"
    );

    let wheel_module = work.join("readcon.so");
    let consumer_module = work.join("_consumer.so");
    std::fs::copy(&wheel, &wheel_module).expect("copy wheel module");
    std::fs::copy(&consumer, &consumer_module).expect("copy consumer module");

    let script = r#"
import ctypes
import importlib.util
import subprocess
import sys
from pathlib import Path

work = Path(sys.argv[1])
src = work / "filler.c"
src.write_text("__thread char slot[65536]; int bump(void) { slot[0] += 1; return slot[0]; }\n")
fillers = []
for i in range(64):
    path = work / f"filler-{i}.so"
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-ftls-model=initial-exec", "-o", str(path), str(src)],
        check=True,
    )
    try:
        fillers.append(ctypes.CDLL(str(path)))
    except OSError as err:
        if "static TLS" not in str(err):
            raise
        break
else:
    raise SystemExit("64 initial-exec objects did not exhaust static TLS")

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"no import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

readcon = load("readcon", work / "readcon.so")
consumer = load("_consumer", work / "_consumer.so")
if consumer.atomic_number("Cu") != 29:
    raise SystemExit("rlib consumer returned the wrong value")
print(f"coexist-ok fillers={len(fillers)}")
"#;
    let output = Command::new("python3")
        .arg("-c")
        .arg(script)
        .arg(&work)
        .output()
        .expect("python");
    assert!(
        output.status.success(),
        "coexistence load failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
