//! Default and non-`capi` feature builds must not export unmangled C ABI
//! symbols (`rkr_*` or legacy C entry points); `--features capi` builds must
//! export the exact 236-symbol C ABI manifest in `tests/capi_symbols.txt` and
//! declared in `include/readcon-core.h` (plus `rkr_block_range` from
//! `include/readcon-core-mpi.h`).

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;

#[cfg(unix)]
static CDYLIB_BUILD_LOCK: Mutex<()> = Mutex::new(());

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

#[cfg(unix)]
fn tool_available(tool: &str) -> bool {
    Command::new(tool)
        .arg("--version")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

#[cfg(unix)]
fn env_truthy(var: &str) -> bool {
    matches!(
        std::env::var(var)
            .ok()
            .as_deref()
            .map(str::trim)
            .map(str::to_ascii_lowercase)
            .as_deref(),
        Some("1" | "true" | "yes" | "on")
    )
}

#[cfg(unix)]
fn require_external_tools() -> bool {
    env_truthy("CI") || env_truthy("READCON_REQUIRE_TOOLS")
}

#[cfg(unix)]
fn check_or_require_tool(tool: &str, row: &str) -> bool {
    if tool_available(tool) {
        return true;
    }
    if require_external_tools() {
        panic!(
            "required tool `{tool}` for symbol-gate row `{row}` was not found on PATH \
             (CI or READCON_REQUIRE_TOOLS is set)"
        );
    }
    eprintln!(
        "SKIP capi_symbol_gate row `{row}`: `{tool}` not found on PATH \
         (set CI=true or READCON_REQUIRE_TOOLS=1 to fail instead of skipping)"
    );
    false
}

#[cfg(unix)]
fn exported_symbols_for_features(features: &[&str]) -> BTreeSet<String> {
    let _guard = CDYLIB_BUILD_LOCK
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let target = work_dir("capi-gate-cdylib");
    let mut cmd = Command::new("cargo");
    cmd.args(["rustc", "--locked", "--lib", "--crate-type", "cdylib"]);
    if !features.is_empty() {
        cmd.arg("--features").arg(features.join(","));
    }
    cmd.arg("--target-dir")
        .arg(&target)
        .arg("--manifest-path")
        .arg(root.join("Cargo.toml"));
    let output = cmd.output().expect("cargo rustc cdylib");
    assert!(
        output.status.success(),
        "cdylib build failed for features={features:?}\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let ext = if cfg!(target_os = "macos") {
        "dylib"
    } else {
        "so"
    };
    let lib = target.join("debug").join(format!("libreadcon_core.{ext}"));
    assert!(lib.is_file(), "missing {}", lib.display());
    exported_symbols(&lib)
}

#[cfg(unix)]
fn parse_nm_exported_symbols(stdout: &str, strip_macho_prefix: bool) -> BTreeSet<String> {
    stdout
        .lines()
        .filter_map(|line| {
            let fields: Vec<&str> = line.split_whitespace().collect();
            let raw = match fields.as_slice() {
                [_, code, name] if code.len() == 1 => *name,
                [code, name] if code.len() == 1 => *name,
                _ => return None,
            };
            let trimmed = raw.split('@').next().unwrap_or(raw);
            let normalized = if strip_macho_prefix {
                trimmed.strip_prefix('_').unwrap_or(trimmed)
            } else {
                trimmed
            };
            Some(normalized.to_string())
        })
        .collect()
}

#[cfg(unix)]
fn exported_symbols(lib: &Path) -> BTreeSet<String> {
    let mut nm = Command::new("nm");
    if cfg!(target_os = "macos") {
        nm.args(["-gU"]);
    } else {
        nm.args(["-D", "--defined-only"]);
    }
    let output = nm.arg(lib).output().expect("nm");
    assert!(output.status.success(), "nm failed on {}", lib.display());
    parse_nm_exported_symbols(
        &String::from_utf8_lossy(&output.stdout),
        cfg!(target_os = "macos"),
    )
}

#[cfg(unix)]
fn expected_capi_symbols() -> BTreeSet<String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let text = std::fs::read_to_string(root.join("tests/capi_symbols.txt"))
        .expect("read tests/capi_symbols.txt");
    let syms: BTreeSet<String> = text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .map(String::from)
        .collect();
    assert_eq!(
        syms.len(),
        236,
        "tests/capi_symbols.txt must list all 236 C ABI symbols (found {})",
        syms.len()
    );
    syms
}

