#![allow(unused_imports)]
//! Build-time wiring. With `metatensor`, locate metatensor-sys install artifacts
//! (include + lib) and emit link metadata so C/Fortran consumers do not guess paths.
//!
//! Also writes `target/<profile>/readcon-metatensor.env` (KEY=value) for scripts.

use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[cfg(feature = "metatensor")]
extern crate metatensor_sys;

#[cfg(feature = "metatensor")]
#[path = "support/metatensor_install.rs"]
mod metatensor_paths;

#[cfg(feature = "chemfiles")]
#[path = "support/chemfiles_link.rs"]
mod chemfiles_link;

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
        hasher.update([0]);
        hasher.update(fs::read(path).unwrap_or_default());
        hasher.update([0]);
    }
    format!("{:x}", hasher.finalize())
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

fn cxx_runtime() -> Option<(&'static str, Option<PathBuf>)> {
    // zstd-sys is C. A chemfiles build is C++. The archive still has to name
    // the C++ runtime or the link drops it. Linux uses libstdc++; macOS and
    // iOS use libc++. MSVC pulls its own. clang does not search GCC's
    // libstdc++ directory, so the link also needs that path.
    let needs = env::var_os("CARGO_FEATURE_ZSTD").is_some()
        || env::var_os("CARGO_FEATURE_CHEMFILES").is_some();
    if !needs {
        return None;
    }
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let env_name = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    match (os.as_str(), env_name.as_str()) {
        // The host g++ library directory is wrong for a cross link.
        ("linux" | "android", _) => Some((
            "stdc++",
            if compiling_for_host() {
                linux_libstdcxx_dir()
            } else {
                None
            },
        )),
        ("macos" | "ios", _) => Some(("c++", None)),
        ("windows", "gnu") => Some(("stdc++", None)),
        _ => None,
    }
}

fn compiling_for_host() -> bool {
    match (env::var("TARGET"), env::var("HOST")) {
        (Ok(target), Ok(host)) => target == host,
        _ => true,
    }
}

