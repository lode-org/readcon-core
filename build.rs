#![allow(unused_imports)]
//! Build-time wiring. With `metatensor`, locate metatensor-sys install artifacts
//! (include + lib) and emit link metadata so C/Fortran consumers do not guess paths.
//!
//! Also writes `target/<profile>/readcon-metatensor.env` (KEY=value) for scripts.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
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
}

#[cfg(feature = "metatensor")]
fn emit_metatensor_sys_metadata() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let profile = env::var("PROFILE").unwrap_or_else(|_| "debug".into());
    let target_dir = env::var("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| manifest_dir.join("target"));
    // Prefer OUT_DIR's ancestor .../build/<crate>-<hash>/out -> walk siblings for metatensor-sys
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let build_root = out_dir
        .ancestors()
        .find(|p| p.file_name().is_some_and(|n| n == "build"))
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| target_dir.join(&profile).join("build"));

    let mut include_dir: Option<PathBuf> = None;
    let mut lib_dir: Option<PathBuf> = None;

    if let Ok(entries) = fs::read_dir(&build_root) {
        for ent in entries.flatten() {
            let name = ent.file_name();
            let name = name.to_string_lossy();
            if !name.starts_with("metatensor-sys-") {
                continue;
            }
            let out = ent.path().join("out");
            let inc = out.join("include");
            if inc.join("metatensor.h").is_file() {
                include_dir = Some(inc);
            }
            // Prefer installed lib/ then nested deps (shared lib location varies by platform/cmake)
            let candidates = [
                out.join("lib"),
                out.join("build")
                    .join("target")
                    .join(env::var("TARGET").unwrap_or_default())
                    .join("release")
                    .join("deps"),
                out.clone(),
            ];
            for c in &candidates {
                if dir_has_metatensor_lib(c) {
                    lib_dir = Some(c.clone());
                    break;
                }
            }
            if include_dir.is_some() && lib_dir.is_some() {
                break;
            }
        }
    }

    // First build of this crate may run before metatensor-sys finishes; still link via
    // the high-level crate. Re-run when OUT_DIR changes so we pick up paths on rebuild.
    println!("cargo:rerun-if-env-changed=OUT_DIR");
    println!("cargo:rerun-if-changed=build.rs");

    if let Some(ref inc) = include_dir {
        println!("cargo:rustc-env=READCON_METATENSOR_INCLUDE={}", inc.display());
        println!("cargo:INCLUDE={}", inc.display());
        // For dependents that read DEP_READCON_CORE_INCLUDE (links = not set; informational)
        println!("cargo:root={}", manifest_dir.display());
    }
    if let Some(ref lib) = lib_dir {
        println!("cargo:rustc-link-search=native={}", lib.display());
        println!("cargo:rustc-link-lib=dylib=metatensor");
        println!("cargo:rustc-env=READCON_METATENSOR_LIB_DIR={}", lib.display());
        println!("cargo:LIB={}", lib.display());
        // rpath so tests/cdylib resolve libmetatensor without LD_LIBRARY_PATH (Unix)
        if env::var("CARGO_CFG_TARGET_FAMILY").as_deref() == Ok("unix") {
            println!("cargo:rustc-link-arg=-Wl,-rpath,{}", lib.display());
        }
    }

    // Script-friendly env file next to the built library
    let env_path = target_dir.join(&profile).join("readcon-metatensor.env");
    if let (Some(inc), Some(lib)) = (&include_dir, &lib_dir) {
        let body = format!(
            "READCON_METATENSOR_INCLUDE={}\nREADCON_METATENSOR_LIB_DIR={}\n",
            inc.display(),
            lib.display()
        );
        let _ = fs::create_dir_all(env_path.parent().unwrap());
        let _ = fs::write(&env_path, body);
        println!("cargo:rustc-env=READCON_METATENSOR_ENV_FILE={}", env_path.display());
    }
}

#[cfg(feature = "metatensor")]
fn dir_has_metatensor_lib(dir: &Path) -> bool {
    if !dir.is_dir() {
        return false;
    }
    for name in [
        "libmetatensor.so",
        "libmetatensor.dylib",
        "metatensor.dll",
        "libmetatensor.a",
        "metatensor.lib",
    ] {
        if dir.join(name).is_file() {
            return true;
        }
    }
    // Some installs use versioned sonames only
    if let Ok(entries) = fs::read_dir(dir) {
        for ent in entries.flatten() {
            let n = ent.file_name();
            let s = n.to_string_lossy();
            if s.starts_with("libmetatensor.") || s == "metatensor.dll" {
                return true;
            }
        }
    }
    false
}
