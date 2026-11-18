//! A default Rust dependency must not install an allocator in its consumer.

use std::path::{Path, PathBuf};
use std::process::Command;

fn work_dir(name: &str) -> PathBuf {
    let base = std::env::var_os("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("target"));
    base.join(name)
}

#[cfg(target_os = "linux")]
#[test]
fn default_rlib_defines_no_allocator_shim_or_mimalloc() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let target = work_dir("rlib-system-alloc");
    let _ = std::fs::remove_dir_all(&target);
    let built = Command::new("cargo")
        .args([
            "rustc",
            "--locked",
            "--release",
            "--lib",
            "--crate-type",
            "rlib",
            "--target-dir",
        ])
        .arg(&target)
        .arg("--manifest-path")
        .arg(root.join("Cargo.toml"))
        .status()
        .expect("cargo rustc");
    assert!(built.success(), "default rlib build failed");

    let rlib = target.join("release").join("libreadcon_core.rlib");
    assert!(rlib.is_file(), "missing {}", rlib.display());
    let output = Command::new("nm")
        .args(["-A", "--defined-only"])
        .arg(&rlib)
        .output()
        .expect("nm");
    assert!(output.status.success(), "nm failed on {}", rlib.display());
    let symbols = String::from_utf8_lossy(&output.stdout);
    let hits = symbols
        .lines()
        .filter(|line| {
            let symbol = line.split_whitespace().last().unwrap_or("");
            symbol.starts_with("__rust_alloc")
                || symbol.starts_with("__rg_")
                || symbol.starts_with("mi_")
        })
        .collect::<Vec<_>>();
    assert!(
        hits.is_empty(),
        "default rlib defines process allocator symbols:\n{}",
        hits.join("\n")
    );
}
