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

fn source_digest(manifest: &Path) -> String {
    let mut files = Vec::new();
    let src = manifest.join("src");
    if src.is_dir() {
        collect_files(&src, &mut files);
    }
    let lock = manifest.join("Cargo.lock");
    if lock.is_file() {
        files.push(lock);
    }
    files.sort();
    let mut hasher = Sha256::new();
    for path in &files {
        let rel = path
            .strip_prefix(manifest)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");
        println!("cargo:rerun-if-changed={}", path.display());
        hasher.update(rel.as_bytes());
        hasher.update(&[0]);
        hasher.update(&fs::read(path).unwrap_or_default());
        hasher.update(&[0]);
    }
    hasher.hex()
}

fn collect_files(dir: &Path, files: &mut Vec<PathBuf>) {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_files(&path, files);
        } else if path.is_file() {
            files.push(path);
        }
    }
}

fn emit_build_identity() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let commit = git_rev("HEAD");
    let tree = git_rev("HEAD^{tree}");
    let digest = source_digest(&manifest_dir);
    println!("cargo:rustc-env=READCON_GIT_COMMIT={commit}");
    println!("cargo:rustc-env=READCON_GIT_TREE={tree}");
    println!("cargo:rustc-env=READCON_SOURCE_DIGEST={digest}");
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=Cargo.lock");
}

struct Sha256 {
    state: [u32; 8],
    buffer: [u8; 64],
    filled: usize,
    bits: u64,
}

impl Sha256 {
    fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
                0x5be0cd19,
            ],
            buffer: [0; 64],
            filled: 0,
            bits: 0,
        }
    }

    fn update(&mut self, data: &[u8]) {
        for &byte in data {
            self.buffer[self.filled] = byte;
            self.filled += 1;
            if self.filled == 64 {
                let block = self.buffer;
                self.compress(&block);
                self.filled = 0;
            }
        }
        self.bits = self.bits.wrapping_add((data.len() as u64).wrapping_mul(8));
    }

    fn hex(mut self) -> String {
        let bits = self.bits;
        self.update(&[0x80]);
        if self.filled > 56 {
            while self.filled != 0 {
                self.update(&[0]);
            }
        }
        while self.filled != 56 {
            self.update(&[0]);
        }
        self.update(&bits.to_be_bytes());
        let mut out = String::with_capacity(64);
        for word in self.state {
            out.push_str(&format!("{word:08x}"));
        }
        out
    }

    fn compress(&mut self, block: &[u8; 64]) {
        const K: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
            0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
            0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
            0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
            0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
            0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
            0xc67178f2,
        ];
        let mut w = [0u32; 64];
        for index in 0..16 {
            let at = index * 4;
            w[index] = u32::from_be_bytes([block[at], block[at + 1], block[at + 2], block[at + 3]]);
        }
        for index in 16..64 {
            let s0 = w[index - 15].rotate_right(7)
                ^ w[index - 15].rotate_right(18)
                ^ (w[index - 15] >> 3);
            let s1 = w[index - 2].rotate_right(17)
                ^ w[index - 2].rotate_right(19)
                ^ (w[index - 2] >> 10);
            w[index] = w[index - 16]
                .wrapping_add(s0)
                .wrapping_add(w[index - 7])
                .wrapping_add(s1);
        }
        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];
        let mut f = self.state[5];
        let mut g = self.state[6];
        let mut h = self.state[7];
        for index in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[index])
                .wrapping_add(w[index]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        self.state[0] = self.state[0].wrapping_add(a);
        self.state[1] = self.state[1].wrapping_add(b);
        self.state[2] = self.state[2].wrapping_add(c);
        self.state[3] = self.state[3].wrapping_add(d);
        self.state[4] = self.state[4].wrapping_add(e);
        self.state[5] = self.state[5].wrapping_add(f);
        self.state[6] = self.state[6].wrapping_add(g);
        self.state[7] = self.state[7].wrapping_add(h);
    }
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
