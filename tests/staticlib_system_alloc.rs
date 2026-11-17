// Copyright (c) readcon-core developers
//! The static archive is linked into C++ hosts beside other Rust
//! staticlibs. It must not install mimalloc; the cdylib keeps it.

use std::path::Path;
use std::process::Command;

#[cfg(target_os = "linux")]
static BUILD_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

#[cfg(target_os = "linux")]
fn lock_build() -> std::sync::MutexGuard<'static, ()> {
    BUILD_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn defined_mimalloc(archive: &Path) -> String {
    let output = Command::new("nm")
        .args(["--defined-only"])
        .arg(archive)
        .output()
        .expect("nm");
    assert!(
        output.status.success(),
        "nm failed on {}",
        archive.display()
    );
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| {
            let mut parts = line.split_whitespace();
            let _addr = parts.next();
            let kind = parts.next().unwrap_or("");
            let name = parts.next().unwrap_or("");
            kind == "T" && (name == "mi_malloc" || name == "mi_free")
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn alloc_work(name: &str) -> std::path::PathBuf {
    let base = std::env::var_os("CARGO_TARGET_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("target"));
    base.join(name)
}

#[cfg(target_os = "linux")]
#[test]
fn static_archive_does_not_install_mimalloc() {
    let _build = lock_build();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let work = alloc_work("staticlib-system-alloc");
    let _ = std::fs::remove_dir_all(&work);
    std::fs::create_dir_all(&work).expect("workdir");
    let status = Command::new("python3")
        .arg(root.join("scripts/meson_cargo_build.py"))
        .args([
            "cargo",
            root.to_str().unwrap(),
            work.join("cargo-target").to_str().unwrap(),
            "release",
            "libreadcon_core.so",
            "libreadcon_core.a",
            work.join("libreadcon_core.so").to_str().unwrap(),
            work.join("libreadcon_core.a").to_str().unwrap(),
        ])
        .status()
        .expect("meson cargo build");
    assert!(status.success(), "staticlib build failed");
    let archive = work.join("libreadcon_core.a");
    let hits = defined_mimalloc(&archive);
    assert!(
        hits.is_empty(),
        "static archive still installs mimalloc:\n{hits}"
    );
}

#[cfg(target_os = "linux")]
#[test]
fn cmake_static_archive_does_not_install_mimalloc() {
    let _build = lock_build();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let work = alloc_work("cmake-static-system-alloc");
    let _ = std::fs::remove_dir_all(&work);
    std::fs::create_dir_all(&work).expect("workdir");
    let configure = Command::new("cmake")
        .args([
            "-S",
            root.to_str().unwrap(),
            "-B",
            work.to_str().unwrap(),
            "-DREADCON_CORE_INSTALL_BOTH_STATIC_SHARED=OFF",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DCMAKE_BUILD_TYPE=debug",
        ])
        .status()
        .expect("cmake");
    assert!(configure.success(), "cmake configure failed");
    let built = Command::new("cmake")
        .args([
            "--build",
            work.to_str().unwrap(),
            "--target",
            "cargo-build-readcon-core",
        ])
        .status()
        .expect("cmake build");
    assert!(built.success(), "cmake static archive build failed");
    let archive = work.join("cargo-target/debug/libreadcon_core.a");
    assert!(archive.is_file(), "missing {}", archive.display());
    let hits = defined_mimalloc(&archive);
    assert!(
        hits.is_empty(),
        "CMake static archive still installs mimalloc:\n{hits}"
    );
}

#[cfg(target_os = "linux")]
#[test]
fn cmake_both_libraries_archive_does_not_install_mimalloc() {
    let _build = lock_build();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let work = alloc_work("cmake-both-system-alloc");
    let _ = std::fs::remove_dir_all(&work);
    std::fs::create_dir_all(&work).expect("workdir");
    // The default installs both libraries. Do not force the static-only option.
    let configure = Command::new("cmake")
        .args([
            "-S",
            root.to_str().unwrap(),
            "-B",
            work.to_str().unwrap(),
            "-DCMAKE_BUILD_TYPE=debug",
        ])
        .status()
        .expect("cmake");
    assert!(configure.success(), "cmake configure failed");
    let built = Command::new("cmake")
        .args([
            "--build",
            work.to_str().unwrap(),
            "--target",
            "cargo-build-readcon-core",
        ])
        .status()
        .expect("cmake build");
    assert!(built.success(), "cmake both-libraries build failed");
    let archive = work.join("cargo-target/debug/libreadcon_core.a");
    assert!(archive.is_file(), "missing {}", archive.display());
    let hits = defined_mimalloc(&archive);
    assert!(
        hits.is_empty(),
        "default CMake archive still installs mimalloc:\n{hits}"
    );
}
