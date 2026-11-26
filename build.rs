#![allow(unused_imports)]
//! Build-time wiring. With `metatensor`, locate metatensor-sys install artifacts
//! (include + lib) and emit link metadata so C/Fortran consumers do not guess paths.
//!
//! Also writes `target/<profile>/readcon-metatensor.env` (KEY=value) for scripts.

use sha2::{Digest, Sha256};
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

    #[cfg(feature = "python")]
    link_libpython_for_tests_and_benches();
}

/// Link libpython into test and bench binaries only.
///
/// `pyo3` is built as an extension module, so it does not link libpython.
/// The byte-cursor test starts an interpreter and needs that library.
/// `pyo3_build_config::get` already applies `PYO3_PYTHON`, `PYO3_CROSS_*`,
/// abi3, free-threading, Windows debug suffixes, `LIBDIR`, and macOS
/// framework prefixes. Those flags stay off the cdylib and the plain lib.
#[cfg(feature = "python")]
fn link_libpython_for_tests_and_benches() {
    let config = pyo3_build_config::get();
    if config.suppress_build_script_link_lines {
        for line in &config.extra_build_script_lines {
            retarget_pyo3_link_line(line);
        }
        write_test_link_rs("");
        return;
    }
    let Some(lib_name) = config.lib_name.as_deref() else {
        panic!(
            "pyo3-build-config reported no lib_name; \
             the test binary cannot link libpython"
        );
    };
    if !lib_name_ok(lib_name) {
        panic!("pyo3-build-config reported an unusable lib_name: {lib_name}");
    }
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let mut flags = Vec::new();
    // `rustc-link-arg-tests` does not reach the library harness
    // (`cargo test --lib`). The `#[link]` below is compiled only into
    // that harness, and it needs these search paths. A search path alone
    // does not link libpython into the cdylib.
    for dir in libpython_search_dirs(config, lib_name) {
        require_single_line("lib_dir", &dir);
        println!("cargo:rustc-link-search=native={dir}");
        flags.push(linker_search_flag(&dir));
    }
    flags.extend(linker_lib_flags(lib_name, config.shared));
    if os != "windows" {
        if let Some(dir) = config.lib_dir.as_deref() {
            flags.push(format!("-Wl,-rpath,{dir}"));
        }
        if matches!(os.as_str(), "macos" | "ios") {
            if let Some(prefix) = config.python_framework_prefix.as_deref() {
                if framework_prefix_ok(prefix) {
                    require_single_line("python_framework_prefix", prefix);
                    flags.push(format!("-Wl,-rpath,{prefix}"));
                }
            }
        }
    }
    // Integration tests and benches link the library without `cfg(test)`,
    // so they do not see the harness `#[link]`.
    emit_test_and_bench_link_args(&flags);
    let kind = if config.shared {
        String::new()
    } else {
        ", kind = \"static\"".to_string()
    };
    write_test_link_rs(&format!(
        "#[link(name = \"{lib_name}\"{kind})]\nunsafe extern \"C\" {{}}\n"
    ));
}

/// Directories the linker should search for `lib_name`.
///
/// PyO3's `lib_dir` is sysconfig `LIBDIR`. On Debian that directory holds
/// `libpython3.12.so.1` and the unversioned `libpython3.12.so` lives in
/// sysconfig `LIBPL`. The host `LIBPL` is ignored while cross-compiling so
/// a target build keeps `PYO3_CROSS_LIB_DIR`.
#[cfg(feature = "python")]
fn libpython_search_dirs(
    config: &pyo3_build_config::InterpreterConfig,
    lib_name: &str,
) -> Vec<String> {
    let mut dirs = Vec::new();
    if let Some(dir) = config.lib_dir.clone() {
        dirs.push(dir);
    }
    if dirs.iter().any(|dir| libpl_has_link_name(dir, lib_name)) {
        return dirs;
    }
    let host = env::var("HOST").ok() == env::var("TARGET").ok();
    if host {
        if let Some(libpl) = libpl_dir(config) {
            if !dirs.iter().any(|dir| dir == &libpl) && libpl_has_link_name(&libpl, lib_name) {
                dirs.push(libpl);
            }
        }
    }
    dirs
}

#[cfg(feature = "python")]
fn libpl_dir(config: &pyo3_build_config::InterpreterConfig) -> Option<String> {
    config.executable.as_ref()?;
    let text = config
        .run_python_script(
            "import sysconfig\nvalue = sysconfig.get_config_var('LIBPL')\nprint(value or '')\n",
        )
        .ok()?;
    let dir = text.lines().next()?.trim();
    if dir.is_empty() {
        None
    } else {
        Some(dir.to_string())
    }
}

#[cfg(feature = "python")]
fn libpl_has_link_name(dir: &str, lib_name: &str) -> bool {
    let dir = Path::new(dir);
    dir.join(format!("lib{lib_name}.so")).is_file()
        || dir.join(format!("lib{lib_name}.dylib")).is_file()
        || dir.join(format!("lib{lib_name}.a")).is_file()
        || dir.join(format!("{lib_name}.lib")).is_file()
}