#[cfg(unix)]
fn expected_mpi_capi_symbols() -> BTreeSet<String> {
    [
        "rkr_mpi_comm_info_f",
        "rkr_mpi_read_block_f",
        "rkr_mpi_rewrite_block_f",
        "rkr_mpi_write_block_f",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}

#[cfg(unix)]
fn strip_c_comments(src: &str) -> String {
    let bytes = src.as_bytes();
    let mut out = String::with_capacity(src.len());
    let mut i = 0;
    while i < bytes.len() {
        if i + 1 < bytes.len() && bytes[i] == b'/' && bytes[i + 1] == b'*' {
            i += 2;
            while i + 1 < bytes.len() && !(bytes[i] == b'*' && bytes[i + 1] == b'/') {
                if bytes[i] == b'\n' {
                    out.push('\n');
                }
                i += 1;
            }
            i = (i + 2).min(bytes.len());
        } else if i + 1 < bytes.len() && bytes[i] == b'/' && bytes[i + 1] == b'/' {
            while i < bytes.len() && bytes[i] != b'\n' {
                i += 1;
            }
        } else {
            out.push(bytes[i] as char);
            i += 1;
        }
    }
    out
}

/// Extract every C function declaration identifier from `include/readcon-core.h`.
///
/// The shipped header is generated by `cbindgen` and wraps declarations in
/// optional `namespace readcon {` / `extern "C" {` blocks. Stripping comments,
/// preprocessor lines, and `struct`/`enum`/`union` bodies leaves top-level
/// statements whose non-`typedef` prototypes end in `... <name>(...);`.
#[cfg(unix)]
fn parse_header_function_decls(header_src: &str) -> BTreeSet<String> {
    let uncommented = strip_c_comments(header_src);
    let mut cleaned = String::with_capacity(uncommented.len());
    for line in uncommented.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#')
            || trimmed == "extern \"C\" {"
            || trimmed == "namespace readcon {"
            || trimmed == "}"
        {
            continue;
        }
        cleaned.push_str(line);
        cleaned.push('\n');
    }

    let mut decls = BTreeSet::new();
    let mut stmt = String::new();
    let mut brace_depth: usize = 0;
    for ch in cleaned.chars() {
        match ch {
            '{' => {
                brace_depth += 1;
                stmt.push(ch);
            }
            '}' => {
                brace_depth = brace_depth.saturating_sub(1);
                stmt.push(ch);
            }
            ';' if brace_depth == 0 => {
                let s = stmt.trim();
                if !s.is_empty() && !s.starts_with("typedef ") && !s.contains('{') {
                    if let Some(paren_idx) = s.find('(') {
                        let prefix = s[..paren_idx].trim_end();
                        let ident: String = prefix
                            .chars()
                            .rev()
                            .take_while(|c| c.is_ascii_alphanumeric() || *c == '_')
                            .collect::<String>()
                            .chars()
                            .rev()
                            .collect();
                        if !ident.is_empty() {
                            decls.insert(ident);
                        }
                    }
                }
                stmt.clear();
            }
            _ => stmt.push(ch),
        }
    }
    decls
}

#[cfg(unix)]
fn declared_header_symbols() -> BTreeSet<String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let main_header =
        std::fs::read_to_string(root.join("include/readcon-core.h")).expect("read readcon-core.h");
    let mpi_header = std::fs::read_to_string(root.join("include/readcon-core-mpi.h"))
        .expect("read readcon-core-mpi.h");

    let mut declared = parse_header_function_decls(&main_header);
    assert!(
        declared.len() >= 200,
        "header parser found unexpectedly few declarations: {}",
        declared.len()
    );
    assert!(
        mpi_header.contains("int rkr_block_range("),
        "include/readcon-core-mpi.h must declare rkr_block_range"
    );
    declared.insert("rkr_block_range".to_string());
    declared
}

#[cfg(unix)]
#[test]
fn default_cdylib_exports_zero_symbols() {
    let default_syms = exported_symbols_for_features(&[]);
    assert!(
        default_syms.is_empty(),
        "default-features cdylib exported {} unexpected symbol(s):\n{default_syms:#?}",
        default_syms.len()
    );
}

