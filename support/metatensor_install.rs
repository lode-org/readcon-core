//! Where a `metatensor-sys` build script installed `libmetatensor` and
//! `metatensor.h`.
//!
//! Cargo 1.100 stores build-script output at
//! `target/<profile>/build/<package>/<hash>/`, not the older
//! `target/<profile>/build/<package>-<hash>/`. A scan that only accepts the
//! hyphen-suffix name never sees the install, so `readcon-metatensor.env` is
//! never written and nothing records an rpath to `libmetatensor.so`.

use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MetatensorInstall {
    pub include_dir: PathBuf,
    pub lib_dir: PathBuf,
    pub shared: bool,
    pub output_file: Option<PathBuf>,
}

pub fn locate(build_root: &Path) -> Option<MetatensorInstall> {
    let mut found = Vec::new();
    for prefix in install_prefixes(build_root) {
        if let Some(install) = install_from_prefix(&prefix) {
            found.push(install);
        }
    }
    found.into_iter().max_by_key(|install| {
        (
            install.shared,
            install.lib_dir.join(shared_filename()).is_file(),
        )
    })
}

fn install_prefixes(build_root: &Path) -> Vec<PathBuf> {
    let mut prefixes = Vec::new();
    let Ok(entries) = fs::read_dir(build_root) else {
        return prefixes;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with("metatensor-sys-") {
            prefixes.push(entry.path());
            continue;
        }
        if name != "metatensor-sys" {
            continue;
        }
        let Ok(children) = fs::read_dir(entry.path()) else {
            continue;
        };
        for child in children.flatten() {
            if child.path().is_dir() {
                prefixes.push(child.path());
            }
        }
    }
    prefixes
}

fn install_from_prefix(prefix: &Path) -> Option<MetatensorInstall> {
    // Cargo 1.100 writes build-script metadata to `run/stdout` (after the
    // cmake log). Older Cargo used a sibling file named `output`.
    for output_file in [prefix.join("run").join("stdout"), prefix.join("output")] {
        if let Some(mut install) = install_from_output(&output_file) {
            install.output_file = Some(output_file);
            return Some(install);
        }
    }
    let out = prefix.join("out");
    let include_dir = out.join("include");
    if !include_dir.join("metatensor.h").is_file() {
        return None;
    }
    let mut candidates = vec![out.join("lib"), out.join("lib64")];
    push_built_lib_dirs(&out, &mut candidates);
    let lib_dir = first_lib_dir(&candidates)?;
    let shared = dir_has_shared_metatensor(&lib_dir);
    Some(MetatensorInstall {
        include_dir,
        lib_dir,
        shared,
        output_file: None,
    })
}

fn push_built_lib_dirs(out: &Path, candidates: &mut Vec<PathBuf>) {
    let target = out.join("build").join("target");
    candidates.push(target.join("release"));
    candidates.push(target.join("debug"));
    let Ok(entries) = fs::read_dir(&target) else {
        return;
    };
    for entry in entries.flatten() {
        if entry.path().is_dir() {
            candidates.push(entry.path().join("release"));
            candidates.push(entry.path().join("debug"));
        }
    }
}

fn install_from_output(path: &Path) -> Option<MetatensorInstall> {
    let text = fs::read_to_string(path).ok()?;
    let mut root = None;
    let mut searches = Vec::new();
    for line in text.lines() {
        if let Some(value) = line.strip_prefix("cargo:root=") {
            root = Some(PathBuf::from(value.trim()));
        } else if let Some(value) = line.strip_prefix("cargo:rustc-link-search=") {
            let value = value.trim().strip_prefix("native=").unwrap_or(value.trim());
            if !value.is_empty() {
                searches.push(PathBuf::from(value));
            }
        }
    }
    let root = root?;
    let include_dir = root.join("include");
    if !include_dir.join("metatensor.h").is_file() {
        return None;
    }
    let mut candidates = searches;
    candidates.push(root.join("lib"));
    candidates.push(root.join("lib64"));
    let lib_dir = first_lib_dir(&candidates)?;
    let shared = dir_has_shared_metatensor(&lib_dir);
    Some(MetatensorInstall {
        include_dir,
        lib_dir,
        shared,
        output_file: None,
    })
}

fn first_lib_dir(candidates: &[PathBuf]) -> Option<PathBuf> {
    candidates
        .iter()
        .find(|dir| dir_has_shared_metatensor(dir))
        .or_else(|| candidates.iter().find(|dir| dir_has_metatensor_lib(dir)))
        .cloned()
}

fn shared_filename() -> &'static str {
    if cfg!(windows) {
        "metatensor.dll"
    } else if cfg!(target_os = "macos") {
        "libmetatensor.dylib"
    } else {
        "libmetatensor.so"
    }
}

fn dir_has_shared_metatensor(dir: &Path) -> bool {
    if !dir.is_dir() {
        return false;
    }
    if dir.join(shared_filename()).is_file() {
        return true;
    }
    let Ok(entries) = fs::read_dir(dir) else {
        return false;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with("libmetatensor.so") || name.starts_with("libmetatensor.dylib") {
            return true;
        }
    }
    false
}

fn dir_has_metatensor_lib(dir: &Path) -> bool {
    if dir_has_shared_metatensor(dir) {
        return true;
    }
    if !dir.is_dir() {
        return false;
    }
    for name in ["libmetatensor.a", "metatensor.lib"] {
        if dir.join(name).is_file() {
            return true;
        }
    }
    false
}
