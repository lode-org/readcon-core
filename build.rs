#![allow(unused_imports)]
//! Build-time wiring. With `metatensor`, locate metatensor-sys install artifacts
//! (include + lib) and emit link metadata so C/Fortran consumers do not guess paths.
//!
//! Also writes `target/<profile>/readcon-metatensor.env` (KEY=value) for scripts.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

#[cfg(feature = "metatensor")]
extern crate metatensor_sys;

#[cfg(feature = "metatensor")]
#[path = "support/metatensor_install.rs"]
mod metatensor_paths;

fn check_package_version_file() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let version_path = manifest_dir.join("VERSION");
    println!("cargo:rerun-if-changed={}", version_path.display());
    let text = fs::read_to_string(&version_path).unwrap_or_else(|err| {
        panic!("read {}: {err}", version_path.display());
    });
    // A Windows checkout may store CRLF. Accept one LF, with an optional CR.
    let mut source = text.as_str();
    source = source.strip_suffix('\n').unwrap_or("");
    source = source.strip_suffix('\r').unwrap_or(source);
    let newline = if text.ends_with("\r\n") { "\r\n" } else { "\n" };
    if source.is_empty()
        || source.contains('\n')
        || source.contains('\r')
        || text != format!("{source}{newline}")
    {
        panic!("VERSION must be a single line ending in one newline");
    }
    let pkg = env::var("CARGO_PKG_VERSION").unwrap();
    if pkg != source {
        panic!("Cargo.toml version {pkg} does not match VERSION ({source})");
    }
}

fn git_rev(spec: &str) -> String {
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let output = std::process::Command::new("git")
        .args(["-C", &manifest_dir, "rev-parse", spec])
        .output();
    let Ok(output) = output else {
        return String::new();
    };
    if !output.status.success() {
        return String::new();
    }
    let text = String::from_utf8(output.stdout).unwrap_or_default();
    let text = text.trim();
    if text.len() == 40 && text.chars().all(|c| c.is_ascii_hexdigit()) {
        text.to_string()
    } else {
        String::new()
    }
}

fn emit_build_identity() {
    let commit = git_rev("HEAD");
    let tree = git_rev("HEAD^{tree}");
    println!("cargo:rustc-env=READCON_GIT_COMMIT={commit}");
    println!("cargo:rustc-env=READCON_GIT_TREE={tree}");
    println!("cargo:rerun-if-changed=build.rs");
}

fn main() {
    check_package_version_file();
    emit_build_identity();

    // Cap'n Proto schema compilation (behind rpc feature)
    #[cfg(feature = "rpc")]
    {
        let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
        let schema_dir = Path::new(&manifest_dir).join("schema");
        let schema_path = schema_dir.join("ReadCon.capnp");
        if schema_path.exists() {
            capnpc::CompilerCommand::new()
                .src_prefix(&schema_dir)
                .file(&schema_path)
                .run()
                .expect("Cap'n Proto schema compilation failed");
        } else {
            panic!(
                "Cap'n Proto schema not found at {}. \
                 The rpc feature requires schema/ReadCon.capnp in the crate root.",
                schema_path.display()
            );
        }
    }

    #[cfg(feature = "metatensor")]
    {
        emit_metatensor_sys_metadata();
    }

    #[cfg(feature = "chemfiles")]
    compile_chemfiles_atom_view();
}

#[cfg(feature = "chemfiles")]
fn compile_chemfiles_atom_view() {
    let headers = chemfiles_include_dir();
    let generated = chemfiles_generated_include();
    println!("cargo:rerun-if-changed=src/chemfiles_atom_view.cpp");
    println!("cargo:rerun-if-changed={}", headers.display());
    let mut build = cc::Build::new();
    build
        .cpp(true)
        .file("src/chemfiles_atom_view.cpp")
        .include(&generated)
        .include(&headers)
        .flag_if_supported("-std=c++17")
        .warnings(false);
    build.compile("readcon_chemfiles_atom_view");
}