#[cfg(feature = "python")]
fn write_test_link_rs(contents: &str) {
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let path = out_dir.join("python_test_link.rs");
    fs::write(&path, contents).unwrap_or_else(|err| panic!("write {}: {err}", path.display()));
}

#[cfg(feature = "python")]
fn lib_name_ok(name: &str) -> bool {
    !name.is_empty()
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-')
}

#[cfg(feature = "python")]
fn linker_search_flag(dir: &str) -> String {
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let env_name = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if os == "windows" && env_name == "msvc" {
        format!("/LIBPATH:{dir}")
    } else {
        format!("-L{dir}")
    }
}

#[cfg(feature = "python")]
fn linker_lib_flags(lib_name: &str, shared: bool) -> Vec<String> {
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let env_name = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if os == "windows" && env_name == "msvc" {
        return vec![format!("{lib_name}.lib")];
    }
    if shared {
        return vec![format!("-l{lib_name}")];
    }
    vec![
        "-Wl,-Bstatic".to_string(),
        format!("-l{lib_name}"),
        "-Wl,-Bdynamic".to_string(),
    ]
}

#[cfg(feature = "python")]
fn retarget_pyo3_link_line(line: &str) {
    require_single_line("extra_build_script_line", line);
    if let Some(spec) = line.strip_prefix("cargo:rustc-link-lib=") {
        emit_test_and_bench_link_args(&linker_flags_from_rustc_link_lib(spec));
        return;
    }
    if let Some(spec) = line.strip_prefix("cargo:rustc-link-search=") {
        if let Some(flag) = linker_flag_from_rustc_link_search(spec) {
            emit_test_and_bench_link_args(&[flag]);
        }
        return;
    }
    if let Some(flag) = line.strip_prefix("cargo:rustc-link-arg=") {
        emit_test_and_bench_link_args(&[flag.to_string()]);
        return;
    }
    if line.starts_with("cargo:rustc-link-arg-tests=")
        || line.starts_with("cargo:rustc-link-arg-benches=")
    {
        println!("{line}");
        return;
    }
    if line.starts_with("cargo:rustc-link")
        || line.starts_with("cargo:rustc-cdylib-link-arg=")
        || line.starts_with("cargo:rustc-link-arg-")
    {
        panic!("refusing to apply a pyo3 link directive outside tests and benches: {line}");
    }
    if line.starts_with("cargo:") {
        println!("{line}");
    }
}

#[cfg(feature = "python")]
fn emit_test_and_bench_link_args(flags: &[String]) {
    for flag in flags {
        require_single_line("link arg", flag);
        println!("cargo:rustc-link-arg-tests={flag}");
        println!("cargo:rustc-link-arg-benches={flag}");
    }
}

/// `cargo:rustc-link-lib` syntax, turned into a linker argument.
#[cfg(feature = "python")]
fn linker_flags_from_rustc_link_lib(spec: &str) -> Vec<String> {
    let (kind, name) = if let Some((kind, name)) = spec.split_once('=') {
        (kind, name)
    } else {
        ("", spec)
    };
    let name = name.rsplit_once(':').map(|(_, real)| real).unwrap_or(name);
    require_single_line("lib_name", name);
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let env_name = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if kind == "framework" {
        return vec!["-framework".to_string(), name.to_string()];
    }
    if os == "windows" && env_name == "msvc" {
        return vec![format!("{name}.lib")];
    }
    if kind == "static" {
        return vec![
            format!("-Wl,-Bstatic"),
            format!("-l{name}"),
            format!("-Wl,-Bdynamic"),
        ];
    }
    vec![format!("-l{name}")]
}

#[cfg(feature = "python")]
fn linker_flag_from_rustc_link_search(spec: &str) -> Option<String> {
    let (kind, path) = if let Some((kind, path)) = spec.split_once('=') {
        (kind, path)
    } else {
        ("native", spec)
    };
    if path.is_empty() {
        return None;
    }
    require_single_line("lib_dir", path);
    let os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let env_name = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if os == "windows" && env_name == "msvc" {
        return Some(format!("/LIBPATH:{path}"));
    }
    if kind == "framework" {
        return Some(format!("-F{path}"));
    }
    Some(format!("-L{path}"))
}

#[cfg(feature = "python")]
fn framework_prefix_ok(prefix: &str) -> bool {
    let trimmed = prefix.trim();
    !trimmed.is_empty() && trimmed != "None"
}

#[cfg(feature = "python")]
fn require_single_line(what: &str, value: &str) {
    if value.chars().any(|c| c == '\n' || c == '\r' || c == '\0') {
        panic!("pyo3-build-config {what} is not a single line");
    }
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
        .flag_if_supported("-fvisibility=hidden")
        .flag_if_supported("-fvisibility-inlines-hidden")
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