fn linux_libstdcxx_dir() -> Option<PathBuf> {
    let output = Command::new("g++")
        .args(["-print-file-name=libstdc++.so"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let path = String::from_utf8(output.stdout).ok()?;
    let path = path.trim();
    if path.is_empty() || path == "libstdc++.so" {
        return None;
    }
    Path::new(path).parent().map(Path::to_path_buf)
}

fn link_cxx_runtime() {
    let Some((lib, search)) = cxx_runtime() else {
        return;
    };
    println!("cargo:rerun-if-changed=build.rs");
    if let Some(dir) = search
        && dir.is_dir()
    {
        println!("cargo:rustc-link-search=native={}", dir.display());
    }
    println!("cargo:rustc-link-lib=dylib={lib}");
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

fn main() {
    check_package_version_file();
    link_cxx_runtime();
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

    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("linux") {
        // Keep symbols from statically linked C/C++ archives (such as
        // libreadcon_chemfiles_atom_view.a and libchemfiles.a) out of the
        // cdylib dynamic export table.
        println!("cargo:rustc-cdylib-link-arg=-Wl,--exclude-libs=ALL");
    }
}

#[cfg(feature = "chemfiles")]
fn compile_chemfiles_atom_view() {
    let (headers, generated) = chemfiles_header_dirs();
    println!("cargo:rerun-if-changed=src/chemfiles_atom_view.cpp");
    println!("cargo:rerun-if-changed=support/chemfiles_link.rs");
    println!("cargo:rerun-if-changed={}", headers.display());
    println!(
        "cargo:rerun-if-changed={}",
        generated.join("chemfiles/exports.h").display()
    );
    let mut build = cc::Build::new();
    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("linux") && compiling_for_host() {
        // cc passes --target to clang. That driver does not search GCC's
        // libstdc++ headers, so the scan fails on `#include <string>`.
        // Host g++ searches its own headers. A cross build keeps cc's
        // compiler instead of this host g++.
        build.compiler("g++");
    }
    build
        .cpp(true)
        .file("src/chemfiles_atom_view.cpp")
        .include(&generated)
        .include(&headers)
        .flag_if_supported("-std=c++17")
        .flag_if_supported("-fvisibility=hidden")
        .flag_if_supported("-fvisibility-inlines-hidden")
        .warnings(false);
    // The prebuilt GCC 4.8 archive is the COW string (Atom is 80 bytes).
    // A from-source build is this compiler's cxx11 string (Atom is 128
    // bytes). Indexing with the wrong layout throws or reads off the atom.
    // The macro is a no-op for libc++ and MSVC.
    let abi = linked_chemfiles_string_abi();
    // cc appends CXXFLAGS after Build::define, so a later -D wins.
    reject_cxxflags_abi_override(abi);
    match abi {
        chemfiles_link::AbiChoice::Cow => {
            build.define("_GLIBCXX_USE_CXX11_ABI", "0");
            println!("cargo:rustc-env=READCON_CHEMFILES_STRING_ABI=cow");
        }
        chemfiles_link::AbiChoice::Cxx11 => {
            println!("cargo:rustc-env=READCON_CHEMFILES_STRING_ABI=cxx11");
        }
        chemfiles_link::AbiChoice::Foreign => {
            println!("cargo:rustc-env=READCON_CHEMFILES_STRING_ABI=foreign");
        }
        chemfiles_link::AbiChoice::Fatal => unreachable!("fatal ABI selection panics first"),
    }
    build.compile("readcon_chemfiles_atom_view");
}

#[cfg(feature = "chemfiles")]
fn chemfiles_header_dirs() -> (PathBuf, PathBuf) {
    for key in [
        "DEP_CHEMFILES_INCLUDE",
        "DEP_CHEMFILES_ROOT",
        "DEP_CHEMFILES_LIBDIR",
        "DEP_CHEMFILES_LIB_DIR",
    ] {
        println!("cargo:rerun-if-env-changed={key}");
    }
    if let Some(include) = metadata_chemfiles_include() {
        return (include.clone(), include);
    }
    (chemfiles_include_dir(), chemfiles_generated_include())
}

/// Installed headers for the chemfiles Cargo will link.
///
/// `DEP_CHEMFILES_ROOT` is the `cargo:root` of the chemfiles-sys build that
/// ran. `DEP_CHEMFILES_LIBDIR` and `DEP_CHEMFILES_INCLUDE` come from a
/// `links = "chemfiles"` override. Any one of them suppresses a scan of
/// leftover `chemfiles-sys` output directories.
#[cfg(feature = "chemfiles")]
fn metadata_chemfiles_include() -> Option<PathBuf> {
    let include = env::var_os("DEP_CHEMFILES_INCLUDE").map(PathBuf::from);
    let root = env::var_os("DEP_CHEMFILES_ROOT").map(PathBuf::from);
    let libdir = env::var_os("DEP_CHEMFILES_LIBDIR")
        .or_else(|| env::var_os("DEP_CHEMFILES_LIB_DIR"))
        .map(PathBuf::from);
    let located = chemfiles_link::include_from_metadata(
        include.as_deref(),
        root.as_deref(),
        libdir.as_deref(),
    );
    if include.is_some() || root.is_some() || libdir.is_some() {
        let include = located.unwrap_or_else(|| {
            panic!(
                "chemfiles metadata did not provide include/chemfiles/exports.h (include={include:?}, root={root:?}, libdir={libdir:?})"
            )
        });
        return Some(include);
    }
    None
}

#[cfg(feature = "chemfiles")]
fn linked_chemfiles_string_abi() -> chemfiles_link::AbiChoice {
    let stdlib = cpp_stdlib();
    if matches!(
        stdlib,
        chemfiles_link::CppStdlib::Libcxx | chemfiles_link::CppStdlib::Msvc
    ) {
        return chemfiles_link::AbiChoice::Foreign;
    }
    let library = linked_chemfiles_library();
    println!("cargo:rerun-if-changed={}", library.display());
    let (status, symbols) = nm_symbols(&library);
    if symbols == chemfiles_link::StringAbi::Conflict {
        panic!(
            "nm of {} contains both __cxx11 and ERKSs; refusing to pick a string ABI",
            library.display()
        );
    }
    match chemfiles_link::choose_string_abi(stdlib, status, symbols) {
        chemfiles_link::AbiChoice::Fatal => panic!(
            "refusing to guess the libstdc++ string ABI of {}",
            library.display()
        ),
        choice => choice,
    }
}

#[cfg(feature = "chemfiles")]
fn reject_cxxflags_abi_override(choice: chemfiles_link::AbiChoice) {
    let wanted = match choice {
        chemfiles_link::AbiChoice::Cow => "0",
        chemfiles_link::AbiChoice::Cxx11 => "1",
        chemfiles_link::AbiChoice::Foreign | chemfiles_link::AbiChoice::Fatal => return,
    };
    let target = env::var("TARGET").unwrap_or_default();
    let host = env::var("HOST").unwrap_or_default();
    let mut groups = Vec::new();
    for key in chemfiles_link::cxxflags_env_keys(&target, &host) {
        println!("cargo:rerun-if-env-changed={key}");
        if let Ok(value) = env::var(&key) {
            groups.push(value);
        }
    }
    let flags = chemfiles_link::split_cxxflags(&groups);
    let Some(got) = chemfiles_link::last_cxx11_abi_define(flags.iter().map(String::as_str)) else {
        return;
    };
    if got != wanted {
        panic!(
            "CXXFLAGS sets -D_GLIBCXX_USE_CXX11_ABI={got}, but the linked libchemfiles needs {wanted}. cc appends CXXFLAGS after the probed define, so drop the macro from CXXFLAGS"
        );
    }
}

#[cfg(feature = "chemfiles")]
fn linked_chemfiles_library() -> PathBuf {
    let include = env::var_os("DEP_CHEMFILES_INCLUDE").map(PathBuf::from);
    let root = env::var_os("DEP_CHEMFILES_ROOT").map(PathBuf::from);
    let libdir = env::var_os("DEP_CHEMFILES_LIBDIR")
        .or_else(|| env::var_os("DEP_CHEMFILES_LIB_DIR"))
        .map(PathBuf::from);
    let dirs =
        chemfiles_link::library_search_dirs(libdir.as_deref(), root.as_deref(), include.as_deref());
    let kind = configured_link_kind();
    if let Some(path) = chemfiles_link::linked_library(&dirs, kind) {
        return path;
    }
    panic!("the chemfiles library Cargo links was not found (kind={kind:?}, dirs={dirs:?})")
}

#[cfg(feature = "chemfiles")]
fn configured_link_kind() -> chemfiles_link::LinkKind {
    let target = env::var("TARGET").unwrap_or_default();
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    for config in cargo_config_paths(&manifest_dir) {
        println!("cargo:rerun-if-changed={}", config.display());
        let Ok(text) = fs::read_to_string(&config) else {
            continue;
        };
        if let Some(kind) = chemfiles_link::link_kind_from_config(&text, &target) {
            return kind;
        }
    }
    // chemfiles-sys declares #[link(name = "chemfiles", kind = "static")].
    chemfiles_link::LinkKind::Static
}

#[cfg(feature = "chemfiles")]
fn cargo_config_paths(manifest_dir: &Path) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    let mut dir = Some(manifest_dir);
    while let Some(current) = dir {
        paths.push(current.join(".cargo/config.toml"));
        paths.push(current.join(".cargo/config"));
        dir = current.parent();
    }
    if let Some(home) = env::var_os("CARGO_HOME") {
        let home = PathBuf::from(home);
        paths.push(home.join("config.toml"));
        paths.push(home.join("config"));
    }
    paths
}

#[cfg(feature = "chemfiles")]
fn nm_symbols(library: &Path) -> (chemfiles_link::NmStatus, chemfiles_link::StringAbi) {
    let program = nm_program();
    let output = match Command::new(&program).arg("--").arg(library).output() {
        Ok(output) => output,
        Err(err) => {
            println!(
                "cargo:warning=nm ({}) failed to start: {err}",
                program.display()
            );
            return (
                chemfiles_link::NmStatus::SpawnFailed,
                chemfiles_link::StringAbi::Unknown,
            );
        }
    };
    if !output.status.success() {
        println!(
            "cargo:warning=nm ({}) exited {} for {}",
            program.display(),
            output.status,
            library.display()
        );
        return (
            chemfiles_link::NmStatus::NonZero,
            chemfiles_link::StringAbi::Unknown,
        );
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let symbols = chemfiles_link::classify_symbol_text(&text);
    if symbols == chemfiles_link::StringAbi::Unknown {
        println!(
            "cargo:warning=nm ({}) found no COW or __cxx11 symbols in {}",
            program.display(),
            library.display()
        );
    }
    (chemfiles_link::NmStatus::Ok, symbols)
}

/// `NM_<target>`, `TARGET_NM`/`HOST_NM`, and `NM`, then the cross `nm`.
#[cfg(feature = "chemfiles")]
fn nm_program() -> PathBuf {
    let target = env::var("TARGET").unwrap_or_default();
    let host = env::var("HOST").unwrap_or_else(|_| target.clone());
    let keys = chemfiles_link::nm_env_keys(&target, &host);
    for key in &keys {
        println!("cargo:rerun-if-env-changed={key}");
    }
    let values: Vec<(String, String)> = keys
        .iter()
        .filter_map(|key| env::var(key).ok().map(|value| (key.clone(), value)))
        .collect();
    if let Some(chosen) = chemfiles_link::first_nm_override(&keys, |key| {
        values
            .iter()
            .find(|(name, _)| name == key)
            .map(|(_, value)| value.as_str())
    }) {
        return PathBuf::from(chosen);
    }
    if !target.is_empty() && target != host {
        return PathBuf::from(format!("{target}-nm"));
    }
    if let Some(beside) = nm_beside_compiler() {
        return beside;
    }
    PathBuf::from("nm")
}

#[cfg(feature = "chemfiles")]
fn nm_beside_compiler() -> Option<PathBuf> {
    println!("cargo:rerun-if-env-changed=CXX");
    println!("cargo:rerun-if-env-changed=CC");
    let compiler = env::var_os("CXX").or_else(|| env::var_os("CC"))?;
    let parent = PathBuf::from(compiler).parent()?.to_path_buf();
    for name in ["llvm-nm", "nm"] {
        let path = parent.join(name);
        if path.is_file() {
            return Some(path);
        }
    }
    None
}

#[cfg(feature = "chemfiles")]
fn cpp_stdlib() -> chemfiles_link::CppStdlib {
    let target_env = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_env == "msvc" {
        return chemfiles_link::CppStdlib::Msvc;
    }
    // An empty translation unit has no stdlib macros. Include a header,
    // and on a native Linux host use g++, the same compiler as the scan.
    // cc's clang adds --target and then cannot see <cstddef>.
    let mut cmd = if target_os == "linux" && compiling_for_host() {
        Command::new("g++")
    } else {
        let compiler = cc::Build::new().cpp(true).get_compiler();
        if compiler.is_like_msvc() {
            return chemfiles_link::CppStdlib::Msvc;
        }
        compiler.to_command()
    };
    cmd.arg("-dM")
        .arg("-E")
        .arg("-x")
        .arg("c++")
        .arg("-include")
        .arg("cstddef")
        .arg("-")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if let Ok(output) = cmd.output()
        && output.status.success()
    {
        let text = String::from_utf8_lossy(&output.stdout);
        if text.contains("_LIBCPP_VERSION") {
            return chemfiles_link::CppStdlib::Libcxx;
        }
        if text.contains("__GLIBCXX__") {
            return chemfiles_link::CppStdlib::Libstdcxx;
        }
    }
    if target_os == "macos" || target_os == "ios" || target_env == "msvc" {
        chemfiles_link::CppStdlib::Libcxx
    } else {
        chemfiles_link::CppStdlib::Libstdcxx
    }
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