/// `chemfiles-sys` writes `exports.h` under its build-script output.
///
/// Cargo used to name that directory `chemfiles-sys-<hash>`. A target
/// build now uses `chemfiles-sys/<hash>`. Both layouts are accepted.
#[cfg(feature = "chemfiles")]
fn chemfiles_exports_include(build_dir: &Path) -> Option<PathBuf> {
    let exports = |dir: &Path| {
        let include = dir.join("out/include");
        include
            .join("chemfiles/exports.h")
            .is_file()
            .then_some(include)
    };
    let entries = fs::read_dir(build_dir).ok()?;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name != "chemfiles-sys" && !name.starts_with("chemfiles-sys-") {
            continue;
        }
        if let Some(include) = exports(&entry.path()) {
            return Some(include);
        }
        let Ok(children) = fs::read_dir(entry.path()) else {
            continue;
        };
        for child in children.flatten() {
            if let Some(include) = exports(&child.path()) {
                return Some(include);
            }
        }
    }
    None
}

/// Directories that can hold `chemfiles-sys`'s build-script output.
///
/// `OUT_DIR` for this build script is the host tree
/// (`target/<profile>/build/<crate>/<hash>/out`). With `--target`, the
/// dependency is built under `target/<triple>/<profile>/build` even when
/// the triple is the host. The package directory is either
/// `<crate>-<hash>` or `<crate>/<hash>`.
#[cfg(feature = "chemfiles")]
fn chemfiles_build_dirs(out_dir: &Path) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    let Some(hash_or_pkg) = out_dir.parent() else {
        return dirs;
    };
    let Some(pkg_or_build) = hash_or_pkg.parent() else {
        return dirs;
    };
    let build = if pkg_or_build.file_name().and_then(|name| name.to_str()) == Some("build") {
        pkg_or_build.to_path_buf()
    } else {
        match pkg_or_build.parent() {
            Some(parent) => parent.to_path_buf(),
            None => return dirs,
        }
    };
    dirs.push(build.clone());
    if let Ok(target) = env::var("TARGET")
        && let Some(profile) = build.parent()
        && let Some(target_root) = profile.parent()
        && let Some(profile_name) = profile.file_name()
    {
        let triple = target_root.join(target).join(profile_name).join("build");
        if triple != build {
            dirs.push(triple);
        }
    }
    dirs
}

#[cfg(feature = "chemfiles")]
fn chemfiles_generated_include() -> PathBuf {
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    for dir in chemfiles_build_dirs(&out) {
        if let Some(include) = chemfiles_exports_include(&dir) {
            return include;
        }
    }
    panic!("chemfiles-sys did not generate include/chemfiles/exports.h");
}

#[cfg(all(test, feature = "chemfiles"))]
mod chemfiles_include_tests {
    use super::{chemfiles_build_dirs, chemfiles_exports_include};
    use std::fs;