#[cfg(unix)]
#[test]
fn non_capi_feature_combinations_export_zero_c_symbols() {
    let run_rpc = cfg!(feature = "rpc") || check_or_require_tool("capnp", "rpc");
    let run_mpi = cfg!(feature = "mpi") || check_or_require_tool("mpicc", "mpi");
    let run_python = cfg!(feature = "python") || check_or_require_tool("python3", "python");

    let self_contained: &[&[&str]] = &[
        &["parallel"],
        &["zstd"],
        &["grammar"],
        &["mimalloc-allocator"],
        &["benchmark"],
        &["static_system_alloc"],
        &["local_dynamic_tls"],
        &["borrow-path-counts"],
        &["cuda"],
    ];

    for features in self_contained {
        let syms = exported_symbols_for_features(features);
        assert!(
            syms.is_empty(),
            "non-capi features={features:?} exported {} unexpected symbol(s):\n{syms:#?}",
            syms.len()
        );
    }

    let mut combined: Vec<&str> = vec![
        "parallel",
        "zstd",
        "grammar",
        "mimalloc-allocator",
        "benchmark",
        "static_system_alloc",
        "local_dynamic_tls",
        "borrow-path-counts",
        "cuda",
    ];

    if run_rpc {
        let syms = exported_symbols_for_features(&["rpc"]);
        assert!(
            syms.is_empty(),
            "non-capi features=[\"rpc\"] exported {} unexpected symbol(s):\n{syms:#?}",
            syms.len()
        );
        combined.push("rpc");
    }

    if run_mpi {
        let syms = exported_symbols_for_features(&["mpi"]);
        assert!(
            syms.is_empty(),
            "non-capi features=[\"mpi\"] exported {} unexpected symbol(s):\n{syms:#?}",
            syms.len()
        );
        combined.push("mpi");
    }

    let combined_syms = exported_symbols_for_features(&combined);
    assert!(
        combined_syms.is_empty(),
        "combined non-capi features={combined:?} exported {} unexpected symbol(s):\n{combined_syms:#?}",
        combined_syms.len()
    );

    if run_python {
        let py_syms = exported_symbols_for_features(&["python"]);
        let expected_py: BTreeSet<String> = ["PyInit_readcon".to_string()].into_iter().collect();
        assert_eq!(
            py_syms, expected_py,
            "python-only cdylib must export only PyInit_readcon"
        );
    }
}

#[cfg(unix)]
#[test]
fn capi_cdylib_exports_exact_header_symbol_set() {
    let expected = expected_capi_symbols();
    let declared = declared_header_symbols();
    let capi_syms = exported_symbols_for_features(&["capi"]);

    let header_missing: Vec<&String> = expected.difference(&declared).collect();
    let header_unexpected: Vec<&String> = declared.difference(&expected).collect();
    assert_eq!(
        declared,
        expected,
        "shipped header declarations do not match tests/capi_symbols.txt (expected={}, declared={})\nmissing ({}): {header_missing:#?}\nunexpected ({}): {header_unexpected:#?}",
        expected.len(),
        declared.len(),
        header_missing.len(),
        header_unexpected.len()
    );

    let missing: Vec<&String> = expected.difference(&capi_syms).collect();
    let unexpected: Vec<&String> = capi_syms.difference(&expected).collect();
    assert_eq!(
        capi_syms,
        expected,
        "capi cdylib export set does not match tests/capi_symbols.txt (expected={}, exported={})\nmissing ({}): {missing:#?}\nunexpected ({}): {unexpected:#?}",
        expected.len(),
        capi_syms.len(),
        missing.len(),
        unexpected.len()
    );

    assert_eq!(capi_syms, declared);
}

#[cfg(unix)]
#[test]
fn nm_parser_strips_leading_underscore_only_on_macho() {
    let sample = "\
0000000000001000 T _rkr_library_version
0000000000001010 T rkr_version@@READCON_1
";

    let elf_syms = parse_nm_exported_symbols(sample, false);
    assert!(elf_syms.contains("_rkr_library_version"));
    assert!(!elf_syms.contains("rkr_library_version"));
    assert!(elf_syms.contains("rkr_version"));

    let expected_elf: BTreeSet<String> = ["rkr_library_version", "rkr_version"]
        .into_iter()
        .map(String::from)
        .collect();
    assert_ne!(
        elf_syms, expected_elf,
        "ELF parser must not normalize stray _rkr_* into rkr_*"
    );

    let macho_syms = parse_nm_exported_symbols("0000000000001000 T _rkr_library_version\n", true);
    let expected_macho: BTreeSet<String> =
        ["rkr_library_version".to_string()].into_iter().collect();
    assert_eq!(macho_syms, expected_macho);
}

