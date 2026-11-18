//! A default Rust dependency must not install an allocator in its consumer.

use std::path::{Path, PathBuf};
use std::process::Command;

fn work_dir(name: &str) -> PathBuf {
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
    base.join(name)
}

fn llvm_nm() -> PathBuf {
    let sysroot = Command::new("rustc")
        .args(["--print", "sysroot"])
        .output()
        .expect("rustc --print sysroot");
    assert!(sysroot.status.success(), "rustc --print sysroot failed");
    let version = Command::new("rustc")
        .arg("-vV")
        .output()
        .expect("rustc -vV");
    assert!(version.status.success(), "rustc -vV failed");
    let version = String::from_utf8_lossy(&version.stdout);
    let host = version
        .lines()
        .find_map(|line| line.strip_prefix("host: "))
        .expect("rustc host");
    let path = PathBuf::from(String::from_utf8_lossy(&sysroot.stdout).trim())
        .join("lib/rustlib")
        .join(host)
        .join("bin/llvm-nm");
    assert!(
        path.is_file(),
        "missing {}; install llvm-tools-preview",
        path.display()
    );
    path
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
    let output = Command::new(llvm_nm())
        .args(["-A", "--defined-only"])
        .arg(&rlib)
        .output()
        .expect("llvm-nm");
    assert!(
        output.status.success(),
        "llvm-nm failed on {}",
        rlib.display()
    );
    let symbols = String::from_utf8_lossy(&output.stdout);
    let names = symbols
        .lines()
        .filter_map(|line| {
            let fields = line.split_whitespace().collect::<Vec<_>>();
            (fields.len() >= 2 && fields[fields.len() - 2].len() == 1)
                .then(|| fields[fields.len() - 1])
        })
        .collect::<Vec<_>>();
    assert!(
        !names.is_empty(),
        "llvm-nm read zero defined symbols from {}",
        rlib.display()
    );
    let hits = names
        .into_iter()
        .filter(|symbol| {
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
