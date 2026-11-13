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

fn main() {
    check_package_version_file();

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

#[cfg(feature = "chemfiles")]
fn chemfiles_generated_include() -> PathBuf {
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let build_dir = out
        .parent()
        .and_then(|path| path.parent())
        .expect("OUT_DIR should sit in target/<profile>/build/<crate>/out");
    let mut found = None;
    if let Ok(entries) = fs::read_dir(build_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if !name.starts_with("chemfiles-sys-") {
                continue;
            }
            let include = entry.path().join("out/include");
            if include.join("chemfiles/exports.h").is_file() {
                found = Some(include);
            }
        }
    }
    found.expect("chemfiles-sys did not generate include/chemfiles/exports.h")
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