#[cfg(all(unix, not(target_os = "macos")))]
#[test]
fn elf_stray_leading_underscore_export_is_preserved() {
    let dir = tempfile::tempdir().expect("tempdir");
    let src = dir.path().join("stray.c");
    let so = dir.path().join("libstray.so");
    std::fs::write(&src, "void _rkr_library_version(void) {}\n").expect("write stray.c");
    let output = Command::new("cc")
        .args(["-shared", "-fPIC"])
        .arg(&src)
        .arg("-o")
        .arg(&so)
        .output()
        .expect("cc -shared");
    assert!(
        output.status.success(),
        "failed to compile test shared object:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let syms = exported_symbols(&so);
    assert!(
        syms.contains("_rkr_library_version"),
        "expected stray _rkr_library_version in ELF exports: {syms:#?}"
    );
    assert!(
        !syms.contains("rkr_library_version"),
        "ELF export parser must not strip leading underscore from _rkr_library_version"
    );
}

#[cfg(unix)]
#[test]
fn capi_mpi_cdylib_exports_exact_symbol_set() {
    if !(cfg!(feature = "mpi") || check_or_require_tool("mpicc", "capi,mpi")) {
        return;
    }
    let mut expected = expected_capi_symbols();
    expected.extend(expected_mpi_capi_symbols());
    let actual = exported_symbols_for_features(&["capi", "mpi"]);

    let missing: Vec<&String> = expected.difference(&actual).collect();
    let unexpected: Vec<&String> = actual.difference(&expected).collect();
    assert_eq!(
        actual,
        expected,
        "capi,mpi cdylib export set mismatch (expected={}, exported={})\nmissing ({}): {missing:#?}\nunexpected ({}): {unexpected:#?}",
        expected.len(),
        actual.len(),
        missing.len(),
        unexpected.len()
    );
}

#[test]
fn consumer_crate_defining_rkr_symbol_links_against_default_features() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let dir = tempfile::tempdir().expect("tempdir");
    let src = dir.path().join("src");
    std::fs::create_dir_all(&src).expect("mkdir src");
    let manifest_path = root.to_str().expect("utf8 manifest path");
    std::fs::write(
        dir.path().join("Cargo.toml"),
        format!(
            r#"[package]
name = "rkr-symbol-clash-check"
version = "0.0.0"
edition = "2024"
publish = false

[dependencies]
readcon-core = {{ path = {manifest_path:?} }}

[workspace]
"#
        ),
    )
    .expect("write Cargo.toml");
    std::fs::write(
        src.join("main.rs"),
        r#"#[unsafe(no_mangle)]
pub extern "C" fn rkr_library_version() -> *const std::ffi::c_char {
    c"downstream-rkr".as_ptr()
}

#[unsafe(no_mangle)]
pub extern "C" fn rkr_block_range(
    _n_frames: u64,
    _n_ranks: u32,
    _rank: u32,
    _start: *mut u64,
    _end: *mut u64,
) -> i32 {
    42
}

fn main() {
    assert!(!readcon_core::VERSION.is_empty());
    let s = unsafe { std::ffi::CStr::from_ptr(rkr_library_version()) };
    assert_eq!(s.to_bytes(), b"downstream-rkr");
    assert_eq!(rkr_block_range(0, 0, 0, std::ptr::null_mut(), std::ptr::null_mut()), 42);
}
"#,
    )
    .expect("write main.rs");

    let target = work_dir("capi-gate-consumer");
    let output = Command::new("cargo")
        .args(["run", "--offline", "--manifest-path"])
        .arg(dir.path().join("Cargo.toml"))
        .arg("--target-dir")
        .arg(&target)
        .output()
        .expect("cargo run consumer");
    assert!(
        output.status.success(),
        "consumer crate defining rkr_library_version and rkr_block_range failed to link against default readcon-core:\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
