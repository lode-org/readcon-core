// Copyright (c) readcon-core developers
//! Where a C example can find a non-Python libreadcon_core.
//!
//! Cargo 1.88 copies the cdylib to `debug/libreadcon_core.so`, next to
//! `debug/deps/<test>`. Cargo 1.100 leaves the test binary in
//! `debug/build/readcon-core/<hash>/out/` and the library in a sibling
//! hash's `out/`. The lookup follows the test binary and that build
//! directory, and it honours `CARGO_TARGET_DIR`.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn is_plain_shared(path: &Path) -> bool {
    let listed = Command::new("nm")
        .args(["-D"])
        .arg(path)
        .output()
        .map(|out| String::from_utf8_lossy(&out.stdout).into_owned())
        .unwrap_or_default();
    !listed.contains("PyExc_BaseException")
}

fn plain_library(dir: &Path) -> bool {
    let so = dir.join("libreadcon_core.so");
    if so.is_file() {
        return is_plain_shared(&so);
    }
    let dylib = dir.join("libreadcon_core.dylib");
    if dylib.is_file() {
        return is_plain_shared(&dylib);
    }
    dir.join("libreadcon_core.a").is_file()
}

fn push_plain(dirs: &mut Vec<PathBuf>, dir: &Path) {
    if plain_library(dir) && !dirs.iter().any(|have| have == dir) {
        dirs.push(dir.to_path_buf());
    }
}

fn scan_build_outs(build_pkg: &Path, dirs: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(build_pkg) else {
        return;
    };
    let mut found = Vec::new();
    for entry in entries.flatten() {
        let out = entry.path().join("out");
        if plain_library(&out) {
            found.push(out);
        }
    }
    found.sort_by_key(|path| fs::metadata(path).and_then(|meta| meta.modified()).ok());
    found.reverse();
    for out in found {
        if !dirs.iter().any(|have| have == &out) {
            dirs.push(out);
        }
    }
}

/// Directories that contain a non-Python libreadcon_core, nearest first.
pub fn libraries_from(start: &Path, target_dir: Option<&Path>) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    let mut dir = start.to_path_buf();
    if dir.is_file() {
        dir.pop();
    }
    for _ in 0..12 {
        push_plain(&mut dirs, &dir);
        if !cfg!(feature = "python") {
            if dir.file_name().and_then(|name| name.to_str()) == Some("readcon-core")
                && dir
                    .parent()
                    .and_then(|parent| parent.file_name())
                    .and_then(|name| name.to_str())
                    == Some("build")
            {
                scan_build_outs(&dir, &mut dirs);
            }
            if dir.file_name().and_then(|name| name.to_str()) == Some("build") {
                scan_build_outs(&dir.join("readcon-core"), &mut dirs);
            }
        }
        if !dir.pop() {
            break;
        }
    }
    if let Some(target) = target_dir {
        for profile in ["debug", "release"] {
            let base = target.join(profile);
            push_plain(&mut dirs, &base);
            push_plain(&mut dirs, &base.join("deps"));
            if !cfg!(feature = "python") {
                scan_build_outs(&base.join("build").join("readcon-core"), &mut dirs);
            }
        }
    }
    dirs
}

pub fn library_dirs() -> Vec<PathBuf> {
    let start = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    let target = std::env::var_os("CARGO_TARGET_DIR").map(PathBuf::from);
    libraries_from(&start, target.as_deref())
}

#[cfg(test)]
mod plain_library_tests {
    use super::libraries_from;
    use std::fs;

    #[test]
    fn a_sibling_build_out_is_found_when_the_test_dir_is_empty() {
        let root = scratch_dir();
        let test_out = root.join("debug/build/readcon-core/test-unit/out");
        let lib_out = root.join("debug/build/readcon-core/lib-unit/out");
        fs::create_dir_all(&test_out).unwrap();
        fs::create_dir_all(&lib_out).unwrap();
        fs::write(lib_out.join("libreadcon_core.a"), b"archive").unwrap();
        let binary = test_out.join("doc_examples-test");
        fs::write(&binary, b"bin").unwrap();
        let found = libraries_from(&binary, None);
        assert!(
            found.iter().any(|dir| dir == &lib_out),
            "lookup missed {lib_out:?} in {found:?}"
        );
        let _ = fs::remove_dir_all(&root);
    }

    fn scratch_dir() -> std::path::PathBuf {
        let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("build")
            .join("test")
            .join(format!("plain-lib-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }
}