    #[test]
    fn nested_hash_directory_is_found() {
        let root = std::path::PathBuf::from("build/test")
            .join(format!("readcon-chemfiles-layout-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let include = root.join("chemfiles-sys/77b8730f9d878a0f/out/include/chemfiles");
        fs::create_dir_all(&include).unwrap();
        fs::write(include.join("exports.h"), "/* generated */\n").unwrap();
        let found = chemfiles_exports_include(&root).expect("nested layout");
        assert!(found.join("chemfiles/exports.h").is_file());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn target_triple_build_is_found_from_the_host_out_dir() {
        let root = std::path::PathBuf::from("build/test")
            .join(format!("readcon-chemfiles-triple-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let out = root.join("target/release/build/readcon-core/hosthash/out");
        let include = root.join(
            "target/x86_64-unknown-linux-gnu/release/build/chemfiles-sys/77b8730f9d878a0f/out/include/chemfiles",
        );
        fs::create_dir_all(&out).unwrap();
        fs::create_dir_all(&include).unwrap();
        fs::write(include.join("exports.h"), "/* generated */\n").unwrap();
        // SAFETY: this test is the only writer of TARGET, and it runs alone.
        unsafe { std::env::set_var("TARGET", "x86_64-unknown-linux-gnu") };
        let dirs = chemfiles_build_dirs(&out);
        let found = dirs.iter().find_map(|dir| chemfiles_exports_include(dir));
        unsafe { std::env::remove_var("TARGET") };
        assert!(found.is_some(), "dirs: {dirs:?}");
        let _ = fs::remove_dir_all(&root);
    }
}

#[cfg(feature = "chemfiles")]
fn chemfiles_include_dir() -> PathBuf {
    let mut roots = Vec::new();
    if let Ok(home) = env::var("CARGO_HOME") {
        roots.push(PathBuf::from(home).join("registry/src"));
    }
    if let Ok(home) = env::var("HOME") {
        roots.push(PathBuf::from(home).join(".cargo/registry/src"));
    }
    for root in roots {
        let Ok(indexes) = fs::read_dir(&root) else {
            continue;
        };
        for index in indexes.flatten() {
            let Ok(crates) = fs::read_dir(index.path()) else {
                continue;
            };
            for crate_dir in crates.flatten() {
                let name = crate_dir.file_name();
                let name = name.to_string_lossy();
                if !name.starts_with("chemfiles-sys-") {
                    continue;
                }
                let include = crate_dir.path().join("chemfiles/include");
                if include.join("chemfiles/Frame.hpp").is_file() {
                    return include;
                }
            }
        }
    }
    panic!("chemfiles headers were not found in the cargo registry");
}

#[cfg(feature = "metatensor")]
fn emit_metatensor_sys_metadata() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let profile = env::var("PROFILE").unwrap_or_else(|_| "debug".into());
    let target_dir = env::var("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| manifest_dir.join("target"));
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let build_root = out_dir
        .ancestors()
        .find(|p| p.file_name().is_some_and(|n| n == "build"))
        .map(Path::to_path_buf)
        .unwrap_or_else(|| target_dir.join(&profile).join("build"));

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=support/metatensor_install.rs");

    // metatensor-sys is a build-dependency of this feature, so its install
    // (include + lib) is already on disk. Cargo 1.100 keeps that install under
    // build/metatensor-sys/<hash>/ rather than build/metatensor-sys-<hash>/.
    let install = metatensor_paths::locate(&build_root).unwrap_or_else(|| {
        panic!(
            "metatensor feature is enabled but libmetatensor was not installed under {}",
            build_root.display()
        )
    });
    if let Some(output) = &install.output_file {
        println!("cargo:rerun-if-changed={}", output.display());
    }

    let include_dir = &install.include_dir;
    let lib_dir = &install.lib_dir;
    println!(
        "cargo:rustc-env=READCON_METATENSOR_INCLUDE={}",
        include_dir.display()
    );
    println!("cargo:INCLUDE={}", include_dir.display());
    println!("cargo:root={}", manifest_dir.display());
    println!("cargo:rustc-link-search=native={}", lib_dir.display());
    let kind = if install.shared { "dylib" } else { "static" };
    println!("cargo:rustc-link-lib={kind}=metatensor");
    println!(
        "cargo:rustc-env=READCON_METATENSOR_LIB_DIR={}",
        lib_dir.display()
    );
    println!("cargo:LIB={}", lib_dir.display());
    if install.shared && env::var("CARGO_CFG_TARGET_FAMILY").as_deref() == Ok("unix") {
        println!("cargo:rustc-link-arg=-Wl,-rpath,{}", lib_dir.display());
    }

    let env_path = target_dir.join(&profile).join("readcon-metatensor.env");
    let body = format!(
        "READCON_METATENSOR_INCLUDE={}\nREADCON_METATENSOR_LIB_DIR={}\n",
        include_dir.display(),
        lib_dir.display()
    );
    fs::create_dir_all(env_path.parent().unwrap())
        .unwrap_or_else(|err| panic!("create {}: {err}", env_path.display()));
    fs::write(&env_path, body).unwrap_or_else(|err| panic!("write {}: {err}", env_path.display()));
    println!(
        "cargo:rustc-env=READCON_METATENSOR_ENV_FILE={}",
        env_path.display()
    );
}
